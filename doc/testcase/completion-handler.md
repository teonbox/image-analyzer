# Completion Handler 测试用例

> **说明**: 本文档中的测试用例对应 [tech.md - Lambda Handler Public Method 设计](../tech.md#lambda-handler-public-method-设计) 中定义的 Completion Handler 方法。

## Layer 1: 单元测试

### 1.1 结果聚合

#### COMP-001: 聚合所有 Frame 结果

**测试层级**: Unit Test  
**Mock**: 无需 AWS 服务

**输入**：
```python
frames = [
    {
        'frame_index': 0,
        'frame_key': 'video/frame-001.jpg',
        'status': 'completed',
        'policy_results': {'description': 'A person eating', 'interval_check': True}
    },
    {
        'frame_index': 1,
        'frame_key': 'video/frame-002.jpg',
        'status': 'completed',
        'policy_results': {'description': 'A person talking'}
    },
    {
        'frame_index': 2,
        'frame_key': 'video/frame-003.jpg',
        'status': 'failed',
        'policy_results': {}
    }
]
```

**预期结果**：
```python
aggregated_result = {
    'total_frames': 3,
    'completed_frames': 2,
    'failed_frames': 1,
    'frames': [
        {
            'frame_index': 0,
            'frame_key': 'video/frame-001.jpg',
            'status': 'completed',
            'results': {'description': 'A person eating', 'interval_check': True}
        },
        {
            'frame_index': 1,
            'frame_key': 'video/frame-002.jpg',
            'status': 'completed',
            'results': {'description': 'A person talking'}
        },
        {
            'frame_index': 2,
            'frame_key': 'video/frame-003.jpg',
            'status': 'failed',
            'results': {}
        }
    ]
}
```

**验证点**：
- 结果聚合逻辑正确
- 统计信息准确

---

#### COMP-002: 处理部分失败的 Frame

**测试层级**: Unit Test  
**Mock**: 无需 AWS 服务

**输入**：
- 10 个 Frame，其中 8 个 completed，2 个 failed

**预期结果**：
- total_frames = 10
- completed_frames = 8
- failed_frames = 2
- frames 数组包含所有 10 个帧

**验证点**：
- 部分失败场景处理正确

---

### 1.2 S3 路径生成

#### COMP-003: 生成正确的 S3 路径

**测试层级**: Unit Test  
**Mock**: 无需 AWS 服务

**输入**：
- request_id = "abc-123-def"

**预期结果**：
- s3_key = "results/abc-123-def/result.json"

**验证点**：
- S3 路径格式正确

---

### 1.3 预签名 URL 生成

#### COMP-004: 生成预签名 URL

**测试层级**: Unit Test  
**Mock**: S3 (使用 moto)

**输入**：
- bucket = "test-results-bucket"
- key = "results/abc-123/result.json"
- expiration = 86400 (1天)

**预期结果**：
- 返回有效的预签名 URL
- URL 包含 bucket 和 key 信息
- URL 包含过期时间参数

**验证点**：
- 预签名 URL 生成逻辑正确

---

## Layer 2: 组件测试

### 2.1 完整流程测试

#### COMP-COMP-001: DynamoDB -> 聚合 -> S3 -> 回调

**测试层级**: Component Test  
**Mock**: DynamoDB, S3, HTTP (使用 moto + requests-mock)

**前置条件**：
- Mock DynamoDB 中有 Request 记录
- Mock DynamoDB 中有 10 个 Frame 记录（8 completed, 2 failed）
- Mock S3 桶已创建
- Mock HTTP 服务器（接收回调）

**执行步骤**：
1. 调用 Completion Handler
2. 传入 Lambda Invoke Event (request_id)

**验证点**：
1. 查询了所有 Frame 记录
2. 聚合结果正确
3. 结果保存到 S3: results/{request_id}/result.json
4. 生成了预签名 URL
5. Request.result_s3_key 被更新
6. Request.result_url_expiration 被更新
7. Request.status 更新为 "completed"
8. 发送了回调请求
9. 回调数据包含:
   - request_id
   - name
   - status
   - statistics (total, completed, failed)
   - result_s3_bucket
   - result_s3_key
   - result_presigned_url
   - result_url_expiration
   - note (提示使用 bucket+key 长期访问)

**Mock 示例代码**：
```python
from moto import mock_dynamodb, mock_s3
import boto3
import json
import requests_mock

@mock_dynamodb
@mock_s3
def test_completion_handler_flow():
    # 创建 mock DynamoDB 表
    dynamodb = boto3.resource('dynamodb', region_name='us-east-1')
    request_table = dynamodb.create_table(
        TableName='Request',
        KeySchema=[{'AttributeName': 'request_id', 'KeyType': 'HASH'}],
        AttributeDefinitions=[{'AttributeName': 'request_id', 'AttributeType': 'S'}],
        BillingMode='PAY_PER_REQUEST'
    )
    
    frame_table = dynamodb.create_table(
        TableName='Frame',
        KeySchema=[
            {'AttributeName': 'request_id', 'KeyType': 'HASH'},
            {'AttributeName': 'frame_index', 'KeyType': 'RANGE'}
        ],
        AttributeDefinitions=[
            {'AttributeName': 'request_id', 'AttributeType': 'S'},
            {'AttributeName': 'frame_index', 'AttributeType': 'N'}
        ],
        BillingMode='PAY_PER_REQUEST'
    )
    
    # 准备 Request 数据
    request_table.put_item(Item={
        'request_id': 'test-123',
        'name': 'test-video',
        'status': 'running',
        'total_frames': 10,
        'frame_stats': {'total': 10, 'completed': 8, 'failed': 2, 'pending': 0},
        'callback_url': 'https://example.com/callback'
    })
    
    # 准备 Frame 数据
    for i in range(8):
        frame_table.put_item(Item={
            'request_id': 'test-123',
            'frame_index': i,
            'frame_key': f'video/frame-{i:03d}.jpg',
            'status': 'completed',
            'policy_results': {'description': f'Frame {i}'}
        })
    
    for i in range(8, 10):
        frame_table.put_item(Item={
            'request_id': 'test-123',
            'frame_index': i,
            'frame_key': f'video/frame-{i:03d}.jpg',
            'status': 'failed',
            'policy_results': {}
        })
    
    # 创建 mock S3 桶
    s3 = boto3.client('s3', region_name='us-east-1')
    s3.create_bucket(Bucket='test-results-bucket')
    
    # Mock HTTP 回调
    with requests_mock.Mocker() as m:
        m.post('https://example.com/callback', status_code=200)
        
        # 调用 handler
        event = {'request_id': 'test-123'}
        response = completion_handler(event, {})
        
        # Assert S3
        s3_response = s3.get_object(
            Bucket='test-results-bucket',
            Key='results/test-123/result.json'
        )
        result_data = json.loads(s3_response['Body'].read())
        assert result_data['total_frames'] == 10
        assert result_data['completed_frames'] == 8
        assert result_data['failed_frames'] == 2
        
        # Assert Request 更新
        request_response = request_table.get_item(Key={'request_id': 'test-123'})
        request = request_response['Item']
        assert request['status'] == 'completed'
        assert request['result_s3_key'] == 'results/test-123/result.json'
        assert 'result_url_expiration' in request
        
        # Assert 回调
        assert m.called
        callback_request = m.request_history[0]
        callback_data = json.loads(callback_request.text)
        assert callback_data['request_id'] == 'test-123'
        assert callback_data['status'] == 'completed'
        assert 'result_presigned_url' in callback_data
```

---

### 2.2 回调重试测试

#### COMP-COMP-002: 回调失败后自动重试

**测试层级**: Component Test  
**Mock**: DynamoDB, S3, HTTP (使用 moto + requests-mock)

**前置条件**：
- Mock DynamoDB 中有 Request 和 Frame 记录
- Mock S3 桶已创建
- Mock HTTP 服务器前 2 次返回 500 错误，第 3 次返回 200

**执行步骤**：
1. 调用 Completion Handler
2. 回调失败 2 次后成功

**验证点**：
1. 结果保存到 S3 成功
2. Request.status 更新为 "completed" 或 "partial_complete"
3. 回调共发送 3 次请求
4. 最终回调成功
5. send_callback 返回 True

**说明**：
- 回调重试在 Lambda 内部完成
- 每 30 秒重试一次，最多重试 5 次

---

#### COMP-COMP-003: 回调达到最大重试次数

**测试层级**: Component Test  
**Mock**: DynamoDB, S3, HTTP (使用 moto + requests-mock)

**前置条件**：
- Mock DynamoDB 中有 Request 和 Frame 记录
- Mock S3 桶已创建
- Mock HTTP 服务器始终返回 500 错误

**执行步骤**：
1. 调用 Completion Handler
2. 回调持续失败

**验证点**：
1. 结果保存到 S3 成功
2. Request.status 更新为 "completed" 或 "partial_complete"
3. 回调共发送 5 次请求（最大重试次数）
4. send_callback 返回 False
5. Lambda 正常完成（不抛出异常）

---

#### COMP-COMP-004: 回调首次成功

**测试层级**: Component Test  
**Mock**: DynamoDB, S3, HTTP (使用 moto + requests-mock)

**前置条件**：
- Mock DynamoDB 中有 Request 和 Frame 记录
- Mock S3 桶已创建
- Mock HTTP 服务器返回 200

**执行步骤**：
1. 调用 Completion Handler
2. 回调首次成功

**验证点**：
1. 回调只发送 1 次请求
2. send_callback 返回 True

---

### 2.3 全部失败场景

#### COMP-COMP-005: 所有 Frame 都失败

**测试层级**: Component Test  
**Mock**: DynamoDB, S3, HTTP (使用 moto + requests-mock)

**前置条件**：
- Mock DynamoDB 中有 Request 记录
- Mock DynamoDB 中有 5 个 Frame 记录，全部 status = 'failed'
- Mock S3 桶已创建
- Mock HTTP 服务器返回 200

**执行步骤**：
1. 调用 Completion Handler

**验证点**：
1. 结果保存到 S3 成功
2. Request.status 更新为 "failed"
3. statistics.completed_frames = 0
4. statistics.failed_frames = 5
5. statistics.success_rate = "0.00%"
6. 回调数据中 status = "failed"

---

## 测试覆盖总结

**Layer 1 单元测试**: 4 个测试用例
- 结果聚合逻辑
- S3 路径生成
- 预签名 URL 生成

**Layer 2 组件测试**: 5 个测试用例
- 完整流程（成功）
- 回调失败后自动重试
- 回调达到最大重试次数
- 回调首次成功
- 所有 Frame 都失败

**总计**: 9 个测试用例
