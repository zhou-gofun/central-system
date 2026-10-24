from decimal import Decimal
from sqlalchemy import String, DateTime, Numeric
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func
from typing import Optional

from app.common.database import Base
from app.common.base import ULIDBaseMixin


class PayRefund(ULIDBaseMixin, Base):
    """退款单表"""
    __tablename__ = 'pay_refund'

    refund_no: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True, comment='中心系统退款单号')
    out_trade_no: Mapped[str] = mapped_column(String(64), nullable=False, index=True, comment='原订单号')
    app_code: Mapped[str] = mapped_column(String(32), nullable=False, index=True, comment='业务平台')
    provider: Mapped[str] = mapped_column(String(20), nullable=False, comment='支付渠道')
    provider_refund_no: Mapped[Optional[str]] = mapped_column(String(128), index=True, comment='渠道退款单号')
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, comment='退款金额(元)')
    total_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, comment='原订单金额(元)')
    reason: Mapped[Optional[str]] = mapped_column(String(200), comment='退款原因')
    status: Mapped[str] = mapped_column(String(20), default='PENDING', index=True, comment='PENDING/SUCCESS/FAILED')
    notify_status: Mapped[str] = mapped_column(String(20), default='PENDING', comment='通知状态')
    created_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now(), comment='创建时间')
    updated_at: Mapped[DateTime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), comment='更新时间'
    )

    def __repr__(self):
        return f"<PayRefund(refund_no='{self.refund_no}', status='{self.status}')>"
