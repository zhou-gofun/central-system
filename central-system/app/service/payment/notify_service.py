"""
支付回调处理服务

处理链路：
    渠道回调 -> 验签(+解密) -> 幂等检查 -> 金额校验 -> 更新订单 -> 转发业务平台

要点：
1. 验签必须在解析报文之前完成，且使用**原始 body**（微信 APIv3 是 AES-GCM 加密的 JSON，
   中间件若改写 body 会导致解密失败）。
2. 渠道会重复投递回调，靠 pay_notify_log 的 (provider, event_id) 唯一索引做幂等。
3. 必须校验回调金额与本地订单金额一致，防止金额篡改。
4. 转发给业务平台的 webhook 用 app_secret 做 HMAC-SHA256 签名，带时间戳防重放。
"""
import json
import logging
import time
from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, Optional, Tuple
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.model.payment.order import PayOrder
from app.model.payment.notify_log import PayNotifyLog
from app.model.payment.merchant import PayMerchant
from app.model.wechat.app import WechatApp
from app.service.payment.crypto import hmac_sha256
from app.service.payment.provider import (
    NotifyEvent,
    PayError,
    STATUS_PAID,
    get_provider,
)
from app.service.payment.merchant_service import to_context

logger = logging.getLogger(__name__)

# 转发给业务平台的通知有效期（秒）
NOTIFY_TTL_SECONDS = 300
# 转发失败重试次数
FORWARD_MAX_RETRY = 3


