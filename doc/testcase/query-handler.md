# Query Handler 测试用例

> **说明**: 本文档中的测试用例对应 [tech.md - Lambda Handler Public Method 设计](../tech.md#lambda-handler-public-method-设计) 中定义的 Query Handler 方法。

## Layer 1: 单元测试

### 1.1 查询逻辑

#### QUERY-001: 识别 UUID 格式

**测试目标**: `is_uuid()` 方法

**测试层级**: Unit Test  
**Mock**: 无需 AWS 服务

**输入**：
- id_or_name = "550e8400-e29b-41d4-a716-446655440000"（标准 UUID 格式：8-4-4-4-12）

**预期结果**：
- is_uuid() 返回 True
- 识别为 UUID，使用 request_id 查询

**验证点**：
- UUID 识别逻辑正确
- 符合标准 UUID 格式（8-4-4-4-12 位十六进制）

---

#### QUERY-002: 识别 name 格式

**测试目标**: `is_uuid()` 方法

**测试层级**: Unit Test  
**Mock**: 无需 AWS 服务

**输入**：
- id_or_name = "my-video-analysis"（非 UUID 格式）

**预期结果**：
- is_uuid() 返回 False
- 识别为 name，使用 name 查询（GSI）

**验证点**：
- name 识别逻辑正确
- 非标准 UUID 格式的字符串被识别为 name

---

### 1.2 预签名 URL 生成

#### QUERY-003: 生成新的预签名 URL 并写回 DynamoDB

**测试目标**: `refresh_presigned_url()` 方法

**测试层级**: Unit Test  
**Mock**: S3, DynamoDB (使用 moto)

**输入**：
- request = {
    'request_id': '550e8400-e29b-41d4-a716-446655440000',
    'result_s3_key': 'results/550e8400-e29b-41d4-a716-446655440000/result.json',
    'result_s3_bucket': 'test-results-bucket'
  }

**预期结果**：
- 生成新的预签名 URL（1天有效期）
- 返回 (presigned_url, url_expiration) 元组
- DynamoDB 中 Request.result_presigned_url 被更新
- DynamoDB 中 Request.result_url_expiration 被更新

**验证点**：
- 每次调用都生成新 URL
- 新 URL 和过期时间写回 DynamoDB

---

## Layer 2: 组件测试

### 2.1 查询状态测试

#### QUERY-COMP-001: 通过 UUID 查询

**测试层级**: Component Test  
**Mock**: DynamoDB (使用 moto)

**前置条件**：
- Mock DynamoDB 中有 Request 记录

**输入**：
- GET /requests/{request_id}

**验证点**：
1. 响应状态码 200
2. 返回 Request 信息
3. frame_stats 正确
4. 不返回 multiple_requests 字段

**Mock 示例代码**：
```python
from moto import mock_dynamodb
import boto3
import json

@mock_dynamodb
def test_query_by_uuid():
    # 创建 mock DynamoDB 表
    dynamodb = boto3.resource('dynamodb', region_name='us-east-1')
    request_table = dynamodb.create_table(
        TableName='Request',
        KeySchema=[{'AttributeName': 'request_id', 'KeyType': 'HASH'}],
        AttributeDefinitions=[{'AttributeName': 'request_id', 'AttributeType': 'S'}],
        BillingMode='PAY_PER_REQUEST'
    )
    
    # 准备数据
    request_table.put_item(Item={
        'request_id': 'test-123',
        'name': 'test-video',
        'status': 'running',
        'total_frames': 100,
        'frame_stats': {'total': 100, 'completed': 50, 'failed': 0, 'pending': 50}
    })
    
    # 调用 handler
    event = {
        'pathParameters': {'id_or_name': 'test-123'}
    }
    response = query_handler(event, {})
    
    # Assert
    assert response['statusCode'] == 200
    body = json.loads(response['body'])
    assert body['request_id'] == 'test-123'
    assert body['name'] == 'test-video'
    assert body['status'] == 'running'
    assert 'multiple_requests' not in body
```

---

#### QUERY-COMP-002: 通过 name 查询（单个匹配）

**测试层级**: Component Test  
**Mock**: DynamoDB (使用 moto)

**前置条件**：
- Mock DynamoDB 中有 1 个同名 Request

**输入**：
- GET /requests/{name}

**验证点**：
1. 响应状态码 200
2. 返回 Request 信息
3. multiple_requests = false

---

#### QUERY-COMP-003: 通过 name 查询（多个匹配）

**测试层级**: Component Test  
**Mock**: DynamoDB (使用 moto)

**前置条件**：
- Mock DynamoDB 中有 3 个同名 Request

**输入**：
- GET /requests/{name}

**验证点**：
1. 响应状态码 200
2. 返回最新的 Request
3. multiple_requests = true

---

#### QUERY-COMP-004: 查询不存在的请求

**测试层级**: Component Test  
**Mock**: DynamoDB (使用 moto)

**前置条件**：
- Mock DynamoDB 中无匹配记录

**输入**：
- GET /requests/non-existent

**验证点**：
1. 响应状态码 404
2. 错误信息明确

---

### 2.2 获取结果测试

#### QUERY-COMP-005: 获取完整结果

**测试层级**: Component Test  
**Mock**: DynamoDB, S3 (使用 moto)

**前置条件**：
- Request 状态为 completed
- S3 中有结果文件

**输入**：
- GET /requests/{id_or_name}/results

**验证点**：
1. 响应状态码 200
2. 返回所有 Frame 结果
3. 包含 S3 信息和预签名 URL
4. 生成了新的预签名 URL

---

#### QUERY-COMP-006: 查询未完成请求的结果

**测试层级**: Component Test  
**Mock**: DynamoDB (使用 moto)

**前置条件**：
- Request 状态为 running

**输入**：
- GET /requests/{id_or_name}/results

**验证点**：
1. 响应状态码 400
2. 错误信息: "Request not completed yet"

---

## 测试覆盖总结

**Layer 1 单元测试**: 3 个测试用例
- UUID/name 识别逻辑
- 预签名 URL 生成

**Layer 2 组件测试**: 6 个测试用例
- 查询状态（UUID、name、不存在）
- 获取结果（完成、未完成）

**总计**: 9 个测试用例
