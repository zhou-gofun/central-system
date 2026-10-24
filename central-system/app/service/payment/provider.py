"""
支付渠道抽象层

每个支付渠道实现 PayProvider 子类，负责:
- 下单（create_order）
- 查单（query_order）
- 关单（close_order）
- 退款（refund）
- 回调验签与解析（verify_notify）

中心系统内部统一用「元」和 Decimal，渠道特有的单位换算（如微信的分）由各 Provider 自行处理。
"""
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


def to_naive_local(value: Optional[datetime]) -> Optional[datetime]:
    """把带时区的 datetime 转成本地时间的 naive datetime

    微信支付的 success_time 是带时区的 RFC3339（如 2026-10-24T10:00:00+08:00），
    而数据库列是 TIMESTAMP WITHOUT TIME ZONE，直接写入会报
    "can't subtract offset-naive and offset-aware datetimes"。
    """
    if value is None:
        return None
    if value.tzinfo is None:
        return value
    return value.astimezone().replace(tzinfo=None)

# 订单状态（中心系统内部统一）
STATUS_PENDING = 'PENDING'
STATUS_PAID = 'PAID'
STATUS_FAILED = 'FAILED'
STATUS_CLOSED = 'CLOSED'
STATUS_REFUNDED = 'REFUNDED'
STATUS_PARTIALLY_REFUNDED = 'PARTIALLY_REFUNDED'

PAID_STATUSES = {STATUS_PAID, STATUS_REFUNDED, STATUS_PARTIALLY_REFUNDED}


class PayError(Exception):
    """支付业务异常"""

    def __init__(self, message: str, status_code: int = 400, code: str = 'pay_error'):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.code = code


@dataclass
class MerchantContext:
    """商户配置上下文"""
    id: str
    app_code: str
    provider: str
    name: str
    config: Dict[str, Any]
    mp_appid: Optional[str] = None


@dataclass
class CreateOrderResult:
    """下单结果"""
    provider_trade_no: Optional[str] = None
    prepay_id: Optional[str] = None
    pay_params: Dict[str, Any] = field(default_factory=dict)
    raw: Dict[str, Any] = field(default_factory=dict)
    snapshot: Dict[str, Any] = field(default_factory=dict)


@dataclass
class QueryOrderResult:
    """查单结果"""
    status: str = STATUS_PENDING
    provider_trade_no: Optional[str] = None
    amount: Optional[Decimal] = None
    paid_at: Optional[datetime] = None
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass
class RefundResult:
    """退款结果"""
    provider_refund_no: Optional[str] = None
    status: str = 'PENDING'
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass
class NotifyEvent:
    """回调事件（已完成验签与解密）"""
    event_id: str
    event_type: str = 'transaction'
    out_trade_no: Optional[str] = None
    provider_trade_no: Optional[str] = None
    status: str = STATUS_PENDING
    amount: Optional[Decimal] = None
    currency: Optional[str] = None
    paid_at: Optional[datetime] = None
    payer_id: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict)


class PayProvider(ABC):
    """支付渠道基类"""

    name: str = ''
    # 该渠道支持的 trade_type
    trade_types: tuple = ()

    @abstractmethod
    async def create_order(self, ctx: MerchantContext, order: Any) -> CreateOrderResult:
        """发起下单"""

    @abstractmethod
    async def query_order(self, ctx: MerchantContext, order: Any) -> QueryOrderResult:
        """主动查单（对账用）"""

    async def close_order(self, ctx: MerchantContext, order: Any) -> None:
        """关单（部分渠道不支持，默认空实现）"""
        raise PayError(f'{self.name} 不支持关单', status_code=400, code='not_supported')

    @abstractmethod
    async def refund(self, ctx: MerchantContext, order: Any, refund: Any) -> RefundResult:
        """发起退款"""

    @abstractmethod
    async def verify_notify(self, ctx: MerchantContext, headers: Dict[str, str], raw_body: bytes) -> NotifyEvent:
        """验签并解析回调报文，验签失败必须抛 PayError"""

    def notify_success_response(self) -> tuple:
        """回调成功时应返回给渠道的响应体"""
        return 'success', 'text/plain; charset=utf-8'

    async def peek_out_trade_no(self, raw_body: bytes, headers: Dict[str, str]) -> Optional[str]:
        """在不验签的前提下尝试从报文里嗅探订单号（仅用于定位商户配置，验签仍然必做）"""
        return None


_REGISTRY: Dict[str, PayProvider] = {}


def register_provider(provider: PayProvider) -> None:
    _REGISTRY[provider.name] = provider


def get_provider(name: str) -> PayProvider:
    """按名称获取渠道实现"""
    if not _REGISTRY:
        from app.service.payment import providers  # noqa: F401  触发注册
    provider = _REGISTRY.get(name)
    if not provider:
        raise PayError(f'不支持的支付渠道: {name}', status_code=400, code='unsupported_provider')
    return provider


def list_providers() -> list:
    """已注册的渠道名"""
    if not _REGISTRY:
        from app.service.payment import providers  # noqa: F401  触发注册
    return sorted(_REGISTRY.keys())
