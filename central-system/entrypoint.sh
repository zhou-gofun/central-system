#!/bin/bash

# ============================================
# 中心系统 (Central System) 启动脚本
# 用法: ./entrypoint.sh [环境] [模式]
#   环境: dev / test / prod (默认 dev)
#   模式: dev / prod (默认根据环境自动选择)
# 示例:
#   ./entrypoint.sh              # 开发环境 + 开发模式
#   ./entrypoint.sh test         # 测试环境 + 生产模式
#   ./entrypoint.sh prod         # 生产环境 + 生产模式
#   ./entrypoint.sh test dev     # 测试环境 + 开发模式(热重载)
#   APP_ENV=prod ./entrypoint.sh # 通过环境变量指定
# ============================================

set -e  # 遇到错误立即退出

echo "========================================"
echo "  中心系统 (Central System) 启动"
echo "========================================"

# 1. 激活虚拟环境
if [ -f "venv/bin/activate" ]; then
    . venv/bin/activate
    echo "✓ 虚拟环境已激活"
elif [ -f "bin/activate" ]; then
    . bin/activate
    echo "✓ 虚拟环境已激活"
else
    echo "警告：未找到虚拟环境，使用系统 Python"
fi

# 2. 检测项目目录结构
if [ -f "app/main.py" ]; then
    echo "✓ 在项目根目录（包含 app/main.py）"
    PROJECT_ROOT=$(pwd)
elif [ -f "main.py" ] && [ -d "../app" ]; then
    echo "检测到在 app 目录，切换到根目录..."
    cd ..
    PROJECT_ROOT=$(pwd)
elif [ -f "main.py" ]; then
    echo "✓ 在 app 目录（直接包含 main.py）"
    PROJECT_ROOT=$(pwd)
else
    echo "错误：找不到应用文件"
    echo "当前目录: $(pwd)"
    echo "文件列表:"
    ls -la
    exit 1
fi

echo "项目根目录: $PROJECT_ROOT"
cd "$PROJECT_ROOT"

# 3. 设置 PYTHONPATH
export PYTHONPATH="$PROJECT_ROOT:$PROJECT_ROOT/app:$PYTHONPATH"
echo "✓ PYTHONPATH 已设置: $PYTHONPATH"

# 4. Python 版本检查
if ! command -v python3 &> /dev/null; then
    echo "错误：未找到 python3"
    exit 1
fi
echo "✓ Python 版本: $(python3 --version)"

# ============================================
# 5. 环境配置（支持 dev/test/prod）
# ============================================
# 优先使用环境变量 APP_ENV，默认 dev
APP_ENV=${APP_ENV:-"dev"}

# 也可以通过第一个参数指定环境
if [ "$1" = "test" ] || [ "$1" = "prod" ] || [ "$1" = "dev" ]; then
    APP_ENV=$1
    shift  # 移除第一个参数，让后续参数生效
fi

export APP_ENV
echo "✓ 运行环境: $APP_ENV"

# 根据环境选择配置文件和默认启动模式
case "$APP_ENV" in
    "prod"|"production")
        ENV_FILE="$PROJECT_ROOT/.env.prod"
        DEFAULT_MODE="prod"
        ;;
    "test"|"testing")
        ENV_FILE="$PROJECT_ROOT/.env.test"
        DEFAULT_MODE="prod"  # 测试环境默认也用 gunicorn
        ;;
    *)
        ENV_FILE="$PROJECT_ROOT/.env"
        DEFAULT_MODE="dev"
        ;;
esac

# 检查环境文件是否存在
if [ -f "$ENV_FILE" ]; then
    echo "✓ 使用配置文件: $ENV_FILE"
    export DOTENV_FILE="$ENV_FILE"
else
    echo "警告：配置文件不存在: $ENV_FILE"
    if [ -f "$PROJECT_ROOT/.env" ]; then
        echo "将使用默认 .env 文件"
        export DOTENV_FILE="$PROJECT_ROOT/.env"
    else
        echo "错误：未找到任何配置文件"
        exit 1
    fi
fi

# ============================================
# 6. 依赖检查
# ============================================
echo "----------------------------------------"
echo "检查依赖包..."

# 检查关键依赖
MISSING_PACKAGES=()

python3 -c "import fastapi" 2>/dev/null || MISSING_PACKAGES+=("fastapi")
python3 -c "import uvicorn" 2>/dev/null || MISSING_PACKAGES+=("uvicorn")
python3 -c "import sqlalchemy" 2>/dev/null || MISSING_PACKAGES+=("sqlalchemy")
python3 -c "import asyncpg" 2>/dev/null || MISSING_PACKAGES+=("asyncpg")
python3 -c "import pydantic" 2>/dev/null || MISSING_PACKAGES+=("pydantic")

