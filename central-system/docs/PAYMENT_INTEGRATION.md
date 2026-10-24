# 支付功能接入指南

中心系统的支付模块为各业务平台提供统一的收银台能力。

**资金模式**：各业务平台使用**自己的商户号**，钱直接进平台自己的商户账户。
中心系统不归集资金、不做分账，只做：收银台 API、渠道验签回调、订单台账、幂等、发货通知。

---

## 一、整体链路

```
豆豆集前端/后端
   │ ① POST /api/v1/pay/order
   │    (X-App-Code / X-App-Secret)
   ▼
中心系统 ──②选商户配置 + 向微信支付下单──▶ 微信支付
   │                                          │
   │ ③返回 pay_params                           │ ④异步回调
   │    (JSAPI五参数 / 二维码 / 跳转链接)        │
   ▼                                          ▼
前端拉起支付                    POST /api/v1/pay/notify/wxpay/{merchant_id}
                                   · 验签 + AES-GCM 解密
                                   · 幂等检查
                                   · 金额校验
                                   · 订单置为 PAID
                                        │
                                        └─▶ ⑤POST 业务平台 notify_url
                                             (HMAC-SHA256 签名)
```

两条到账路径都保留：
- **前端轮询** `GET /api/v1/pay/order/{out_trade_no}` —— 简单可靠，业务平台无需公网入口
- **webhook 转发** —— 用户不刷新页面也能立刻发货

---

## 二、接入步骤

### 步骤 1：中心系统侧配置商户（管理端操作）

需要商户号、商户 API 私钥、APIv3 密钥、商户证书序列号、微信支付公钥。

```bash
ADMIN_KEY=$(grep PAY_ADMIN_KEY /data/projects/central-system/central-system/deploy/.env | cut -d= -f2)

curl -X POST https://central.system.sevenblue.cn/api/v1/pay/merchant \
  -H "X-Pay-Admin-Key: $ADMIN_KEY" \
  -H 'Content-Type: application/json' \
  -d '{
    "app_code": "doudouji_prod",
    "provider": "wxpay",
    "name": "default",
    "mp_appid": "wxe6f4c82236f269b5",
    "config": {
      "mch_id": "你的商户号",
      "api_v3_key": "32位APIv3密钥",
      "cert_serial_no": "商户证书序列号",
      "private_key_pem": "-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----",
      "public_key_pem": "-----BEGIN PUBLIC KEY-----\n...\n-----END PUBLIC KEY-----",
      "public_key_id": "PUB_KEY_ID_xxx"
    }
  }'
```

`config` 里各渠道的必填字段：

| 渠道 | 必填字段 | 可选字段 |
|------|---------|---------|
| `wxpay` | `mch_id` `api_v3_key` `cert_serial_no` `private_key_pem` | `public_key_pem`+`public_key_id`（或 `platform_cert_pem`）`appid` |
| `alipay` | `app_id` `app_private_key` | `alipay_public_key` `gateway` |
| `easypay` | `pid` `key` `gateway` | `sitename` |

> 微信支付公钥与平台证书二选一即可。**没有验签公钥/证书就无法验证回调签名**，中心系统会拒绝所有回调。

### 步骤 2：微信支付商户平台配置回调地址

在**微信支付商户平台**（不是公众号后台）→ 产品中心 → Native/JSAPI → 开发配置 → 支付配置里，
把通知地址填成中心系统的回调地址：

```
https://central.system.sevenblue.cn/api/v1/pay/notify/wxpay/{merchant_id}
```

`{merchant_id}` 是上一步创建商户配置返回的 `id`（形如 `01M5MXV2WDMRRRZ2D0V3EEV6PY`）。

同时把服务器出口 IP `207.57.122.116` 加进**微信支付商户平台的 IP 白名单**
（和公众号后台那个白名单是两回事，两个都要加）。

### 步骤 3：业务平台配置回调地址

中心系统支付成功后会把通知发到业务平台的地址。两种来源，优先级从高到低：

1. 下单时传的 `notify_url`
2. `wechat_app.callback_url`（应用注册表里配的全局地址）

