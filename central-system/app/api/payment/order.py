from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.database import get_db
from app.common.security import verify_app_request
from app.service.payment.order_service import OrderService
from app.service.payment.provider import PayError

router = APIRouter(prefix="/api/v1/pay", tags=["支付"])


class CreateOrderRequest(BaseModel):
    """创建支付订单请求"""
    provider: str = Field(default='wxpay', description='支付渠道 wxpay/alipay/easypay')
    trade_type: str = Field(default='jsapi', description='jsapi/native/h5/app/page/wap/qr/redirect')
    subject: str = Field(..., description='订单标题')
    description: Optional[str] = Field(default=None, description='订单描述')
    amount: Decimal = Field(..., gt=0, description='金额(元)')
    currency: str = Field(default='CNY', description='币种')
    payer_openid: Optional[str] = Field(default=None, description='付款人openid(JSAPI必填)')
    payer_id: Optional[str] = Field(default=None, description='付款人渠道用户ID')
    client_order_no: Optional[str] = Field(default=None, description='业务订单号(幂等)')
    merchant_id: Optional[str] = Field(default=None, description='指定商户配置ID')
    notify_url: Optional[str] = Field(default=None, description='支付成功通知地址(默认用应用注册的)')
    attach: Optional[str] = Field(default=None, description='业务透传参数')
    expire_minutes: int = Field(default=30, ge=1, le=1440, description='订单有效期(分钟)')
    extra: Optional[Dict[str, Any]] = Field(default=None, description='扩展参数')


class OrderItem(BaseModel):
    out_trade_no: str
    client_order_no: Optional[str] = None
    app_code: str
    provider: str
    trade_type: str
    subject: Optional[str] = None
    amount: str
    currency: str
    payer_openid: Optional[str] = None
    provider_trade_no: Optional[str] = None
    status: str
    notify_status: str
    notify_count: int
    attach: Optional[str] = None
    pay_params: Optional[Dict[str, Any]] = None
    paid_at: Optional[str] = None
    closed_at: Optional[str] = None
    expires_at: str
    created_at: str
    updated_at: str


class CreateOrderResponse(BaseModel):
    out_trade_no: str
    client_order_no: Optional[str] = None
    provider: str
    trade_type: str
    subject: Optional[str] = None
    amount: str
    currency: str
    status: str
    pay_params: Optional[Dict[str, Any]] = None
    expires_at: str
    created_at: str


class OrderListResponse(BaseModel):
    total: int
    page: int
    page_size: int
    items: List[OrderItem]


class RefundRequest(BaseModel):
    out_trade_no: str = Field(..., description='原订单号')
    amount: Optional[Decimal] = Field(default=None, gt=0, description='退款金额(元)，默认全额')
    reason: Optional[str] = Field(default=None, description='退款原因')
    refund_no: Optional[str] = Field(default=None, description='业务退款单号(幂等)')


class RefundItem(BaseModel):
    refund_no: str
    out_trade_no: str
    provider: str
    provider_refund_no: Optional[str] = None
    amount: str
    total_amount: str
    reason: Optional[str] = None
    status: str
    created_at: str


def _order_item(order) -> OrderItem:
    return OrderItem(
        out_trade_no=order.out_trade_no,
        client_order_no=order.client_order_no,
        app_code=order.app_code,
        provider=order.provider,
        trade_type=order.trade_type,
        subject=order.subject,
        amount=str(order.amount),
        currency=order.currency,
        payer_openid=order.payer_openid,
        provider_trade_no=order.provider_trade_no,
        status=order.status,
        notify_status=order.notify_status,
        notify_count=order.notify_count or 0,
        attach=order.attach,
        pay_params=order.pay_params,
        paid_at=order.paid_at.isoformat() if order.paid_at else None,
        closed_at=order.closed_at.isoformat() if order.closed_at else None,
        expires_at=order.expires_at.isoformat() if order.expires_at else '',
        created_at=order.created_at.isoformat() if order.created_at else '',
        updated_at=order.updated_at.isoformat() if order.updated_at else '',
    )


