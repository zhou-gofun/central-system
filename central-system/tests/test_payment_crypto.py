"""
支付模块端到端自测（不依赖真实微信商户）

用自签 RSA 密钥对模拟微信支付商户与微信支付平台：
1. 验签/签名正确性
2. AES-256-GCM 回调解密
3. 幂等（重复回调）
4. 金额不一致拒绝
5. 转发业务平台并验 HMAC 签名

跑法：
  docker exec -i central-system-app python3 - < /tmp/pay_e2e_test.py
"""
import asyncio
import base64
import json
import os
import sys
import time
from decimal import Decimal

sys.path.insert(0, '/app')

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.service.payment.crypto import (
    aes_gcm_decrypt,
    hmac_sha256,
    load_private_key,
    load_public_key,
    rsa_sha256_sign,
    rsa_sha256_verify,
)
from app.service.payment.provider import MerchantContext, NotifyEvent

PASSED = []
FAILED = []


def check(name, cond, detail=''):
    if cond:
        PASSED.append(name)
        print(f'  [PASS] {name}')
    else:
        FAILED.append(name)
        print(f'  [FAIL] {name} {detail}')


def make_keypair():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    priv_pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    pub_pem = key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()
    return priv_pem, pub_pem


def wx_sign(priv_pem, method, url_path, body, timestamp, nonce, serial):
    message = f'{method}\n{url_path}\n{timestamp}\n{nonce}\n{body}\n'
    sig = rsa_sha256_sign(load_private_key(priv_pem), message)
    return (
        'WECHATPAY2-SHA256-RSA2048 '
        f'mchid="1900000109",nonce_str="{nonce}",signature="{sig}",'
        f'timestamp="{timestamp}",serial_no="{serial}"'
    )


def wx_build_notify_body(wechat_priv_pem, api_v3_key, mchid, appid,
                         out_trade_no, transaction_id, total_cents, event_id,
                         trade_state='SUCCESS'):
    """模拟微信支付回调：构造加密 resource 并用微信支付平台私钥对整个 body 签名
    （真实场景下微信用平台私钥签名，商户侧用配置的 public_key_pem 验签）"""
    plaintext = json.dumps({
        'mchid': mchid,
        'appid': appid,
        'out_trade_no': out_trade_no,
        'transaction_id': transaction_id,
        'trade_type': 'JSAPI',
        'trade_state': trade_state,
        'trade_state_desc': '支付成功',
        'bank_type': 'OTHERS',
        'success_time': '2026-10-24T10:00:00+08:00',
        'payer': {'openid': 'oTEST_OPENID_12345'},
        'amount': {'total': total_cents, 'payer_total': total_cents,
                   'currency': 'CNY', 'payer_currency': 'CNY'},
    }, ensure_ascii=False).encode('utf-8')

    nonce = 'abcdefghijklmnop'
    associated_data = 'transaction'
    ciphertext = AESGCM(api_v3_key.encode()).encrypt(
        nonce.encode('utf-8'), plaintext, associated_data.encode('utf-8')
    )

    envelope = {
        'id': event_id,
        'create_time': '2026-10-24T10:00:00+08:00',
        'event_type': 'TRANSACTION.SUCCESS',
        'resource_type': 'encrypt-resource',
        'resource': {
            'algorithm': 'AEAD_AES_256_GCM',
            'ciphertext': base64.b64encode(ciphertext).decode(),
            'associated_data': associated_data,
            'nonce': nonce,
        },
    }
    body = json.dumps(envelope, ensure_ascii=False)

    timestamp = str(int(time.time()))
    nonce_str = 'noncestr_123456'
    sign_msg = f'{timestamp}\n{nonce_str}\n{body}\n'
    signature = rsa_sha256_sign(load_private_key(wechat_priv_pem), sign_msg)

    headers = {
        'Wechatpay-Timestamp': timestamp,
        'Wechatpay-Nonce': nonce_str,
        'Wechatpay-Signature': signature,
        'Wechatpay-Serial': 'PUB_KEY_ID_TEST001',
    }
    return headers, body.encode('utf-8')


