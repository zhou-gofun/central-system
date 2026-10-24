#!/bin/bash
# ============================================
# 中心系统 容器启动脚本
# 1) 等待数据库就绪并同步表结构（幂等）
# 2) 启动 Gunicorn + UvicornWorker
# ============================================

set -e

# 传入参数时直接执行（如一次性任务：docker compose run --rm seed）
if [ "$#" -gt 0 ]; then
    exec "$@"
fi

echo "----------------------------------------"
echo "等待数据库并同步表结构..."
python3 /app/deploy/init_db.py

WORKERS=${WORKERS:-2}

echo "----------------------------------------"
echo "启动 Gunicorn (workers=${WORKERS}, port=8000)"
echo "----------------------------------------"

exec gunicorn app.main:app \
    --workers "${WORKERS}" \
    -k uvicorn.workers.UvicornWorker \
    -b 0.0.0.0:8000 \
    --timeout 120 \
    --keep-alive 5 \
    --max-requests 5000 \
    --max-requests-jitter 500 \
    --access-logfile - \
    --error-logfile - \
    --log-level info
