from sqlalchemy import String, Integer, DateTime
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.common.database import Base
from app.common.base import ULIDBaseMixin


class WechatMpConfig(ULIDBaseMixin, Base):
    """微信公众号配置表"""
    __tablename__ = 'wechat_mp_config'

    appid: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True, comment='公众号AppID')
    secret: Mapped[str] = mapped_column(String(100), nullable=False, comment='公众号Secret')
    token: Mapped[str] = mapped_column(String(100), nullable=False, comment='微信Token')
    aes_key: Mapped[str] = mapped_column(String(100), comment='消息加密密钥')
    name: Mapped[str] = mapped_column(String(100), comment='公众号名称')
    status: Mapped[int] = mapped_column(Integer, default=1, comment='1=启用 0=禁用')
    created_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now(), comment='创建时间')

    def __repr__(self):
        return f"<WechatMpConfig(appid='{self.appid}', name='{self.name}')>"
