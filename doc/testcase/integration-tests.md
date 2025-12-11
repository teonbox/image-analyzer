# Layer 3: 集成测试文档

## 概述

本文档描述系统的集成测试用例，测试真实 AWS 环境中的端到端流程。集成测试验证各个组件之间的交互，确保系统在真实环境中正常工作。

**测试环境**: 真实 AWS 资源（DynamoDB、SQS、S3、Lambda、API Gateway）

**测试工具**: 
- pytest + boto3（Python 测试）
- curl + jq（Shell 脚本）
- aws-cli（AWS 命令行）

**测试数据位置**: `test/fixtures/integration/`

---

## 测试分类说明

本文档包含两类集成测试：

### 1. 组件集成测试（INT-001 ~ INT-016）

**特点**:
- 测试系统各个组件的集成（API、Lambda、DynamoDB、SQS）
- 片段化测试：每个测试只覆盖部分流程
- 需要手动操作和验证（如 INT-013 需要手动轮询状态）
- 适合开发阶段的功能验证

**测试范围**:
- INT-001~004: 只测试提交 API
- INT-005~006: 只测试 Frame 处理
- INT-007~012: 只测试查询 API
- INT-013~014: 描述完整流程但需要手动操作
- INT-015~016: 特定场景测试

### 2. 端到端自动化测试（INT-E2E-001 ~ INT-E2E-004）

**特点**:
- 完整的端到端流程：提交 -> 自动等待 -> 验证结果
- 完全自动化：无需手动轮询或验证
- 验证业务逻辑：检测结果的准确性
- 使用配置文件管理测试数据和预期结果
- 可集成到 CI/CD 进行回归测试

**测试范围**:
- 从 API 提交开始
- 自动等待处理完成（指数退避轮询）
- 验证检测结果与预期一致
- 验证业务逻辑正确性

**推荐使用场景**:
- 开发阶段: 使用组件集成测试快速验证功能
- 发布前: 运行端到端自动化测试确保整体质量
- CI/CD: 集成端到端自动化测试进行回归测试

---

## 1. API 提交流程测试

### INT-001: 提交请求（Image List）

**测试目标**: 验证通过 URL 列表提交请求的完整流程

**前置条件**：
- API Gateway 已部署
- 测试图片已上传到 S3（公开访问或预签名 URL）
- DynamoDB 表已创建
- SQS 队列已创建

**执行步骤**：
```bash
# 1. 提交请求
response=$(curl -X POST https://api.example.com/requests \
  -H "x-api-key: YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "test-video-urllist",
    "input_config": {
      "type": "url_list",
      "urls": [
        "https://test-bucket.s3.amazonaws.com/video/frame-001.jpg",
        "https://test-bucket.s3.amazonaws.com/video/frame-002.jpg",
        "https://test-bucket.s3.amazonaws.com/video/frame-003.jpg"
      ]
    },
    "callback_url": "https://webhook.site/your-unique-id"
  }')

# 2. 提取 request_id
request_id=$(echo $response | jq -r '.data.request_id')
```

**验证点**：
1. API 响应状态码 200
2. 响应包含 `success: true`
3. 返回有效的 `request_id`（UUID 格式）
4. 返回 `status: 'pending'`
5. 返回 `total_frames: 3`

**DynamoDB 验证**：
```bash
# 查询 Request 记录
aws dynamodb get-item \
  --table-name Request \
  --key "{\"request_id\": {\"S\": \"$request_id\"}}"
```

验证：
- Request 记录存在
- `name: 'test-video-urllist'`
- `status: 'pending'`
- `total_frames: 3`
- `frame_stats.total: 3`
- `frame_stats.pending: 3`

**SQS 验证**：
```bash
# 查询队列消息数
aws sqs get-queue-attributes \
  --queue-url https://sqs.us-east-1.amazonaws.com/123456789/frame-queue \
  --attribute-names ApproximateNumberOfMessages
```

验证：
- 队列中有 3 条消息

---

### INT-002: 提交请求（S3）

**测试目标**: 验证通过 S3 存储桶提交请求的完整流程

**前置条件**：
- 测试图片已上传到 S3（10 张图片）
- 图片命名格式：`video1/frame-001.jpg` 到 `video1/frame-010.jpg`

**执行步骤**：
```bash
# 1. 提交请求
response=$(curl -X POST https://api.example.com/requests \
  -H "x-api-key: YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "test-video-s3",
    "input_config": {
      "type": "s3",
      "storage": {
        "bucket": "test-bucket",
        "prefix": "video1/",
        "region": "us-east-1"
      }
    },
    "callback_url": "https://webhook.site/your-unique-id"
  }')

# 2. 提取 request_id
request_id=$(echo $response | jq -r '.data.request_id')
```

