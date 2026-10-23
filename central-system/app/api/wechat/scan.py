from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from typing import Optional, Dict
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.common.database import get_db
from app.common.security import verify_app_request
from app.service.wechat.scan_service import ScanService
from app.model.wechat.app import WechatApp

router = APIRouter(prefix="/api/v1/scan", tags=["扫码"])


class CreateScanRequest(BaseModel):
    """创建扫码会话请求"""
    purpose: str = Field(..., description="用途: login/register/bind")
    expire_seconds: int = Field(default=300, ge=60, le=600, description="过期时间(秒)")
    extra_data: Optional[Dict] = Field(default=None, description="额外数据")


class CreateScanResponse(BaseModel):
    """创建扫码会话响应"""
    scene_key: str
    qrcode_url: str
    expired_at: str


class ScanStatusResponse(BaseModel):
    """扫码状态响应"""
    status: int = Field(..., description="-2=过期 -1=无效 0=待扫码 1=已扫码 2=已消费")
    purpose: Optional[str] = None
    openid: Optional[str] = None
    unionid: Optional[str] = None
    nickname: Optional[str] = None
    headimgurl: Optional[str] = None


class ConsumeScanRequest(BaseModel):
    """消费扫码会话请求"""
    scene_key: str
    external_user_id: Optional[str] = Field(default=None, description="业务系统用户ID")


class ConsumeScanResponse(BaseModel):
    """消费扫码会话响应"""
    success: bool


@router.post("/create", response_model=CreateScanResponse)
async def create_scan(
    request: CreateScanRequest,
    app_info: dict = Depends(verify_app_request),
    db: AsyncSession = Depends(get_db)
):
    """
    创建扫码会话

    需要提供请求头：
    - X-App-Code: 应用标识
    - X-App-Secret: 应用密钥
    """
    if request.purpose not in ["login", "register", "bind"]:
        raise HTTPException(status_code=400, detail="purpose必须是login/register/bind之一")

    service = ScanService(db)
    result = await service.create_session(
        app_code=app_info["app_code"],
        mp_appid=app_info["mp_appid"],
        purpose=request.purpose,
        expire_seconds=request.expire_seconds,
        extra_data=request.extra_data
    )

    return result


@router.get("/status", response_model=ScanStatusResponse)
async def get_scan_status(
    scene_key: str,
    app_info: dict = Depends(verify_app_request),
    db: AsyncSession = Depends(get_db)
):
    """
    查询扫码状态

    需要提供请求头：
    - X-App-Code: 应用标识
    - X-App-Secret: 应用密钥
    """
    service = ScanService(db)
    result = await service.get_status(scene_key, app_info["app_code"])

    return result


@router.post("/consume", response_model=ConsumeScanResponse)
async def consume_scan(
    request: ConsumeScanRequest,
    app_info: dict = Depends(verify_app_request),
    db: AsyncSession = Depends(get_db)
):
    """
    消费扫码会话

    需要提供请求头：
    - X-App-Code: 应用标识
    - X-App-Secret: 应用密钥
    """
    service = ScanService(db)
    success = await service.consume_session(
        scene_key=request.scene_key,
        app_code=app_info["app_code"],
        external_user_id=request.external_user_id
    )

    return {"success": success}


@router.get("/qrcode")
async def get_wechat_qrcode(
    app_code: str,
    purpose: str = "login",
    expire_seconds: int = 300,
    db: AsyncSession = Depends(get_db)
):
    """
    获取微信登录二维码（简化版接口）

    兼容旧项目风格，通过 URL 参数传递认证信息

    参数：
    - app_code: 应用标识（必填）需要区分正式服与测试服，jgweb_test、jgweb_prod，所有业务系统都适用
    - purpose: 用途，默认 login（可选：login/register/bind）
    - expire_seconds: 过期时间（秒），默认 300 秒

    示例：
    GET /api/v1/scan/qrcode?app_code=jgweb_test&purpose=login

    返回：
    {
        "qrcode": "二维码URL",
        "scene_key": "场景值",
        "expired_at": "过期时间"
    }
    """
    # 验证 purpose
    if purpose not in ["login", "register", "bind"]:
        raise HTTPException(status_code=400, detail="purpose必须是login/register/bind之一")

    # 通过 app_code 查询应用信息
    result = await db.execute(
        select(WechatApp).where(WechatApp.app_code == app_code)
    )
    app = result.scalar_one_or_none()

    if not app:
        raise HTTPException(status_code=404, detail=f"应用 {app_code} 不存在")

    # 创建扫码会话
    service = ScanService(db)
    scan_result = await service.create_session(
        app_code=app.app_code,
        mp_appid=app.mp_appid,
        purpose=purpose,
        expire_seconds=expire_seconds,
        extra_data=None
    )

    # 返回结果（兼容旧接口格式）
    return {
        "qrcode": scan_result["qrcode_url"],
        "scene_key": scan_result["scene_key"],
        "expired_at": scan_result["expired_at"]
    }


@router.get("/check")
async def check_wechat_auth(
    app_code: str,
    scene_key: str,
    db: AsyncSession = Depends(get_db)
):
    """
    检查扫码状态（简化版接口）

    兼容旧项目风格，通过 URL 参数传递认证信息

    参数：
    - app_code: 应用标识（必填）
    - scene_key: 场景值（必填，对应旧项目的 logkey）

    示例：
    GET /api/v1/scan/check?app_code=spls&scene_key=xxx

    返回：
    {
        "status": "待扫码" | "已扫码" | "已消费" | "已过期" | "无效",
        "openid": "用户openid",
        "unionid": "用户unionid",
        "nickname": "用户昵称",
        "headimgurl": "用户头像"
    }
    """
    # 通过 app_code 查询应用信息（验证 app_code 是否有效）
    result = await db.execute(
        select(WechatApp).where(WechatApp.app_code == app_code)
    )
    app = result.scalar_one_or_none()

    if not app:
        raise HTTPException(status_code=404, detail=f"应用 {app_code} 不存在")

    # 查询扫码状态
    service = ScanService(db)
    scan_status = await service.get_status(scene_key, app_code)

    # 转换状态码为文字描述（兼容旧接口）
    status_map = {
        -2: "已过期",
        -1: "无效",
        0: "待扫码",
        1: "已扫码",
        2: "已消费"
    }

    return {
        "status": status_map.get(scan_status["status"], "未知"),
        "status_code": scan_status["status"],  # 同时返回数字状态码
        "openid": scan_status.get("openid", ""),
        "unionid": scan_status.get("unionid", ""),
        "nickname": scan_status.get("nickname", ""),
        "headimgurl": scan_status.get("headimgurl", "")
    }
