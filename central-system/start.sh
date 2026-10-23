#!/bin/bash
# 中心系统启动脚本

echo "========================================="
echo "  中心系统 (Central System) 启动"
echo "========================================="
echo ""

# 激活虚拟环境
if [ -d "venv" ]; then
    echo "✓ 激活虚拟环境..."
    source venv/bin/activate
fi
echo ""

# 检查Python
if ! command -v python3 &> /dev/null; then
    echo "❌ 错误: 未找到 python3"
    exit 1
fi

echo "✓ Python 版本: $(python3 --version)"

# 检查必要的包
echo ""
echo "检查依赖包..."

MISSING_PACKAGES=()

python3 -c "import fastapi" 2>/dev/null || MISSING_PACKAGES+=("python3-fastapi")
python3 -c "import uvicorn" 2>/dev/null || MISSING_PACKAGES+=("python3-uvicorn")
python3 -c "import sqlalchemy" 2>/dev/null || MISSING_PACKAGES+=("python3-sqlalchemy")
python3 -c "import pydantic" 2>/dev/null || MISSING_PACKAGES+=("python3-pydantic")
python3 -c "import asyncpg" 2>/dev/null || MISSING_PACKAGES+=("python3-asyncpg" "需要pip安装")

if [ ${#MISSING_PACKAGES[@]} -ne 0 ]; then
    echo ""
    echo "❌ 缺少以下依赖包:"
    for pkg in "${MISSING_PACKAGES[@]}"; do
        echo "  - $pkg"
    done
    echo ""
    echo "请先安装依赖:"
    echo "  sudo apt install python3-fastapi python3-uvicorn python3-sqlalchemy python3-pydantic"
    echo ""
    echo "或者使用 pip:"
    echo "  pip install -r requirements.txt"
    exit 1
fi

echo "✓ 所有依赖包已安装"
echo ""

# 检查数据库连接
echo "检查数据库连接..."
python3 -c "
import psycopg2
try:
    conn = psycopg2.connect(
        host='central-system-db-postgresql.ns-2z3k0kqh.svc',
        port=5432,
        user='postgres',
        password='d5rtwm47',
        database='central_system',
        connect_timeout=3
    )
    conn.close()
    print('✓ 数据库连接成功')
except Exception as e:
    print(f'❌ 数据库连接失败: {e}')
    exit(1)
"

if [ $? -ne 0 ]; then
    exit 1
fi

echo ""
echo "========================================="
echo "  启动 FastAPI 服务"
echo "========================================="
echo ""
echo "  API 文档: http://localhost:8000/docs"
echo "  健康检查: http://localhost:8000/health"
echo ""
echo "按 Ctrl+C 停止服务"
echo ""

# 启动服务
python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8080 --reload
