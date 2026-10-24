"""
支付渠道回调入口

URL 形如 /api/v1/pay/notify/{provider}/{merchant_id}
merchant_id 用来定位商户配置（取证书/公钥/APIv3密钥），也是多商户并存时区分回调的路由键。

该接口是公开接口，不走 X-App-Code 鉴权，靠渠道签名验签保证安全。
"""
import logging

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.database import get_db
from app.service.payment.notify_service import NotifyService
from app.service.payment.provider import PayError, get_provider

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/pay/notify", tags=["支付回调"])


@router.post("/{provider}/{merchant_id}")
async def payment_notify(
    provider: str,
    merchant_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """接收支付渠道回调"""
    raw_body = await request.body()
    headers = dict(request.headers)

    try:
        impl = get_provider(provider)
    except PayError as exc:
        logger.error(f'未知支付渠道回调: {provider}')
        return Response(content=f'unsupported provider: {provider}', status_code=404)

    service = NotifyService(db)
    try:
        body, media_type = await service.handle(provider, merchant_id, headers, raw_body)
    except PayError as exc:
        logger.error(f'支付回调处理失败 provider={provider} merchant={merchant_id}: {exc.message}')
        # 验签失败等返回 400，渠道会重试；注意不要泄露细节
        return Response(content=exc.message, status_code=exc.status_code)
    except Exception as exc:  # noqa: BLE001
        logger.exception(f'支付回调异常 provider={provider} merchant={merchant_id}')
        return Response(content='internal error', status_code=500)

    return Response(content=body, media_type=media_type)
