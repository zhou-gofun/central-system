import httpx
from typing import Dict, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime, timedelta
import logging

from app.model.wechat.mp_config import WechatMpConfig

logger = logging.getLogger(__name__)


class WechatMPService:
    """微信公众号服务"""

    def __init__(self, mp_appid: str, db: AsyncSession):
        self.mp_appid = mp_appid
        self.db = db
        self._access_token: Optional[str] = None
        self._token_expires_at: Optional[datetime] = None

    async def _get_mp_config(self) -> WechatMpConfig:
        """获取公众号配置"""
        result = await self.db.execute(
            select(WechatMpConfig).where(
                WechatMpConfig.appid == self.mp_appid,
                WechatMpConfig.status == 1
            )
        )
        config = result.scalar_one_or_none()
        if not config:
            raise ValueError(f"公众号配置不存在: {self.mp_appid}")
        return config

    async def _get_access_token(self) -> str:
        """获取access_token"""
        # 检查缓存
        if self._access_token and self._token_expires_at:
            if datetime.now() < self._token_expires_at:
                logger.info(f"使用缓存的 access_token (appid={self.mp_appid})")
                return self._access_token

        # 从微信服务器获取
        config = await self._get_mp_config()
        url = "https://api.weixin.qq.com/cgi-bin/token"
        params = {
            "grant_type": "client_credential",
            "appid": config.appid,
            "secret": config.secret
        }

        logger.info(f"正在获取 access_token (appid={config.appid})")

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(url, params=params)
                data = response.json()

                if "access_token" in data:
                    self._access_token = data["access_token"]
                    # 提前5分钟过期
                    expires_in = data.get("expires_in", 7200) - 300
                    self._token_expires_at = datetime.now() + timedelta(seconds=expires_in)
                    logger.info(f"成功获取 access_token (appid={config.appid}, expires_in={expires_in}s)")
                    return self._access_token
                else:
                    logger.error(f"获取 access_token 失败 (appid={config.appid}): {data}")
                    raise Exception(f"获取access_token失败: {data}")
        except httpx.TimeoutException as e:
            logger.error(f"获取 access_token 超时 (appid={config.appid}): {e}")
            raise Exception(f"获取access_token超时: 无法连接到微信服务器")
        except httpx.RequestError as e:
            logger.error(f"获取 access_token 网络错误 (appid={config.appid}): {e}")
            raise Exception(f"获取access_token网络错误: {e}")

    async def create_qrcode(self, scene_key: str, expire_seconds: int = 300) -> Dict:
        """
        创建临时二维码

        Args:
            scene_key: 场景值
            expire_seconds: 过期时间(秒)

        Returns:
            dict: {"ticket": "...", "url": "https://mp.weixin.qq.com/..."}
        """
        access_token = await self._get_access_token()
        url = f"https://api.weixin.qq.com/cgi-bin/qrcode/create?access_token={access_token}"

        payload = {
            "expire_seconds": expire_seconds,
            "action_name": "QR_STR_SCENE",
            "action_info": {
                "scene": {
                    "scene_str": scene_key
                }
            }
        }

        logger.info(f"正在创建二维码 (scene_key={scene_key}, expire_seconds={expire_seconds})")

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(url, json=payload)
                data = response.json()

                if "ticket" in data:
                    qrcode_url = f"https://mp.weixin.qq.com/cgi-bin/showqrcode?ticket={data['ticket']}"
                    logger.info(f"成功创建二维码 (scene_key={scene_key})")
                    return {
                        "ticket": data["ticket"],
                        "url": qrcode_url
                    }
                else:
                    logger.error(f"创建二维码失败 (scene_key={scene_key}): {data}")
                    raise Exception(f"创建二维码失败: {data}")
        except httpx.TimeoutException as e:
            logger.error(f"创建二维码超时 (scene_key={scene_key}): {e}")
            raise Exception(f"创建二维码超时: 无法连接到微信服务器")
        except httpx.RequestError as e:
            logger.error(f"创建二维码网络错误 (scene_key={scene_key}): {e}")
            raise Exception(f"创建二维码网络错误: {e}")

    async def get_user_info(self, openid: str) -> Dict:
        """
        获取用户信息

        Args:
            openid: 用户的openid

        Returns:
            dict: 用户信息字典
        """
        access_token = await self._get_access_token()
        url = "https://api.weixin.qq.com/cgi-bin/user/info"
        params = {
            "access_token": access_token,
            "openid": openid,
            "lang": "zh_CN"
        }

        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(url, params=params)
            data = response.json()

            if "openid" in data:
                return {
                    "openid": data.get("openid"),
                    "unionid": data.get("unionid"),
                    "nickname": data.get("nickname"),
                    "headimgurl": data.get("headimgurl")
                }
            else:
                raise Exception(f"获取用户信息失败: {data}")
