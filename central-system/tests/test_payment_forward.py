"""
支付回调转发业务平台链路测试

验证：
1. 支付成功后中心系统 POST 业务平台的 notify_url
2. 请求带 X-Pay-Signature (HMAC-SHA256, key=app_secret)
3. 业务平台侧能独立验签通过
4. 转发失败会重试并记录 notify_status=FAILED
5. 业务平台返回非2xx时中心系统记录失败

跑法：docker exec -i central-system-app python3 - < /tmp/pay_forward_test.py
"""
import asyncio
import base64
import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.path.insert(0, '/app')

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
import httpx
from httpx import ASGITransport
from sqlalchemy import select, delete

from app.common.database import AsyncSessionLocal
from app.common.config import settings
from app.model.payment.order import PayOrder
from app.model.payment.notify_log import PayNotifyLog
from app.model.payment.merchant import PayMerchant
from app.model.wechat.app import WechatApp
from app.service.payment.crypto import hmac_sha256

PASSED, FAILED = [], []
RECEIVED = []
RECEIVE_STATUS = {'code': 200}


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


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(length)
        RECEIVED.append({
            'path': self.path,
            'headers': {k.lower(): v for k, v in self.headers.items()},
            'body': body.decode('utf-8'),
        })
        self.send_response(RECEIVE_STATUS['code'])
        self.end_headers()
        self.wfile.write(b'ok')

    def log_message(self, *args):
        pass


def build_notify(wechat_priv, api_v3_key, out_trade_no, txn_id, cents, event_id):
    plaintext = json.dumps({
        'mchid': '1900000109', 'appid': 'wx123',
        'out_trade_no': out_trade_no, 'transaction_id': txn_id,
        'trade_state': 'SUCCESS', 'success_time': '2026-10-24T10:00:00+08:00',
        'amount': {'total': cents, 'currency': 'CNY'},
    }).encode()
    nonce, aad = 'abcdefghijklmnop', 'transaction'
    ct = AESGCM(api_v3_key.encode()).encrypt(nonce.encode(), plaintext, aad.encode())
    body = json.dumps({
        'id': event_id, 'event_type': 'TRANSACTION.SUCCESS',
        'resource': {'algorithm': 'AEAD_AES_256_GCM',
                     'ciphertext': base64.b64encode(ct).decode(),
                     'associated_data': aad, 'nonce': nonce},
    }, ensure_ascii=False)
    ts, nc = str(int(time.time())), 'n1'
    from app.service.payment.crypto import rsa_sha256_sign, load_private_key
    sig = rsa_sha256_sign(load_private_key(wechat_priv), f'{ts}\n{nc}\n{body}\n')
    return {'Wechatpay-Timestamp': ts, 'Wechatpay-Nonce': nc,
            'Wechatpay-Signature': sig, 'Wechatpay-Serial': 'PUB_KEY_ID_TEST'}, body.encode()


