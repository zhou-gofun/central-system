#!/bin/bash
# ============================================
# 支付模块回归测试
#
# 跑法（在 deploy 目录下）：
#   docker compose build app && docker compose up -d
#   ./tests/run_tests.sh
#
# 测试不需要真实商户配置，用自签密钥模拟微信支付。
# test_payment_api.py / test_payment_forward.py 会往数据库写临时数据，
# 跑完自动清理。
# ============================================

set -e
cd "$(dirname "$0")/.."

APP=central-system-app
FAILED=0

for t in test_payment_crypto test_payment_api test_payment_forward; do
    echo ""
    echo "=========================================="
    echo "运行 $t"
    echo "=========================================="
    docker cp "tests/$t.py" "$APP:/tmp/$t.py"
    if docker exec "$APP" python3 "/tmp/$t.py" 2>&1 | grep -E "^\s*\[(PASS|FAIL)\]|^通过|^失败|全部通过"; then
        :
    fi
    # 用退出码判定
    if ! docker exec "$APP" python3 "/tmp/$t.py" >/dev/null 2>&1; then
        echo "❌ $t 失败"
        FAILED=1
    else
        echo "✅ $t 通过"
    fi
done

echo ""
if [ "$FAILED" -eq 0 ]; then
    echo "全部测试通过"
else
    echo "有测试失败"
    exit 1
fi
