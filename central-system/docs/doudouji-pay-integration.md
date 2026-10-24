# 豆豆集支付接入指南

> 适用场景：豆豆集（`app_code=doudouji_prod`，运行在**另一台服务器**）接入中心系统的支付收银台能力。
> 资金模式：**豆豆集自有微信支付商户号**，中心系统不归集资金，只做收银台 API、验签回调、订单台账、幂等与发货通知。

---

## 1. 链路总览

```
        豆豆集前端                豆豆集后端(豆豆集服务器)              中心系统(207.57.122.116)         微信支付
             │                          │                                │                             │
             │ ①下单 ──────────────────►│                                │                             │
             │                          │ ②POST /api/v1/pay/order ─────►│                             │
             │                          │   (X-App-Code/Secret)         │ ③JSAPI 下单 ────────────────►│
             │                          │                                │                             │
             │ ◄──pay_params──────────│◄──────prepay_id/paySign───────│                             │
             │ ④拉起支付 ─────────────────────────────────────────────────────────────────────────────►│
             │                          │                                │                             │
             │                          │                                │ ◄────⑥微信异步回调(加密)─────│
             │                          │                                │  验签解密→改订单→转发         │
             │                          │ ◄─⑤POST 通知(带HMAC签名)───────│                             │
             │                          │  ⑥发货                        │                             │
```

四个方向的网络要求（**全部必须满足，否则功能跑不通**）：

| 方向 | 走哪条路 | 备注 |
|---|---|---|
| ① 豆豆集前端 → 豆豆集后端 | 豆豆集自己内网 | 与本文档无关 |
| ② 豆豆集后端 → 中心系统 | `https://central.system.sevenblue.cn` 出网 443 | 需放通 |
| ③ 中心系统 → 微信支付 | `api.mch.weixin.qq.com` 出网 443 | 已有 |
| ④ 微信支付 → 中心系统回调 | `https://central.system.sevenblue.cn/api/v1/pay/notify/wxpay/{merchant_id}` | 公网可达 + 有效 TLS 证书，**已就绪** |
| ⑤ 中心系统 → 豆豆集后端回调 | 豆豆集自己提供的公网 HTTPS 地址 | **需放通 + 证书必须是公共信任证书**（见 §6） |

> ⚠️ 中心系统**没有配 CORS 中间件**，浏览器前端不能直接跨域调中心系统。
> 豆豆集前端只跟豆豆集后端交互，由豆豆集后端代调中心系统。

---

## 2. 前置条件清单

### 2.1 豆豆集侧要准备

- [ ] 微信支付商户号 `mch_id`
- [ ] APIv3 密钥（**必须正好 32 字节**，中心系统建商户配置时会强校验）
- [ ] 商户证书序列号 `cert_serial_no`
- [ ] 商户 API 私钥 `private_key_pem`（PKCS#8 PEM）
- [ ] **微信支付公钥** `public_key_pem` + `public_key_id`（公钥模式，推荐）
      或 **平台证书** `platform_cert_pem`（证书模式）
      → 二选一，**回调验签必须靠它**，缺了回调必然 400（见 §6 坑 1）
- [ ] 公众号 AppID（豆豆集已绑：`wxe6f4c82236f269b5`「小飞雁服务号」）
- [ ] 用户 `openid` 的获取方式（JSAPI 必填，中心系统**不提供** code2openid，见 §5.1）
- [ ] 一个公网 HTTPS 回调地址，例如 `https://<豆豆集域名>/api/pay/notify`
- [ ] 若豆豆集自己调公众号接口取 openid：把**豆豆集服务器的出口 IP** 加进公众号后台「基本配置 → IP 白名单」
      （中心系统自己的出口 IP `207.57.122.116` 已放行，加的是豆豆集那台机器的 IP）

### 2.2 中心系统侧（已在生产就绪，无需改动）