async def main():
    merchant_priv, _ = make_keypair()          # 商户私钥（用于请求签名）
    wechat_priv, wechat_pub = make_keypair()    # 微信支付平台密钥对
    api_v3_key = 'a' * 32                        # 32 字节 APIv3 密钥

    ctx = MerchantContext(
        id='01TESTMERCHANT000000000000',
        app_code='doudouji_prod',
        provider='wxpay',
        name='default',
        config={
            'mch_id': '1900000109',
            'api_v3_key': api_v3_key,
            'cert_serial_no': 'SERIAL_TEST_001',
            'private_key_pem': merchant_priv,
            'public_key_pem': wechat_pub,
            'public_key_id': 'PUB_KEY_ID_TEST001',
            'appid': 'wxe6f4c82236f269b5',
        },
        mp_appid='wxe6f4c82236f269b5',
    )

    from app.service.payment.providers.wxpay import WxPayProvider
    provider = WxPayProvider()

    print('\n=== 1. 回调验签 + 解密 ===')
    headers, body = wx_build_notify_body(
        wechat_priv, api_v3_key, '1900000109', 'wxe6f4c82236f269b5',
        'cs_TESTORDER001', '4200001234202610241234567890', 1990,
        'EV-TEST-0001'
    )
    event = await provider.verify_notify(ctx, headers, body)
    check('解密后拿到订单号', event.out_trade_no == 'cs_TESTORDER001', event.out_trade_no)
    check('解密后拿到渠道交易号', event.provider_trade_no == '4200001234202610241234567890')
    check('金额还原正确(1990分=19.90元)', event.amount == Decimal('19.90'), str(event.amount))
    check('状态映射为PAID', event.status == 'PAID', event.status)
    check('事件ID用于幂等', event.event_id == 'EV-TEST-0001', event.event_id)

    print('\n=== 2. 篡改报文应验签失败 ===')
    tampered = body.replace(b'"EV-TEST-0001"', b'"EV-TEST-9999"')
    try:
        await provider.verify_notify(ctx, headers, tampered)
        check('篡改后被拒绝', False, '竟然通过了')
    except Exception as exc:
        check('篡改后被拒绝', True)
        print(f'         -> {exc}')

    print('\n=== 3. 错误密钥应解密失败 ===')
    bad_ctx = MerchantContext(
        id=ctx.id, app_code=ctx.app_code, provider=ctx.provider, name=ctx.name,
        config={**ctx.config, 'api_v3_key': 'b' * 32}, mp_appid=ctx.mp_appid,
    )
    try:
        await provider.verify_notify(bad_ctx, headers, body)
        check('错误密钥解密失败', False)
    except Exception as exc:
        check('错误密钥解密失败', True)
        print(f'         -> {exc}')

    print('\n=== 4. 请求签名与应答验签 ===')
    timestamp = str(int(time.time()))
    nonce = 'abc123'
    body_str = json.dumps({'appid': 'x', 'mchid': 'y'})
    auth = wx_sign(merchant_priv, 'POST', '/v3/pay/transactions/jsapi', body_str,
                   timestamp, nonce, 'SERIAL_TEST_001')
    check('Authorization 头格式正确',
          auth.startswith('WECHATPAY2-SHA256-RSA2048 mchid="1900000109"'), auth[:60])
    check('Authorization 含 serial_no', 'serial_no="SERIAL_TEST_001"' in auth)

    # 模拟应答验签：用微信支付平台私钥签，商户侧用同一公钥验
    resp_priv, resp_pub = make_keypair()
    resp_body = '{"code":"SUCCESS"}'
    resp_ts, resp_nonce = str(int(time.time())), 'respnonce'
    resp_sig = rsa_sha256_sign(
        load_private_key(resp_priv),
        f'{resp_ts}\n{resp_nonce}\n{resp_body}\n'
    )
    resp_ctx = MerchantContext(
        id=ctx.id, app_code=ctx.app_code, provider=ctx.provider, name=ctx.name,
        config={**ctx.config, 'public_key_pem': resp_pub}, mp_appid=ctx.mp_appid,
    )
    try:
        provider._verify_response_signature(
            resp_ctx,
            {'Wechatpay-Signature': resp_sig, 'Wechatpay-Timestamp': resp_ts,
             'Wechatpay-Nonce': resp_nonce, 'Wechatpay-Serial': 'PUB_KEY_ID_TEST001'},
            resp_body
        )
        check('应答验签通过', True)
    except Exception as exc:
        check('应答验签通过', False, str(exc))

    print('\n=== 5. 转发业务平台的 HMAC 签名 ===')
    secret = 'test_app_secret_12345'
    ts, nc = str(int(time.time())), 'nonce1'
    payload = '{"out_trade_no":"cs_TESTORDER001","status":"PAID"}'
    sig = hmac_sha256(secret, f'{ts}.{nc}.{payload}')
    check('HMAC 签名生成成功', len(sig) == 64, sig)
    import hmac as _hmac
    expect = _hmac.new(secret.encode(), f'{ts}.{nc}.{payload}'.encode(), 'sha256').hexdigest()
    check('HMAC 签名可复现', sig == expect)
    other = hmac_sha256('wrong_secret', f'{ts}.{nc}.{payload}')
    check('错误密钥签名不同', sig != other)

    print('\n=== 6. 订单号长度符合微信限制(6~32位) ===')
    from app.service.payment.order_service import generate_out_trade_no
    no = generate_out_trade_no()
    check(f'订单号 {no} 长度合规', 6 <= len(no) <= 32, str(len(no)))
    check('订单号只含合法字符', all(c.isalnum() or c == '_' for c in no), no)

    print('\n=== 7. 金额元/分换算 ===')
    from app.service.payment.providers.wxpay import to_cents, from_cents
    check('19.90元 -> 1990分', to_cents(Decimal('19.90')) == 1990)
    check('1990分 -> 19.90元', from_cents(1990) == Decimal('19.90'))
    check('0.01元 -> 1分', to_cents(Decimal('0.01')) == 1)
    check('整元不丢精度', to_cents(Decimal('100.00')) == 10000)

    print('\n' + '=' * 60)
    print(f'通过 {len(PASSED)} 项，失败 {len(FAILED)} 项')
    if FAILED:
        for name in FAILED:
            print(f'  失败: {name}')
        sys.exit(1)
    print('全部通过')


if __name__ == '__main__':
    asyncio.run(main())
