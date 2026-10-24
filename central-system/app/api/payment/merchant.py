"""
支付商户配置管理接口（管理端）

这类接口涉及商户私钥、APIv3 密钥等敏感信息，因此不走业务应用的 app_secret，
而是要求独立的 X-Pay-Admin-Key（由部署时的 PAY_ADMIN_KEY 环境变量指定）。
"""
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.config import settings
from app.common.database import get_db
from app.service.payment.merchant_service import MerchantService, mask_config
from app.service.payment.provider import PayError, list_providers

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/pay/merchant", tags=["支付商户配置"])


def verify_pay_admin(
    x_pay_admin_key: str = Header(..., alias='X-Pay-Admin-Key')
) -> bool:
    """校验支付管理端密钥"""
    expected = settings.PAY_ADMIN_KEY
    if not expected:
        raise HTTPException(status_code=503, detail='支付管理接口未启用(未配置 PAY_ADMIN_KEY)')
    if x_pay_admin_key != expected:
        raise HTTPException(status_code=401, detail='管理密钥无效')
    return True


class MerchantCreateRequest(BaseModel):
    app_code: str = Field(..., description='业务平台标识')
    provider: str = Field(..., description='支付渠道 wxpay/alipay/easypay')
    name: str = Field(default='default', description='商户配置名称，同平台同渠道下唯一')
    config: Dict[str, Any] = Field(..., description='渠道参数(含密钥)')
    mp_appid: Optional[str] = Field(default=None, description='关联公众号AppID(微信JSAPI用)')
    remark: Optional[str] = Field(default=None)


class MerchantUpdateRequest(BaseModel):
    config: Optional[Dict[str, Any]] = Field(default=None, description='渠道参数(含密钥)')
    mp_appid: Optional[str] = Field(default=None)
    remark: Optional[str] = Field(default=None)
    status: Optional[int] = Field(default=None, description='1=启用 0=禁用')


class MerchantItem(BaseModel):
    id: str
    app_code: str
    provider: str
    name: str
    config: Dict[str, Any]
    mp_appid: Optional[str] = None
    status: int
    remark: Optional[str] = None
    created_at: str
    updated_at: str


def _merchant_item(merchant) -> MerchantItem:
    return MerchantItem(
        id=merchant.id,
        app_code=merchant.app_code,
        provider=merchant.provider,
        name=merchant.name,
        config=mask_config(merchant.merchant_config),
        mp_appid=merchant.mp_appid,
        status=merchant.status,
        remark=merchant.remark,
        created_at=merchant.created_at.isoformat() if merchant.created_at else '',
        updated_at=merchant.updated_at.isoformat() if merchant.updated_at else '',
    )


@router.get("/providers")
async def get_providers(_: bool = Depends(verify_pay_admin)):
    """列出支持的支付渠道"""
    return {'providers': list_providers()}


@router.get("", response_model=List[MerchantItem])
async def list_merchants(
    app_code: Optional[str] = Query(default=None),
    provider: Optional[str] = Query(default=None),
    _: bool = Depends(verify_pay_admin),
    db: AsyncSession = Depends(get_db)
):
    """查询商户配置列表（密钥已打码）"""
    service = MerchantService(db)
    merchants = await service.list(app_code, provider)
    return [_merchant_item(m) for m in merchants]


@router.post("", response_model=MerchantItem)
async def create_merchant(
    request: MerchantCreateRequest,
    _: bool = Depends(verify_pay_admin),
    db: AsyncSession = Depends(get_db)
):
    """创建商户配置"""
    service = MerchantService(db)
    try:
        merchant = await service.create(
            app_code=request.app_code,
            provider=request.provider,
            name=request.name,
            config=request.config,
            mp_appid=request.mp_appid,
            remark=request.remark,
        )
    except PayError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message)
    return _merchant_item(merchant)


@router.put("/{merchant_id}", response_model=MerchantItem)
async def update_merchant(
    merchant_id: str,
    request: MerchantUpdateRequest,
    _: bool = Depends(verify_pay_admin),
    db: AsyncSession = Depends(get_db)
):
    """更新商户配置"""
    service = MerchantService(db)
    try:
        merchant = await service.update(
            merchant_id,
            config=request.config,
            mp_appid=request.mp_appid,
            remark=request.remark,
            status=request.status,
        )
    except PayError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message)
    if not merchant:
        raise HTTPException(status_code=404, detail='商户配置不存在')
    return _merchant_item(merchant)


@router.delete("/{merchant_id}")
async def delete_merchant(
    merchant_id: str,
    _: bool = Depends(verify_pay_admin),
    db: AsyncSession = Depends(get_db)
):
    """删除商户配置"""
    service = MerchantService(db)
    ok = await service.delete(merchant_id)
    if not ok:
        raise HTTPException(status_code=404, detail='商户配置不存在')
    return {'success': True}
