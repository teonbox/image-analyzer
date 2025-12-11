#!/bin/bash
# Request Handler Layer 1 单元测试运行脚本

set -e

echo "=========================================="
echo "Request Handler Layer 1 单元测试"
echo "=========================================="
echo ""

# 检查依赖
if ! python -c "import pytest" 2>/dev/null; then
    echo "❌ pytest 未安装，正在安装依赖..."
    pip install -q -r test/requirements.txt
    echo "✅ 依赖安装完成"
    echo ""
fi

# 运行测试
echo "🧪 运行测试..."
echo ""

python -m pytest test/unit/request-handler/test_request_handler_unit.py -v

echo ""
echo "=========================================="
echo "✅ 测试完成！"
echo "=========================================="
