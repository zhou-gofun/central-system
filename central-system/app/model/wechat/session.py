from sqlalchemy import String, Integer, DateTime, Text
from sqlalchemy.dialects.postgresql import JSON
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func
from typing import Optional, Dict, Any
from datetime import datetime

from app.common.database import Base
from app.common.base import ULIDBaseMixin


class ScanSession(ULIDBaseMixin, Base):
    """扫码会话表"""
    __tablename__ = 'wechat_scan_session'

    scene_key: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True, comment='场景值')
    app_code: Mapped[str] = mapped_column(String(32), nullable=False, index=True, comment='来源应用')
    mp_appid: Mapped[Optional[str]] = mapped_column(String(50), comment='公众号AppID')
    purpose: Mapped[str] = mapped_column(String(20), nullable=False, comment='login/register/bind')
    openid: Mapped[Optional[str]] = mapped_column(String(100), comment='微信openid')
    unionid: Mapped[Optional[str]] = mapped_column(String(100), comment='微信unionid')
    nickname: Mapped[Optional[str]] = mapped_column(String(100), comment='微信昵称')
    headimgurl: Mapped[Optional[str]] = mapped_column(Text, comment='头像URL')
    status: Mapped[int] = mapped_column(Integer, default=0, index=True, comment='0=待扫码 1=已扫码 2=已消费')
    extra_data: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, comment='额外数据')
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), comment='创建时间')
    expired_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True, comment='过期时间')

    def __repr__(self):
        return f"<ScanSession(scene_key='{self.scene_key}', status={self.status})>"
