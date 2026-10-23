# 中心系统 - 快速启动指南

## 项目入口

项目启动入口文件为: `/home/devbox/project/entrypoint.sh`

## 使用方法

```bash
# 在项目根目录下运行
cd /home/devbox/project

# 开发环境（默认）- 使用 Uvicorn，支持热重载
./entrypoint.sh

# 测试环境 - 使用 Gunicorn，2个 workers
./entrypoint.sh test

# 生产环境 - 使用 Gunicorn，根据 CPU 自动配置 workers
./entrypoint.sh prod

# 也可以指定模式
./entrypoint.sh test dev  # 测试环境 + 开发模式
```

## 项目结构

```
/home/devbox/project/
├── entrypoint.sh              # 项目统一入口（会调用下面的脚本）
└── central-system/            # 中心系统项目
    ├── entrypoint.sh          # 中心系统启动脚本
    ├── app/                   # 应用代码
    ├── migrations/            # 数据库迁移
    ├── requirements.txt       # 依赖包
    ├── .env                   # 开发环境配置
    ├── .env.test              # 测试环境配置
    ├── .env.prod              # 生产环境配置
    ├── README.md              # 项目说明
    └── DEPLOYMENT.md          # 详细部署文档
```

## 启动流程

1. 激活虚拟环境
2. 检测项目目录
3. 设置 PYTHONPATH
4. 选择环境配置文件（.env / .env.test / .env.prod）
5. 检查依赖包
6. 自动执行数据库迁移
7. 启动服务（Uvicorn 或 Gunicorn）

## 环境说明

| 环境 | 配置文件 | 默认模式 | Workers | 端口 |
|------|---------|---------|---------|------|
| dev  | .env    | 开发模式 | 1       | 8000 |
| test | .env.test | 生产模式 | 2     | 8000 |
| prod | .env.prod | 生产模式 | 自动计算 | 8000 |

## 日志位置

生产模式下，日志保存在:
- `/data/logs/access.log` - 访问日志
- `/data/logs/error.log` - 错误日志

## 访问地址

启动后可通过以下地址访问:
- API 文档: http://localhost:8000/docs
- 健康检查: http://localhost:8000/health
- 根路径: http://localhost:8000/

## 更多信息

详细部署文档请查看: `/home/devbox/project/central-system/DEPLOYMENT.md`