**验证点**：
1. API 响应状态码 200
2. 返回 `total_frames: 10`
3. DynamoDB 中 Request 记录正确
4. SQS 中有 10 条消息

---

### INT-003: 提交请求（多个前缀错误）

**测试目标**: 验证检测到多个前缀时返回错误

**前置条件**：
- S3 中有不同前缀的图片

**执行步骤**：
```bash
curl -X POST https://api.example.com/requests \
  -H "x-api-key: YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "test-multiple-prefix",
    "input_config": {
      "type": "url_list",
      "urls": [
        "https://test-bucket.s3.amazonaws.com/video1/frame-001.jpg",
        "https://test-bucket.s3.amazonaws.com/video2/frame-001.jpg"
      ]
    },
    "callback_url": "https://webhook.site/your-unique-id"
  }'
```

**验证点**：
1. 响应状态码 400
2. 返回 `success: false`
3. 错误码 `MULTIPLE_PREFIXES_DETECTED`
4. 错误详情包含检测到的前缀列表

---

### INT-004: 提交请求（API Key 认证失败）

**测试目标**: 验证 API Key 认证

**执行步骤**：
```bash
curl -X POST https://api.example.com/requests \
  -H "x-api-key: INVALID_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "test-auth",
    "input_config": {
      "type": "url_list",
      "urls": ["https://test-bucket.s3.amazonaws.com/video/frame-001.jpg"]
    },
    "callback_url": "https://webhook.site/your-unique-id"
  }'
```

**验证点**：
1. 响应状态码 403
2. 返回 `success: false`
3. 错误码 `UNAUTHORIZED`

---

## 2. Frame 处理流程测试

### INT-005: SQS 触发 Lambda

**测试目标**: 验证 SQS 消息触发 Frame Processor Lambda

**前置条件**：
- 测试图片已上传到 S3
- DynamoDB 中有 Request 记录

**执行步骤**：
```bash
# 1. 创建 Request 记录
aws dynamodb put-item \
  --table-name Request \
  --item '{
    "request_id": {"S": "test-123"},
    "name": {"S": "test-sqs-trigger"},
    "status": {"S": "running"},
    "total_frames": {"N": "3"},
    "frame_stats": {"M": {
      "total": {"N": "3"},
      "completed": {"N": "0"},
      "failed": {"N": "0"},
      "pending": {"N": "3"}
    }},
    "version": {"N": "1"}
  }'

# 2. 发送 SQS 消息
aws sqs send-message \
  --queue-url https://sqs.us-east-1.amazonaws.com/123456789/frame-queue \
  --message-body '{
    "request_id": "test-123",
    "frame_index": 1,
    "frame_key": "video/frame-002.jpg",
    "context_frame_range": [0, 2]
  }'

# 3. 等待处理（10 秒）
sleep 10
```

**验证点**：

**Lambda 日志验证**：
```bash
aws logs tail /aws/lambda/FrameProcessor --since 1m
```

验证日志包含：
- `Processing frame 1 for request test-123`
- `Executing policy: eating_detection`
- `Frame 1 completed`

**DynamoDB 验证**：
```bash
# 查询 Frame 记录
aws dynamodb get-item \
  --table-name Frame \
  --key '{
    "request_id": {"S": "test-123"},
    "frame_index": {"N": "1"}
  }'
```

验证：
- Frame 记录存在
- `status: 'completed'`
- `policy_results` 包含策略结果
- `policy_status` 包含策略状态

**Request 更新验证**：
```bash
# 查询 Request 记录
aws dynamodb get-item \
  --table-name Request \
  --key '{"request_id": {"S": "test-123"}}'
```

验证：
- `frame_stats.completed: 1`
- `frame_stats.pending: 2`
- `last_activity_at` 已更新

---

### INT-006: 并发处理多个 Frame

**测试目标**: 验证多个 Lambda 实例并发处理

**前置条件**：
- DynamoDB 中有 Request 记录
- 测试图片已上传到 S3

**执行步骤**：
```bash
# 发送 10 条 SQS 消息
for i in {0..9}; do
  aws sqs send-message \
    --queue-url https://sqs.us-east-1.amazonaws.com/123456789/frame-queue \
    --message-body "{
      \"request_id\": \"test-concurrent\",
      \"frame_index\": $i,
      \"frame_key\": \"video/frame-$(printf '%03d' $i).jpg\",
      \"context_frame_range\": [0, 9]
    }"
done

# 等待处理（30 秒）
sleep 30
```