- `PAY_NOTIFY_BASE_URL=https://central.system.sevenblue.cn` —— 渠道回调地址前缀，已配好
- `PAY_ADMIN_KEY=...` —— 商户配置管理接口密钥，已配好（在 `central-system/deploy/.env`）
- `pay_merchant` / `pay_order` / `pay_notify_log` / `pay_refund` 四张表已建好
- 业务应用 `doudouji_prod` 已存在，但 **`callback_url` 是空的** → 必须补（§3.1）

---

## 3. 中心系统侧一次性配置

### 3.1 补上豆豆集的业务回调地址

下单时若不传 `notify_url`，中心系统会回落到 `wechat_app.callback_url`；该字段现在是空的，
**不补的话支付成功后中心系统无处转发，订单会停在 `notify_status=SKIPPED`**。

```sql
-- 在中心系统宿主机 207.57.122.116 上执行
docker exec central-system-db psql -U postgres -d central_system -c \
  "UPDATE wechat_app SET callback_url='https://<豆豆集域名>/api/pay/notify' WHERE app_code='doudouji_prod';"
```

也可以每次下单传 `notify_url` 覆盖它（推荐这样，多环境/多业务可分别配）。

### 3.2 取豆豆集的 app_secret

```bash
docker exec central-system-db psql -U postgres -d central_system -tAc \
  "select app_secret from wechat_app where app_code='doudouji_prod'"
```

这个密钥有**两个用途**：① 调中心系统接口的 `X-App-Secret`；② 验证中心系统回调通知的 HMAC 签名。
豆豆集后端要妥善保管，不要写进前端。

### 3.3 创建微信支付商户配置

```bash
cd /data/projects/central-system/central-system/deploy
PAY_ADMIN_KEY=$(grep '^PAY_ADMIN_KEY=' .env | cut -d= -f2)

curl -sS -X POST 'https://central.system.sevenblue.cn/api/v1/pay/merchant' \
  -H "X-Pay-Admin-Key: ${PAY_ADMIN_KEY}" \
  -H 'Content-Type: application/json' \
  -d @- <<'JSON'
{
  "app_code": "doudouji_prod",
  "provider": "wxpay",
  "name": "default",
  "mp_appid": "wxe6f4c82236f269b5",
  "remark": "豆豆集自有微信支付商户号",
  "config": {
    "mch_id": "1900000000",
    "api_v3_key": "<32字节APIv3密钥>",
    "cert_serial_no": "5157F09EFDC096DE15EBE81A47057A72F4B9A9C0",
    "private_key_pem": "-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----\n",
    "public_key_pem": "-----BEGIN PUBLIC KEY-----\n...\n-----END PUBLIC KEY-----\n",
    "public_key_id": "PUB_KEY_ID_xxxxxxxx",
    "appid": "wxe6f4c82236f269b5"
  }
}
JSON
```

要点：

- `name` 用 `default` —— 中心系统选默认商户配置时优先取这个名字（`merchant_service.py:130-133`）。
  不传 `merchant_id` 下单时走的就是它。
- `private_key_pem` / `public_key_pem` 是 JSON 字符串里的**多行 PEM**，JSON 会把换行转义成 `\n`，
  中心系统解析时会还原（`crypto.py:36-57`），不用手工处理。
- `config.appid` 与 `mp_appid` 都填 JSAPI 用的公众号 AppID。`config.appid` 优先，
  没填则回落到 `mp_appid`（`wxpay.py:214`）。
- **注意**：`config` 里只有 `mch_id`/`api_v3_key`/`cert_serial_no`/`private_key_pem` 是中心系统
  强校验的必填项；`public_key_pem`/`public_key_id` **不在必填列表里**，但回调验签必须用，
  漏填的话「建配置能成功、回调 100% 失败」（见 §6 坑 1）。
- 创建后**立即生效**，无需重启容器；改配置用 `PUT /api/v1/pay/merchant/{merchant_id}`，
  同样带 `X-Pay-Admin-Key`。
- 响应里的 `config` 是**打码**后的（密钥只回显首尾 4 位），这是正常的。

建好后记下返回的 `id`（形如 `01M5...`，26 位 ULID），它会出现在微信回调地址里：

```
https://central.system.sevenblue.cn/api/v1/pay/notify/wxpay/<merchant_id>
```

