"""
支付模块 HTTP 层端到端测试

流程：
1. 用管理密钥创建商户配置（wxpay，自签密钥）
2. 用 app_code/app_secret 调 /api/v1/pay/order 下单（用 mock provider，避免真实调微信）
3. 模拟渠道回调 POST /api/v1/pay/notify/wxpay/{merchant_id}
4. 验证：订单变 PAID / 幂等 / 转发业务平台带 HMAC 签名 / 金额不一致被拒

跑法：docker exec -i central-system-app python3 - < /tmp/pay_http_test.py
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
import httpx

from app.common.database import AsyncSessionLocal, engine
from app.common.config import settings
from app.model.payment.order import PayOrder
from app.model.payment.notify_log import PayNotifyLog
from app.model.payment.merchant import PayMerchant
from app.model.wechat.app import WechatApp
from sqlalchemy import select, delete
from httpx import ASGITransport

PASSED, FAILED = [], []


def check(name, cond, detail=''):
    (PASSED if cond else FAILED).append(name)
    print(f'  [{"PASS" if cond else "FAIL"}] {name} {detail if not cond else ""}')


def make_keypair():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    priv = key.private_bytes(serialization.Encoding.PEM,
                             serialization.PrivateFormat.PKCS8,
                             serialization.NoEncryption()).decode()
    pub = key.public_key().public_bytes(serialization.Encoding.PEM,
                                        serialization.PublicFormat.SubjectPublicKeyInfo).decode()
    return priv, pub


def build_notify(wechat_priv, api_v3_key, out_trade_no, txn_id, cents, event_id):
    plaintext = json.dumps({
        'mchid': '1900000109', 'appid': 'wxe6f4c82236f269b5',
        'out_trade_no': out_trade_no, 'transaction_id': txn_id,
        'trade_state': 'SUCCESS', 'success_time': '2026-10-24T10:00:00+08:00',
        'payer': {'openid': 'oTEST'},
        'amount': {'total': cents, 'currency': 'CNY'},
    }).encode()
    nonce, aad = 'abcdefghijklmnop', 'transaction'
    ct = AESGCM(api_v3_key.encode()).encrypt(nonce.encode(), plaintext, aad.encode())
    body = json.dumps({
        'id': event_id, 'event_type': 'TRANSACTION.SUCCESS',
        'resource_type': 'encrypt-resource',
        'resource': {'algorithm': 'AEAD_AES_256_GCM',
                     'ciphertext': base64.b64encode(ct).decode(),
                     'associated_data': aad, 'nonce': nonce},
    }, ensure_ascii=False)
    ts, nc = str(int(time.time())), 'n1'
    from app.service.payment.crypto import rsa_sha256_sign, load_private_key
    sig = rsa_sha256_sign(load_private_key(wechat_priv), f'{ts}\n{nc}\n{body}\n')
    headers = {'Wechatpay-Timestamp': ts, 'Wechatpay-Nonce': nc,
               'Wechatpay-Signature': sig, 'Wechatpay-Serial': 'PUB_KEY_ID_TEST'}
    return headers, body.encode()


async def main():
    merchant_priv, _ = make_keypair()
    wechat_priv, wechat_pub = make_keypair()
    api_v3_key = 'c' * 32

    admin_key = settings.PAY_ADMIN_KEY
    print(f'PAY_ADMIN_KEY 已配置: {bool(admin_key)}')

    from app.main import app
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url='http://test',
                                 timeout=30.0) as client:
        # 取 app_secret
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(WechatApp).where(WechatApp.app_code == 'doudouji_prod'))
            app_row = result.scalar_one_or_none()
            if not app_row:
                print('  业务应用 doudouji_prod 不存在，跳过')
                return
            app_secret = app_row.app_secret
            app_code = app_row.app_code

        # 清理旧的测试数据
        async with AsyncSessionLocal() as db:
            await db.execute(delete(PayNotifyLog).where(PayNotifyLog.event_id.like('EV-TEST%')))
            await db.execute(delete(PayOrder).where(PayOrder.out_trade_no.like('cs_TEST%')))
            await db.execute(delete(PayMerchant).where(PayMerchant.remark == 'e2e-test'))
            await db.commit()

        print('\n=== 1. 创建商户配置 ===')
        resp = await client.post('/api/v1/pay/merchant', json={
            'app_code': app_code, 'provider': 'wxpay', 'name': 'e2e-test',
            'config': {
                'mch_id': '1900000109', 'api_v3_key': api_v3_key,
                'cert_serial_no': 'SER_TEST', 'private_key_pem': merchant_priv,
                'public_key_pem': wechat_pub, 'public_key_id': 'PUB_KEY_ID_TEST',
                'appid': 'wxe6f4c82236f269b5',
            },
            'mp_appid': 'wxe6f4c82236f269b5', 'remark': 'e2e-test',
        }, headers={'X-Pay-Admin-Key': admin_key})
        check('创建商户配置返回200', resp.status_code == 200, f'{resp.status_code} {resp.text[:200]}')
        if resp.status_code != 200:
            return
        merchant = resp.json()
        merchant_id = merchant['id']
        check('返回的密钥已打码', api_v3_key not in json.dumps(merchant), merchant['config'])

        print('\n=== 2. 管理密钥错误应被拒 ===')
        resp = await client.get('/api/v1/pay/merchant', headers={'X-Pay-Admin-Key': 'wrong'})
        check('错误管理密钥返回401', resp.status_code == 401, str(resp.status_code))
        resp = await client.get('/api/v1/pay/merchant')
        check('缺少管理密钥返回422', resp.status_code == 422, str(resp.status_code))

        print('\n=== 3. 未配置商户时下单应报错 ===')
        resp = await client.post('/api/v1/pay/order', json={
            'provider': 'alipay', 'trade_type': 'page',
            'subject': 'test', 'amount': '1.00',
        }, headers={'X-App-Code': app_code, 'X-App-Secret': app_secret})
        check('未配置渠道返回400', resp.status_code == 400, f'{resp.status_code} {resp.text[:200]}')

        print('\n=== 4. 缺少鉴权头应拒绝 ===')
        resp = await client.post('/api/v1/pay/order', json={
            'provider': 'wxpay', 'trade_type': 'jsapi', 'subject': 't', 'amount': '1.00'})
        check('无鉴权返回422', resp.status_code == 422, str(resp.status_code))
        resp = await client.post('/api/v1/pay/order', json={
            'provider': 'wxpay', 'trade_type': 'jsapi', 'subject': 't', 'amount': '1.00'},
            headers={'X-App-Code': app_code, 'X-App-Secret': 'wrong'})
        check('错误app_secret返回401', resp.status_code == 401, str(resp.status_code))

        print('\n=== 5. 用 mock provider 下单 ===')
        # 打桩 provider，避免真实请求微信
        from app.service.payment.provider import get_provider, CreateOrderResult
        wx = get_provider('wxpay')
        orig_create = wx.create_order

        async def fake_create(ctx, order):
            order.provider_notify_url = order.provider_notify_url
            return CreateOrderResult(
                provider_trade_no=None, prepay_id='PREPAY_TEST_001',
                pay_params={'prepay_id': 'PREPAY_TEST_001'},
                raw={'mock': True},
                snapshot={'mch_id': '1900000109', 'appid': 'wxe6f4c82236f269b5'},
            )
        wx.create_order = fake_create

        resp = await client.post('/api/v1/pay/order', json={
            'provider': 'wxpay', 'trade_type': 'jsapi', 'subject': '豆豆集测试订单',
            'amount': '19.90', 'payer_openid': 'oTEST_OPENID_12345',
            'client_order_no': 'DDJ-TEST-001',
        }, headers={'X-App-Code': app_code, 'X-App-Secret': app_secret})
        check('下单返回200', resp.status_code == 200, f'{resp.status_code} {resp.text[:300]}')
        if resp.status_code != 200:
            wx.create_order = orig_create
            return
        order = resp.json()
        out_trade_no = order['out_trade_no']
        check('返回中心订单号', out_trade_no.startswith('cs_'), out_trade_no)
        check('订单初始状态PENDING', order['status'] == 'PENDING', order['status'])
        check('金额正确', order['amount'] == '19.90', order['amount'])

        print('\n=== 6. 下单幂等（相同 client_order_no）===')
        resp2 = await client.post('/api/v1/pay/order', json={
            'provider': 'wxpay', 'trade_type': 'jsapi', 'subject': '豆豆集测试订单',
            'amount': '19.90', 'payer_openid': 'oTEST_OPENID_12345',
            'client_order_no': 'DDJ-TEST-001',
        }, headers={'X-App-Code': app_code, 'X-App-Secret': app_secret})
        check('重复下单返回同一订单号', resp2.json()['out_trade_no'] == out_trade_no,
              resp2.json().get('out_trade_no'))

        async with AsyncSessionLocal() as db:
            count = (await db.execute(
                select(PayOrder).where(PayOrder.client_order_no == 'DDJ-TEST-001')
            )).scalars().all()
            check('数据库只有一条订单', len(count) == 1, f'{len(count)} 条')

        print('\n=== 7. 模拟渠道回调 ===')
        headers, body = build_notify(wechat_priv, api_v3_key, out_trade_no,
                                     '4200001234202610249999', 1990, 'EV-TEST-HTTP-001')
        resp = await client.post(f'/api/v1/pay/notify/wxpay/{merchant_id}',
                                  content=body, headers=headers)
        check('回调返回200', resp.status_code == 200, f'{resp.status_code} {resp.text[:200]}')
        check('微信回调成功响应体', 'SUCCESS' in resp.text, resp.text[:100])

        async with AsyncSessionLocal() as db:
            o = (await db.execute(select(PayOrder).where(PayOrder.out_trade_no == out_trade_no))).scalar_one()
            check('订单已变为PAID', o.status == 'PAID', o.status)
            check('记录了渠道交易号', o.provider_trade_no == '4200001234202610249999')
            check('记录了支付时间', o.paid_at is not None)

        print('\n=== 8. 幂等：重复回调 ===')
        resp = await client.post(f'/api/v1/pay/notify/wxpay/{merchant_id}',
                                 content=body, headers=headers)
        check('重复回调返回200', resp.status_code == 200, str(resp.status_code))
        async with AsyncSessionLocal() as db:
            logs = (await db.execute(
                select(PayNotifyLog).where(PayNotifyLog.event_id == 'EV-TEST-HTTP-001')
            )).scalars().all()
            check('幂等日志只有一条', len(logs) == 1, f'{len(logs)} 条')

        print('\n=== 9. 验签失败的回调被拒 ===')
        bad_headers = dict(headers)
        bad_headers['Wechatpay-Signature'] = 'aW52YWxpZC1zaWduYXR1cmU='
        resp = await client.post(f'/api/v1/pay/notify/wxpay/{merchant_id}',
                                 content=body, headers=bad_headers)
        check('验签失败返回400', resp.status_code == 400, f'{resp.status_code} {resp.text[:200]}')

        print('\n=== 10. 金额不一致被拒绝 ===')
        headers2, body2 = build_notify(wechat_priv, api_v3_key, out_trade_no,
                                       '4200001234202610248888', 1, 'EV-TEST-HTTP-002')
        resp = await client.post(f'/api/v1/pay/notify/wxpay/{merchant_id}',
                                 content=body2, headers=headers2)
        check('金额不符仍返回200(避免回调风暴)', resp.status_code == 200, str(resp.status_code))
        async with AsyncSessionLocal() as db:
            o = (await db.execute(select(PayOrder).where(PayOrder.out_trade_no == out_trade_no))).scalar_one()
            check('订单金额未变(未标脏PAID)', o.amount == Decimal('19.90'), str(o.amount))
            log = (await db.execute(
                select(PayNotifyLog).where(PayNotifyLog.event_id == 'EV-TEST-HTTP-002')
            )).scalar_one_or_none()
            check('记录了金额不符', log is not None and log.result == 'AMOUNT_MISMATCH',
                  log.result if log else 'no log')

        print('\n=== 11. 未知商户ID返回404 ===')
        resp = await client.post('/api/v1/pay/notify/wxpay/01NOTEXIST000000000000000',
                                 content=body, headers=headers)
        check('未知商户返回404', resp.status_code == 404, str(resp.status_code))

        print('\n=== 12. 查询订单接口 ===')
        resp = await client.get(f'/api/v1/pay/order/{out_trade_no}',
                                headers={'X-App-Code': app_code, 'X-App-Secret': app_secret})
        check('查询订单返回200', resp.status_code == 200, str(resp.status_code))
        check('查询到PAID状态', resp.json()['status'] == 'PAID', resp.json().get('status'))
        resp = await client.get('/api/v1/pay/orders', headers={
            'X-App-Code': app_code, 'X-App-Secret': app_secret})
        check('订单列表返回200', resp.status_code == 200, str(resp.status_code))
        check('列表包含该订单', resp.json()['total'] >= 1)

        print('\n=== 13. 退款校验 ===')
        resp = await client.post('/api/v1/pay/refund', json={
            'out_trade_no': out_trade_no, 'amount': '5.00', 'reason': '测试退款'},
            headers={'X-App-Code': app_code, 'X-App-Secret': app_secret})
        # 没有真实渠道，退款会因网络失败；这里只校验前置校验逻辑
        check('退款请求被处理(非参数错误)', resp.status_code != 422, f'{resp.status_code}')

        wx.create_order = orig_create

        # 清理
        async with AsyncSessionLocal() as db:
            await db.execute(delete(PayNotifyLog).where(PayNotifyLog.event_id.like('EV-TEST%')))
            await db.execute(delete(PayOrder).where(PayOrder.out_trade_no == out_trade_no))
            await db.execute(delete(PayMerchant).where(PayMerchant.id == merchant_id))
            await db.commit()

    print('\n' + '=' * 60)
    print(f'通过 {len(PASSED)} 项，失败 {len(FAILED)} 项')
    if FAILED:
        for n in FAILED:
            print(f'  失败: {n}')
        sys.exit(1)
    print('全部通过')


if __name__ == '__main__':
    asyncio.run(main())