**验证点**：
1. 所有 10 个 Frame 记录被创建
2. 所有 Frame 状态为 `completed`
3. Request 的 `frame_stats.completed: 10`
4. CloudWatch Logs 显示多个 Lambda 实例并发执行

---

## 3. 查询流程测试

### INT-007: 通过 UUID 查询状态

**测试目标**: 验证通过 request_id 查询状态

**前置条件**：
- DynamoDB 中有 Request 记录

**执行步骤**：
```bash
curl -X GET "https://api.example.com/requests/{request_id}" \
  -H "x-api-key: YOUR_API_KEY"
```

**验证点**：
1. 响应状态码 200
2. 返回 `success: true`
3. 返回完整的 Request 信息
4. `frame_stats` 正确
5. `progress.percentage` 正确计算

---

### INT-008: 通过 name 查询状态

**测试目标**: 验证通过 name 查询状态

**前置条件**：
- DynamoDB 中有同名 Request（2 个）

**执行步骤**：
```bash
curl -X GET "https://api.example.com/requests/test-video" \
  -H "x-api-key: YOUR_API_KEY"
```

**验证点**：
1. 返回最新的 Request
2. `multiple_requests: true`

---

### INT-009: 查询不存在的请求

**测试目标**: 验证查询不存在的请求返回 404

**执行步骤**：
```bash
curl -X GET "https://api.example.com/requests/non-existent" \
  -H "x-api-key: YOUR_API_KEY"
```

**验证点**：
1. 响应状态码 404
2. 返回 `success: false`
3. 错误码 `REQUEST_NOT_FOUND`

---

### INT-010: 获取结果

**测试目标**: 验证获取完整结果

**前置条件**：
- Request 状态为 `completed`
- S3 中有结果文件

**执行步骤**：
```bash
# 1. 获取结果
response=$(curl -X GET "https://api.example.com/requests/{request_id}/results" \
  -H "x-api-key: YOUR_API_KEY")

# 2. 提取预签名 URL
presigned_url=$(echo $response | jq -r '.data.result_presigned_url')

# 3. 访问预签名 URL
curl "$presigned_url"
```

**验证点**：
1. API 响应状态码 200
2. 返回 `result_s3_bucket` 和 `result_s3_key`
3. 返回 `result_presigned_url`
4. 预签名 URL 可访问
5. 下载的 JSON 内容正确

---

### INT-011: 获取未完成请求的结果

**测试目标**: 验证获取未完成请求的结果返回错误

**前置条件**：
- Request 状态为 `running`

**执行步骤**：
```bash
curl -X GET "https://api.example.com/requests/{request_id}/results" \
  -H "x-api-key: YOUR_API_KEY"
```

**验证点**：
1. 响应状态码 400
2. 返回 `success: false`
3. 错误码 `REQUEST_NOT_COMPLETED`
4. 错误详情包含当前状态和进度

---

### INT-012: 预签名 URL 刷新

**测试目标**: 验证每次调用 API 生成新的预签名 URL

**前置条件**：
- Request 已完成

**执行步骤**：
```bash
# 1. 第一次获取结果
response1=$(curl -X GET "https://api.example.com/requests/{request_id}/results" \
  -H "x-api-key: YOUR_API_KEY")
url1=$(echo $response1 | jq -r '.data.result_presigned_url')

# 2. 等待 2 秒
sleep 2

# 3. 第二次获取结果
response2=$(curl -X GET "https://api.example.com/requests/{request_id}/results" \
  -H "x-api-key: YOUR_API_KEY")
url2=$(echo $response2 | jq -r '.data.result_presigned_url')
```

**验证点**：
1. `url1 != url2`（URL 不同）
2. 两个 URL 都可访问
3. 下载的内容相同

---

## 4. 完成流程测试

### INT-013: 完整流程（所有 Frame 成功）

**测试目标**: 验证从提交到完成的完整流程

**前置条件**：
- 测试图片已上传到 S3（3 张）
- 回调服务器已启动（webhook.site 或本地测试服务器）

**执行步骤**：
```bash
# 1. 提交请求
response=$(curl -X POST https://api.example.com/requests \
  -H "x-api-key: YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "test-complete-flow",
    "input_config": {
      "type": "url_list",
      "urls": [
        "https://test-bucket.s3.amazonaws.com/video/frame-001.jpg",
        "https://test-bucket.s3.amazonaws.com/video/frame-002.jpg",
        "https://test-bucket.s3.amazonaws.com/video/frame-003.jpg"
      ]
    },
    "callback_url": "https://webhook.site/your-unique-id"
  }')

request_id=$(echo $response | jq -r '.data.request_id')

# 2. 轮询状态（每 5 秒查询一次，最多 60 秒）
for i in {1..12}; do
  status=$(curl -s -X GET "https://api.example.com/requests/$request_id" \
    -H "x-api-key: YOUR_API_KEY" | jq -r '.data.status')
  
  echo "[$i] Status: $status"
  
  if [ "$status" == "completed" ]; then
    echo "Request completed!"
    break
  fi
  
  sleep 5
done

# 3. 获取结果
curl -X GET "https://api.example.com/requests/$request_id/results" \
  -H "x-api-key: YOUR_API_KEY"
```

