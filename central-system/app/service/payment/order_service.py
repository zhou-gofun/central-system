"""
支付订单服务

对外提供统一的下单/查单/关单入口，对下屏蔽各渠道差异。
订单号由中心系统生成（out_trade_no），业务平台自己的订单号存在 client_order_no，
配合 (app_code, client_order_no) 唯一索引实现下单幂等。
"""
import logging
import re
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Dict, List, Optional
from ulid import ULID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.model.payment.order import PayOrder
from app.model.payment.refund import PayRefund
from app.model.payment.notify_log import PayNotifyLog
from app.model.wechat.app import WechatApp
from app.service.payment.merchant_service import (
    MerchantService,
    check_trade_type,
    to_context,
)
from app.service.payment.provider import (
    PAID_STATUSES,
    PayError,
    STATUS_CLOSED,
    STATUS_PAID,
    STATUS_PENDING,
    get_provider,
)

logger = logging.getLogger(__name__)

# 业务平台订单号 -> 中心订单号 的前缀
ORDER_PREFIX = 'cs'
MAX_OUT_TRADE_NO = 32


def generate_out_trade_no() -> str:
    """生成中心系统订单号：cs_ + ULID（微信支付要求 6~32 位纯数字字母下划线）"""
    return f'{ORDER_PREFIX}_{ULID()}'[:MAX_OUT_TRADE_NO]


