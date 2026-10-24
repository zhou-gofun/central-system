from sqlalchemy import String, DateTime, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func
from typing import Optional

from app.common.database import Base
from app.common.base import ULIDBaseMixin


class PayNotifyLog(ULIDBaseMixin, Base):
    """支付回调通知日志（幂等控制）"""
    __tablename__ = 'pay_notify_log'
    __table_args__ = (
        UniqueConstraint('provider', 'event_id', name='uq_pay_notify_event'),
    )

    provider: Mapped[str] = mapped_column(String(20), nullable=False, index=True, comment='支付渠道')
    event_id: Mapped[str] = mapped_column(String(128), nullable=False, comment='渠道事件ID，同渠道唯一')
    out_trade_no: Mapped[Optional[str]] = mapped_column(String(64), index=True, comment='中心系统订单号')
    provider_trade_no: Mapped[Optional[str]] = mapped_column(String(128), index=True, comment='渠道交易号')
    event_type: Mapped[Optional[str]] = mapped_column(String(50), comment='事件类型')
    result: Mapped[str] = mapped_column(String(20), comment='SUCCESS/DUPLICATE/AMOUNT_MISMATCH/FAILED')
    message: Mapped[Optional[str]] = mapped_column(Text, comment='处理说明')
    raw_body: Mapped[Optional[str]] = mapped_column(Text, comment='原始报文')
    created_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now(), comment='创建时间')

    def __repr__(self):
        return f"<PayNotifyLog(provider='{self.provider}', event_id='{self.event_id}', result='{self.result}')>"