class NotifyService:
    """支付回调处理"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def handle(
        self,
        provider: str,
        merchant_id: str,
        headers: Dict[str, str],
        raw_body: bytes,
    ) -> Tuple[bytes, str]:
        """
        处理渠道回调

        Returns:
            (响应体, content_type)
        """
        impl = get_provider(provider)

        # 1. 取商户配置
        result = await self.db.execute(
            select(PayMerchant).where(PayMerchant.id == merchant_id)
        )
        merchant = result.scalar_one_or_none()
        if not merchant:
            logger.error(f'支付回调：商户配置不存在 merchant_id={merchant_id}')
            raise PayError('商户配置不存在', status_code=404, code='merchant_not_found')
        if merchant.provider != provider:
            logger.error(f'支付回调：渠道不匹配 merchant={merchant_id} provider={provider}')
            raise PayError('渠道不匹配', status_code=400, code='provider_mismatch')

        ctx = to_context(merchant)

        # 2. 验签 + 解密（失败直接拒绝，不落库）
        event = await impl.verify_notify(ctx, headers, raw_body)
        logger.info(
            f'收到支付回调 provider={provider} event_id={event.event_id} '
            f'out_trade_no={event.out_trade_no} status={event.status}'
        )

        # 3. 幂等检查
        existing = await self.db.execute(
            select(PayNotifyLog).where(
                PayNotifyLog.provider == provider,
                PayNotifyLog.event_id == event.event_id,
            )
        )
        if existing.scalar_one_or_none():
            logger.info(f'支付回调重复投递，直接忽略 event_id={event.event_id}')
            # 重复投递时如果订单还没通知成功，仍然补发一次
            if event.out_trade_no:
                order = await self._get_order(event.out_trade_no)
                if order and order.status == STATUS_PAID and order.notify_status != 'SUCCESS':
                    await self._forward_to_app(order, event)
            return self._success_response(impl)

        # 4. 定位订单
        if not event.out_trade_no:
            logger.error(f'支付回调缺少订单号 event_id={event.event_id}')
            await self._log_event(provider, event, 'FAILED', '回调缺少订单号', raw_body)
            raise PayError('回调缺少订单号', status_code=400)

        order = await self._get_order(event.out_trade_no)
        if not order:
            logger.error(f'支付回调订单不存在 out_trade_no={event.out_trade_no}')
            await self._log_event(provider, event, 'FAILED', '订单不存在', raw_body)
            raise PayError('订单不存在', status_code=404, code='order_not_found')

        # 5. 金额校验（防篡改）
        if event.amount is not None and Decimal(event.amount) != Decimal(order.amount):
            logger.error(
                f'支付回调金额不一致 out_trade_no={order.out_trade_no} '
                f'本地={order.amount} 回调={event.amount}'
            )
            await self._log_event(provider, event, 'AMOUNT_MISMATCH',
                                  f'金额不一致 本地={order.amount} 回调={event.amount}', raw_body)
            # 不更新订单，但向渠道返回成功，避免无意义的重复回调风暴
            return self._success_response(impl)

        # 6. 更新订单
        if event.status == STATUS_PAID and order.status != STATUS_PAID:
            order.status = STATUS_PAID
            order.paid_at = event.paid_at or order.paid_at
        if event.provider_trade_no:
            order.provider_trade_no = event.provider_trade_no
        if event.payer_id and not order.payer_id:
            order.payer_id = event.payer_id
        self.db.add(order)

        # 7. 写幂等日志（唯一索引冲突即视为重复）
        try:
            await self._log_event(provider, event, 'SUCCESS', None, raw_body, commit=False)
            await self.db.commit()
        except IntegrityError:
            await self.db.rollback()
            logger.info(f'支付回调并发重复 event_id={event.event_id}')
            return self._success_response(impl)

        # 8. 转发给业务平台
        await self._forward_to_app(order, event)

        return self._success_response(impl)

    async def _get_order(self, out_trade_no: str) -> Optional[PayOrder]:
        result = await self.db.execute(
            select(PayOrder).where(PayOrder.out_trade_no == out_trade_no)
        )
        return result.scalar_one_or_none()

    async def _log_event(
        self,
        provider: str,
        event: NotifyEvent,
        result: str,
        message: Optional[str],
        raw_body: bytes,
        commit: bool = True,
    ) -> None:
        log = PayNotifyLog(
            provider=provider,
            event_id=event.event_id[:128],
            out_trade_no=event.out_trade_no,
            provider_trade_no=event.provider_trade_no,
            event_type=event.event_type[:50] if event.event_type else None,
            result=result,
            message=message,
            raw_body=raw_body[:4000].decode('utf-8', errors='ignore'),
        )
        self.db.add(log)
        if commit:
            await self.db.commit()

    @staticmethod
    def _success_response(impl) -> Tuple[bytes, str]:
        body, media_type = impl.notify_success_response()
        if isinstance(body, str):
            body = body.encode('utf-8')
        return body, media_type

    # ---------- 转发给业务平台 ----------

    async def _forward_to_app(self, order: PayOrder, event: NotifyEvent) -> bool:
        """
        把支付结果通知给业务平台

        通知报文用 app_secret 做 HMAC-SHA256 签名，业务平台用同一密钥验签。
        """
        if not order.notify_url:
            logger.info(f'订单未配置业务通知地址，跳过转发 out_trade_no={order.out_trade_no}')
            order.notify_status = 'SKIPPED'
            self.db.add(order)
            await self.db.commit()
            return False

        app_result = await self.db.execute(
            select(WechatApp).where(WechatApp.app_code == order.app_code)
        )
        app_row = app_result.scalar_one_or_none()
        if not app_row:
            logger.error(f'业务应用不存在 app_code={order.app_code}')
            return False

        payload = {
            'out_trade_no': order.out_trade_no,
            'client_order_no': order.client_order_no,
            'app_code': order.app_code,
            'provider': order.provider,
            'provider_trade_no': order.provider_trade_no,
            'trade_type': order.trade_type,
            'subject': order.subject,
            'amount': str(order.amount),
            'currency': order.currency,
            'status': order.status,
            'attach': order.attach,
            'paid_at': order.paid_at.isoformat() if order.paid_at else None,
            'event_type': event.event_type,
            'event_id': event.event_id,
        }
        body = json.dumps(payload, ensure_ascii=False, separators=(',', ':'))
        timestamp = str(int(time.time()))
        nonce = event.event_id[:32]
        message = f'{timestamp}.{nonce}.{body}'
        signature = hmac_sha256(app_row.app_secret, message)

        headers = {
            'Content-Type': 'application/json',
            'X-App-Code': order.app_code,
            'X-Pay-Timestamp': timestamp,
            'X-Pay-Nonce': nonce,
            'X-Pay-Signature': signature,
            'X-Pay-Event': 'payment.success' if order.status == STATUS_PAID else f'payment.{order.status.lower()}',
        }

        import httpx
        success = False
        last_error = ''
        attempts = 0
        for attempt in range(1, FORWARD_MAX_RETRY + 1):
            attempts = attempt
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    response = await client.post(order.notify_url, content=body.encode('utf-8'),
                                                headers=headers)
                if 200 <= response.status_code < 300:
                    success = True
                    break
                last_error = f'HTTP {response.status_code}'
            except Exception as exc:  # noqa: BLE001
                last_error = str(exc)

            logger.warning(
                f'业务通知失败(第{attempt}次) out_trade_no={order.out_trade_no} '
                f'url={order.notify_url} err={last_error}'
            )
            if attempt < FORWARD_MAX_RETRY:
                import asyncio
                await asyncio.sleep(attempt * 2)

        order.notify_count = (order.notify_count or 0) + attempts
        if success:
            order.notify_status = 'SUCCESS'
            order.notified_at = datetime.now()
            logger.info(f'业务通知成功 out_trade_no={order.out_trade_no} url={order.notify_url}')
        else:
            order.notify_status = 'FAILED'
            logger.error(f'业务通知最终失败 out_trade_no={order.out_trade_no} err={last_error}')

        self.db.add(order)
        await self.db.commit()
        return success

    # ---------- 供业务平台主动查询时使用 ----------

    @staticmethod
    def build_query_signature(app_secret: str, timestamp: str, nonce: str, body: str) -> str:
        """生成查询应答签名（供业务平台验签）"""
        return hmac_sha256(app_secret, f'{timestamp}.{nonce}.{body}')
