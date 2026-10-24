"""
支付宝渠道实现（RSA2 签名）

配置项（pay_merchant.config）：
    app_id             支付宝应用APPID
    app_private_key    应用私钥（RSA2，PKCS1 或 PKCS8 PEM）
    alipay_public_key  支付宝公钥（用于验签回调）
    gateway            网关地址，默认 https://openapi.alipay.com/gateway.do
    notify_url         回调地址（默认由中心系统生成）
    sign_type          签名算法，默认 RSA2

覆盖 PC网页支付(trade.page.pay)、手机网站支付(trade.wap.pay)、
APP支付(trade.app.pay)、二维码当面付(trade.create)。
"""
import json
import logging
from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, Optional
from urllib.parse import urlencode

import httpx

from app.service.payment.crypto import (
    build_sorted_query,
    load_private_key,
    load_public_key,
    rsa_sha256_sign,
    rsa_sha256_verify,
)
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

DEFAULT_GATEWAY = 'https://openapi.alipay.com/gateway.do'

TRADE_STATUS_MAP = {
    'WAIT_BUYER_PAY': STATUS_PENDING,
    'TRADE_SUCCESS': STATUS_PAID,
    'TRADE_FINISHED': STATUS_PAID,
    'TRADE_CLOSED': STATUS_CLOSED,
}


def fmt_amount(amount: Decimal) -> str:
    """元 -> 支付宝要求的字符串（两位小数）"""
    return f'{amount:.2f}'


