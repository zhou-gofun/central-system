"""
豆豆集侧调用中心系统支付接口的客户端

放到豆豆集服务器上用（依赖：httpx）。

环境变量：
    CENTER_URL        中心系统公网地址，默认 https://central.system.sevenblue.cn
    CENTER_APP_CODE   业务应用标识，默认 doudouji_prod
    CENTER_APP_SECRET 业务应用密钥（调接口用 + 验证中心系统回调签名，同一个）

用法：
    client = PayClient()
    order = await client.create_order(
        client_order_no='DDJ20261023000123',
        subject='豆豆集-会员年费',
        amount=Decimal('39.90'),
        trade_type='jsapi',
        payer_openid='oUpF8uMuAJO_M2pxb1Q9zNjWeS6o',
    )
    # order['pay_params'] 直接给前端拉起支付
"""
import hashlib
import hmac
import os
import time
from decimal import Decimal
from typing import Any, Dict, Optional

import httpx

CENTER_URL = os.getenv('CENTER_URL', 'https://central.system.sevenblue.cn').rstrip('/')
CENTER_APP_CODE = os.getenv('CENTER_APP_CODE', 'doudouji_prod')
CENTER_APP_SECRET = os.getenv('CENTER_APP_SECRET', '')

# 中心系统通知的时间戳容忍窗口（秒），与中心系统 NOTIFY_TTL_SECONDS 一致
NOTIFY_TIMESTAMP_TOLERANCE = 300


class PayError(Exception):
    """中心系统返回的业务错误"""


class PayClient:
    """中心系统支付接口客户端"""

    def __init__(
        self,
        base_url: str = CENTER_URL,
        app_code: str = CENTER_APP_CODE,
        app_secret: str = CENTER_APP_SECRET,
        timeout: float = 15.0,
    ):
        if not app_secret:
            raise ValueError('缺少 CENTER_APP_SECRET 环境变量')
        self.base_url = base_url.rstrip('/')
        self.app_code = app_code
        self.app_secret = app_secret
        self.timeout = timeout

    # ---------- 内部 ----------

    def _headers(self) -> Dict[str, str]:
        return {
            'X-App-Code': self.app_code,
            'X-App-Secret': self.app_secret,
            'Content-Type': 'application/json',
        }

    async def _request(
        self,
        method: str,
        path: str,
        json_body: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        url = f'{self.base_url}{path}'
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.request(
                method, url, json=json_body, headers=self._headers()
            )

        text = response.text
        if response.status_code >= 400:
            raise PayError(f'中心系统返回 {response.status_code}: {text[:500]}')

        try:
            data = response.json()
        except ValueError:
            return {}
        return data if isinstance(data, dict) else {}

    # ---------- 业务接口 ----------

    async def create_order(
        self,
        *,
        client_order_no: str,
        subject: str,
        amount: Decimal,
        trade_type: str = 'jsapi',
        provider: str = 'wxpay',
        payer_openid: Optional[str] = None,
        description: Optional[str] = None,
        notify_url: Optional[str] = None,
        merchant_id: Optional[str] = None,
        attach: Optional[str] = None,
        currency: str = 'CNY',
        expire_minutes: int = 30,
        extra: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        创建支付订单

        幂等：同一个 client_order_no 只会有一张订单，重复调用直接返回原订单。
        amount 单位是**元**；用字符串传避免浮点误差。
        """
        body: Dict[str, Any] = {
            'provider': provider,
            'trade_type': trade_type,
            'subject': subject,
            'amount': str(amount),
            'currency': currency,
            'client_order_no': client_order_no,
            'expire_minutes': expire_minutes,
        }
        if description:
            body['description'] = description
        if payer_openid:
            body['payer_openid'] = payer_openid
        if notify_url:
            body['notify_url'] = notify_url
        if merchant_id:
            body['merchant_id'] = merchant_id
        if attach:
            body['attach'] = attach
        if extra:
            body['extra'] = extra

        return await self._request('POST', '/api/v1/pay/order', body)

    async def get_order(self, out_trade_no: str) -> Dict[str, Any]:
        """查订单状态"""
        return await self._request('GET', f'/api/v1/pay/order/{out_trade_no}')

    async def sync_order(self, out_trade_no: str) -> Dict[str, Any]:
        """主动向微信查单并同步状态（对账用）"""
        return await self._request('POST', f'/api/v1/pay/order/{out_trade_no}/sync')

    async def close_order(self, out_trade_no: str) -> Dict[str, Any]:
        """关闭未支付订单"""
        return await self._request('POST', f'/api/v1/pay/order/{out_trade_no}/close')

    async def list_orders(
        self,
        status: Optional[str] = None,
        client_order_no: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Dict[str, Any]:
        """分页查订单列表"""
        params = [f'page={page}', f'page_size={page_size}']
        if status:
            params.append(f'status={status}')
        if client_order_no:
            params.append(f'client_order_no={client_order_no}')
        path = '/api/v1/pay/orders?' + '&'.join(params)
        return await self._request('GET', path)

    async def create_refund(
        self,
        out_trade_no: str,
        amount: Optional[Decimal] = None,
        reason: Optional[str] = None,
        refund_no: Optional[str] = None,
    ) -> Dict[str, Any]:
        """发起退款；amount 不传默认全额；refund_no 是退款幂等键"""
        body: Dict[str, Any] = {'out_trade_no': out_trade_no}
        if amount is not None:
            body['amount'] = str(amount)
        if reason:
            body['reason'] = reason
        if refund_no:
            body['refund_no'] = refund_no
        return await self._request('POST', '/api/v1/pay/refund', body)

    async def get_refund(self, refund_no: str) -> Dict[str, Any]:
        """查退款单"""
        return await self._request('GET', f'/api/v1/pay/refund/{refund_no}')


# ---------- 中心系统回调验签 ----------


def verify_notify_signature(
    app_secret: str,
    raw_body: bytes,
    headers: Dict[str, str],
    tolerance_seconds: int = NOTIFY_TIMESTAMP_TOLERANCE,
) -> bool:
    """
    验证中心系统支付通知的 HMAC-SHA256 签名

    待签串 = f'{timestamp}.{nonce}.{原始请求体}'
    签名   = HMAC-SHA256(app_secret, 待签串).hexdigest()

    ⚠️ raw_body 必须是收到的原始字节，不要 json.loads 之后重新序列化。
    """
    lower = {k.lower(): v for k, v in (headers or {}).items()}

    signature = lower.get('x-pay-signature')
    timestamp = lower.get('x-pay-timestamp')
    nonce = lower.get('x-pay-nonce')
    if not signature or not timestamp or not nonce:
        return False

    # 防重放：时间戳超出容忍窗口直接拒
    try:
        if abs(int(time.time()) - int(timestamp)) > tolerance_seconds:
            return False
    except (TypeError, ValueError):
        return False

    message = f'{timestamp}.{nonce}.{raw_body.decode("utf-8")}'
    expected = hmac.new(
        app_secret.encode('utf-8'), message.encode('utf-8'), hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected.lower(), signature.lower())


if __name__ == '__main__':
    import asyncio

    async def _demo() -> None:
        client = PayClient()
        order = await client.create_order(
            client_order_no=f'DDJ{int(time.time())}',
            subject='豆豆集-测试订单',
            amount=Decimal('0.01'),
            trade_type='jsapi',
            payer_openid=os.getenv('PAYER_OPENID', ''),
        )
        print(order)

    asyncio.run(_demo())