```bash
docker exec central-system-db psql -U postgres -d central_system -c \
  "UPDATE wechat_app SET callback_url='https://豆豆集域名/api/pay/notify' WHERE app_code='doudouji_prod'"
```

### 步骤 4：业务平台调用下单接口

```bash
curl -X POST https://central.system.sevenblue.cn/api/v1/pay/order \
  -H 'Content-Type: application/json' \
  -H 'X-App-Code: doudouji_prod' \
  -H "X-App-Secret: $APP_SECRET" \
  -d '{
    "provider": "wxpay",
    "trade_type": "jsapi",
    "subject": "VIP会员月卡",
    "amount": "19.90",
    "payer_openid": "用户openid",
    "client_order_no": "豆豆集自己的订单号",
    "notify_url": "https://豆豆集域名/api/pay/notify"
  }'
```

响应：

```json
{
  "out_trade_no": "cs_01M5MXV2ZFZ4KB19GKDADY6RQX",
  "client_order_no": "豆豆集自己的订单号",
  "provider": "wxpay",
  "trade_type": "jsapi",
  "amount": "19.90",
  "currency": "CNY",
  "status": "PENDING",
  "pay_params": {
    "appId": "wx...",
    "timeStamp": "1758000000",
    "nonceStr": "...",
    "package": "prepay_id=wx...",
    "signType": "RSA",
    "paySign": "..."
  },
  "expires_at": "2026-10-24T11:30:00"
}
```

前端拿 `pay_params` 直接调 `wx.requestPayment`：

```js
wx.requestPayment({
  appId: pay_params.appId,
  timeStamp: pay_params.timeStamp,
  nonceStr: pay_params.nonceStr,
  package: pay_params.package,
  signType: pay_params.signType,
  paySign: pay_params.paySign,
  success: () => { /* 支付完成，可开始轮询订单状态 */ }
})
```

**openid 从哪来**：用户先走已有的扫码登录（`/api/v1/scan/create`），
拿到 openid 后直接用于支付，不需要二次授权。

### 步骤 5：业务平台接收支付成功通知

中心系统 POST 业务平台的 `notify_url`，请求头：

| 请求头 | 值 |
|--------|-----|
| `X-App-Code` | 业务平台标识 |
| `X-Pay-Timestamp` | Unix 时间戳 |
| `X-Pay-Nonce` | 随机串 |
| `X-Pay-Signature` | HMAC-SHA256 签名 |
| `X-Pay-Event` | `payment.success` |

**验签算法**（密钥就是 `app_secret`）：

```
message  = timestamp + "." + nonce + "." + raw_body
expected = hex(HMAC_SHA256(app_secret, message))
验签通过 ⇔ expected == X-Pay-Signature
```

建议同时校验时间戳与当前时间相差不超过 5 分钟（防重放）。

请求体：

```json
{
  "out_trade_no": "cs_01M5MXV2ZFZ4KB19GKDADY6RQX",
  "client_order_no": "豆豆集自己的订单号",
  "app_code": "doudouji_prod",
  "provider": "wxpay",
  "provider_trade_no": "4200001234202610249999",
  "trade_type": "jsapi",
  "subject": "VIP会员月卡",
  "amount": "19.90",
  "currency": "CNY",
  "status": "PAID",
  "attach": null,
  "paid_at": "2026-10-24T10:00:00",
  "event_type": "TRANSACTION.SUCCESS",
  "event_id": "EV-20261024-xxxxx"
}
```

**返回 2xx 才算通知成功**，非 2xx 中心系统会重试 3 次（间隔 2s、4s）。

---

## 三、接口清单

### 业务平台接口（需要 `X-App-Code` + `X-App-Secret`）

| 接口 | 方法 | 说明 |
|------|------|------|
| `/api/v1/pay/order` | POST | 创建订单，返回 `pay_params` |
| `/api/v1/pay/order/{out_trade_no}` | GET | 查询订单状态 |
| `/api/v1/pay/orders` | GET | 分页查询订单（支持 `status`/`provider`/`client_order_no` 过滤） |
| `/api/v1/pay/order/{out_trade_no}/close` | POST | 关单 |
| `/api/v1/pay/order/{out_trade_no}/sync` | POST | 主动向渠道查单（对账用） |
| `/api/v1/pay/refund` | POST | 发起退款 |
| `/api/v1/pay/refund/{refund_no}` | GET | 查询退款单 |

