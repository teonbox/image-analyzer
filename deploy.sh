#!/bin/bash
set -e

echo "=== Deploying Image Analyzer Stack ==="

# 更新 Lambda Layer
echo "Updating Lambda Layer..."
rm -rf layer/python
mkdir -p layer/python
cp -r lambda/shared layer/python/
cp -r lambda/policies layer/python/

# 安装 Python 依赖到 Layer
echo "Installing Python dependencies..."
pip install -r lambda/requirements.txt -t layer/python --quiet

# 进入 infrastructure 目录
cd infrastructure

# 安装 CDK 依赖（如果需要）
if [ ! -d "node_modules" ]; then
    echo "Installing CDK dependencies..."
    npm install
fi

# Bootstrap CDK（如果是第一次部署）
echo "Bootstrapping CDK..."
npx cdk bootstrap || true

# 部署 stack
echo "Deploying stack..."
npx cdk deploy InfrastructureStack --require-approval never

echo "=== Deployment Complete ==="
