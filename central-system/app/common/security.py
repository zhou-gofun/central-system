from fastapi import Header, HTTPException, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.common.database import get_db
from app.model.wechat.app import WechatApp


async def verify_app_request(
    x_app_code: str = Header(..., alias="X-App-Code"),
    x_app_secret: str = Header(..., alias="X-App-Secret"),
    db: AsyncSession = Depends(get_db)
) -> dict:
    """
    验证业务应用请求

    Args:
        x_app_code: 应用标识
        x_app_secret: 应用密钥
        db: 数据库会话

    Returns:
        dict: 包含app_code和mp_appid的字典

    Raises:
        HTTPException: 401 无效的应用凭证
    """
    result = await db.execute(
        select(WechatApp).where(
            WechatApp.app_code == x_app_code,
            WechatApp.app_secret == x_app_secret,
            WechatApp.status == 1
        )
    )
    app = result.scalar_one_or_none()

    if not app:
        raise HTTPException(status_code=401, detail="无效的应用凭证")

    return {
        "app_code": app.app_code,
        "mp_appid": app.mp_appid
    }
