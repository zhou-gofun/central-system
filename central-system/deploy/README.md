# 中心系统 部署说明

生产环境部署目录。应用 + PostgreSQL 全部跑在 Docker 里，由宿主机上已有的 Caddy 容器统一提供 HTTPS。

## 架构

```
公网 https://central.system.sevenblue.cn
        │  (DNS A → 207.57.122.116, Let's Encrypt 自动签发/续期)
        ▼
Caddy 容器 (sub2api-caddy, 80/443)
   └─ reverse_proxy → central-system-app:8000
                          │  (docker network: deploy_sub2api-network)
                          ▼
                    central-system-app (FastAPI + Gunicorn, 2 workers)
                          │  (docker network: central-system-net)
                          ▼
                    central-system-db (PostgreSQL 16)
```

| 组件 | 容器名 | 端口 | 说明 |
|------|--------|------|------|
| 应用 | `central-system-app` | `127.0.0.1:8000` | 只监听本机，对外由 Caddy 代理 |
| 数据库 | `central-system-db` | `127.0.0.1:5432` | 只监听本机，不对公网暴露 |
| 数据卷 | `central-system-pgdata` | - | PostgreSQL 数据持久化 |

## 目录文件

| 文件 | 说明 |
|------|------|
| `Dockerfile` | 应用镜像构建（python:3.12-slim + requirements.txt） |
| `docker-compose.yml` | app + db 编排 |
| `entrypoint.sh` | 容器入口：等待数据库 → 建表 → 启动 Gunicorn |
| `init_db.py` | 按 ORM 模型建表（幂等，不写示例数据） |
| `seed_from_xlsx.py` | 从 xlsx 导入公众号配置并创建业务应用（幂等） |
| `.env` | 密钥与配置（DB 密码、PAY_ADMIN_KEY 等，**勿提交**） |

支付模块接入文档见 [`docs/PAYMENT_INTEGRATION.md`](../docs/PAYMENT_INTEGRATION.md)。

## 常用命令

```bash
cd /data/projects/central-system/central-system/deploy

docker compose ps            # 查看状态
docker compose logs -f app   # 跟踪应用日志
docker compose up -d         # 启动 / 应用变更
docker compose restart app   # 重启应用
docker compose down          # 停止（数据卷保留）
docker compose build --no-cache && docker compose up -d   # 重新构建镜像
```

## 数据库

```bash
# 进入 psql
docker exec -it central-system-db psql -U postgres -d central_system

# 查看表
docker exec central-system-db psql -U postgres -d central_system -c '\dt'
```

表结构：`wechat_app`（业务应用）、`wechat_mp_config`（公众号配置）、`wechat_scan_session`（扫码会话）、
`pay_merchant`（支付商户配置）、`pay_order`（支付订单）、`pay_notify_log`（回调幂等日志）、`pay_refund`（退款单）。

## 初始化数据导入

公众号配置来自 `data/wechat_mp_config.xlsx`，业务应用通过 `seed` 服务一次性导入：

```bash
cd /data/projects/central-system/central-system/deploy
docker compose run --rm seed
```

- 读取 `../../data/wechat_mp_config.xlsx`（只读挂载到容器 `/seed`）→ upsert `wechat_mp_config`
- 创建/更新业务应用 `wechat_app`：`app_code` / `app_name` 取自 `.env` 的 `SEED_APP_CODE` / `SEED_APP_NAME`
- 首次运行自动生成随机 `app_secret` 并打印，**重跑保留原密钥**（幂等）
- 需要指定自己的密钥时：`--app-secret` 或 `--app-secret-file`（文件内容优先）

当前数据：

| 表 | 内容 |
|----|------|
| `wechat_mp_config` | 小飞雁服务号 `wxe6f4c82236f269b5` |
| `wechat_app` | `doudouji_prod` / 豆豆集-生产环境 / 绑定上面这个公众号 |

## 微信公众号后台配置

### 1. IP 白名单（必做，否则创建二维码报 500）

调用微信 `api.weixin.qq.com` 换 access_token 时，微信会校验调用方出口 IP，未放行会返回：

```
errcode 40164: invalid ip 207.57.122.116 ipv6 ::ffff:207.57.122.116, not in whitelist
```

需要到**小飞雁服务号**（appid `wxe6f4c82236f269b5`）的
**微信公众号后台 → 设置与开发 → 基本配置 → IP 白名单**，把服务器出口 IP `207.57.122.116` 加进去
（IPv6 形式 `::ffff:207.57.122.116` 一并加上更保险）。

注意：
- 必须加在**该公众号账号**下，不是微信开放平台，也不是小程序账号；
- 修改后微信侧有生效延迟（通常 1~5 分钟），期间请求仍会返回 40164；
- 验证是否生效：`docker compose logs app | grep 40164`，无该错误即已生效。

> 状态：✅ 已放行并生效，`/api/v1/scan/create` 已实测返回 200 + 二维码 ticket。

### 2. 服务器配置（回调地址）

| 项 | 值 |
|----|----|
| URL | `https://central.system.sevenblue.cn/api/v1/wechat/callback/wxe6f4c82236f269b5` |
| Token | 见 `wechat_mp_config.xlsx` 的 `token` 列，或查库 `wechat_mp_config.token`（**勿提交到仓库**） |
| EncodingAESKey | xlsx 中的 `aes_key`，留空则不加密 |

配置时微信会先发 GET 验证请求，服务端用 `sha1(sorted(token, timestamp, nonce))` 校验签名，
校验通过返回 `echostr`，微信后台即显示"配置成功"。

