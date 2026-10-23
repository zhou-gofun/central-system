# 微信中心系统设计方案

## 1. 架构概览

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│   业务系统 A    │     │   业务系统 B    │     │   业务系统 C    │
│  (jgweb_prod)   │     │  (jgweb_test)   │     │   (其他项目)    │
└────────┬────────┘     └────────┬────────┘     └────────┬────────┘
         │                       │                       │
         └───────────────────────┼───────────────────────┘
                                 │ HTTP API
                                 ▼
                    ┌────────────────────────┐
                    │      中心系统          │
                    │  (WeChat Auth Center)  │
                    ├────────────────────────┤
                    │ • 微信公众号回调       │
                    │ • 二维码生成           │
                    │ • 扫码状态管理         │
                    │ • 多公众号支持         │
                    └────────────┬───────────┘
                                 │
                                 ▼
                    ┌────────────────────────┐
                    │      微信服务器        │
                    └────────────────────────┘
```

## 2. 数据库设计

### 2.1 业务应用表 (wechat_app)

```sql
CREATE TABLE wechat_app (
    id VARCHAR(26) PRIMARY KEY,
    app_code VARCHAR(32) UNIQUE NOT NULL COMMENT '应用标识 如jgweb_prod',
    app_name VARCHAR(100) COMMENT '应用名称',
    app_secret VARCHAR(64) NOT NULL COMMENT '应用密钥',
    mp_appid VARCHAR(50) COMMENT '绑定的公众号AppID',
    callback_url VARCHAR(500) COMMENT '回调地址(可选)',
    status TINYINT DEFAULT 1 COMMENT '1=启用 0=禁用',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

### 2.2 扫码会话表 (wechat_scan_session)

```sql
CREATE TABLE wechat_scan_session (
    id VARCHAR(26) PRIMARY KEY,
    scene_key VARCHAR(64) UNIQUE NOT NULL COMMENT '场景值',
    app_code VARCHAR(32) NOT NULL COMMENT '来源应用',
    mp_appid VARCHAR(50) COMMENT '公众号AppID',
    purpose VARCHAR(20) NOT NULL COMMENT 'login/register/bind',
    openid VARCHAR(100) COMMENT '微信openid',
    unionid VARCHAR(100) COMMENT '微信unionid',
    nickname VARCHAR(100),
    headimgurl TEXT,
    status TINYINT DEFAULT 0 COMMENT '0=待扫码 1=已扫码 2=已消费',
    extra_data JSON COMMENT '额外数据',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    expired_at DATETIME NOT NULL,
    INDEX idx_scene_key (scene_key),
    INDEX idx_app_status (app_code, status),
    INDEX idx_expired (expired_at)
);
```

### 2.3 公众号配置表 (wechat_mp_config)

```sql
CREATE TABLE wechat_mp_config (
    id VARCHAR(26) PRIMARY KEY,
    appid VARCHAR(50) UNIQUE NOT NULL,
    secret VARCHAR(100) NOT NULL,
    token VARCHAR(100) NOT NULL,
    aes_key VARCHAR(100),
    name VARCHAR(100) COMMENT '公众号名称',
    status TINYINT DEFAULT 1,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

## 3. API 接口设计

### 3.1 业务系统调用接口

| 接口 | 方法 | 说明 |
|------|------|------|
| `/api/v1/scan/create` | POST | 创建扫码会话 |
| `/api/v1/scan/status` | GET | 查询扫码状态 |
| `/api/v1/scan/consume` | POST | 消费会话 |

#### 创建扫码会话
```
POST /api/v1/scan/create
Headers: X-App-Code, X-App-Secret
Body: {
    "purpose": "login",        // login/register/bind
    "expire_seconds": 300,
    "extra_data": {}           // 可选
}
Response: {
    "scene_key": "log_abc123",
    "qrcode_url": "https://mp.weixin.qq.com/...",
    "expired_at": "2026-01-09T12:00:00"
}
```

#### 查询扫码状态
```
GET /api/v1/scan/status?scene_key=xxx
Headers: X-App-Code, X-App-Secret
Response: {
    "status": 1,           // -2=过期 -1=无效 0=待扫码 1=已扫码 2=已消费
    "purpose": "login",
    "openid": "xxx",       // status>=1时返回
    "unionid": "xxx",
    "nickname": "xxx",
    "headimgurl": "xxx"
}
```

#### 消费扫码会话
```
POST /api/v1/scan/consume
Headers: X-App-Code, X-App-Secret
Body: {
    "scene_key": "xxx",
    "external_user_id": "业务系统用户ID"  // 可选
}
Response: { "success": true }
```

### 3.2 微信回调接口

```
GET/POST /api/v1/wechat/callback/{mp_appid}
```
- GET: 微信服务器验证
- POST: 处理扫码事件

## 4. 中心系统目录结构

```
wechat-center/
├── app/
│   ├── main.py
│   ├── api/
│   │   ├── wechat.py          # 微信回调
│   │   ├── scan.py            # 扫码会话
│   │   └── app_manage.py      # 应用管理
│   ├── model/
│   │   ├── wechat_app.py
│   │   ├── scan_session.py
│   │   └── mp_config.py
│   ├── service/
│   │   ├── wechat_mp.py       # 微信API
│   │   └── scan_service.py    # 扫码服务
│   └── common/
│       ├── config.py
│       ├── database.py
│       └── security.py
├── migrations/
├── .env
└── requirements.txt
```

## 5. 核心代码

### 5.1 扫码服务 (scan_service.py)

```python
class ScanService:
    async def create_session(self, app_code, mp_appid, purpose, expire_seconds=300):
        scene_key = f"{purpose[:3]}_{uuid.uuid4().hex[:16]}"
        expired_at = datetime.now() + timedelta(seconds=expire_seconds)

        mp_service = WechatMPService(mp_appid)
        qrcode = await mp_service.create_qrcode(scene_key, expire_seconds)

        session = ScanSession(
            id=generate_ulid(),
            scene_key=scene_key,
            app_code=app_code,
            mp_appid=mp_appid,
            purpose=purpose,
            expired_at=expired_at
        )
        self.db.add(session)
        await self.db.commit()

        return {"scene_key": scene_key, "qrcode_url": qrcode["url"], "expired_at": expired_at}

    async def handle_scan_event(self, mp_appid, scene_key, openid):
        session = await self._get_session(scene_key, mp_appid)
        if not session or session.status != 0:
            return

        user_info = await WechatMPService(mp_appid).get_user_info(openid)
        session.openid = openid
        session.unionid = user_info.get("unionid")
        session.nickname = user_info.get("nickname")
        session.headimgurl = user_info.get("headimgurl")
        session.status = 1
        await self.db.commit()

    async def get_status(self, scene_key, app_code):
        session = await self._get_session_by_app(scene_key, app_code)
        if not session:
            return {"status": -1}
        if datetime.now() > session.expired_at:
            return {"status": -2}

        result = {"status": session.status, "purpose": session.purpose}
        if session.status >= 1:
            result.update({
                "openid": session.openid,
                "unionid": session.unionid,
                "nickname": session.nickname,
                "headimgurl": session.headimgurl
            })
        return result

    async def consume_session(self, scene_key, app_code, external_user_id=None):
        result = await self.db.execute(
            update(ScanSession)
            .where(ScanSession.scene_key == scene_key,
                   ScanSession.app_code == app_code,
                   ScanSession.status == 1)
            .values(status=2)
        )
        await self.db.commit()
        return result.rowcount > 0
```

### 5.2 安全验证 (security.py)

```python
async def verify_app_request(
    x_app_code: str = Header(..., alias="X-App-Code"),
    x_app_secret: str = Header(..., alias="X-App-Secret"),
    db: AsyncSession = Depends(get_db)
) -> dict:
    app = await db.execute(
        select(WechatApp).where(
            WechatApp.app_code == x_app_code,
            WechatApp.app_secret == x_app_secret,
            WechatApp.status == 1
        )
    )
    app = app.scalar_one_or_none()
    if not app:
        raise HTTPException(401, "无效的应用凭证")
    return {"app_code": app.app_code, "mp_appid": app.mp_appid}
```

## 6. 业务系统客户端 SDK

```python
# service/wechat/center_client.py
class WechatCenterClient:
    def __init__(self):
        self.base_url = settings.WECHAT_CENTER_URL
        self.app_code = settings.WECHAT_APP_CODE
        self.app_secret = settings.WECHAT_APP_SECRET

    def _headers(self):
        return {"X-App-Code": self.app_code, "X-App-Secret": self.app_secret}

    async def create_qrcode(self, purpose: str, expire_seconds: int = 300) -> dict:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{self.base_url}/api/v1/scan/create",
                headers=self._headers(),
                json={"purpose": purpose, "expire_seconds": expire_seconds}
            )
            return resp.json()

    async def check_status(self, scene_key: str) -> dict:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{self.base_url}/api/v1/scan/status",
                headers=self._headers(),
                params={"scene_key": scene_key}
            )
            return resp.json()

    async def consume(self, scene_key: str, user_id: str = None) -> bool:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{self.base_url}/api/v1/scan/consume",
                headers=self._headers(),
                json={"scene_key": scene_key, "external_user_id": user_id}
            )
            return resp.status_code == 200

wechat_center = WechatCenterClient()
```

## 7. 环境配置

### 中心系统 .env
```bash
DATABASE_URL=mysql+aiomysql://user:pass@host/wechat_center
```

### 业务系统 .env
```bash
WECHAT_CENTER_URL=https://wechat.your-domain.com
WECHAT_APP_CODE=jgweb_prod
WECHAT_APP_SECRET=your_secret_here
```

## 8. 交互流程

```
前端 → 业务系统 → 中心系统 → 微信API (创建二维码)
                      ↑
              微信服务器回调 (用户扫码)
                      ↓
前端 ← 业务系统 ← 中心系统 (返回用户信息)
        ↓
    本地用户处理
        ↓
    业务系统 → 中心系统 (消费会话)
```

## 9. 优势

| 方面 | 说明 |
|------|------|
| 解决测试服问题 | 所有回调走中心系统，通过app_code区分环境 |
| 多项目复用 | 新项目只需注册app_code即可接入 |
| 多公众号支持 | 不同项目可绑定不同公众号 |
| 业务解耦 | 用户管理在业务系统，中心系统只处理微信交互 |