**验证点**：

**Request 状态验证**：
- 初始状态: `pending`
- 处理中状态: `running`
- 最终状态: `completed`

**Frame 验证**：
```bash
aws dynamodb query \
  --table-name Frame \
  --key-condition-expression "request_id = :rid" \
  --expression-attribute-values '{":rid": {"S": "'$request_id'"}}'
```

验证：
- 3 个 Frame 记录存在
- 所有 Frame 状态为 `completed`
- 所有 Frame 包含 `policy_results`

**S3 结果验证**：
```bash
aws s3 ls s3://results-bucket/results/$request_id/
```

验证：
- 存在 `result.json` 文件

**回调验证**：
- 访问 webhook.site 查看回调请求
- 验证回调数据包含：
  - `request_id`
  - `status: 'completed'`
  - `statistics`
  - `result_s3_bucket` 和 `result_s3_key`
  - `result_presigned_url`

---

### INT-014: 完整流程（部分 Frame 失败）

**测试目标**: 验证部分 Frame 失败时的流程

**前置条件**：
- 测试图片：2 张有效，1 张无效（不存在或损坏）

**执行步骤**：
```bash
# 提交请求（包含无效图片）
curl -X POST https://api.example.com/requests \
  -H "x-api-key: YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "test-partial-failure",
    "input_config": {
      "type": "url_list",
      "urls": [
        "https://test-bucket.s3.amazonaws.com/video/frame-001.jpg",
        "https://test-bucket.s3.amazonaws.com/video/invalid.jpg",
        "https://test-bucket.s3.amazonaws.com/video/frame-003.jpg"
      ]
    },
    "callback_url": "https://webhook.site/your-unique-id"
  }'
```

**验证点**：
1. Request 最终状态为 `partial_complete`
2. `frame_stats.completed: 2`
3. `frame_stats.failed: 1`
4. 失败的 Frame 状态为 `failed`
5. 成功的 Frame 包含结果
6. 回调数据包含失败信息

---

## 5. 超时和重试测试

### INT-015: Health Check 超时处理

**测试目标**: 验证 Health Check 检测超时并强制完成

**前置条件**：
- DynamoDB 中有长时间未更新的 Request

**执行步骤**：
```bash
# 1. 创建一个 2 小时前的 Request
aws dynamodb put-item \
  --table-name Request \
  --item '{
    "request_id": {"S": "test-timeout"},
    "name": {"S": "test-timeout"},
    "status": {"S": "running"},
    "total_frames": {"N": "10"},
    "frame_stats": {"M": {
      "total": {"N": "10"},
      "completed": {"N": "5"},
      "failed": {"N": "0"},
      "pending": {"N": "5"}
    }},
    "last_activity_at": {"S": "'$(date -u -d '2 hours ago' +%Y-%m-%dT%H:%M:%SZ)'"},
    "created_at": {"S": "'$(date -u -d '2 hours ago' +%Y-%m-%dT%H:%M:%SZ)'"}
  }'

# 2. 手动触发 Health Check Lambda
aws lambda invoke \
  --function-name HealthCheck \
  --payload '{}' \
  response.json

# 3. 查询 Request 状态
aws dynamodb get-item \
  --table-name Request \
  --key '{"request_id": {"S": "test-timeout"}}'
```

**验证点**：
1. Request 状态变为 `partial_complete`
2. 未完成的 Frame 状态变为 `failed`
3. Completion Handler 被触发
4. 回调被发送

---

### INT-016: 回调重试

**测试目标**: 验证回调失败时的重试机制

**前置条件**：
- 回调 URL 返回 500 错误（使用 webhook.site 的自定义响应）

**执行步骤**：
```bash
# 1. 提交请求（回调 URL 返回 500）
curl -X POST https://api.example.com/requests \
  -H "x-api-key: YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "test-callback-retry",
    "input_config": {
      "type": "url_list",
      "urls": ["https://test-bucket.s3.amazonaws.com/video/frame-001.jpg"]
    },
    "callback_url": "https://webhook.site/your-unique-id"
  }'

# 2. 等待处理完成
sleep 30

# 3. 查询 Request 的回调状态
aws dynamodb get-item \
  --table-name Request \
  --key '{"request_id": {"S": "'$request_id'"}}'
```

