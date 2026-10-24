from datetime import datetime
from decimal import Decimal
from sqlalchemy import String, Integer, DateTime, Numeric, Index
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func
from sqlalchemy.dialects.postgresql import JSONB
from typing import Optional

from app.common.database import Base
from app.common.base import ULIDBaseMixin


class PayOrder(ULIDBaseMixin, Base):
    """支付订单台账"""
    __tablename__ = 'pay_order'

    out_trade_no: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True, comment='中心系统生成的商户订单号')
    client_order_no: Mapped[Optional[str]] = mapped_column(String(64), index=True, comment='业务平台自己的订单号(幂等用)')
    __table_args__ = (
        # Postgres 唯一索引中 NULL 互不相等，多笔无 client_order_no 的订单不会冲突
        Index('idx_pay_order_client_no', 'app_code', 'client_order_no', unique=True),
    )
    app_code: Mapped[str] = mapped_column(String(32), nullable=False, index=True, comment='下单的业务平台')
    provider: Mapped[str] = mapped_column(String(20), nullable=False, index=True, comment='支付渠道')
    merchant_id: Mapped[Optional[str]] = mapped_column(String(26), index=True, comment='使用的商户配置ID')
    trade_type: Mapped[str] = mapped_column(String(20), nullable=False, comment='jsapi/native/h5/app/page/wap/qr')
    subject: Mapped[Optional[str]] = mapped_column(String(200), comment='订单标题')
    description: Mapped[Optional[str]] = mapped_column(String(500), comment='订单描述')
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, comment='订单金额(元)')
    currency: Mapped[str] = mapped_column(String(3), default='CNY', comment='币种')
    payer_openid: Mapped[Optional[str]] = mapped_column(String(100), comment='付款人openid(JSAPI)')
    payer_id: Mapped[Optional[str]] = mapped_column(String(100), comment='付款人渠道用户ID')
    pay_params: Mapped[Optional[dict]] = mapped_column(JSONB, comment='前端拉起支付所需参数')
    provider_trade_no: Mapped[Optional[str]] = mapped_column(String(128), index=True, comment='渠道交易号')
    provider_prepay_id: Mapped[Optional[str]] = mapped_column(String(128), comment='渠道预支付ID')
    status: Mapped[str] = mapped_column(String(20), default='PENDING', index=True, comment='PENDING/PAID/FAILED/CLOSED/REFUNDED/PARTIALLY_REFUNDED')
    notify_status: Mapped[str] = mapped_column(String(20), default='PENDING', comment='对业务平台的通知状态')
    notify_count: Mapped[int] = mapped_column(Integer, default=0, comment='通知次数')
    notified_at: Mapped[Optional[datetime]] = mapped_column(DateTime, comment='通知成功时间')
    paid_at: Mapped[Optional[datetime]] = mapped_column(DateTime, comment='支付成功时间')
    closed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, comment='关单时间')
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, comment='订单过期时间')
    attach: Mapped[Optional[str]] = mapped_column(String(200), comment='业务透传参数')
    notify_url: Mapped[Optional[str]] = mapped_column(String(500), comment='支付成功后通知业务平台的地址')
    provider_notify_url: Mapped[Optional[str]] = mapped_column(String(500), comment='提交给支付渠道的回调地址')
    provider_snapshot: Mapped[Optional[dict]] = mapped_column(JSONB, comment='下单时渠道关键参数快照(用于回调校验)')
    extra: Mapped[Optional[dict]] = mapped_column(JSONB, comment='扩展信息')
    created_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now(), index=True, comment='创建时间')
    updated_at: Mapped[DateTime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), comment='更新时间'
    )

    def __repr__(self):
        return f"<PayOrder(out_trade_no='{self.out_trade_no}', status='{self.status}')>"