---

## 4. 豆豆集侧接口调用

所有业务接口都走 `https://central.system.sevenblue.cn/api/v1/pay/*`，请求头固定：

```
X-App-Code: doudouji_prod
X-App-Secret: <app_secret>
Content-Type: application/json
```

### 4.1 下单

```
POST /api/v1/pay/order
```

```json
{
  "provider": "wxpay",
  "trade_type": "jsapi",
  "subject": "豆豆集-会员年费",
  "description": "VIP 年卡",
  "amount": "39.90",
  "currency": "CNY",
  "payer_openid": "oUpF8uMuAJO_M2pxb1Q9zNjWeS6o",
  "client_order_no": "DDJ20261023000123",
  "notify_url": "https://<豆豆集域名>/api/pay/notify",
  "attach": "member_id=8899",
  "expire_minutes": 30
}
```

| 字段 | 说明 |
|---|---|
| `amount` | **单位是元**，字符串或数字都行（建议字符串，避开浮点误差）；内部按分发给微信 |
| `client_order_no` | **幂等键**。同一个 `app_code + client_order_no` 只会有一张订单，重复下单直接返回原订单，不会二次扣款 |
| `trade_type` | `jsapi`（公众号内唤起）/ `native`（扫码）/ `h5`（手机浏览器）/ `app`（原生 App） |
| `payer_openid` | **JSAPI 必填**，且必须是 `config.appid` 那个公众号下的 openid |
| `notify_url` | 支付成功后中心系统通知豆豆集的地址；不传则用 §3.1 配的 `callback_url` |
| `attach` | 业务透传参数（≤200 字符），支付成功通知里原样带回 |

响应：

```json
{
  "out_trade_no": "cs_01M5XK2P...",
  "client_order_no": "DDJ20261023000123",
  "provider": "wxpay",
  "trade_type": "jsapi",
  "subject": "豆豆集-会员年费",
  "amount": "39.90",
  "currency": "CNY",
  "status": "PENDING",
  "pay_params": {
    "appId": "wxe6f4c82236f269b5",
    "timeStamp": "1792800000",
    "nonceStr": "a1b2c3...",
    "package": "prepay_id=wx2611...",
    "signType": "RSA",
    "paySign": "o0PGR..."
  },
  "expires_at": "2026-10-23T18:30:00",
  "created_at": "2026-10-23T18:00:00"
}
```

`pay_params` 交给前端直接拉起支付：

- **jsapi**：`WeixinJSBridge.invoke('getBrandWCPayRequest', pay_params)`
  （公众号网页用 `wx.chooseWXPay`；小程序用 `wx.requestPayment`）
- **native**：`{code_url}` → 前端渲染成二维码
- **h5**：`{h5_url}` → `location.href = h5_url`（需在 `extra.client_ip` 传用户 IP）
- **app**：`{appid, partnerid, prepayid, package, noncestr, timestamp, sign}` → 传给原生 SDK

### 4.2 查单 / 主动对账 / 关单 / 退款

| 用途 | 方法 | 路径 | 请求体 |
|---|---|---|---|
| 查订单 | GET | `/api/v1/pay/order/{out_trade_no}` | — |
| 订单列表 | GET | `/api/v1/pay/orders?status=PAID&page=1&page_size=20` | — |
| 主动向微信查单并同步状态 | POST | `/api/v1/pay/order/{out_trade_no}/sync` | — |
| 关单（未支付时） | POST | `/api/v1/pay/order/{out_trade_no}/close` | — |
| 退款 | POST | `/api/v1/pay/refund` | `{"out_trade_no":"...","amount":"39.90","reason":"用户申请","refund_no":"RF20261023001"}` |
| 查退款 | GET | `/api/v1/pay/refund/{refund_no}` | — |

- 退款金额不传默认全额；`refund_no` 是退款幂等键。
- 退款回调也走同一个 `notify_url`（微信会异步通知退款结果），报文同上，`status` 为 `REFUNDED` 等。

---

## 5. 支付成功通知（中心系统 → 豆豆集）

### 5.1 触发方式