class AlipayProvider(PayProvider):
    """支付宝"""

    name = 'alipay'
    trade_types = ('page', 'wap', 'app', 'qr')

    def _require(self, ctx: MerchantContext, *keys: str) -> Dict[str, Any]:
        config = ctx.config or {}
        missing = [k for k in keys if not config.get(k)]
        if missing:
            raise PayError(
                f'支付宝商户配置缺少字段: {", ".join(missing)}',
                status_code=400,
                code='merchant_config_invalid',
            )
        return config

    def _gateway(self, ctx: MerchantContext) -> str:
        return (ctx.config or {}).get('gateway') or DEFAULT_GATEWAY

    def _sign(self, ctx: MerchantContext, params: Dict[str, Any]) -> str:
        config = self._require(ctx, 'app_id', 'app_private_key')
        private_key = load_private_key(config['app_private_key'])
        message = build_sorted_query(params)
        return rsa_sha256_sign(private_key, message)

    def _build_params(self, ctx: MerchantContext, method: str, biz_content: Dict[str, Any],
                      notify_url: str) -> Dict[str, Any]:
        config = self._require(ctx, 'app_id')
        params: Dict[str, Any] = {
            'app_id': config['app_id'],
            'method': method,
            'format': 'JSON',
            'charset': 'utf-8',
            'sign_type': 'RSA2',
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'version': '1.0',
            'notify_url': notify_url,
            'biz_content': json.dumps(biz_content, ensure_ascii=False),
        }
        params['sign'] = self._sign(ctx, params)
        return params

    async def _call(self, ctx: MerchantContext, method: str, biz_content: Dict[str, Any],
                    notify_url: str = '') -> Dict[str, Any]:
        params = self._build_params(ctx, method, biz_content, notify_url)
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(self._gateway(ctx), data=params)

        try:
            data = response.json()
        except ValueError as exc:
            raise PayError(
                f'支付宝网关返回非 JSON 响应: {response.text[:300]}',
                status_code=502,
                code='upstream_error',
            ) from exc

        if not isinstance(data, dict):
            raise PayError('支付宝网关返回格式异常', status_code=502, code='upstream_error')

        error = data.get('error_response')
        if error:
            code = error.get('code', '')
            message = error.get('sub_msg') or error.get('msg') or ''
            raise PayError(
                f'支付宝接口错误 [{code}]: {message}',
                status_code=502,
                code='upstream_error',
            )
        return data.get('alipay_trade_page_pay_response') or data.get('alipay_trade_wap_pay_response') \
            or data.get('alipay_trade_app_pay_response') or data.get('alipay_trade_create_response') \
            or data.get('alipay_trade_query_response') or data.get('alipay_trade_close_response') \
            or data.get('alipay_trade_refund_response') or {}

    # ---------- 下单 ----------

    async def create_order(self, ctx: MerchantContext, order: Any) -> CreateOrderResult:
        config = self._require(ctx, 'app_id')
        trade_type = order.trade_type
        if trade_type not in self.trade_types:
            raise PayError(f'支付宝不支持的 trade_type: {trade_type}', status_code=400)

        product_code = {
            'page': 'FAST_INSTANT_TRADE_PAY',
            'wap': 'QUICK_WAP_WAY',
            'app': 'QUICK_MSECURITY_PAY',
            'qr': 'FACE_TO_FACE_PAYMENT',
        }[trade_type]

        biz_content: Dict[str, Any] = {
            'out_trade_no': order.out_trade_no,
            'total_amount': fmt_amount(order.amount),
            'subject': (order.subject or '订单')[:256],
            'product_code': product_code,
        }
        if order.description:
            biz_content['body'] = order.description[:200]
        if order.attach:
            biz_content['passback_params'] = order.attach[:200]
        if order.payer_id:
            biz_content['buyer_id'] = order.payer_id
        if trade_type == 'wap' and (order.extra or {}).get('quit_url'):
            biz_content['quit_url'] = order.extra['quit_url']
        if trade_type == 'qr':
            biz_content['qr_mode'] = '4'

        data: Dict[str, Any] = {}
        if trade_type == 'qr':
            data = await self._call(ctx, 'alipay.trade.create', biz_content, order.provider_notify_url)
            qr_code = data.get('qr_code')
            if not qr_code:
                raise PayError(f'支付宝当面付未返回 qr_code: {data}', status_code=502)
            pay_params = {'qr_code': qr_code}
        else:
            method = {
                'page': 'alipay.trade.page.pay',
                'wap': 'alipay.trade.wap.pay',
                'app': 'alipay.trade.app.pay',
            }[trade_type]
            params = self._build_params(ctx, method, biz_content, order.provider_notify_url)
            gateway = self._gateway(ctx)
            pay_params = {
                'gateway_url': gateway,
                'method': method,
                'params': params,
                'form_html': self._build_form(gateway, params),
            }

        return CreateOrderResult(
            provider_trade_no=data.get('trade_no') if trade_type == 'qr' else None,
            prepay_id=data.get('trade_no') if trade_type == 'qr' else None,
            pay_params=pay_params,
            raw=data,
            snapshot={
                'app_id': config['app_id'],
                'trade_type': trade_type,
                'amount': fmt_amount(order.amount),
            },
        )

    @staticmethod
    def _build_form(gateway: str, params: Dict[str, Any]) -> str:
        """生成自动提交的表单 HTML"""
        fields = ''.join(
            f'<input type="hidden" name="{k}" value="{v}"/>' for k, v in params.items()
        )
        return (
            f'<form id="alipay_submit" name="alipay_submit" action="{gateway}" method="post">{fields}'
            '<button type="submit">正在跳转到支付宝...</button></form>'
            '<script>document.getElementById("alipay_submit").submit();</script>'
        )

    # ---------- 查单 ----------

    async def query_order(self, ctx: MerchantContext, order: Any) -> QueryOrderResult:
        data = await self._call(ctx, 'alipay.trade.query', {'out_trade_no': order.out_trade_no})
        trade_status = data.get('trade_status', '')
        amount = None
        if data.get('total_amount'):
            amount = Decimal(data['total_amount'])
        return QueryOrderResult(
            status=TRADE_STATUS_MAP.get(trade_status, STATUS_PENDING),
            provider_trade_no=data.get('trade_no'),
            amount=amount,
            paid_at=self._parse_time(data.get('send_pay_date')),
            raw=data,
        )

    # ---------- 关单 ----------

    async def close_order(self, ctx: MerchantContext, order: Any) -> None:
        await self._call(ctx, 'alipay.trade.close', {'out_trade_no': order.out_trade_no})

    # ---------- 退款 ----------

    async def refund(self, ctx: MerchantContext, order: Any, refund: Any) -> RefundResult:
        biz_content = {
            'out_trade_no': order.out_trade_no,
            'refund_amount': fmt_amount(refund.amount),
            'out_request_no': refund.refund_no,
        }
        if refund.reason:
            biz_content['refund_reason'] = refund.reason[:200]
        data = await self._call(ctx, 'alipay.trade.refund', biz_content)
        fund_change = data.get('fund_change')
        if data.get('sub_code') == 'ACQ.TRADE_HAS_FINISHED' or fund_change == 'N':
            status = 'FAILED'
        elif fund_change == 'Y':
            status = 'SUCCESS'
        else:
            status = 'PENDING'
        return RefundResult(
            provider_refund_no=data.get('trade_no') or refund.refund_no,
            status=status,
            raw=data,
        )

    # ---------- 回调 ----------

    def notify_success_response(self):
        return 'success', 'text/plain; charset=utf-8'

    async def peek_out_trade_no(self, raw_body: bytes, headers: Dict[str, str]) -> Optional[str]:
        """支付宝回调是表单，订单号未加密，可直接嗅探（验签仍然必做）"""
        from urllib.parse import parse_qsl
        try:
            params = dict(parse_qsl(raw_body.decode('utf-8')))
        except Exception:  # noqa: BLE001
            return None
        return params.get('out_trade_no')

    async def verify_notify(self, ctx: MerchantContext, headers: Dict[str, str], raw_body: bytes) -> NotifyEvent:
        from urllib.parse import parse_qsl
        config = self._require(ctx, 'app_id', 'alipay_public_key')

        try:
            params = {k: v for k, v in parse_qsl(raw_body.decode('utf-8'))}
        except Exception as exc:  # noqa: BLE001
            raise PayError(f'支付宝回调报文解析失败: {exc}', status_code=400) from exc

        signature = params.get('sign')
        if not signature:
            raise PayError('支付宝回调缺少 sign', status_code=400, code='notify_unsigned')

        sign_type = params.get('sign_type', 'RSA2')
        if sign_type != 'RSA2':
            raise PayError(f'暂不支持的支付宝签名算法: {sign_type}', status_code=400)

        public_key = load_public_key(config['alipay_public_key'])
        message = build_sorted_query(params)
        if not rsa_sha256_verify(public_key, message, signature):
            raise PayError('支付宝回调验签失败', status_code=400, code='notify_verify_failed')

        trade_status = params.get('trade_status', '')
        amount = None
        if params.get('total_amount'):
            amount = Decimal(params['total_amount'])

        # 事件ID：支付宝没有唯一事件号，用 交易号+交易状态+通知时间 组合
        event_id = f"{params.get('trade_no', '')}-{trade_status}-{params.get('notify_time', '')}"

        return NotifyEvent(
            event_id=event_id,
            event_type=trade_status,
            out_trade_no=params.get('out_trade_no'),
            provider_trade_no=params.get('trade_no'),
            status=TRADE_STATUS_MAP.get(trade_status, STATUS_PENDING),
            amount=amount,
            currency='CNY',
            paid_at=self._parse_time(params.get('gmt_payment')),
            payer_id=params.get('buyer_id') or params.get('buyer_user_id'),
            raw=params,
        )

    @staticmethod
    def _parse_time(value: Optional[str]) -> Optional[datetime]:
        if not value:
            return None
        for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%dT%H:%M:%S'):
            try:
                return datetime.strptime(value, fmt)
            except ValueError:
                continue
        return None