async def main():
    merchant_priv, _ = make_keypair()
    wechat_priv, wechat_pub = make_keypair()
    api_v3_key = 'd' * 32

    # 起一个本地 HTTP 服务模拟业务平台
    server = HTTPServer(('127.0.0.1', 0), Handler)
    port = server.server_address[1]
    notify_url = f'http://127.0.0.1:{port}/api/pay/notify'
    threading.Thread(target=server.serve_forever, daemon=True).start()
    print(f'模拟业务平台监听 {notify_url}')

    from app.main import app
    transport = ASGITransport(app=app)

    async with AsyncSessionLocal() as db:
        app_row = (await db.execute(
            select(WechatApp).where(WechatApp.app_code == 'doudouji_prod'))).scalar_one()
        app_secret = app_row.app_secret
        app_code = app_row.app_code

    async with AsyncSessionLocal() as db:
        await db.execute(delete(PayNotifyLog).where(PayNotifyLog.event_id.like('EV-FWD%')))
        await db.execute(delete(PayOrder).where(PayOrder.out_trade_no.like('cs_FWD%')))
        await db.execute(delete(PayMerchant).where(PayMerchant.remark == 'fwd-test'))
        await db.commit()

    async with httpx.AsyncClient(transport=transport, base_url='http://test', timeout=30.0) as client:
        # 建商户
        resp = await client.post('/api/v1/pay/merchant', json={
            'app_code': app_code, 'provider': 'wxpay', 'name': 'fwd-test',
            'config': {'mch_id': '1900000109', 'api_v3_key': api_v3_key,
                       'cert_serial_no': 'S', 'private_key_pem': merchant_priv,
                       'public_key_pem': wechat_pub, 'public_key_id': 'PUB_KEY_ID_TEST',
                       'appid': 'wx123'},
            'remark': 'fwd-test'}, headers={'X-Pay-Admin-Key': settings.PAY_ADMIN_KEY})
        merchant_id = resp.json()['id']

        # 打桩下单
        from app.service.payment.provider import get_provider, CreateOrderResult
        wx = get_provider('wxpay')
        orig = wx.create_order

        async def fake_create(ctx, order):
            return CreateOrderResult(prepay_id='PP1', pay_params={'prepay_id': 'PP1'},
                                     raw={}, snapshot={'mch_id': '1900000109'})
        wx.create_order = fake_create

        print('\n=== 1. 下单（带 notify_url 指向模拟业务平台）===')
        resp = await client.post('/api/v1/pay/order', json={
            'provider': 'wxpay', 'trade_type': 'jsapi', 'subject': '转发测试',
            'amount': '88.88', 'payer_openid': 'oX',
            'client_order_no': 'FWD-001', 'notify_url': notify_url,
        }, headers={'X-App-Code': app_code, 'X-App-Secret': app_secret})
        check('下单成功', resp.status_code == 200, resp.text[:200])
        out_trade_no = resp.json()['out_trade_no']

        print('\n=== 2. 回调触发转发 ===')
        headers, body = build_notify(wechat_priv, api_v3_key, out_trade_no,
                                     'TXN-FWD-001', 8888, 'EV-FWD-001')
        resp = await client.post(f'/api/v1/pay/notify/wxpay/{merchant_id}',
                                 content=body, headers=headers)
        check('回调返回200', resp.status_code == 200, str(resp.status_code))
        check('业务平台收到通知', len(RECEIVED) == 1, f'收到 {len(RECEIVED)} 条')
        if RECEIVED:
            got = RECEIVED[0]
            check('通知路径正确', got['path'] == '/api/pay/notify', got['path'])
            check('带 X-App-Code 头', got['headers'].get('x-app-code') == app_code)
            check('带 X-Pay-Timestamp', 'x-pay-timestamp' in got['headers'])
            check('带 X-Pay-Nonce', 'x-pay-nonce' in got['headers'])
            check('带 X-Pay-Signature', 'x-pay-signature' in got['headers'])
            check('带 X-Pay-Event', got['headers'].get('x-pay-event') == 'payment.success',
                  got['headers'].get('x-pay-event'))

            print('\n=== 3. 业务平台侧独立验签 ===')
            sig = got['headers'].get('x-pay-signature')
            ts = got['headers'].get('x-pay-timestamp')
            nc = got['headers'].get('x-pay-nonce')
            expect = hmac_sha256(app_secret, f'{ts}.{nc}.{got["body"]}')
            check('HMAC 签名校验通过', sig == expect, f'{sig} != {expect}')
            payload = json.loads(got['body'])
            check('通知含订单号', payload['out_trade_no'] == out_trade_no)
            check('通知含业务订单号', payload['client_order_no'] == 'FWD-001')
            check('通知含金额', payload['amount'] == '88.88', payload.get('amount'))
            check('通知含状态PAID', payload['status'] == 'PAID', payload.get('status'))
            check('通知含渠道交易号', payload['provider_trade_no'] == 'TXN-FWD-001')
            check('通知含平台标识', payload['app_code'] == app_code)

        async with AsyncSessionLocal() as db:
            o = (await db.execute(
                select(PayOrder).where(PayOrder.out_trade_no == out_trade_no))).scalar_one()
            check('订单 notify_status=SUCCESS', o.notify_status == 'SUCCESS', o.notify_status)
            check('通知次数=1', o.notify_count == 1, str(o.notify_count))
            check('记录了通知时间', o.notified_at is not None)

        print('\n=== 4. 业务平台返回500时记录失败并重试 ===')
        RECEIVED.clear()
        RECEIVE_STATUS['code'] = 500
        resp = await client.post('/api/v1/pay/order', json={
            'provider': 'wxpay', 'trade_type': 'jsapi', 'subject': '转发失败测试',
            'amount': '1.00', 'payer_openid': 'oX',
            'client_order_no': 'FWD-002', 'notify_url': notify_url,
        }, headers={'X-App-Code': app_code, 'X-App-Secret': app_secret})
        out_trade_no2 = resp.json()['out_trade_no']
        headers2, body2 = build_notify(wechat_priv, api_v3_key, out_trade_no2,
                                       'TXN-FWD-002', 100, 'EV-FWD-002')
        resp = await client.post(f'/api/v1/pay/notify/wxpay/{merchant_id}',
                                 content=body2, headers=headers2)
        check('回调仍返回200(不阻塞渠道)', resp.status_code == 200, str(resp.status_code))
        check('重试了3次', len(RECEIVED) == 3, f'收到 {len(RECEIVED)} 次')
        async with AsyncSessionLocal() as db:
            o = (await db.execute(
                select(PayOrder).where(PayOrder.out_trade_no == out_trade_no2))).scalar_one()
            check('notify_status=FAILED', o.notify_status == 'FAILED', o.notify_status)
            check('通知次数=3', o.notify_count == 3, str(o.notify_count))
            check('订单仍标记PAID', o.status == 'PAID', o.status)

        RECEIVE_STATUS['code'] = 200

        wx.create_order = orig

        async with AsyncSessionLocal() as db:
            await db.execute(delete(PayNotifyLog).where(PayNotifyLog.event_id.like('EV-FWD%')))
            await db.execute(delete(PayOrder).where(PayOrder.out_trade_no.in_([out_trade_no, out_trade_no2])))
            await db.execute(delete(PayMerchant).where(PayMerchant.id == merchant_id))
            await db.commit()

    server.shutdown()
    print('\n' + '=' * 60)
    print(f'通过 {len(PASSED)} 项，失败 {len(FAILED)} 项')
    if FAILED:
        for n in FAILED:
            print(f'  失败: {n}')
        sys.exit(1)
    print('全部通过')


if __name__ == '__main__':
    asyncio.run(main())