**验证点**：
1. `callback_status: 'retrying'`
2. `callback_retry_count > 0`
3. EventBridge 中有重试任务
4. CloudWatch Logs 显示重试日志

---

## 6. 端到端自动化测试（配置化）

### INT-E2E-001: 喝东西检测 - 正向场景

**测试目标**: 验证从提交到完成的完整端到端流程，并验证检测结果准确性

**测试类型**: 端到端自动化测试（真正的 E2E）

**前置条件**：
- 测试数据集已准备（标准测试图片）
- 测试配置文件已创建：`test/fixtures/integration/test-cases/drinking-positive.json`
- 测试图片已上传到 S3

**测试配置文件**：
```json
{
  "name": "drinking-detection-positive",
  "description": "测试喝东西检测 - 正向场景（真的在喝）",
  "enabled_policies": ["drinking_detection"],
  "frames": [
    {
      "url": "https://test-bucket.s3.amazonaws.com/drinking/frame-001.jpg",
      "description": "人物正在将杯子倾斜送入口中",
      "expected_results": {
        "drinking_is_drinking": true,
        "drinking_confidence_min": 0.8,
        "drinking_confidence_max": 1.0,
        "drinking_details_contains": "饮用"
      }
    },
    {
      "url": "https://test-bucket.s3.amazonaws.com/drinking/frame-002.jpg",
      "description": "人物正在吞咽动作",
      "expected_results": {
        "drinking_is_drinking": true,
        "drinking_confidence_min": 0.8,
        "drinking_confidence_max": 1.0
      }
    },
    {
      "url": "https://test-bucket.s3.amazonaws.com/drinking/frame-003.jpg",
      "description": "人物放下杯子",
      "expected_results": {
        "drinking_is_drinking": false,
        "drinking_confidence_min": 0.7,
        "drinking_confidence_max": 1.0
      }
    }
  ]
}
```

**配置格式说明**:
- **精确匹配**: `"field_name": value` (如 `"drinking_is_drinking": true`)
- **范围匹配**: `"field_name_min": value, "field_name_max": value` (如 `"drinking_confidence_min": 0.8`)
- **包含匹配**: `"field_name_contains": "substring"` (如 `"drinking_details_contains": "饮用"`)

**注意**: 测试数据（图片）需要测试人员提前准备好并上传到 S3

**执行步骤**（自动化）：