# 生产环境检查 gunicorn
if [ "$DEFAULT_MODE" = "prod" ]; then
    python3 -c "import gunicorn" 2>/dev/null || MISSING_PACKAGES+=("gunicorn")
fi

if [ ${#MISSING_PACKAGES[@]} -ne 0 ]; then
    echo ""
    echo "缺少以下依赖包:"
    for pkg in "${MISSING_PACKAGES[@]}"; do
        echo "  - $pkg"
    done
    echo ""
    echo "请先安装依赖:"
    echo "  pip install -r requirements.txt"
    exit 1
fi

echo "✓ 所有依赖包已安装"

# ============================================
# 7. 数据库迁移（每次发版自动执行）
# ============================================
echo "----------------------------------------"
echo "执行数据库迁移..."

if [ -f "$PROJECT_ROOT/migrate.py" ]; then
    if python3 "$PROJECT_ROOT/migrate.py"; then
        echo "✓ 数据库迁移完成"
    else
        echo "警告：数据库迁移失败，但继续启动应用"
    fi
else
    echo "警告：未找到 migrate.py 文件，跳过迁移"
fi

# ============================================
# 8. 选择启动模式
# ============================================
MODE=${1:-$DEFAULT_MODE}

if [ "$MODE" = "dev" ] || [ "$MODE" = "development" ]; then
    echo "----------------------------------------"
    echo "启动开发模式 (Uvicorn)"
    echo "环境: $APP_ENV"
    echo "配置: $DOTENV_FILE"
    echo "端口: 8080"
    echo "文档: http://localhost:8080/docs"
    echo "健康检查: http://localhost:8080/health"
    echo "----------------------------------------"
    echo ""
    echo "按 Ctrl+C 停止服务"
    echo ""

    # 使用 uvicorn 启动开发模式（热重载）
    exec python3 -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8080

else
    echo "----------------------------------------"
    echo "启动生产模式 (Gunicorn)"
    echo "环境: $APP_ENV"
    echo "配置: $DOTENV_FILE"
    echo "----------------------------------------"

    # 检查是否安装了 gunicorn
    if ! python3 -c "import gunicorn" 2>/dev/null; then
        echo "错误：生产模式需要 gunicorn"
        echo "请安装: pip install gunicorn"
        exit 1
    fi

    # 计算 workers（根据 CPU 核心数）
    CPU_CORES=$(nproc 2>/dev/null || echo 1)
    echo "CPU 核心数: $CPU_CORES"

    # 根据 CPU 核心数和环境调整 workers 数量
    if [ "$APP_ENV" = "test" ] || [ "$APP_ENV" = "testing" ]; then
        # 测试环境使用1个worker节省资源
        WORKERS=1
        echo "测试环境，限制 workers 为 $WORKERS"
    elif [ $CPU_CORES -eq 1 ]; then
        # 1核服务器（1c2g），使用1个worker节省内存
        WORKERS=1
        echo "单核服务器，workers 设置为 $WORKERS（节省内存）"
    elif [ $CPU_CORES -eq 2 ]; then
        # 2核服务器，使用2个workers
        WORKERS=2
        echo "双核服务器，workers 设置为 $WORKERS"
    elif [ $CPU_CORES -ge 16 ]; then
        # 16核以上，限制为 8 个 workers
        WORKERS=8
        echo "CPU核心数较多，限制 workers 为 $WORKERS"
    elif [ $CPU_CORES -ge 8 ]; then
        WORKERS=6
    else
        WORKERS=$((CPU_CORES * 2 + 1))
    fi

    echo "Workers 数量: $WORKERS"
    echo "端口: 8080"
    echo "文档: http://localhost:8080/docs"
    echo "健康检查: http://localhost:8080/health"
    echo "----------------------------------------"
    echo ""
    echo "按 Ctrl+C 停止服务"
    echo ""

    # 创建日志目录
    # test环境使用本地目录，prod环境使用挂载的/data/logs
    if [ "$APP_ENV" = "test" ] || [ "$APP_ENV" = "testing" ]; then
        LOG_DIR="${LOG_DIR:-$PROJECT_ROOT/logs}"
        echo "测试环境，使用本地日志目录"
    else
        LOG_DIR="${LOG_DIR:-/data/logs}"
    fi
    mkdir -p "$LOG_DIR"
    echo "日志目录: $LOG_DIR"

    # 启动 Gunicorn
    # 针对1c2g服务器优化的参数配置
    exec gunicorn app.main:app \
        -w $WORKERS \
        -k uvicorn.workers.UvicornWorker \
        -b 0.0.0.0:8080 \
        --timeout 120 \
        --keep-alive 5 \
        --max-requests 5000 \
        --max-requests-jitter 500 \
        --access-logfile "$LOG_DIR/access.log" \
        --error-logfile "$LOG_DIR/error.log" \
        --log-level info \
        --preload
fi
