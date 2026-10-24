from sqlalchemy import String, Integer, DateTime, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func
from sqlalchemy.dialects.postgresql import JSONB
from typing import Optional

from app.common.database import Base
from app.common.base import ULIDBaseMixin


class PayMerchant(ULIDBaseMixin, Base):
    """支付商户配置表：业务平台 × 支付渠道"""
    __tablename__ = 'pay_merchant'
    __table_args__ = (
        UniqueConstraint('app_code', 'provider', 'name', name='uq_pay_merchant'),
    )

    app_code: Mapped[str] = mapped_column(String(32), nullable=False, index=True, comment='归属的业务平台')
    provider: Mapped[str] = mapped_column(String(20), nullable=False, index=True, comment='支付渠道 wxpay/alipay/easypay')
    name: Mapped[str] = mapped_column(String(100), nullable=False, comment='商户配置名称')
    # 注意: SQLAlchemy 声明式基类已占用 config 属性名，列名仍为 config
    merchant_config: Mapped[dict] = mapped_column(
        'config', JSONB, nullable=False, default=dict, comment='渠道参数(含密钥)'
    )
    mp_appid: Mapped[Optional[str]] = mapped_column(String(50), comment='关联公众号AppID(微信JSAPI用)')
    status: Mapped[int] = mapped_column(Integer, default=1, comment='1=启用 0=禁用')
    remark: Mapped[Optional[str]] = mapped_column(String(500), comment='备注')
    created_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now(), comment='创建时间')
    updated_at: Mapped[DateTime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), comment='更新时间'
    )

    def __repr__(self):
        return f"<PayMerchant(app_code='{self.app_code}', provider='{self.provider}', name='{self.name}')>"
