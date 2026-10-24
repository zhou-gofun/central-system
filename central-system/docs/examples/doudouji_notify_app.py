"""
豆豆集侧接收「中心系统支付成功通知」的最小可运行服务

依赖：fastapi、uvicorn、sqlalchemy[asyncio]、asyncpg、httpx

环境变量：
    CENTER_URL        中心系统公网地址，默认 https://central.system.sevenblue.cn
    CENTER_APP_CODE   业务应用标识，默认 doudouji_prod
    CENTER_APP_SECRET 业务应用密钥（与调接口用的同一个）
    DATABASE_URL      豆豆集自己的库，例如 postgresql+asyncpg://user:pw@host/db
    NOTIFY_URL        豆豆集自己的公网回调地址（要填进中心系统的下单请求 notify_url）

幂等表 DDL（先建好）：
    CREATE TABLE pay_notify_inbox (
        out_trade_no   VARCHAR(64) PRIMARY KEY,
        event_id       VARCHAR(128),
        amount         NUMERIC(12,2),
        raw_payload    TEXT,
        received_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

流程：
    微信 → 中心系统（验签解密、改订单） → 豆豆集（本服务）
    本服务：验签 → 幂等落库 → 立刻返回 2xx → 后台任务发货
"""
import hashlib
import hmac
import json
import logging
import os
import time
from decimal import Decimal
from typing import Any, Dict, Optional

from fastapi import BackgroundTasks, FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('doudouji-pay-notify')

CENTER_URL = os.getenv('CENTER_URL', 'https://central.system.sevenblue.cn').rstrip('/')
CENTER_APP_CODE = os.getenv('CENTER_APP_CODE', 'doudouji_prod')
CENTER_APP_SECRET = os.getenv('CENTER_APP_SECRET', '')
NOTIFY_URL = os.getenv('NOTIFY_URL', '')

NOTIFY_TIMESTAMP_TOLERANCE = 300

app = FastAPI(title='豆豆集支付回调接收')

engine = create_async_engine(
    os.getenv('DATABASE_URL', ''),
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=10,
)


# ---------- 验签 ----------

def verify_notify_signature(
    app_secret: str,
    raw_body: bytes,
    headers: Dict[str, str],
    tolerance_seconds: int = NOTIFY_TIMESTAMP_TOLERANCE,
) -> bool:
    """
    验证中心系统通知签名

    待签串 = f'{timestamp}.{nonce}.{原始请求体}'
    签名   = HMAC-SHA256(app_secret, 待签串).hexdigest()

    ⚠️ raw_body 必须是收到的原始字节，不要 json.loads 之后重新序列化。
    """
    lower = {k.lower(): v for k, v in (headers or {}).items()}

    signature = lower.get('x-pay-signature')
    timestamp = lower.get('x-pay-timestamp')
    nonce = lower.get('x-pay-nonce')
    if not signature or not timestamp or not nonce:
        logger.warning('通知缺少签名请求头')
        return False

    try:
        if abs(int(time.time()) - int(timestamp)) > tolerance_seconds:
            logger.warning('通知时间戳过期: %s', timestamp)
            return False
    except (TypeError, ValueError):
        return False

    message = f'{timestamp}.{nonce}.{raw_body.decode("utf-8")}'
    expected = hmac.new(
        app_secret.encode('utf-8'), message.encode('utf-8'), hashlib.sha256
    ).hexdigest()
    ok = hmac.compare_digest(expected.lower(), signature.lower())
    if not ok:
        logger.warning('通知验签失败')
    return ok


# ---------- 幂等 ----------

async def mark_processed_once(out_trade_no: str, event_id: Optional[str],
                              amount: Optional[Decimal], raw_payload: str) -> bool:
    """
    落幂等记录，返回 True 表示这是**首次**处理，False 表示重复通知。

    依赖 pay_notify_inbox 表的 out_trade_no 主键冲突。
    """
    async with engine.begin() as conn:
        result = await conn.execute(
            text(
                'INSERT INTO pay_notify_inbox (out_trade_no, event_id, amount, raw_payload) '
                'VALUES (:out_trade_no, :event_id, :amount, :raw_payload) '
                'ON CONFLICT (out_trade_no) DO NOTHING'
            ),
            {
                'out_trade_no': out_trade_no,
                'event_id': event_id,
                'amount': amount,
                'raw_payload': raw_payload,
            },
        )
        return result.rowcount > 0


# ---------- 发货（替换成你自己的业务逻辑） ----------

async def deliver(order: Dict[str, Any]) -> None:
    """
    支付成功后的发货逻辑。

    放在 BackgroundTasks 里执行：HTTP 响应已经返回给中心系统了，
    不要让发货耗时拖住响应（中心系统的 httpx 超时是 10 秒，超时了会重投 3 次）。
    """
    out_trade_no = order.get('out_trade_no')
    try:
        # 伪代码：开通会员 / 发放商品 / 记账
        # await db.execute(text('UPDATE member SET ... WHERE order_no = :no'), {'no': out_trade_no})
        logger.info('发货完成 out_trade_no=%s amount=%s attach=%s',
                    out_trade_no, order.get('amount'), order.get('attach'))
    except Exception:
        # 发货失败要能被发现：告警 + 落待补偿表，后台重试
        logger.exception('发货失败 out_trade_no=%s，需要人工/定时补偿', out_trade_no)


# ---------- 路由 ----------

@app.post('/api/pay/notify')
async def pay_notify(request: Request, background: BackgroundTasks):
    """接收中心系统的支付结果通知"""
    raw_body = await request.body()
    headers = dict(request.headers)

    if not verify_notify_signature(CENTER_APP_SECRET, raw_body, headers):
        # 验签失败返回非 2xx，中心系统会重试 3 次
        return JSONResponse({'code': 'FAIL', 'message': 'invalid signature'}, status_code=401)

    try:
        payload = json.loads(raw_body.decode('utf-8'))
    except ValueError:
        return JSONResponse({'code': 'FAIL', 'message': 'invalid json'}, status_code=400)

    out_trade_no = payload.get('out_trade_no')
    if not out_trade_no:
        return JSONResponse({'code': 'FAIL', 'message': 'missing out_trade_no'}, status_code=400)

    status = payload.get('status')
    event_id = payload.get('event_id')
    amount = payload.get('amount')

    # 只有支付成功才发货；退款/关闭等状态同样会推过来，按需处理
    if status != 'PAID':
        logger.info('收到非支付成功通知 out_trade_no=%s status=%s', out_trade_no, status)
        return {'code': 'SUCCESS', 'message': 'ok'}

    try:
        first_time = await mark_processed_once(
            out_trade_no, event_id,
            Decimal(amount) if amount is not None else None,
            raw_body.decode('utf-8')[:4000],
        )
    except Exception:
        logger.exception('幂等落库失败 out_trade_no=%s', out_trade_no)
        # 落库失败就不能发货，否则重投时会重复发货；返回 5xx 让中心系统重投
        return JSONResponse({'code': 'FAIL', 'message': 'internal error'}, status_code=500)

    if not first_time:
        logger.info('重复通知，忽略 out_trade_no=%s', out_trade_no)
        return {'code': 'SUCCESS', 'message': 'duplicate ignored'}

    background.add_task(deliver, payload)
    return {'code': 'SUCCESS', 'message': 'ok'}


@app.get('/health')
async def health():
    return {'status': 'ok'}


if __name__ == '__main__':
    import uvicorn

    uvicorn.run(app, host='0.0.0.0', port=int(os.getenv('PORT', '9000')))
