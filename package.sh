#!/bin/bash

PROJECT_NAME="image-analyzer"
OUTPUT_FILE="${PROJECT_NAME}-$(date +%Y%m%d-%H%M%S).zip"

zip -r "$OUTPUT_FILE" . \
  -x "*.git*" \
  -x "*node_modules*" \
  -x "*.pytest_cache*" \
  -x "*cdk.out*" \
  -x "*cdk.out.new*" \
  -x "*.DS_Store" \
  -x "*log.log" \
  -x "*.pyc" \
  -x "*__pycache__*" \
  -x "*layer/python*" \
  -x "*.kiro*"

echo "打包完成: $OUTPUT_FILE"