中心系统收到微信异步回调后，验签解密 → 改订单状态 → **主动 POST 豆豆集的 `notify_url`**。

### 5.2 请求

```
POST https://<豆豆集域名>/api/pay/notify
Content-Type: application/json
X-App-Code: doudouji_prod
X-Pay-Timestamp: 1792800000
X-Pay-Nonce: wx2611xxxx
X-Pay-Signature: <hex>
X-Pay-Event: payment.success
```

```json
{
  "out_trade_no": "cs_01M5XK2P...",
  "client_order_no": "DDJ20261023000123",
  "app_code": "doudouji_prod",
  "provider": "wxpay",
  "provider_trade_no": "4200001234567890123",
  "trade_type": "jsapi",
  "subject": "豆豆集-会员年费",
  "amount": "39.90",
  "currency": "CNY",
  "status": "PAID",
  "attach": "member_id=8899",
  "paid_at": "2026-10-23T18:05:12",
  "event_type": "TRANSACTION.SUCCESS",
  "event_id": "EVT2018022511223320873"
}
```

### 5.3 验签（豆豆集必须做）

```
待签串 = f'{X-Pay-Timestamp}.{X-Pay-Nonce}.{原始请求体}'
签名   = HMAC-SHA256(app_secret, 待签串) 的 hexdigest
```

- **必须用原始请求体字节**（不要 `json.loads` 后重新序列化，键序/空格变了就对不上）。
- 比较用大小写不敏感。
- 建议校验时间戳新鲜度（中心系统侧的 TTL 常量是 300 秒）。
- 示例代码见 `examples/doudouji_notify_app.py`。

### 5.4 幂等与响应

- **中心系统会重投**：通知失败（豆豆集返回非 2xx 或超时）时中心系统最多重试 **3 次**，退避 2s、4s。
  微信自己也会重投（它看到中心系统回了失败才会重试；中心系统回的是成功）。
  → **豆豆集必须自己做幂等**，幂等键用 `out_trade_no`（`event_id` 可作二次幂等键）。
- 豆豆集只要返回 **2xx** 就认为通知成功，**立刻返回，把发货逻辑放异步**（中心系统超时是 10 秒）。
- 通知失败后中心系统**没有补发接口**，只能靠豆豆集主动调 `/sync` 或 `/order/{out_trade_no}` 兜底，
  所以强烈建议豆豆集后台做**定时对账**（扫 `PENDING` 超时订单 → 调 `/sync`）。

---

## 6. 已知坑（照着做就不会踩）

1. **回调验签公钥漏配**：`pay_merchant.config` 的强校验只查 `mch_id`/`api_v3_key`/`cert_serial_no`/`private_key_pem`，
   `public_key_pem`+`public_key_id`（或 `platform_cert_pem`）**不在必填列表**里，
   但没有它微信回调验签必然失败（`wxpay.py:147-167`）。**配置时手工带上。**
2. **`callback_url` 为空**：`wechat_app.callback_url` 现在是空的，不补的话订单通知状态是 `SKIPPED`，
   豆豆集永远收不到支付成功通知。
3. **豆豆集回调地址的证书必须是公共信任证书**（Let's Encrypt 等）。中心系统用 httpx 直连豆豆集，
   默认校验证书，自签/过期证书会导致通知直接失败（错误落在中心系统日志里，豆豆集侧看不到）。
4. **金额单位**：中心系统对外是**元**，微信 APIv3 是**分**，中心系统内部已转换，别自己再乘 100。
5. **金额不一致的处理**：微信回调金额与本地订单金额不一致时，中心系统**不更新订单但仍返回成功**
   （避免回调风暴），并在 `pay_notify_log` 记 `AMOUNT_MISMATCH`。这类单子要人工介入，豆豆集侧永远收不到通知。
6. **JSAPI 的 openid 要对得上**：必须是用 `config.appid`（豆豆集公众号）换来的 openid，
   拿别的公众号的 openid 会下单失败。中心系统**没有** code2openid 接口，
   豆豆集要自己走公众号网页授权（`snsapi_base`）或小程序 `code2openid`。