@router.post("/order", response_model=CreateOrderResponse)
async def create_order(
    request: CreateOrderRequest,
    app_info: dict = Depends(verify_app_request),
    db: AsyncSession = Depends(get_db)
):
    """
    创建支付订单

    幂等：传入相同的 client_order_no 会返回已存在的订单，不会重复下单。
    """
    from app.common.config import settings

    service = OrderService(db)
    try:
        order = await service.create_order(
            app_code=app_info['app_code'],
            provider=request.provider,
            trade_type=request.trade_type,
            subject=request.subject,
            amount=request.amount,
            currency=request.currency,
            payer_openid=request.payer_openid,
            payer_id=request.payer_id,
            client_order_no=request.client_order_no,
            merchant_id=request.merchant_id,
            notify_url=request.notify_url,
            attach=request.attach,
            extra=request.extra,
            expire_minutes=request.expire_minutes,
            description=request.description,
            notify_base_url=settings.PAY_NOTIFY_BASE_URL,
        )
    except PayError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message)

    return CreateOrderResponse(
        out_trade_no=order.out_trade_no,
        client_order_no=order.client_order_no,
        provider=order.provider,
        trade_type=order.trade_type,
        subject=order.subject,
        amount=str(order.amount),
        currency=order.currency,
        status=order.status,
        pay_params=order.pay_params,
        expires_at=order.expires_at.isoformat() if order.expires_at else '',
        created_at=order.created_at.isoformat() if order.created_at else '',
    )


@router.get("/order/{out_trade_no}", response_model=OrderItem)
async def get_order(
    out_trade_no: str,
    app_info: dict = Depends(verify_app_request),
    db: AsyncSession = Depends(get_db)
):
    """查询订单状态"""
    service = OrderService(db)
    order = await service.get_order(out_trade_no, app_info['app_code'])
    if not order:
        raise HTTPException(status_code=404, detail='订单不存在')
    return _order_item(order)


@router.get("/orders", response_model=OrderListResponse)
async def list_orders(
    status: Optional[str] = Query(default=None, description='PENDING/PAID/CLOSED/...'),
    provider: Optional[str] = Query(default=None),
    client_order_no: Optional[str] = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
    app_info: dict = Depends(verify_app_request),
    db: AsyncSession = Depends(get_db)
):
    """分页查询订单"""
    service = OrderService(db)
    result = await service.list_orders(
        app_code=app_info['app_code'],
        status=status,
        provider=provider,
        client_order_no=client_order_no,
        page=page,
        page_size=page_size,
    )
    return OrderListResponse(
        total=result['total'],
        page=result['page'],
        page_size=result['page_size'],
        items=[_order_item(o) for o in result['items']],
    )


@router.post("/order/{out_trade_no}/close", response_model=OrderItem)
async def close_order(
    out_trade_no: str,
    app_info: dict = Depends(verify_app_request),
    db: AsyncSession = Depends(get_db)
):
    """关闭订单"""
    service = OrderService(db)
    try:
        order = await service.close_order(out_trade_no, app_info['app_code'])
    except PayError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message)
    return _order_item(order)


@router.post("/order/{out_trade_no}/sync", response_model=OrderItem)
async def sync_order(
    out_trade_no: str,
    app_info: dict = Depends(verify_app_request),
    db: AsyncSession = Depends(get_db)
):
    """主动向渠道查单并同步状态（对账用）"""
    service = OrderService(db)
    try:
        order = await service.sync_order(out_trade_no, app_info['app_code'])
    except PayError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message)
    return _order_item(order)


@router.post("/refund", response_model=RefundItem)
async def create_refund(
    request: RefundRequest,
    app_info: dict = Depends(verify_app_request),
    db: AsyncSession = Depends(get_db)
):
    """发起退款"""
    service = OrderService(db)
    try:
        refund = await service.create_refund(
            out_trade_no=request.out_trade_no,
            app_code=app_info['app_code'],
            amount=request.amount,
            reason=request.reason,
            refund_no=request.refund_no,
        )
    except PayError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message)

    return RefundItem(
        refund_no=refund.refund_no,
        out_trade_no=refund.out_trade_no,
        provider=refund.provider,
        provider_refund_no=refund.provider_refund_no,
        amount=str(refund.amount),
        total_amount=str(refund.total_amount),
        reason=refund.reason,
        status=refund.status,
        created_at=refund.created_at.isoformat() if refund.created_at else '',
    )


@router.get("/refund/{refund_no}", response_model=RefundItem)
async def get_refund(
    refund_no: str,
    app_info: dict = Depends(verify_app_request),
    db: AsyncSession = Depends(get_db)
):
    """查询退款单"""
    service = OrderService(db)
    refund = await service.get_refund(refund_no, app_info['app_code'])
    if not refund:
        raise HTTPException(status_code=404, detail='退款单不存在')
    return RefundItem(
        refund_no=refund.refund_no,
        out_trade_no=refund.out_trade_no,
        provider=refund.provider,
        provider_refund_no=refund.provider_refund_no,
        amount=str(refund.amount),
        total_amount=str(refund.total_amount),
        reason=refund.reason,
        status=refund.status,
        created_at=refund.created_at.isoformat() if refund.created_at else '',
    )