```python
# test/integration/test_e2e_drinking_detection.py
import pytest
import json
import time
import requests
from typing import Dict, Any

class TestE2EDrinkingDetection:
    """端到端测试：喝东西检测"""
    
    @pytest.fixture
    def test_config(self):
        """加载测试配置"""
        with open('test/fixtures/integration/test-cases/drinking-positive.json') as f:
            return json.load(f)
    
    @pytest.mark.e2e
    @pytest.mark.bedrock
    def test_drinking_detection_positive(self, test_config, api_url, api_key):
        """测试喝东西检测 - 正向场景（完整自动化）"""
        
        # 1. 提交请求
        print(f"\n[步骤 1] 提交请求: {test_config['name']}")
        request_data = {
            'name': f"e2e-{test_config['name']}-{int(time.time())}",
            'input_config': {
                'type': 'url_list',
                'urls': [frame['url'] for frame in test_config['frames']]
            },
            'callback_url': 'https://webhook.site/test'
        }
        
        response = requests.post(
            f'{api_url}/requests',
            headers={'x-api-key': api_key},
            json=request_data
        )
        assert response.status_code == 200, f"提交失败: {response.text}"
        
        result = response.json()
        assert result['success'] is True
        request_id = result['data']['request_id']
        print(f"  ✓ Request ID: {request_id}")
        print(f"  ✓ Total frames: {result['data']['total_frames']}")
        
        # 2. 自动等待处理完成（指数退避轮询）
        print(f"\n[步骤 2] 等待处理完成...")
        total_frames = len(test_config['frames'])
        timeout = max(120, total_frames * 15)  # 每帧最多 15 秒
        
        final_status = self._wait_for_completion(
            api_url, api_key, request_id, timeout
        )
        print(f"  ✓ 最终状态: {final_status}")
        assert final_status in ['completed', 'partial_complete'], \
            f"处理失败，状态: {final_status}"
        
        # 3. 获取结果
        print(f"\n[步骤 3] 获取分析结果...")
        results_response = requests.get(
            f'{api_url}/requests/{request_id}/results',
            headers={'x-api-key': api_key}
        )
        assert results_response.status_code == 200
        results_data = results_response.json()['data']
        print(f"  ✓ 成功帧数: {results_data['frame_stats']['completed']}")
        print(f"  ✓ 失败帧数: {results_data['frame_stats']['failed']}")
        
        # 4. 验证检测结果
        print(f"\n[步骤 4] 验证检测结果准确性...")
        actual_frames = results_data['frames']
        self._verify_detection_results(test_config['frames'], actual_frames)
        print(f"  ✓ 所有检测结果符合预期")
        
        print(f"\n✅ 测试通过: {test_config['name']}")
    
    def _wait_for_completion(
        self, 
        api_url: str, 
        api_key: str, 
        request_id: str, 
        timeout: int
    ) -> str:
        """等待请求完成，使用指数退避轮询"""
        start_time = time.time()
        wait_time = 1
        iteration = 0
        
        while time.time() - start_time < timeout:
            iteration += 1
            response = requests.get(
                f'{api_url}/requests/{request_id}',
                headers={'x-api-key': api_key}
            )
            
            if response.status_code != 200:
                print(f"  ⚠ 查询失败: {response.status_code}")
                time.sleep(wait_time)
                continue
            
            data = response.json()['data']
            status = data['status']
            progress = data.get('progress', {}).get('percentage', 0)
            
            print(f"  [{iteration}] 状态: {status}, 进度: {progress:.1f}%")
            
            if status in ['completed', 'partial_complete', 'failed']:
                return status
            
            time.sleep(wait_time)
            wait_time = min(wait_time * 1.5, 10)  # 指数退避，最多 10 秒
        
        raise TimeoutError(
            f"请求 {request_id} 在 {timeout} 秒内未完成"
        )
    
    def _verify_detection_results(
        self, 
        expected_frames: list, 
        actual_frames: list
    ):
        """验证检测结果与预期一致"""
        assert len(actual_frames) == len(expected_frames), \
            f"帧数不匹配: 预期 {len(expected_frames)}, 实际 {len(actual_frames)}"
        
        for i, (expected, actual) in enumerate(zip(expected_frames, actual_frames)):
            frame_desc = expected.get('description', f'Frame {i}')
            print(f"\n  验证 {frame_desc}:")
            
            expected_results = expected['expected_results']
            actual_results = actual['results']
            
            for key, expected_value in expected_results.items():
                assert key in actual_results, \
                    f"  ✗ 缺少字段 '{key}'"
                
                actual_value = actual_results[key]
                
                # 处理不同类型的预期值
                if isinstance(expected_value, dict):
                    if 'min' in expected_value and 'max' in expected_value:
                        # 范围匹配
                        assert expected_value['min'] <= actual_value <= expected_value['max'], \
                            f"  ✗ {key} = {actual_value} 不在范围 [{expected_value['min']}, {expected_value['max']}]"
                        print(f"    ✓ {key} = {actual_value} (在预期范围内)")
                    
                    elif 'contains' in expected_value:
                        # 包含匹配
                        assert expected_value['contains'] in str(actual_value), \
                            f"  ✗ {key} = '{actual_value}' 不包含 '{expected_value['contains']}'"
                        print(f"    ✓ {key} 包含 '{expected_value['contains']}'")
                else:
                    # 精确匹配
                    assert actual_value == expected_value, \
                        f"  ✗ {key} = {actual_value}, 预期 {expected_value}"
                    print(f"    ✓ {key} = {actual_value}")
```

**验证点**：
1. **提交阶段**:
   - API 响应成功
   - 返回有效的 request_id
   - total_frames 正确

2. **处理阶段**:
   - 自动等待处理完成（无需手动轮询）
   - 使用指数退避策略（1s, 1.5s, 2.25s, ...）
   - 实时显示处理进度
   - 最终状态为 completed 或 partial_complete

3. **结果验证阶段**:
   - 所有帧都有分析结果
   - `drinking_is_drinking` 值正确
   - `drinking_confidence` 在预期范围内
   - `drinking_details` 包含预期关键词

4. **业务逻辑验证**:
   - Frame 1: 正在喝 (is_drinking=true)
   - Frame 2: 正在喝 (is_drinking=true)
   - Frame 3: 不在喝 (is_drinking=false)

---

### INT-E2E-002: 喝东西检测 - 负向场景

**测试目标**: 验证"只是拿着杯子"不会被误判为"正在喝"