7. **公众号 IP 白名单**：若豆豆集后端自己调公众号接口取 openid，豆豆集服务器的出口 IP 要加进公众号白名单。
8. **`native` 场景的 appid**：中心系统 `wxpay.py:223` 在没配 appid 时可能把 `null` 传给微信，
   所以 `config.appid` 建议一定配上。
9. **商户配置改动即时生效**，无需重启；但改 `api_v3_key` 之类要同步确认渠道侧一致，否则验签/解密全挂。
10. **CORS 没有**：前端不要直连中心系统。

---

## 7. 联调 checklist

按顺序做，每步都有明确的成功标志：

| # | 步骤 | 成功标志 |
|---|---|---|
| 1 | 中心系统建 `wxpay` 商户配置（§3.3） | 返回 `id`，`status=1` |
| 2 | 中心系统 `GET /api/v1/pay/merchant?app_code=doudouji_prod` | 能查到，且 `config` 里密钥已打码 |
| 3 | 豆豆集 `POST /api/v1/pay/order`（金额 0.01 元） | 返回 `out_trade_no` + `pay_params.paySign` |
| 4 | 前端拉起支付 | 微信能弹出支付面板（能拉起就说明商户号/证书/密钥都对） |
| 5 | 支付完成后查中心系统 `GET /api/v1/pay/order/{out_trade_no}` | `status=PAID`，`notify_status=SUCCESS` |
| 6 | 豆豆集收到通知 | 验签通过、`status=PAID`；微信商户后台能查到这笔交易 |
| 7 | 重复通知 | 豆豆集只发货一次（幂等生效） |
| 8 | 退款 | `POST /api/v1/pay/refund` 返回 `status=SUCCESS` 或 `PENDING`，微信侧看到退款 |
| 9 | 故意让豆豆集回调返回 500 | 中心系统日志有 3 次重试，订单 `notify_status=FAILED`；恢复后靠 `/sync` 兜底 |

排错时看这几处：

```bash
# 中心系统日志（回调验签、转发、重试）
cd /data/projects/central-system/central-system/deploy
docker compose logs -f app | grep -E "支付回调|业务通知|pay"

# 回调幂等/异常落库记录
docker exec central-system-db psql -U postgres -d central_system -c \
  "select provider,event_id,out_trade_no,result,message,created_at from pay_notify_log order by created_at desc limit 20;"
```

---

## 8. 示例代码

| 文件 | 用途 |
|---|---|
| `examples/doudouji_pay_client.py` | 豆豆集后端调中心系统：下单/查单/同步/关单/退款 + 通知验签函数 |
| `examples/doudouji_notify_app.py` | 豆豆集侧接收支付成功通知的最小 FastAPI 服务（含幂等示例） |

拷到豆豆集服务器后改环境变量即可：

```bash
export CENTER_URL=https://central.system.sevenblue.cn
export CENTER_APP_CODE=doudouji_prod
export CENTER_APP_SECRET=<从中心系统库中取到的 app_secret>
export NOTIFY_URL=https://<豆豆集域名>/api/pay/notify
```

---

## 9. 豆豆集调用中心系统 API 速查

### 9.1 调用形态

**只有豆豆集后端能调中心系统**。中心系统没配 CORS，浏览器跨域会被拦；
豆豆集前端只跟豆豆集自己的后端交互，后端代调中心系统。

```
豆豆集前端 ──► 豆豆集后端 ──► 中心系统
                (持 app_secret，加 X-App-Code/X-App-Secret 头)
```

### 9.2 认证

除支付回调入口（`/api/v1/pay/notify/*`，靠微信签名）外，**所有业务接口**都要带：

```
X-App-Code: doudouji_prod
X-App-Secret: <app_secret>
```

`verify_app_request`（`app/common/security.py:9-43`）会校验 app_code + app_secret + `status=1`，
不匹配返回 401「无效的应用凭证」。**订单的 app_code 由请求头决定**，
所以豆豆集只能创建归属自己 `doudouji_prod` 的订单，查别人的订单会 404。

