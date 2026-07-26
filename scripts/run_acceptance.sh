#!/bin/bash
# 每次修改后一键运行全套验收测试
# 用法: bash scripts/run_acceptance.sh
#
# 包含：
# 1. JS 语法检查
# 2. 回归测试（API 层）
# 3. 扫描+归档验收测试（完整业务流程）
#
# 要求：服务已在 127.0.0.1:8111 运行
# 如果没运行，脚本会自动重启

set -e

cd "D:/AgentProjects/IpoPBC/0"
PYTHON="D:/programs/Python/python.exe"
MGPY="C:/Users/caca/.workbuddy/binaries/python/versions/3.13.12/python.exe"

echo "=========================================="
echo "  PBC 工作站 全套验收测试"
echo "=========================================="
echo ""

# 1. JS 语法检查
echo "[1/3] JS 语法检查..."
node .workbuddy/tmp/check_js.js 2>&1 || { echo "JS 检查失败"; exit 1; }
echo ""

# 2. 检查服务是否在运行
echo "[2/3] 检查服务..."
if ! curl -s http://127.0.0.1:8111/health > /dev/null 2>&1; then
    echo "服务未运行，重启中..."
    # 杀旧进程
    for pid in $(netstat -ano 2>/dev/null | grep ":8111.*LISTENING" | awk '{print $5}' | sort -u); do
        taskkill //F //PID $pid 2>/dev/null || true
    done
    sleep 3
    PBC_SKIP_AI_INIT=1 "$MGPY" -m uvicorn app.main:app --host 127.0.0.1 --port 8111 > /dev/null 2>&1 &
    sleep 12
fi
curl -s http://127.0.0.1:8111/health || { echo "服务启动失败"; exit 1; }
echo "服务正常"
echo ""

# 3. 回归测试
echo "[3/3] 运行测试..."
echo ""
echo "--- 回归测试（API 层）---"
"$MGPY" scripts/regression_v7.py 2>&1 | tail -5
echo ""

echo "--- 扫描+归档验收测试（完整业务流程）---"
"$PYTHON" -X utf8 scripts/test_accept_scan.py 2>&1 | grep -E "===|PASS|FAIL|总计"
echo ""

echo "=========================================="
echo "  测试完成"
echo "=========================================="
