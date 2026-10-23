# 中心系统 (Central System)

统一的中心化服务平台，为多个业务系统提供共享功能和服务。

## 系统简介

中心系统是一个基于FastAPI的微服务平台，采用模块化架构设计，当前已集成微信扫码授权功能，后续可扩展更多业务功能模块。

### 核心特性

- 模块化架构设计，易于扩展新功能
- 统一的应用鉴权机制
- 支持多业务系统接入
- 基于 FastAPI + PostgreSQL + SQLAlchemy 异步架构

## 项目结构

```
central-system/
├── app/
│   ├── api/                  # API接口层（按功能模块划分）
│   │   └── wechat/          # 微信功能模块API
│   ├── model/                # 数据模型层（按功能模块划分）
│   │   └── wechat/          # 微信功能模块数据模型
│   ├── service/              # 业务逻辑层（按功能模块划分）
│   │   └── wechat/          # 微信功能模块业务逻辑
│   ├── common/               # 公共模块
│   └── main.py              # FastAPI应用入口
├── migrations/               # 数据库迁移脚本
├── requirements.txt
└── README.md
```

## 功能模块

### 1. 微信扫码授权模块

提供微信公众号扫码登录/注册/绑定功能。

**API接口:**
- POST /api/v1/scan/create - 创建扫码会话
- GET /api/v1/scan/status - 查询扫码状态
- POST /api/v1/scan/consume - 消费扫码会话
- GET/POST /api/v1/wechat/callback/{mp_appid} - 微信回调接口

## 快速开始

### 方式一：使用启动脚本（推荐）

项目已配置完整的启动脚本，支持多环境部署：

```bash
# 开发环境（默认，支持热重载）
./entrypoint.sh

# 测试环境（使用 Gunicorn）
./entrypoint.sh test

# 生产环境（使用 Gunicorn）
./entrypoint.sh prod
```

启动脚本会自动完成：
- 激活虚拟环境
- 检查依赖
- 执行数据库迁移
- 启动服务

访问地址：
- API 文档: http://localhost:8000/docs
- 健康检查: http://localhost:8000/health

详细部署文档请查看 [DEPLOYMENT.md](DEPLOYMENT.md)

### 方式二：手动启动

```bash
# 安装依赖
pip install -r requirements.txt

# 配置环境变量
cp .env.example .env

# 初始化数据库
python migrate.py

# 启动服务（开发模式）
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# 或启动服务（生产模式）
gunicorn app.main:app -w 4 -k uvicorn.workers.UvicornWorker -b 0.0.0.0:8000
```

访问 http://localhost:8000/docs 查看API文档

## 扩展新功能模块

在 app/api/、app/model/、app/service/ 下创建新模块目录即可。

## 技术栈

- FastAPI 0.109.0
- SQLAlchemy 2.0.25
- PostgreSQL (asyncpg)
- Pydantic 2.5.3
