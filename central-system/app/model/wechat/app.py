from sqlalchemy import String, Integer, DateTime
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func
from typing import Optional

from app.common.database import Base
from app.common.base import ULIDBaseMixin


class WechatApp(ULIDBaseMixin, Base):
    """业务应用表"""
    __tablename__ = 'wechat_app'

    app_code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False, index=True, comment='应用标识 如jgweb_prod')
    app_name: Mapped[Optional[str]] = mapped_column(String(100), comment='应用名称')
    app_secret: Mapped[str] = mapped_column(String(64), nullable=False, comment='应用密钥')
    mp_appid: Mapped[Optional[str]] = mapped_column(String(50), comment='绑定的公众号AppID')
    callback_url: Mapped[Optional[str]] = mapped_column(String(500), comment='回调地址(可选)')
    status: Mapped[int] = mapped_column(Integer, default=1, comment='1=启用 0=禁用')
    created_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now(), comment='创建时间')

    def __repr__(self):
        return f"<WechatApp(app_code='{self.app_code}', app_name='{self.app_name}')>"
