from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import hashlib
import xml.etree.ElementTree as ET

from app.common.database import get_db
from app.model.wechat.mp_config import WechatMpConfig
from app.service.wechat.scan_service import ScanService

router = APIRouter(prefix="/api/v1/wechat", tags=["微信回调"])


def verify_signature(token: str, signature: str, timestamp: str, nonce: str) -> bool:
    """验证微信签名"""
    tmp_list = sorted([token, timestamp, nonce])
    tmp_str = "".join(tmp_list)
    tmp_hash = hashlib.sha1(tmp_str.encode()).hexdigest()
    return tmp_hash == signature


@router.get("/callback/{mp_appid}")
async def wechat_callback_verify(
    mp_appid: str,
    signature: str = Query(...),
    timestamp: str = Query(...),
    nonce: str = Query(...),
    echostr: str = Query(...),
    db: AsyncSession = Depends(get_db)
):
    """
    微信服务器验证

    微信在配置URL时会发送GET请求验证服务器
    """
    # 获取公众号配置
    result = await db.execute(
        select(WechatMpConfig).where(
            WechatMpConfig.appid == mp_appid,
            WechatMpConfig.status == 1
        )
    )
    config = result.scalar_one_or_none()

    if not config:
        return Response(content="invalid appid", status_code=404)

    # 验证签名
    if verify_signature(config.token, signature, timestamp, nonce):
        return Response(content=echostr)
    else:
        return Response(content="invalid signature", status_code=403)


@router.post("/callback/{mp_appid}")
async def wechat_callback_event(
    mp_appid: str,
    request: Request,
    signature: str = Query(...),
    timestamp: str = Query(...),
    nonce: str = Query(...),
    db: AsyncSession = Depends(get_db)
):
    """
    接收微信事件推送

    处理用户扫码事件
    """
    # 获取公众号配置
    result = await db.execute(
        select(WechatMpConfig).where(
            WechatMpConfig.appid == mp_appid,
            WechatMpConfig.status == 1
        )
    )
    config = result.scalar_one_or_none()

    if not config:
        return Response(content="success", media_type="text/plain")

    # 验证签名
    if not verify_signature(config.token, signature, timestamp, nonce):
        return Response(content="success", media_type="text/plain")

    # 解析XML消息
    body = await request.body()
    try:
        root = ET.fromstring(body.decode("utf-8"))
        msg_type = root.find("MsgType").text
        event = root.find("Event").text if root.find("Event") is not None else None

        # 处理扫码事件
        if msg_type == "event" and event in ["SCAN", "subscribe"]:
            openid = root.find("FromUserName").text
            event_key = root.find("EventKey").text

            # subscribe事件的EventKey格式是qrscene_xxx，需要去掉前缀
            if event == "subscribe" and event_key.startswith("qrscene_"):
                scene_key = event_key[8:]
            else:
                scene_key = event_key

            # 处理扫码
            scan_service = ScanService(db)
            await scan_service.handle_scan_event(mp_appid, scene_key, openid)

    except Exception as e:
        print(f"处理微信回调异常: {e}")

    # 返回success给微信服务器
    return Response(content="success", media_type="text/plain")
