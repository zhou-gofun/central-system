"""
易支付（EasyPay）聚合渠道实现

一个 MD5 签名协议同时覆盖支付宝与微信，适合接入方多、没有各渠道商户资质的情况。
sub2api 的文档也推荐过这条路线（ZPay / 启润 等）。

配置项（pay_merchant.config）：
    pid     商户ID
    key     商户密钥（MD5 签名用）
    gateway 支付网关地址，例如 https://pay.example.com
    sitename 站点名称（可选）
"""
import logging
from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, Optional
from urllib.parse import parse_qsl, urlencode

import httpx

from app.service.payment.crypto import build_sorted_query, md5_sign
from app.service.payment.provider import (
    CreateOrderResult,
    MerchantContext,
    NotifyEvent,
    PayError,
    PayProvider,
    QueryOrderResult,
    RefundResult,
    STATUS_CLOSED,
    STATUS_FAILED,
    STATUS_PAID,
    STATUS_PENDING,
)

logger = logging.getLogger(__name__)

# 易支付 type 参数 -> 展示名
TYPE_MAP = {
    'alipay': '支付宝',
    'wxpay': '微信支付',
    'qqpay': 'QQ钱包',
}


class EasyPayProvider(PayProvider):
    """易支付聚合通道"""

    name = 'easypay'
    trade_types = ('redirect', 'qr', 'api')

    def _require(self, ctx: MerchantContext, *keys: str) -> Dict[str, Any]:
        config = ctx.config or {}
        missing = [k for k in keys if not config.get(k)]
        if missing:
            raise PayError(
                f'易支付商户配置缺少字段: {", ".join(missing)}',
                status_code=400,
                code='merchant_config_invalid',
            )
        return config

    def _gateway(self, ctx: MerchantContext) -> str:
        return ((ctx.config or {}).get('gateway') or '').rstrip('/')

    def _sign(self, config: Dict[str, Any], params: Dict[str, Any]) -> str:
        return md5_sign(params, config['key'])

    # ---------- 下单 ----------

    async def create_order(self, ctx: MerchantContext, order: Any) -> CreateOrderResult:
        config = self._require(ctx, 'pid', 'key', 'gateway')
        gateway = self._gateway(ctx)

        pay_type = (order.extra or {}).get('pay_type') if order.extra else None
        if not pay_type:
            pay_type = 'alipay'
        if pay_type not in TYPE_MAP:
            raise PayError(f'易支付不支持的支付类型: {pay_type}', status_code=400)

        params: Dict[str, Any] = {
            'pid': config['pid'],
            'type': pay_type,
            'out_trade_no': order.out_trade_no,
            'notify_url': order.provider_notify_url,
            'name': (order.subject or '订单')[:100],
            'money': f'{order.amount:.2f}',
            'sitename': config.get('sitename') or '中心系统',
        }
        if order.attach:
            params['attach'] = order.attach[:100]
        if (order.extra or {}).get('return_url'):
            params['return_url'] = order.extra['return_url']
        params['sign'] = self._sign(config, params)
        params['sign_type'] = 'MD5'

        submit_url = f'{gateway}/submit.php?{urlencode(params)}'

        return CreateOrderResult(
            provider_trade_no=None,
            prepay_id=None,
            pay_params={
                'pay_url': submit_url,
                'gateway': gateway,
                'params': params,
                'pay_type': pay_type,
                'pay_type_name': TYPE_MAP[pay_type],
            },
            raw=params,
            snapshot={
                'pid': config['pid'],
                'pay_type': pay_type,
                'amount': f'{order.amount:.2f}',
            },
        )

    # ---------- 查单 ----------

    async def query_order(self, ctx: MerchantContext, order: Any) -> QueryOrderResult:
        config = self._require(ctx, 'pid', 'key', 'gateway')
        params = {
            'act': 'order',
            'pid': config['pid'],
            'key': config['key'],
            'out_trade_no': order.out_trade_no,
        }
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(f'{self._gateway(ctx)}/api.php', params=params)
        try:
            data = response.json()
        except ValueError:
            data = {}

        # 易支付查单返回 status=1 表示已付款
        if data.get('status') == 1:
            status = STATUS_PAID
        elif data.get('status') == 0:
            status = STATUS_PENDING
        elif data.get('status') == 2:
            status = STATUS_CLOSED
        else:
            status = STATUS_PENDING

        amount = None
        if data.get('money'):
            try:
                amount = Decimal(str(data['money']))
            except Exception:  # noqa: BLE001
                amount = None

        return QueryOrderResult(
            status=status,
            provider_trade_no=data.get('trade_no'),
            amount=amount,
            raw=data if isinstance(data, dict) else {},
        )

    # ---------- 关单 ----------

    async def close_order(self, ctx: MerchantContext, order: Any) -> None:
        raise PayError('易支付聚合通道不支持关单', status_code=400, code='not_supported')

    # ---------- 退款 ----------

    async def refund(self, ctx: MerchantContext, order: Any, refund: Any) -> RefundResult:
        config = self._require(ctx, 'pid', 'key', 'gateway')
        params = {
            'act': 'refund',
            'pid': config['pid'],
            'key': config['key'],
            'out_trade_no': order.out_trade_no,
            'money': f'{refund.amount:.2f}',
        }
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(f'{self._gateway(ctx)}/api.php', params=params)
        try:
            data = response.json()
        except ValueError:
            data = {}

        if data.get('code') == 0 or data.get('msg') in ('success', 'SUCCESS'):
            status = 'SUCCESS'
        elif data.get('code') == 1:
            status = 'PENDING'
        else:
            status = 'FAILED'

        return RefundResult(
            provider_refund_no=data.get('trade_no') if isinstance(data, dict) else None,
            status=status,
            raw=data if isinstance(data, dict) else {},
        )

    # ---------- 回调 ----------

    def notify_success_response(self):
        return 'success', 'text/plain; charset=utf-8'

    async def peek_out_trade_no(self, raw_body: bytes, headers: Dict[str, str]) -> Optional[str]:
        try:
            params = dict(parse_qsl(raw_body.decode('utf-8')))
        except Exception:  # noqa: BLE001
            return None
        return params.get('out_trade_no')

    async def verify_notify(self, ctx: MerchantContext, headers: Dict[str, str], raw_body: bytes) -> NotifyEvent:
        config = self._require(ctx, 'pid', 'key')

        try:
            params = {k: v for k, v in parse_qsl(raw_body.decode('utf-8'))}
        except Exception as exc:  # noqa: BLE001
            raise PayError(f'易支付回调报文解析失败: {exc}', status_code=400) from exc

        signature = params.get('sign')
        if not signature:
            raise PayError('易支付回调缺少 sign', status_code=400, code='notify_unsigned')

        expected = self._sign(config, params)
        if expected.lower() != signature.lower():
            raise PayError('易支付回调验签失败', status_code=400, code='notify_verify_failed')

        trade_status = params.get('trade_status', '')
        amount = None
        if params.get('money'):
            try:
                amount = Decimal(params['money'])
            except Exception:  # noqa: BLE001
                amount = None

        status = STATUS_PAID if trade_status == 'TRADE_SUCCESS' else STATUS_PENDING
        event_id = f"{params.get('trade_no', '')}-{trade_status}"

        return NotifyEvent(
            event_id=event_id,
            event_type=trade_status,
            out_trade_no=params.get('out_trade_no'),
            provider_trade_no=params.get('trade_no'),
            status=status,
            amount=amount,
            currency='CNY',
            payer_id=params.get('buyer'),
            raw=params,
        )