### 渠道回调接口（公开，靠验签保护）

| 接口 | 方法 | 说明 |
|------|------|------|
| `/api/v1/pay/notify/{provider}/{merchant_id}` | POST | 接收渠道回调 |

### 管理端接口（需要 `X-Pay-Admin-Key`）

| 接口 | 方法 | 说明 |
|------|------|------|
| `/api/v1/pay/merchant/providers` | GET | 列出支持的渠道 |
| `/api/v1/pay/merchant` | GET | 商户配置列表（密钥已打码） |
| `/api/v1/pay/merchant` | POST | 创建商户配置 |
| `/api/v1/pay/merchant/{merchant_id}` | PUT | 更新商户配置 |
| `/api/v1/pay/merchant/{merchant_id}` | DELETE | 删除商户配置 |

---

## 四、关键设计说明

### 订单号

中心系统生成 `out_trade_no`（格式 `cs_` + ULID，32 位内，符合微信支付要求），
业务平台自己的订单号存 `client_order_no`。`(app_code, client_order_no)` 唯一索引保证**下单幂等**：
传相同的 `client_order_no` 重复调用不会重复下单，直接返回已有订单。

### 订单状态

| 状态 | 含义 |
|------|------|
| `PENDING` | 待支付 |
| `PAID` | 已支付 |
| `FAILED` | 支付失败 |
| `CLOSED` | 已关闭 |
| `PARTIALLY_REFUNDED` | 部分退款 |
| `REFUNDED` | 已全额退款 |

通知状态单独记在 `notify_status`：`PENDING` / `SUCCESS` / `FAILED` / `SKIPPED`。

### 幂等

渠道会重复投递回调。中心系统靠 `pay_notify_log` 的 `(provider, event_id)` 唯一索引拦截：
重复回调不会重复改订单、不会重复发货（若上次通知失败会补发一次）。

### 金额校验

回调金额与本地订单金额不一致时**不更新订单**，记 `AMOUNT_MISMATCH` 日志，但**仍向渠道返回成功**
（否则渠道会一直重试形成回调风暴）。这一条能挡住金额篡改。

### 回调验签时机

验签在解析报文**之前**完成，且使用**原始 body**。微信支付 APIv3 回调是 AES-256-GCM 加密的 JSON，
中间件若改写 body 会导致解密失败。

### 时间

数据库列是 `TIMESTAMP WITHOUT TIME ZONE`，渠道返回的带时区时间统一转成本地时间（Asia/Shanghai）再入库。

---

## 五、常见问题

**Q：回调一直 404？**
`merchant_id` 路径段写错了。用 `GET /api/v1/pay/merchant` 查实际的 id。

**Q：回调一直 400「验签失败」？**
`public_key_pem` / `platform_cert_pem` 配错了，或者 `public_key_id` 与微信返回的
`Wechatpay-Serial` 不一致。检查商户平台下载的微信支付公钥是否最新。

**Q：回调 400「解密失败」？**
`api_v3_key` 不是商户平台当前生效的 APIv3 密钥（改过密钥但没同步配置）。

**Q：下单报「未配置 wxpay 支付通道」？**
该 `app_code` 下没有启用的商户配置。先 `POST /api/v1/pay/merchant` 创建。

**Q：下单报「微信支付 JSAPI 缺少 payer_openid」？**
JSAPI 必须带 openid，且该 openid 要属于配置的公众号。

**Q：订单一直 PENDING？**
① 渠道回调没到（查 `pay_notify_log` 和应用日志）；
② 用 `POST /api/v1/pay/order/{no}/sync` 主动查单。

**Q：通知业务平台失败？**
查 `pay_order.notify_status` 和 `notify_count`。`FAILED` 说明重试 3 次都失败，
检查业务平台地址是否可达、是否返回 2xx、验签是否通过。

**Q：微信支付下单报 IP 不在白名单？**
把 `207.57.122.116` 加到**微信支付商户平台**的 IP 白名单
（和公众号后台的白名单是两回事，两个都要加）。