class OrderService:
    """支付订单服务"""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.merchant_service = MerchantService(db)

    # ---------- 下单 ----------

    async def create_order(
        self,
        app_code: str,
        provider: str,
        trade_type: str,
        subject: str,
        amount: Decimal,
        currency: str = 'CNY',
        payer_openid: Optional[str] = None,
        payer_id: Optional[str] = None,
        client_order_no: Optional[str] = None,
        merchant_id: Optional[str] = None,
        notify_url: Optional[str] = None,
        attach: Optional[str] = None,
        extra: Optional[Dict[str, Any]] = None,
        expire_minutes: int = 30,
        description: Optional[str] = None,
        notify_base_url: Optional[str] = None,
    ) -> PayOrder:
        """
        创建支付订单并向渠道下单

        Args:
            app_code: 业务平台标识
            provider: 支付渠道
            trade_type: 支付方式（jsapi/native/h5/app/page/wap/qr/redirect）
            subject: 订单标题
            amount: 金额（元）
            client_order_no: 业务平台自己的订单号，用于幂等
            notify_url: 支付成功后通知业务平台的地址（不传则用应用注册的 callback_url）
            notify_base_url: 中心系统对外地址，用于拼接渠道回调地址
        """
        if amount is None or amount <= 0:
            raise PayError('金额必须大于0', status_code=400, code='invalid_amount')

        check_trade_type(provider, trade_type)

        # 幂等：同一个 app_code + client_order_no 直接返回已有订单
        if client_order_no:
            existing = await self.db.execute(
                select(PayOrder).where(
                    PayOrder.app_code == app_code,
                    PayOrder.client_order_no == client_order_no,
                )
            )
            found = existing.scalar_one_or_none()
            if found:
                logger.info(f'命中幂等订单 {app_code}/{client_order_no} -> {found.out_trade_no}')
                return found

        # 选商户配置
        if merchant_id:
            merchant = await self.merchant_service.get(merchant_id)
            if not merchant:
                raise PayError(f'商户配置不存在: {merchant_id}', status_code=404, code='merchant_not_found')
            if merchant.app_code != app_code:
                raise PayError('商户配置不属于该业务平台', status_code=403, code='merchant_forbidden')
            if merchant.status != 1:
                raise PayError('商户配置已禁用', status_code=400, code='merchant_disabled')
        else:
            merchant = await self.merchant_service.find_default(app_code, provider)
            if not merchant:
                raise PayError(
                    f'业务平台 {app_code} 未配置 {provider} 支付通道，请先创建商户配置',
                    status_code=400,
                    code='merchant_not_configured',
                )

        ctx = to_context(merchant)
        impl = get_provider(provider)

        # 通知地址：优先用请求指定的，否则用应用注册的 callback_url
        target_notify_url = notify_url
        if not target_notify_url:
            app_result = await self.db.execute(
                select(WechatApp).where(WechatApp.app_code == app_code)
            )
            app_row = app_result.scalar_one_or_none()
            target_notify_url = app_row.callback_url if app_row else None

        # 渠道回调地址由中心系统持有，按商户配置编号路由
        base = (notify_base_url or '').rstrip('/')
        provider_notify_url = f'{base}/api/v1/pay/notify/{provider}/{merchant.id}'

        order = PayOrder(
            out_trade_no=generate_out_trade_no(),
            client_order_no=client_order_no,
            app_code=app_code,
            provider=provider,
            merchant_id=merchant.id,
            trade_type=trade_type,
            subject=subject[:200],
            description=description[:500] if description else None,
            amount=amount,
            currency=currency,
            payer_openid=payer_openid,
            payer_id=payer_id,
            notify_url=target_notify_url,
            provider_notify_url=provider_notify_url,
            attach=attach[:200] if attach else None,
            extra=extra or {},
            status=STATUS_PENDING,
            notify_status='PENDING',
            expires_at=datetime.now() + timedelta(minutes=expire_minutes),
        )
        self.db.add(order)
        await self.db.commit()
        await self.db.refresh(order)

        # 向渠道下单
        try:
            result = await impl.create_order(ctx, order)
        except Exception:
            await self.db.delete(order)
            await self.db.commit()
            raise

        order.provider_trade_no = result.provider_trade_no
        order.provider_prepay_id = result.prepay_id
        order.pay_params = result.pay_params
        order.provider_snapshot = result.snapshot
        self.db.add(order)
        await self.db.commit()
        await self.db.refresh(order)

        logger.info(
            f'创建支付订单 {order.out_trade_no} app={app_code} provider={provider} '
            f'type={trade_type} amount={amount}'
        )
        return order

    # ---------- 查询 ----------

    async def get_order(self, out_trade_no: str, app_code: Optional[str] = None) -> Optional[PayOrder]:
        stmt = select(PayOrder).where(PayOrder.out_trade_no == out_trade_no)
        if app_code:
            stmt = stmt.where(PayOrder.app_code == app_code)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def list_orders(
        self,
        app_code: Optional[str] = None,
        status: Optional[str] = None,
        provider: Optional[str] = None,
        client_order_no: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Dict[str, Any]:
        """分页查询订单"""
        page = max(1, page)
        page_size = min(200, max(1, page_size))

        stmt = select(PayOrder)
        count_stmt = select(func.count()).select_from(PayOrder)

        conditions = []
        if app_code:
            conditions.append(PayOrder.app_code == app_code)
        if status:
            conditions.append(PayOrder.status == status)
        if provider:
            conditions.append(PayOrder.provider == provider)
        if client_order_no:
            conditions.append(PayOrder.client_order_no == client_order_no)

        for cond in conditions:
            stmt = stmt.where(cond)
            count_stmt = count_stmt.where(cond)

        total = (await self.db.execute(count_stmt)).scalar_one()
        stmt = stmt.order_by(PayOrder.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
        rows = (await self.db.execute(stmt)).scalars().all()

        return {
            'total': total,
            'page': page,
            'page_size': page_size,
            'items': list(rows),
        }

    # ---------- 关单 ----------

    async def close_order(self, out_trade_no: str, app_code: Optional[str] = None) -> PayOrder:
        order = await self.get_order(out_trade_no, app_code)
        if not order:
            raise PayError('订单不存在', status_code=404, code='order_not_found')
        if order.status in PAID_STATUSES:
            raise PayError('订单已支付，不能关闭', status_code=400, code='order_already_paid')
        if order.status == STATUS_CLOSED:
            return order

        merchant = await self.merchant_service.get(order.merchant_id)
        if not merchant:
            raise PayError('商户配置不存在', status_code=404, code='merchant_not_found')

        impl = get_provider(order.provider)
        try:
            await impl.close_order(to_context(merchant), order)
        except PayError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning(f'关单失败 {out_trade_no}: {exc}')

        order.status = STATUS_CLOSED
        order.closed_at = datetime.now()
        self.db.add(order)
        await self.db.commit()
        await self.db.refresh(order)
        return order

    # ---------- 主动查单（对账） ----------

    async def sync_order(self, out_trade_no: str, app_code: Optional[str] = None) -> PayOrder:
        """向渠道查单并同步状态"""
        order = await self.get_order(out_trade_no, app_code)
        if not order:
            raise PayError('订单不存在', status_code=404, code='order_not_found')
        if order.status in PAID_STATUSES:
            return order

        merchant = await self.merchant_service.get(order.merchant_id)
        if not merchant:
            raise PayError('商户配置不存在', status_code=404, code='merchant_not_found')

        impl = get_provider(order.provider)
        result = await impl.query_order(to_context(merchant), order)

        if result.provider_trade_no:
            order.provider_trade_no = result.provider_trade_no
        if result.status == STATUS_PAID:
            if result.amount is not None and result.amount != order.amount:
                logger.error(
                    f'订单金额不一致 {out_trade_no}: 本地={order.amount} 渠道={result.amount}'
                )
            order.status = STATUS_PAID
            order.paid_at = result.paid_at or datetime.now()
        elif result.status == STATUS_CLOSED:
            order.status = STATUS_CLOSED
            order.closed_at = datetime.now()

        self.db.add(order)
        await self.db.commit()
        await self.db.refresh(order)
        return order

    # ---------- 退款 ----------

    async def create_refund(
        self,
        out_trade_no: str,
        app_code: Optional[str] = None,
        amount: Optional[Decimal] = None,
        reason: Optional[str] = None,
        refund_no: Optional[str] = None,
    ) -> PayRefund:
        order = await self.get_order(out_trade_no, app_code)
        if not order:
            raise PayError('订单不存在', status_code=404, code='order_not_found')
        if order.status not in PAID_STATUSES:
            raise PayError('订单未支付，不能退款', status_code=400, code='order_not_paid')

        refund_amount = amount if amount is not None else order.amount
        if refund_amount <= 0 or refund_amount > order.amount:
            raise PayError('退款金额不合法', status_code=400, code='invalid_amount')

        merchant = await self.merchant_service.get(order.merchant_id)
        if not merchant:
            raise PayError('商户配置不存在', status_code=404, code='merchant_not_found')

        refund = PayRefund(
            refund_no=refund_no or f'rf_{ULID()}'[:32],
            out_trade_no=order.out_trade_no,
            app_code=order.app_code,
            provider=order.provider,
            amount=refund_amount,
            total_amount=order.amount,
            reason=reason[:200] if reason else None,
            status='PENDING',
        )
        self.db.add(refund)
        await self.db.commit()
        await self.db.refresh(refund)

        impl = get_provider(order.provider)
        try:
            result = await impl.refund(to_context(merchant), order, refund)
        except Exception:
            await self.db.delete(refund)
            await self.db.commit()
            raise

        refund.provider_refund_no = result.provider_refund_no
        refund.status = result.status
        self.db.add(refund)
        await self.db.commit()
        await self.db.refresh(refund)

        if result.status == 'SUCCESS':
            if refund.amount >= order.amount:
                order.status = 'REFUNDED'
            else:
                order.status = 'PARTIALLY_REFUNDED'
            self.db.add(order)
            await self.db.commit()
            await self.db.refresh(order)

        logger.info(f'创建退款 {refund.refund_no} 订单={order.out_trade_no} 金额={refund_amount}')
        return refund

    async def get_refund(self, refund_no: str, app_code: Optional[str] = None) -> Optional[PayRefund]:
        stmt = select(PayRefund).where(PayRefund.refund_no == refund_no)
        if app_code:
            stmt = stmt.where(PayRefund.app_code == app_code)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()
