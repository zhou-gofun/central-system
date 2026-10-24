"""
微信支付 APIv3 渠道实现

覆盖 JSAPI / Native / H5 / APP 四种下单方式，以及查单、关单、退款、回调验签解密。

配置项（pay_merchant.config）：
    mch_id           微信支付商户号
    api_v3_key       APIv3 密钥（32字节）
    cert_serial_no   商户证书序列号（用于请求头 serial_no）
    private_key_pem  商户 API 私钥（PKCS8 PEM）
    public_key_pem   微信支付公钥（公钥模式，PUB_KEY_ID_xxx）
    public_key_id    微信支付公钥ID
    platform_cert_pem 平台证书（证书模式，与 public_key_pem 二选一）
    appid            公众号/小程序 AppID（JSAPI 必填）
"""
import json
import logging
import secrets
import time
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, Optional
from urllib.parse import quote

import httpx

from app.service.payment.crypto import (
    aes_gcm_decrypt,
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
    STATUS_PAID,
    STATUS_CLOSED,
    STATUS_FAILED,
    STATUS_PENDING,
    STATUS_REFUNDED,
    to_naive_local,
)

logger = logging.getLogger(__name__)

API_BASE = 'https://api.mch.weixin.qq.com'

# 微信支付 trade_state -> 中心系统订单状态
TRADE_STATE_MAP = {
    'SUCCESS': STATUS_PAID,
    'REFUND': STATUS_REFUNDED,
    'NOTPAY': STATUS_PENDING,
    'USERPAYING': STATUS_PENDING,
    'CLOSED': STATUS_CLOSED,
    'REVOKED': STATUS_CLOSED,
    'PAYERROR': STATUS_FAILED,
}


def to_cents(amount: Decimal) -> int:
    """元 -> 分"""
    return int((amount * 100).quantize(Decimal('1'), rounding=ROUND_HALF_UP))


def from_cents(cents: int) -> Decimal:
    """分 -> 元"""
    return (Decimal(cents) / 100).quantize(Decimal('0.01'))


def parse_time(value: Optional[str]) -> Optional[datetime]:
    """解析微信的 RFC3339 时间，统一转成本地时间 naive 值"""
    if not value:
        return None
    text = value.replace('Z', '+00:00')
    try:
        return to_naive_local(datetime.fromisoformat(text))
    except ValueError:
        return None