**测试配置文件**：
```json
{
  "name": "drinking-detection-negative",
  "description": "测试喝东西检测 - 负向场景（只是拿着杯子）",
  "enabled_policies": ["drinking_detection"],
  "frames": [
    {
      "url": "https://test-bucket.s3.amazonaws.com/holding/frame-001.jpg",
      "description": "人物手持杯子但在讲话",
      "expected_results": {
        "drinking_is_drinking": false,
        "drinking_confidence_min": 0.7,
        "drinking_confidence_max": 1.0,
        "drinking_details_contains": "拿着"
      }
    },
    {
      "url": "https://test-bucket.s3.amazonaws.com/holding/frame-002.jpg",
      "description": "人物展示饮品",
      "expected_results": {
        "drinking_is_drinking": false,
        "drinking_confidence_min": 0.7,
        "drinking_confidence_max": 1.0
      }
    }
  ]
}
```

**执行步骤**: 同 INT-E2E-001（使用相同的自动化测试框架）

**验证点**：
- 所有帧的 `drinking_is_drinking` 都为 false
- 不会误判"拿着杯子"为"正在喝"

---

### INT-E2E-003: 多策略场景

**测试目标**: 验证多个策略同时执行的端到端流程

**测试配置文件**：
```json
{
  "name": "multi-policy",
  "description": "测试多策略场景",
  "enabled_policies": ["drinking_detection", "interval"],
  "frames": [
    {
      "url": "https://test-bucket.s3.amazonaws.com/multi/frame-000.jpg",
      "description": "第 0 帧 - interval 策略会处理",
      "expected_results": {
        "drinking_is_drinking": true,
        "interval_objects_contains": "cup"
      }
    },
    {
      "url": "https://test-bucket.s3.amazonaws.com/multi/frame-005.jpg",
      "description": "第 5 帧 - interval 策略会跳过",
      "expected_results": {
        "drinking_is_drinking": false
      },
      "not_expected": ["interval_objects"]
    },
    {
      "url": "https://test-bucket.s3.amazonaws.com/multi/frame-010.jpg",
      "description": "第 10 帧 - interval 策略会处理",
      "expected_results": {
        "drinking_is_drinking": true,
        "interval_objects_contains": "person"
      }
    }
  ]
}
```

**验证点**：
- 所有策略的结果都正确合并
- interval 策略只在 10 的倍数帧有结果
- drinking_detection 策略在所有帧都有结果
- 不同策略的 key 不冲突

---

### INT-E2E-004: 部分失败场景

**测试目标**: 验证部分帧失败时的端到端流程

**测试配置文件**：
```json
{
  "name": "partial-failure",
  "description": "测试部分帧失败场景",
  "enabled_policies": ["drinking_detection"],
  "frames": [
    {
      "url": "https://test-bucket.s3.amazonaws.com/valid/frame-001.jpg",
      "expected_results": {
        "drinking_is_drinking": true
      }
    },
    {
      "url": "https://test-bucket.s3.amazonaws.com/invalid/not-exist.jpg",
      "expected_status": "failed"
    },
    {
      "url": "https://test-bucket.s3.amazonaws.com/valid/frame-003.jpg",
      "expected_results": {
        "drinking_is_drinking": false
      }
    }
  ]
}
```

**验证点**：
- 最终状态为 `partial_complete`
- frame_stats.completed = 2
- frame_stats.failed = 1
- 成功的帧有正确的检测结果
- 失败的帧状态为 failed

---

## 7. 测试数据准备

### 测试图片上传

```bash
# 上传测试图片到 S3
aws s3 cp test/fixtures/integration/images/ s3://test-bucket/video/ --recursive

# 验证上传
aws s3 ls s3://test-bucket/video/
```

### 测试回调服务器

使用 webhook.site 或本地测试服务器：

```python
# test/fixtures/integration/callback-server.py
from flask import Flask, request, jsonify

app = Flask(__name__)
callbacks = []

@app.route('/callback', methods=['POST'])
def callback():
    data = request.json
    callbacks.append(data)
    print(f"Received callback: {data}")
    return jsonify({"success": True})

@app.route('/callbacks', methods=['GET'])
def get_callbacks():
    return jsonify(callbacks)

if __name__ == '__main__':
    app.run(port=5000)
```

启动服务器：
```bash
python test/fixtures/integration/callback-server.py
```

---

## 7. 测试执行

### 自动化测试脚本

```bash
# test/integration/run-all.sh
#!/bin/bash

set -e

API_URL="https://api.example.com"
API_KEY="YOUR_API_KEY"

echo "Running integration tests..."

# INT-001: 提交请求（Image List）
echo "INT-001: Submit request (Image List)"
response=$(curl -s -X POST "$API_URL/requests" \
  -H "x-api-key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d @test/fixtures/integration/request-urllist.json)

request_id=$(echo $response | jq -r '.data.request_id')
echo "Request ID: $request_id"

# 验证响应
if [ "$(echo $response | jq -r '.success')" != "true" ]; then
  echo "FAILED: Response not successful"
  exit 1
fi

echo "PASSED: INT-001"

# INT-007: 查询状态
echo "INT-007: Query status"
response=$(curl -s -X GET "$API_URL/requests/$request_id" \
  -H "x-api-key: $API_KEY")

if [ "$(echo $response | jq -r '.success')" != "true" ]; then
  echo "FAILED: Query failed"
  exit 1
fi

echo "PASSED: INT-007"

# 更多测试...

echo "All integration tests passed!"
```