回调接口已验证：GET 正确签名返回 200 + echostr，错误签名返回 403；POST 事件推送返回 200 `success`。

### 3. 扫码事件

用户扫码后微信推送 `SCAN`（已关注）或 `subscribe`（未关注，EventKey 带 `qrscene_` 前缀）事件，
服务端据 `scene_key` 更新 `wechat_scan_session` 状态并写回 openid。

## 业务应用密钥（app_secret）

`wechat_app.app_secret` 由 seed 脚本首次运行时随机生成并打印，**重跑保留原值**。需要随时取回：

```bash
docker exec central-system-db psql -U postgres -d central_system -tAc \
  "select app_secret from wechat_app where app_code='doudouji_prod'"
```

调用业务接口时放进请求头 `X-App-Secret`：

```bash
curl -X POST https://central.system.sevenblue.cn/api/v1/scan/create \
  -H 'Content-Type: application/json' \
  -H 'X-App-Code: doudouji_prod' \
  -H "X-App-Secret: <上面查出来的密钥>" \
  -d '{"purpose":"login"}'
```

## 接口速查

| 接口 | 方法 | 鉴权 | 说明 |
|------|------|------|------|
| `/api/v1/scan/create` | POST | `X-App-Code` + `X-App-Secret` | 创建扫码会话，返回二维码 URL |
| `/api/v1/scan/status` | GET | 同上 | 会话状态（0 待扫码 / 1 已扫码 / 2 已消费 / -1 无效 / -2 过期） |
| `/api/v1/scan/consume` | POST | 同上 | 消费会话（已扫码 → 已消费） |
| `/api/v1/scan/qrcode` | GET | URL 参数 `app_code` | 兼容旧项目的简化接口 |
| `/api/v1/scan/check` | GET | URL 参数 `app_code` | 兼容旧项目的状态查询（返回中文状态） |
| `/api/v1/wechat/callback/{mp_appid}` | GET | 微信签名 | 回调地址验证 |
| `/api/v1/wechat/callback/{mp_appid}` | POST | 微信签名 | 接收扫码事件 |

支付接口（详见 `docs/PAYMENT_INTEGRATION.md`）：

| 接口 | 方法 | 鉴权 | 说明 |
|------|------|------|------|
| `/api/v1/pay/order` | POST | `X-App-Code` + `X-App-Secret` | 创建支付订单 |
| `/api/v1/pay/order/{out_trade_no}` | GET | 同上 | 查询订单状态 |
| `/api/v1/pay/orders` | GET | 同上 | 分页查询订单 |
| `/api/v1/pay/order/{out_trade_no}/close` | POST | 同上 | 关单 |
| `/api/v1/pay/order/{out_trade_no}/sync` | POST | 同上 | 主动向渠道查单 |
| `/api/v1/pay/refund` | POST | 同上 | 发起退款 |
| `/api/v1/pay/notify/{provider}/{merchant_id}` | POST | 渠道签名 | 支付渠道回调 |
| `/api/v1/pay/merchant` | GET/POST | `X-Pay-Admin-Key` | 商户配置管理 |

`X-Pay-Admin-Key` 在 `deploy/.env` 的 `PAY_ADMIN_KEY`，取用：

```bash
grep PAY_ADMIN_KEY /data/projects/central-system/central-system/deploy/.env | cut -d= -f2
```

## Caddy 说明

反向代理配置在 **`/data/projects/sub2api/deploy/Caddyfile`**（sub2api 项目的 Caddy 容器，两边共用 80/443）。

⚠️ 该文件是以**单文件 bind mount** 挂进容器的。用编辑器替换文件（inode 变化）后，容器内看到的仍是旧内容，需要：

```bash
docker cp /data/projects/sub2api/deploy/Caddyfile sub2api-caddy:/root/Caddyfile
docker exec sub2api-caddy caddy reload --config /root/Caddyfile
```

（容器重启后会自动重新解析挂载，恢复为宿主机上的最新文件。）

## 排查

```bash
curl -s https://central.system.sevenblue.cn/health        # 期望 {"status":"ok"}
docker logs --tail 50 central-system-app
docker logs --tail 50 sub2api-caddy | grep central.system
```

- **502/503**：应用未就绪。Caddy 健康检查间隔 30s，容器重建后可能有约 30s 的 503 窗口。
- **证书失败**：确认 DNS A 记录仍指向 `207.57.122.116`，且 80/443 可从公网访问。
- **数据库连不上**：`docker compose logs db`，检查 `.env` 里的 `DB_PASSWORD` 与数据卷是否匹配（改密码后旧卷里的密码不会变）。
- **Caddy 容器显示 unhealthy**：属 sub2api 项目的历史问题——它的 healthcheck 请求 `http://localhost:2019/health`，
  而 Caddy admin API 没有该路径（返回 404 → wget 退出码 1）。与本项目无关，站点实际访问正常。
- **支付回调 400 验签失败**：商户配置里的 `public_key_pem`/`platform_cert_pem` 配错，或 `public_key_id`
  与微信返回的 `Wechatpay-Serial` 不一致。渠道的 `Wechatpay-Serial` 头可以在应用日志里看到。
- **支付回调 400 解密失败**：`api_v3_key` 与商户平台当前生效的 APIv3 密钥不一致。
- **微信支付下单报 IP 不在白名单**：出口 IP `207.57.122.116` 要同时加到**微信支付商户平台**的白名单
  （公众号后台那个白名单只管 `api.weixin.qq.com`，管不到支付接口）。