class WxPayProvider(PayProvider):
    """微信支付 APIv3"""

    name = 'wxpay'
    trade_types = ('jsapi', 'native', 'h5', 'app')

    # ---------- 内部工具 ----------

    def _require(self, ctx: MerchantContext, *keys: str) -> Dict[str, Any]:
        config = ctx.config or {}
        missing = [k for k in keys if not config.get(k)]
        if missing:
            raise PayError(
                f'微信支付商户配置缺少字段: {", ".join(missing)}',
                status_code=400,
                code='merchant_config_invalid',
            )
        return config

    def _sign_request(self, ctx: MerchantContext, method: str, url_path: str, body: str) -> Dict[str, str]:
        """生成 APIv3 Authorization 请求头"""
        config = self._require(ctx, 'mch_id', 'cert_serial_no', 'private_key_pem')
        private_key = load_private_key(config['private_key_pem'])

        timestamp = str(int(time.time()))
        nonce = secrets.token_hex(16)
        message = f'{method}\n{url_path}\n{timestamp}\n{nonce}\n{body}\n'
        signature = rsa_sha256_sign(private_key, message)

        authorization = (
            'WECHATPAY2-SHA256-RSA2048 '
            f'mchid="{config["mch_id"]}",'
            f'nonce_str="{nonce}",'
            f'signature="{signature}",'
            f'timestamp="{timestamp}",'
            f'serial_no="{config["cert_serial_no"]}"'
        )
        return {
            'Authorization': authorization,
            'Accept': 'application/json',
            'Content-Type': 'application/json',
            'User-Agent': 'CentralSystem/1.0 (wechatpay)',
        }

    def _verify_response_signature(self, ctx: MerchantContext, headers: Any, body: str) -> None:
        """校验微信支付应答签名"""
        config = ctx.config or {}
        signature = headers.get('Wechatpay-Signature') or headers.get('wechatpay-signature')
        timestamp = headers.get('Wechatpay-Timestamp') or headers.get('wechatpay-timestamp')
        nonce = headers.get('Wechatpay-Nonce') or headers.get('wechatpay-nonce')
        serial = headers.get('Wechatpay-Serial') or headers.get('wechatpay-serial')

        if not signature or not timestamp or not nonce:
            raise PayError('微信支付应答缺少验签请求头', status_code=502, code='response_unsigned')

        public_key = self._load_verify_key(config, serial)
        message = f'{timestamp}\n{nonce}\n{body}\n'
        if not rsa_sha256_verify(public_key, message, signature):
            raise PayError('微信支付应答验签失败', status_code=502, code='response_verify_failed')

    def _load_verify_key(self, config: Dict[str, Any], serial: Optional[str]):
        """按 Wechatpay-Serial 取验签公钥：优先微信支付公钥，其次平台证书"""
        public_key_pem = config.get('public_key_pem')
        public_key_id = config.get('public_key_id')
        if public_key_pem:
            # 公钥模式下 serial 就是公钥ID
            if public_key_id and serial and serial != public_key_id:
                logger.warning(
                    f'微信支付公钥ID不匹配(配置={public_key_id}, 响应={serial})，仍尝试用已配置公钥验签'
                )
            return load_public_key(public_key_pem)

        platform_cert = config.get('platform_cert_pem')
        if platform_cert:
            return load_public_key(platform_cert)

        raise PayError(
            '微信支付商户配置缺少 public_key_pem 或 platform_cert_pem，无法验签',
            status_code=400,
            code='merchant_config_invalid',
        )

    async def _request(
        self,
        ctx: MerchantContext,
        method: str,
        url_path: str,
        payload: Optional[Dict[str, Any]] = None,
        query: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """调用微信支付 APIv3 并验签应答"""
        path_with_query = url_path
        if query:
            path_with_query = f'{url_path}?{"&".join(f"{k}={quote(str(v))}" for k, v in query.items())}'
        url = f'{API_BASE}{path_with_query}'

        body = '' if payload is None else json.dumps(payload, ensure_ascii=False)
        headers = self._sign_request(ctx, method, path_with_query, body)

        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.request(method, url, content=body.encode('utf-8') if body else None,
                                            headers=headers)

        text = response.text
        if response.status_code >= 400:
            raise PayError(
                f'微信支付接口返回错误: HTTP {response.status_code} {text[:500]}',
                status_code=502,
                code='upstream_error',
            )

        self._verify_response_signature(ctx, response.headers, text)

        try:
            data = response.json()
        except ValueError:
            data = {}
        return data if isinstance(data, dict) else {}

    # ---------- 下单 ----------

    async def create_order(self, ctx: MerchantContext, order: Any) -> CreateOrderResult:
        config = self._require(ctx, 'mch_id', 'api_v3_key', 'private_key_pem', 'cert_serial_no')
        trade_type = order.trade_type
        if trade_type not in self.trade_types:
            raise PayError(f'微信支付不支持的 trade_type: {trade_type}', status_code=400)

        appid = config.get('appid') or ctx.mp_appid
        if trade_type == 'jsapi':
            if not appid:
                raise PayError('微信支付 JSAPI 需要配置 appid', status_code=400, code='merchant_config_invalid')
            if not order.payer_openid:
                raise PayError('微信支付 JSAPI 缺少 payer_openid', status_code=400, code='missing_openid')

        amount_cents = to_cents(order.amount)
        payload: Dict[str, Any] = {
            'appid': appid,
            'mchid': config['mch_id'],
            'description': (order.subject or '订单')[:127],
            'out_trade_no': order.out_trade_no,
            'notify_url': order.provider_notify_url,
            'amount': {
                'total': amount_cents,
                'currency': order.currency or 'CNY',
            },
            'time_expire': order.expires_at.astimezone().strftime('%Y-%m-%dT%H:%M:%S%z'),
        }
        if order.attach:
            payload['attach'] = order.attach[:127]
        if trade_type == 'jsapi':
            payload['payer'] = {'openid': order.payer_openid}
        elif trade_type == 'h5':
            client_ip = (order.extra or {}).get('client_ip') if order.extra else None
            if not client_ip:
                raise PayError('微信支付 H5 需要 client_ip', status_code=400, code='missing_client_ip')
            payload['scene_info'] = {
                'payer_client_ip': client_ip,
                'h5_info': {'type': 'Wap'},
            }

        url_path = f'/v3/pay/transactions/{trade_type}'
        data = await self._request(ctx, 'POST', url_path, payload)

        pay_params: Dict[str, Any] = {}
        prepay_id = data.get('prepay_id')

        if trade_type == 'jsapi':
            if not prepay_id:
                raise PayError(f'微信支付 JSAPI 下单未返回 prepay_id: {data}', status_code=502)
            package = f'prepay_id={prepay_id}'
            timestamp = str(int(time.time()))
            nonce = secrets.token_hex(16)
            sign_message = f'{appid}\n{timestamp}\n{nonce}\n{package}\n'
            pay_sign = rsa_sha256_sign(load_private_key(config['private_key_pem']), sign_message)
            pay_params = {
                'appId': appid,
                'timeStamp': timestamp,
                'nonceStr': nonce,
                'package': package,
                'signType': 'RSA',
                'paySign': pay_sign,
            }
        elif trade_type == 'native':
            code_url = data.get('code_url')
            if not code_url:
                raise PayError(f'微信支付 Native 下单未返回 code_url: {data}', status_code=502)
            pay_params = {'code_url': code_url}
        elif trade_type == 'h5':
            h5_url = data.get('h5_url')
            if not h5_url:
                raise PayError(f'微信支付 H5 下单未返回 h5_url: {data}', status_code=502)
            pay_params = {'h5_url': h5_url}
        elif trade_type == 'app':
            if not prepay_id:
                raise PayError(f'微信支付 APP 下单未返回 prepay_id: {data}', status_code=502)
            package = f'prepay_id={prepay_id}'
            timestamp = str(int(time.time()))
            nonce = secrets.token_hex(16)
            sign_message = f'{appid}\n{timestamp}\n{nonce}\n{package}\n'
            pay_sign = rsa_sha256_sign(load_private_key(config['private_key_pem']), sign_message)
            pay_params = {
                'appid': appid,
                'partnerid': config['mch_id'],
                'prepayid': prepay_id,
                'package': 'Sign=WXPay',
                'noncestr': nonce,
                'timestamp': timestamp,
                'sign': pay_sign,
            }

        return CreateOrderResult(
            provider_trade_no=None,
            prepay_id=prepay_id,
            pay_params=pay_params,
            raw=data,
            snapshot={
                'mch_id': config['mch_id'],
                'appid': appid,
                'trade_type': trade_type,
                'amount_cents': amount_cents,
            },
        )

    # ---------- 查单 ----------

    async def query_order(self, ctx: MerchantContext, order: Any) -> QueryOrderResult:
        config = self._require(ctx, 'mch_id')
        data = await self._request(
            ctx,
            'GET',
            f'/v3/pay/transactions/out-trade-no/{order.out_trade_no}',
            query={'mchid': config['mch_id']},
        )
        trade_state = data.get('trade_state', '')
        amount = data.get('amount') or {}
        return QueryOrderResult(
            status=TRADE_STATE_MAP.get(trade_state, STATUS_PENDING),
            provider_trade_no=data.get('transaction_id'),
            amount=from_cents(amount['total']) if amount.get('total') is not None else None,
            paid_at=parse_time(data.get('success_time')),
            raw=data,
        )

    # ---------- 关单 ----------

    async def close_order(self, ctx: MerchantContext, order: Any) -> None:
        config = self._require(ctx, 'mch_id')
        await self._request(
            ctx,
            'POST',
            f'/v3/pay/transactions/out-trade-no/{order.out_trade_no}/close',
            {'mchid': config['mch_id']},
        )

    # ---------- 退款 ----------

    async def refund(self, ctx: MerchantContext, order: Any, refund: Any) -> RefundResult:
        config = self._require(ctx, 'mch_id', 'api_v3_key')
        total_cents = to_cents(refund.total_amount)
        refund_cents = to_cents(refund.amount)
        payload = {
            'out_trade_no': order.out_trade_no,
            'out_refund_no': refund.refund_no,
            'reason': (refund.reason or '用户申请退款')[:80],
            'notify_url': order.provider_notify_url,
            'amount': {
                'refund': refund_cents,
                'total': total_cents,
                'currency': order.currency or 'CNY',
            },
        }
        data = await self._request(ctx, 'POST', '/v3/refund/domestic/refunds', payload)
        status = data.get('status', 'PROCESSING')
        return RefundResult(
            provider_refund_no=data.get('refund_id'),
            status='SUCCESS' if status == 'SUCCESS' else ('FAILED' if status == 'ABNORMAL' else 'PENDING'),
            raw=data,
        )

    # ---------- 回调 ----------

    def notify_success_response(self):
        return json.dumps({'code': 'SUCCESS', 'message': '成功'}), 'application/json'

    async def verify_notify(self, ctx: MerchantContext, headers: Dict[str, str], raw_body: bytes) -> NotifyEvent:
        """验签 + 解密微信支付回调"""
        config = self._require(ctx, 'api_v3_key')

        header_map = {k.lower(): v for k, v in (headers or {}).items()}
        signature = header_map.get('wechatpay-signature')
        timestamp = header_map.get('wechatpay-timestamp')
        nonce = header_map.get('wechatpay-nonce')
        serial = header_map.get('wechatpay-serial')

        if not signature or not timestamp or not nonce:
            raise PayError('微信支付回调缺少验签请求头', status_code=400, code='notify_unsigned')

        # 1. 先验签（用原始报文）
        public_key = self._load_verify_key(config, serial)
        message = f'{timestamp}\n{nonce}\n{raw_body.decode("utf-8")}\n'
        if not rsa_sha256_verify(public_key, message, signature):
            raise PayError('微信支付回调验签失败', status_code=400, code='notify_verify_failed')

        # 2. 解密资源
        try:
            envelope = json.loads(raw_body.decode('utf-8'))
        except ValueError as exc:
            raise PayError(f'微信支付回调报文不是合法 JSON: {exc}', status_code=400) from exc

        resource = envelope.get('resource') or {}
        ciphertext = resource.get('ciphertext')
        if not ciphertext:
            raise PayError('微信支付回调缺少 resource.ciphertext', status_code=400)

        try:
            plaintext = aes_gcm_decrypt(
                config['api_v3_key'],
                resource.get('nonce') or nonce,
                ciphertext,
                resource.get('associated_data') or '',
            )
            data = json.loads(plaintext.decode('utf-8'))
        except PayError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise PayError(f'微信支付回调解密失败: {exc}', status_code=400, code='notify_decrypt_failed') from exc

        amount = data.get('amount') or {}
        trade_state = data.get('trade_state', '')
        event_type = envelope.get('event_type', 'TRANSACTION.SUCCESS')

        return NotifyEvent(
            event_id=envelope.get('id') or f"{data.get('transaction_id', '')}-{event_type}",
            event_type=event_type,
            out_trade_no=data.get('out_trade_no'),
            provider_trade_no=data.get('transaction_id'),
            status=TRADE_STATE_MAP.get(trade_state, STATUS_PENDING),
            amount=from_cents(amount['total']) if amount.get('total') is not None else None,
            currency=amount.get('currency'),
            paid_at=parse_time(data.get('success_time')),
            payer_id=(data.get('payer') or {}).get('openid'),
            raw=data,
        )
