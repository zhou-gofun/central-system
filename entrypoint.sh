#!/bin/bash

# ============================================
# 项目统一启动入口
# 启动中心系统 (Central System)
# ============================================

cd "$(dirname "$0")/central-system" || exit 1
exec ./entrypoint.sh "$@"
