# 中心系统部署指南

## 启动脚本使用说明

### entrypoint.sh 脚本

`entrypoint.sh` 是应用的统一启动入口，支持多环境和多种启动模式。

### 使用方法

#### 基础用法

```bash
# 开发环境 + 开发模式（热重载）
./entrypoint.sh

# 测试环境 + 生产模式（Gunicorn）
./entrypoint.sh test

# 生产环境 + 生产模式（Gunicorn）
./entrypoint.sh prod

# 测试环境 + 开发模式（热重载）
./entrypoint.sh test dev
```

#### 通过环境变量指定

```bash
APP_ENV=prod ./entrypoint.sh
```

### 环境说明

#### 1. 开发环境 (dev)
- 配置文件: `.env`
- 默认模式: 开发模式 (uvicorn with reload)
- DEBUG: true
- 端口: 8000

#### 2. 测试环境 (test)
- 配置文件: `.env.test`
- 默认模式: 生产模式 (gunicorn)
- DEBUG: false
- Workers: 2
- 端口: 8000

#### 3. 生产环境 (prod)
- 配置文件: `.env.prod`
- 默认模式: 生产模式 (gunicorn)
- DEBUG: false
- Workers: 根据CPU核心数自动计算
- 端口: 8000

### 启动模式

#### 开发模式 (dev)
- 使用 Uvicorn
- 支持热重载
- 单进程
- 适合开发调试

```bash
./entrypoint.sh dev
```

#### 生产模式 (prod)
- 使用 Gunicorn + Uvicorn Worker
- 多进程
- 自动计算 Workers 数量
- 支持平滑重启
- 日志记录

```bash
./entrypoint.sh prod
```

### 配置文件

在部署前，请根据环境创建相应的配置文件：

#### .env (开发环境)
```env
# 数据库配置
DATABASE_URL=postgresql+asyncpg://postgres:password@localhost:5432/central_system

# 应用配置
APP_NAME=Central System
APP_VERSION=1.0.0
DEBUG=true
```

#### .env.test (测试环境)
```env
# 数据库配置
DATABASE_URL=postgresql+asyncpg://postgres:password@test-db:5432/central_system_test

# 应用配置
APP_NAME=Central System
APP_VERSION=1.0.0
DEBUG=false
```

#### .env.prod (生产环境)
```env
# 数据库配置
DATABASE_URL=postgresql+asyncpg://postgres:password@prod-db:5432/central_system

# 应用配置
APP_NAME=Central System
APP_VERSION=1.0.0
DEBUG=false
```

### 自动化功能

启动脚本会自动执行以下操作：

1. **虚拟环境激活**: 自动检测并激活 venv 虚拟环境
2. **PYTHONPATH 设置**: 确保模块正确导入
3. **依赖检查**: 验证所有必需的 Python 包是否安装
4. **数据库迁移**: 自动执行 `migrate.py` 进行数据库初始化/迁移
5. **环境检测**: 根据环境选择正确的配置文件

### 日志

生产模式下，日志文件默认保存在 `/data/logs/` 目录：

- `/data/logs/access.log` - 访问日志
- `/data/logs/error.log` - 错误日志

可以通过环境变量 `LOG_DIR` 自定义日志目录：

```bash
LOG_DIR=/var/log/central-system ./entrypoint.sh prod
```

**注意**: 请确保 `/data` 目录已挂载并具有写入权限

### Workers 配置

生产模式下，Workers 数量根据以下规则自动计算：

- 测试环境：固定 2 个 workers
- 生产环境 (CPU < 8核)：`CPU核心数 * 2 + 1`
- 生产环境 (CPU 8-15核)：6 个 workers
- 生产环境 (CPU >= 16核)：8 个 workers（避免内存不足）

### Docker 部署

在 Dockerfile 中使用：

```dockerfile
FROM python:3.12-slim

WORKDIR /app

# 复制应用文件
COPY . /app

# 安装依赖
RUN pip install --no-cache-dir -r requirements.txt

# 设置启动脚本为可执行
RUN chmod +x /app/entrypoint.sh

# 设置环境变量
ENV APP_ENV=prod

# 暴露端口
EXPOSE 8000

# 启动应用
CMD ["./entrypoint.sh"]
```

### Kubernetes 部署

在 Deployment 中使用：

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: central-system
spec:
  replicas: 3
  template:
    spec:
      containers:
      - name: app
        image: central-system:latest
        command: ["./entrypoint.sh"]
        env:
        - name: APP_ENV
          value: "prod"
        ports:
        - containerPort: 8000
```

### 故障排查

#### 1. 虚拟环境未找到
```bash
# 创建虚拟环境
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

#### 2. 依赖缺失
```bash
# 安装依赖
pip install -r requirements.txt
```

#### 3. 数据库连接失败
检查 `.env` 文件中的 `DATABASE_URL` 配置是否正确

#### 4. 端口被占用
修改启动脚本中的端口号，或停止占用端口的进程

### 健康检查

应用启动后，可以通过以下端点进行健康检查：

- 基础检查: `http://localhost:8000/`
- 健康检查: `http://localhost:8000/health`
- API 文档: `http://localhost:8000/docs`

### 停止应用

按 `Ctrl+C` 停止运行中的应用

### 技术栈

- **Web 框架**: FastAPI
- **ASGI 服务器**: Uvicorn (开发) / Gunicorn (生产)
- **数据库**: PostgreSQL + asyncpg
- **配置管理**: pydantic-settings + python-dotenv
