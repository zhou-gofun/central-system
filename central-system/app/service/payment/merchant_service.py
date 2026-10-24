"""
支付商户配置服务

一个业务平台（app_code）在一个支付渠道（provider）下可以有多套商户配置，
但默认使用创建时标记为 default 的那套。
"""
import logging
from typing import Any, Dict, List, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.model.payment.merchant import PayMerchant
from app.service.payment.provider import PayError, get_provider

logger = logging.getLogger(__name__)

# 各渠道必填的配置字段
REQUIRED_FIELDS: Dict[str, List[str]] = {
    'wxpay': ['mch_id', 'api_v3_key', 'cert_serial_no', 'private_key_pem'],
    'alipay': ['app_id', 'app_private_key'],
    'easypay': ['pid', 'key', 'gateway'],
}

# 敏感字段，接口返回时打码
SECRET_FIELDS = {
    'api_v3_key', 'private_key_pem', 'public_key_pem', 'platform_cert_pem',
    'app_private_key', 'alipay_public_key', 'key',
}


def mask_config(config: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """隐藏密钥字段"""
    if not config:
        return {}
    masked = {}
    for key, value in config.items():
        if key in SECRET_FIELDS and value:
            text = str(value)
            masked[key] = f'{text[:4]}****{text[-4:]}' if len(text) > 12 else '****'
        else:
            masked[key] = value
    return masked


class MerchantService:
    """商户配置 CRUD"""

    def __init__(self, db: AsyncSession):
        self.db = db

    @staticmethod
    def validate(provider: str, config: Dict[str, Any]) -> None:
        """校验渠道配置完整性"""
        if provider not in REQUIRED_FIELDS:
            raise PayError(f'不支持的支付渠道: {provider}', status_code=400, code='unsupported_provider')

        missing = [field for field in REQUIRED_FIELDS[provider] if not config.get(field)]
        if missing:
            raise PayError(
                f'{provider} 商户配置缺少字段: {", ".join(missing)}',
                status_code=400,
                code='merchant_config_invalid',
            )

        if provider == 'wxpay':
            key = str(config.get('api_v3_key', ''))
            if len(key.encode('utf-8')) != 32:
                raise PayError('微信支付 APIv3 密钥必须为 32 字节', status_code=400,
                               code='merchant_config_invalid')

    async def create(self, app_code: str, provider: str, name: str, config: Dict[str, Any],
                     mp_appid: Optional[str] = None, remark: Optional[str] = None) -> PayMerchant:
        self.validate(provider, config)

        existing = await self.db.execute(
            select(PayMerchant).where(
                PayMerchant.app_code == app_code,
                PayMerchant.provider == provider,
                PayMerchant.name == name,
            )
        )
        if existing.scalar_one_or_none():
            raise PayError(f'商户配置已存在: {app_code}/{provider}/{name}', status_code=409,
                           code='merchant_exists')

        merchant = PayMerchant(
            app_code=app_code,
            provider=provider,
            name=name,
            merchant_config=config,
            mp_appid=mp_appid,
            remark=remark,
            status=1,
        )
        self.db.add(merchant)
        await self.db.commit()
        await self.db.refresh(merchant)
        logger.info(f'创建支付商户配置 {app_code}/{provider}/{name}')
        return merchant

    async def get(self, merchant_id: str) -> Optional[PayMerchant]:
        result = await self.db.execute(
            select(PayMerchant).where(PayMerchant.id == merchant_id)
        )
        return result.scalar_one_or_none()

    async def list(self, app_code: Optional[str] = None,
                   provider: Optional[str] = None) -> List[PayMerchant]:
        stmt = select(PayMerchant).order_by(PayMerchant.created_at.desc())
        if app_code:
            stmt = stmt.where(PayMerchant.app_code == app_code)
        if provider:
            stmt = stmt.where(PayMerchant.provider == provider)
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def find_default(self, app_code: str, provider: str) -> Optional[PayMerchant]:
        """取该平台该渠道的默认商户配置"""
        result = await self.db.execute(
            select(PayMerchant).where(
                PayMerchant.app_code == app_code,
                PayMerchant.provider == provider,
                PayMerchant.status == 1,
            ).order_by(PayMerchant.created_at.asc())
        )
        merchants = list(result.scalars().all())
        if not merchants:
            return None
        # 优先 default 命名的那套
        for merchant in merchants:
            if merchant.name == 'default':
                return merchant
        return merchants[0]

    async def update(self, merchant_id: str, config: Optional[Dict[str, Any]] = None,
                     mp_appid: Optional[str] = None, remark: Optional[str] = None,
                     status: Optional[int] = None) -> Optional[PayMerchant]:
        merchant = await self.get(merchant_id)
        if not merchant:
            return None

        if config is not None:
            self.validate(merchant.provider, config)
            merchant.merchant_config = config
        if mp_appid is not None:
            merchant.mp_appid = mp_appid
        if remark is not None:
            merchant.remark = remark
        if status is not None:
            merchant.status = status

        self.db.add(merchant)
        await self.db.commit()
        await self.db.refresh(merchant)
        return merchant

    async def delete(self, merchant_id: str) -> bool:
        merchant = await self.get(merchant_id)
        if not merchant:
            return False
        await self.db.delete(merchant)
        await self.db.commit()
        return True


def to_context(merchant: PayMerchant):
    """构造渠道上下文"""
    from app.service.payment.provider import MerchantContext

    return MerchantContext(
        id=merchant.id,
        app_code=merchant.app_code,
        provider=merchant.provider,
        name=merchant.name,
        config=merchant.merchant_config or {},
        mp_appid=merchant.mp_appid,
    )


def check_trade_type(provider: str, trade_type: str) -> None:
    """校验 trade_type 是否被该渠道支持"""
    impl = get_provider(provider)
    if trade_type not in impl.trade_types:
        raise PayError(
            f'{provider} 不支持 trade_type={trade_type}，可用: {", ".join(impl.trade_types)}',
            status_code=400,
            code='invalid_trade_type',
        )
