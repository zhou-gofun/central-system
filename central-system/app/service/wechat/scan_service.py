from ulid import ULID
from datetime import datetime, timedelta
from typing import Dict, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update

from app.model.wechat.session import ScanSession
from app.service.wechat.mp_service import WechatMPService


def generate_ulid() -> str:
    """生成ULID格式的ID"""
    return str(ULID())


class ScanService:
    """扫码会话服务"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_session(
        self,
        app_code: str,
        mp_appid: str,
        purpose: str,
        expire_seconds: int = 300,
        extra_data: Optional[Dict] = None
    ) -> Dict:
        """
        创建扫码会话

        Args:
            app_code: 应用标识
            mp_appid: 公众号AppID
            purpose: 用途 (login/register/bind)
            expire_seconds: 过期时间(秒)
            extra_data: 额外数据

        Returns:
            dict: 包含scene_key、qrcode_url、expired_at的字典
        """
        # 生成场景值（使用ULID保证时间有序，提升索引效率）
        scene_key = f"{purpose[:3]}_{ULID()}"
        expired_at = datetime.now() + timedelta(seconds=expire_seconds)

        # 创建微信二维码
        mp_service = WechatMPService(mp_appid, self.db)
        qrcode = await mp_service.create_qrcode(scene_key, expire_seconds)

        # 保存会话
        session = ScanSession(
            id=generate_ulid(),
            scene_key=scene_key,
            app_code=app_code,
            mp_appid=mp_appid,
            purpose=purpose,
            expired_at=expired_at,
            extra_data=extra_data,
            status=0
        )
        self.db.add(session)
        await self.db.commit()

        return {
            "scene_key": scene_key,
            "qrcode_url": qrcode["url"],
            "expired_at": expired_at.isoformat()
        }

    async def handle_scan_event(self, mp_appid: str, scene_key: str, openid: str):
        """
        处理扫码事件

        Args:
            mp_appid: 公众号AppID
            scene_key: 场景值
            openid: 用户openid
        """
        # 查询会话
        result = await self.db.execute(
            select(ScanSession).where(
                ScanSession.scene_key == scene_key,
                ScanSession.mp_appid == mp_appid,
                ScanSession.status == 0
            )
        )
        session = result.scalar_one_or_none()

        if not session:
            return

        # 获取用户信息
        mp_service = WechatMPService(mp_appid, self.db)
        user_info = await mp_service.get_user_info(openid)

        # 更新会话
        session.openid = openid
        session.unionid = user_info.get("unionid")
        session.nickname = user_info.get("nickname")
        session.headimgurl = user_info.get("headimgurl")
        session.status = 1

        await self.db.commit()

    async def get_status(self, scene_key: str, app_code: str) -> Dict:
        """
        查询扫码状态

        Args:
            scene_key: 场景值
            app_code: 应用标识

        Returns:
            dict: 状态信息
        """
        result = await self.db.execute(
            select(ScanSession).where(
                ScanSession.scene_key == scene_key,
                ScanSession.app_code == app_code
            )
        )
        session = result.scalar_one_or_none()

        if not session:
            return {"status": -1}  # 无效

        # 检查是否过期
        if datetime.now() > session.expired_at:
            return {"status": -2}  # 过期

        # 构建返回数据
        result_data = {
            "status": session.status,
            "purpose": session.purpose
        }

        # 已扫码时返回用户信息
        if session.status >= 1:
            result_data.update({
                "openid": session.openid,
                "unionid": session.unionid,
                "nickname": session.nickname,
                "headimgurl": session.headimgurl
            })

        return result_data

    async def consume_session(
        self,
        scene_key: str,
        app_code: str,
        external_user_id: Optional[str] = None
    ) -> bool:
        """
        消费会话（标记为已使用）

        Args:
            scene_key: 场景值
            app_code: 应用标识
            external_user_id: 业务系统用户ID（可选）

        Returns:
            bool: 是否消费成功
        """
        result = await self.db.execute(
            update(ScanSession)
            .where(
                ScanSession.scene_key == scene_key,
                ScanSession.app_code == app_code,
                ScanSession.status == 1
            )
            .values(status=2)
        )
        await self.db.commit()

        return result.rowcount > 0
