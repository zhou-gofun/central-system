"""
数据模型注册

导入所有模型，以便 SQLAlchemy 可以发现它们
"""
from app.common.database import Base
from app.common.base import ULIDBaseMixin

# 导入所有模型（确保 SQLAlchemy 可以发现它们）
from app.model.wechat.app import WechatApp
from app.model.wechat.mp_config import WechatMpConfig
from app.model.wechat.session import ScanSession

# 导出所有模型
__all__ = [
    "Base",
    "ULIDBaseMixin",
    "WechatApp",
    "WechatMpConfig",
    "ScanSession",
]
