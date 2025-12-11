# Health Check 测试用例

> **说明**: 本文档中的测试用例对应 [tech.md - Lambda Handler Public Method 设计](../tech.md#lambda-handler-public-method-设计) 中定义的 Health Check 方法。

## Layer 1: 单元测试

### 1.1 超时检测

#### HEALTH-001: 检测超时的 Request

**测试层级**: Unit Test  
**Mock**: 无需 AWS 服务

**输入**：
```python
request = {
    'request_id': 'test-123',
    'status': 'running',
    'last_activity_at': '2025-01-01T10:00:00Z'  # 3小时前
}
current_time = '2025-01-01T13:00:00Z'
timeout_limit = 7200  # 2小时
```

**预期结果**：
- 识别为超时（3小时 > 2小时）

**验证点**：
- 超时检测逻辑正确

---

#### HEALTH-002: 不检测未超时的 Request

**测试层级**: Unit Test  
**Mock**: 无需 AWS 服务

**输入**：
```python
request = {
    'request_id': 'test-123',
    'status': 'running',
    'last_activity_at': '2025-01-01T12:00:00Z'  # 1小时前
}
current_time = '2025-01-01T13:00:00Z'
timeout_limit = 7200  # 2小时
```

**预期结果**：
- 不识别为超时（1小时 < 2小时）

**验证点**：
- 超时检测逻辑正确

---

### 1.2 状态更新

#### HEALTH-003: 标记 Request 为 completed

**测试层级**: Unit Test  
**Mock**: 无需 AWS 服务

**输入**：
- 超时的 Request

**预期结果**：
- Request.status 更新为 "completed"

**验证点**：
- 状态更新逻辑正确

---

#### HEALTH-004: 标记未完成的 Frame 为 failed

**测试层级**: Unit Test  
**Mock**: 无需 AWS 服务

**输入**：
- 超时的 Request
- 10 个 Frame，其中 8 个 completed，2 个 pending

**预期结果**：
- 2 个 pending Frame 标记为 failed

**验证点**：
- Frame 状态更新逻辑正确

---

## Layer 2: 组件测试

### 2.1 完整流程测试

#### HEALTH-COMP-001: 检测超时 -> 标记完成 -> 触发回调

**测试层级**: Component Test  
**Mock**: DynamoDB, Lambda (使用 moto)

**前置条件**：
- Mock DynamoDB 中有超时的 Request
- Mock DynamoDB 中有部分未完成的 Frame

**执行步骤**：
1. 调用 Health Check Lambda
2. 传入 EventBridge Event

**验证点**：
1. 查询了 running 状态的 Request
2. 识别出超时的 Request
3. Request.status 更新为 "completed"
4. 未完成的 Frame 标记为 failed
5. 触发了 Completion Handler

**Mock 示例代码**：
```python
from moto import mock_dynamodb
import boto3
import json
from datetime import datetime, timedelta

@mock_dynamodb
def test_health_check_timeout():
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
    
    # 准备超时的 Request
    timeout_time = (datetime.now() - timedelta(hours=3)).isoformat()
    request_table.put_item(Item={
        'request_id': 'test-123',
        'name': 'test-video',
        'status': 'running',
        'total_frames': 10,
        'frame_stats': {'total': 10, 'completed': 8, 'failed': 0, 'pending': 2},
        'last_activity_at': timeout_time
    })
    
    # 准备 Frame 数据
    for i in range(8):
        frame_table.put_item(Item={
            'request_id': 'test-123',
            'frame_index': i,
            'status': 'completed'
        })
    
    for i in range(8, 10):
        frame_table.put_item(Item={
            'request_id': 'test-123',
            'frame_index': i,
            'status': 'pending'
        })
    
    # 调用 handler
    event = {}
    response = health_check_handler(event, {})
    
    # Assert Request 更新
    request_response = request_table.get_item(Key={'request_id': 'test-123'})
    request = request_response['Item']
    assert request['status'] == 'completed'
    
    # Assert Frame 更新
    for i in range(8, 10):
        frame_response = frame_table.get_item(
            Key={'request_id': 'test-123', 'frame_index': i}
        )
        frame = frame_response['Item']
        assert frame['status'] == 'failed'
```

---

#### HEALTH-COMP-002: 不处理未超时的 Request

**测试层级**: Component Test  
**Mock**: DynamoDB (使用 moto)

**前置条件**：
- Mock DynamoDB 中有未超时的 Request

**执行步骤**：
1. 调用 Health Check Lambda

**验证点**：
1. 查询了 running 状态的 Request
2. 未识别出超时的 Request
3. 不更新任何状态

---

#### HEALTH-COMP-003: 处理多个超时的 Request

**测试层级**: Component Test  
**Mock**: DynamoDB (使用 moto)

**前置条件**：
- Mock DynamoDB 中有 3 个超时的 Request

**执行步骤**：
1. 调用 Health Check Lambda

**验证点**：
1. 识别出所有 3 个超时的 Request
2. 所有 3 个 Request 都被标记为 completed
3. 触发了 3 次 Completion Handler

---

## Layer 3: 集成测试

### 3.1 真实环境测试

#### HEALTH-INT-001: EventBridge 定时触发

**测试层级**: Integration Test  
**环境**: 真实 AWS 资源

**前置条件**：
- EventBridge 规则已配置（每5分钟）
- DynamoDB 中有超时的 Request

**执行步骤**：
1. 等待 EventBridge 自动触发
2. 或手动触发 Lambda

**验证点**：
1. Lambda 被触发
2. 超时的 Request 被处理
3. CloudWatch Logs 中有处理日志

---

#### HEALTH-INT-002: 手动触发测试

**测试层级**: Integration Test  
**环境**: 真实 AWS 资源

**前置条件**：
- DynamoDB 中有超时的 Request

**执行步骤**：
```bash
aws lambda invoke \
  --function-name health-check \
  --region ap-northeast-2 \
  response.json
```

**验证点**：
1. Lambda 执行成功
2. DynamoDB 中 Request 状态被更新
3. Completion Handler 被触发

---

## 测试覆盖总结

**Layer 1 单元测试**: 4 个测试用例
- 超时检测逻辑
- 状态更新逻辑

**Layer 2 组件测试**: 3 个测试用例
- 完整流程（超时处理）
- 不处理未超时的 Request
- 处理多个超时的 Request

**总计**: 7 个测试用例