### 9.3 支付接口（`/api/v1/pay/*`）

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/v1/pay/order` | 下单（幂等键 `client_order_no`） |
| GET | `/api/v1/pay/order/{out_trade_no}` | 查单 |
| GET | `/api/v1/pay/orders` | 订单列表（分页、可按状态/业务单号过滤） |
| POST | `/api/v1/pay/order/{out_trade_no}/sync` | 主动向微信查单并同步状态（对账） |
| POST | `/api/v1/pay/order/{out_trade_no}/close` | 关单 |
| POST | `/api/v1/pay/refund` | 退款 |
| GET | `/api/v1/pay/refund/{refund_no}` | 查退款 |

详细字段见 §4。

### 9.4 扫码接口（`/api/v1/scan/*`）——JSAPI 支付的 openid 从这来

中心系统已经托管了豆豆集公众号（`wxe6f4c82236f269b5`）的事件回调，
**豆豆集不需要自己做网页授权就能拿到 openid**：用公众号扫码会话即可。

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/v1/scan/create` | 创建扫码会话，返回 `scene_key` / `qrcode_url` / `expired_at` |
| GET | `/api/v1/scan/status?scene_key=xxx` | 查状态，已扫码时返回 `openid`/`unionid`/`nickname` |
| POST | `/api/v1/scan/consume` | 消费会话，把 openid 绑定到豆豆集的用户 |
| GET | `/api/v1/scan/qrcode?app_code=doudouji_prod&purpose=login` | 简化版：一步拿二维码（免鉴权，仅校验 app_code 存在） |
| GET | `/api/v1/scan/check?app_code=doudouji_prod&scene_key=xxx` | 简化版：查状态，openid 直接在返回值里 |

推荐流程（豆豆集用它同时解决「登录」和「支付 openid」）：

```
用户扫码 → 豆豆集轮询 /api/v1/scan/status → 拿到 openid
        → 豆豆集调 /api/v1/scan/consume 把 openid 绑到自己的 user_id
        → 用同一个 openid 调 /api/v1/pay/order（trade_type=jsapi）下单
```

⚠️ 前提：公众号后台的「服务器地址」要指向中心系统
`https://central.system.sevenblue.cn/api/v1/wechat/callback/wxe6f4c82236f269b5`，
否则扫码事件推不到中心系统，拿不到 openid。

### 9.5 调用示例（curl）

```bash
CENTER=https://central.system.sevenblue.cn
APP_CODE=doudouji_prod
APP_SECRET='<app_secret>'

# 下单
curl -sS -X POST "$CENTER/api/v1/pay/order" \
  -H "X-App-Code: $APP_CODE" -H "X-App-Secret: $APP_SECRET" \
  -H 'Content-Type: application/json' \
  -d '{"provider":"wxpay","trade_type":"jsapi","subject":"豆豆集-会员年费",
       "amount":"39.90","payer_openid":"oUpF8u...",
       "client_order_no":"DDJ20261023000123",
       "notify_url":"https://<豆豆集域名>/api/pay/notify"}'

# 查单
curl -sS "$CENTER/api/v1/pay/order/cs_01M5XK2P..." \
  -H "X-App-Code: $APP_CODE" -H "X-App-Secret: $APP_SECRET"

# 主动对账
curl -sS -X POST "$CENTER/api/v1/pay/order/cs_01M5XK2P.../sync" \
  -H "X-App-Code: $APP_CODE" -H "X-App-Secret: $APP_SECRET"
```

### 9.6 调用侧建议

- **超时**：中心系统侧 httpx 调上游是 10~15 秒；豆豆集调中心系统建议超时 10~15 秒，别更长。
- **重试**：网络错误/5xx 可以重试；**4xx 不要重试**（参数错或没配商户配置，重试也不会成功）。
- **幂等**：下单永远带 `client_order_no`，退款带 `refund_no`；重试同一次请求不会产生第二张单。
- **不要在前端放 app_secret**。
- **对账**：定时扫 `PENDING` 且超时的订单，调 `/sync` 拉真实状态（中心系统的通知失败不会自动补发）。