### 运行测试

```bash
# 设置环境变量
export API_URL="https://api.example.com"
export API_KEY="YOUR_API_KEY"

# 运行所有集成测试
./test/integration/run-all.sh

# 运行单个测试
pytest test/integration/test_api_submit.py -v
```

---

## 8. 测试覆盖总结

### 8.1 组件集成测试（片段化测试）

| 测试用例 | 测试目标 | 测试范围 | 验证点数量 |
|---------|---------|---------|-----------|
| INT-001 | 提交请求（Image List） | 只测提交 | 5 |
| INT-002 | 提交请求（S3） | 只测提交 | 4 |
| INT-003 | 多个前缀错误 | 只测提交 | 4 |
| INT-004 | API Key 认证 | 只测提交 | 3 |
| INT-005 | SQS 触发 Lambda | 只测处理 | 6 |
| INT-006 | 并发处理 | 只测处理 | 4 |
| INT-007 | UUID 查询 | 只测查询 | 5 |
| INT-008 | name 查询 | 只测查询 | 2 |
| INT-009 | 查询不存在 | 只测查询 | 3 |
| INT-010 | 获取结果 | 只测查询 | 5 |
| INT-011 | 获取未完成结果 | 只测查询 | 4 |
| INT-012 | URL 刷新 | 只测查询 | 3 |
| INT-013 | 完整流程（成功） | 手动轮询 | 10+ |
| INT-014 | 完整流程（部分失败） | 手动轮询 | 6 |
| INT-015 | 超时处理 | 特定场景 | 4 |
| INT-016 | 回调重试 | 特定场景 | 4 |

**小计**: 16 个组件集成测试，72+ 个验证点

**特点**: 
- 测试各个组件的集成
- 需要手动操作和验证
- 适合开发阶段的功能验证

### 8.2 端到端自动化测试（完整流程测试）

| 测试用例 | 测试目标 | 测试范围 | 验证点数量 |
|---------|---------|---------|-----------|
| INT-E2E-001 | 喝东西检测 - 正向 | 完整 E2E + 业务验证 | 15+ |
| INT-E2E-002 | 喝东西检测 - 负向 | 完整 E2E + 业务验证 | 10+ |
| INT-E2E-003 | 多策略场景 | 完整 E2E + 业务验证 | 12+ |
| INT-E2E-004 | 部分失败场景 | 完整 E2E + 容错验证 | 8+ |

**小计**: 4 个端到端自动化测试，45+ 个验证点

**特点**:
- 完全自动化（提交 -> 等待 -> 验证）
- 验证业务逻辑（检测结果准确性）
- 使用配置文件管理测试数据
- 可集成到 CI/CD
- 支持回归测试

### 8.3 总计

**总测试用例**: 20 个  
**总验证点**: 117+

**测试分类**:
- 组件集成测试: 16 个（验证组件交互）
- 端到端自动化测试: 4 个（验证完整流程和业务逻辑）

---

## 9. 注意事项

### 测试环境清理

每次测试后清理资源：

```bash
# 删除测试 Request
aws dynamodb delete-item \
  --table-name Request \
  --key '{"request_id": {"S": "test-123"}}'

# 删除测试 Frame
aws dynamodb query \
  --table-name Frame \
  --key-condition-expression "request_id = :rid" \
  --expression-attribute-values '{":rid": {"S": "test-123"}}' \
  | jq -r '.Items[].frame_index.N' \
  | xargs -I {} aws dynamodb delete-item \
      --table-name Frame \
      --key '{"request_id": {"S": "test-123"}, "frame_index": {"N": "{}"}}'

# 清空 SQS 队列
aws sqs purge-queue \
  --queue-url https://sqs.us-east-1.amazonaws.com/123456789/frame-queue

# 删除 S3 结果文件
aws s3 rm s3://results-bucket/results/test-123/ --recursive
```

### 成本控制

- 使用小规模测试数据（3-10 张图片）
- 测试完成后立即清理资源
- 使用 AWS Free Tier 资源
- 避免频繁运行完整流程测试

### 测试隔离

- 使用唯一的 `name` 前缀（如 `test-{timestamp}`）
- 使用独立的 S3 前缀（如 `test/integration/`）
- 避免并发运行相同的测试用例
