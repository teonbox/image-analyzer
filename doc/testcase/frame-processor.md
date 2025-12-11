# Frame Processor 测试用例

## 测试范围说明

**本测试关注点**：
- SQS 消息解析的正确性
- DynamoDB 数据的正确读写（Request、Frame 表）
- 状态转换的正确性（Request.status、Frame.status、policy_status）
- frame_stats 统计数据的准确更新
- 乐观锁（version）的正确使用
- 时间戳字段的正确更新
- 完成检测逻辑的正确触发

**本测试不关注**：
- Policy 本身的分析逻辑正确性（由 Policy 单元测试覆盖）
- Bedrock 模型调用的实际结果（由集成测试覆盖）
- 策略使用内置测试策略，仅验证框架对结果的处理

## 测试策略说明

本测试使用 tech.md 中定义的测试策略，详见 [tech.md - 测试策略](../../.kiro/steering/tech.md#测试策略)。

**主要使用的策略**：

| 策略 | get_name() | 用途 | 调用 Bedrock |
|------|------------|------|-------------|
| EmptyPolicy | `'empty'` | 验证框架逻辑，返回静态数据 | 否 |
| FailingPolicy | `'failing'` | 验证策略失败场景，总是抛出异常 | 否 |

**业务策略（需 mock Bedrock）**：

测试中如需验证跳过逻辑或上下文加载，可使用业务策略并 mock Bedrock：

| 策略 | get_name() | 用途 |
|------|------------|------|
| IntervalPolicy | `'interval'` | 验证跳过逻辑（每 10 帧处理一次） |
| ContextAwarePolicy | `'context_aware'` | 验证上下文帧加载 |

**策略配置方式**：
```python
os.environ['ENABLED_POLICIES'] = 'empty'  # 单策略
os.environ['ENABLED_POLICIES'] = 'empty,interval'  # 多策略
```

**EmptyPolicy 返回结果**：
```python
{
    'empty_result': 'static_value',
    'empty_frame_index': <frame_index>
}
```

**FailingPolicy 行为**：
```python
# 总是抛出 RuntimeError
raise RuntimeError(f"FailingPolicy intentionally failed for frame {frame_index}")
```

## Layer 1: 单元测试

### 1.1 消息解析

#### FP-001: 正确解析 SQS 消息

**测试目标**: `FrameProcessor.parse_sqs_message()`  
**测试层级**: Unit Test  
**Mock**: 无需 AWS 服务

**输入**：
```json
{
  "Records": [{
    "body": "{\"request_id\": \"test-123\", \"request_name\": \"my-video\", \"frame_index\": 100, \"target_frame_url\": \"https://example.com/frame-100.jpg\", \"before_frame_urls\": [\"https://example.com/frame-99.jpg\", \"https://example.com/frame-98.jpg\"], \"after_frame_urls\": [\"https://example.com/frame-101.jpg\"]}"
  }]
}
```

**预期结果**：
- request_id = "test-123"
- request_name = "my-video"
- frame_index = 100
- target_frame_url = "https://example.com/frame-100.jpg"
- before_frame_urls = ["https://example.com/frame-99.jpg", "https://example.com/frame-98.jpg"]
- after_frame_urls = ["https://example.com/frame-101.jpg"]

**验证点**：
- 所有字段正确提取，值完全匹配

---

#### FP-002: 处理无效 JSON 消息

**测试目标**: `FrameProcessor.parse_sqs_message()` - 错误处理  
**测试层级**: Unit Test  
**Mock**: 无需 AWS 服务

**输入**：
```json
{
  "Records": [{
    "body": "invalid json {"
  }]
}
```

**预期结果**：
- 抛出 ValueError 或返回错误响应
- 错误信息包含 "JSON" 或 "parse" 关键字

---

#### FP-003: 处理缺少必需字段的消息

**测试目标**: `FrameProcessor.parse_sqs_message()` - 字段验证  
**测试层级**: Unit Test  
**Mock**: 无需 AWS 服务

**输入**（缺少 request_id）：
```json
{
  "Records": [{
    "body": "{\"frame_index\": 0, \"target_frame_url\": \"https://example.com/frame-0.jpg\"}"
  }]
}
```

**预期结果**：
- 抛出 ValueError 或返回错误响应
- 错误信息指明缺少 request_id 字段

---

#### FP-004: 处理 before_frame_urls 包含 null 的消息

**测试目标**: `FrameProcessor.parse_sqs_message()` - 丢帧场景  
**测试层级**: Unit Test  
**Mock**: 无需 AWS 服务

**输入**：
```json
{
  "Records": [{
    "body": "{\"request_id\": \"test-123\", \"request_name\": \"my-video\", \"frame_index\": 100, \"target_frame_url\": \"https://example.com/frame-100.jpg\", \"before_frame_urls\": [\"https://example.com/frame-99.jpg\", null, \"https://example.com/frame-97.jpg\"], \"after_frame_urls\": []}"
  }]
}
```

**预期结果**：
- 正确解析，before_frame_urls[1] = null
- 不抛出异常

---

## Layer 2: 组件测试

### 2.1 Frame 记录创建与状态管理

#### FP-COMP-001: 首次处理帧 - 创建 Frame 记录

**测试目标**: `FrameProcessor.load_or_create_frame()` - Frame 创建  
**测试层级**: Component Test  
**Mock**: DynamoDB (使用 moto), HTTP 请求 (使用 responses)  
**使用策略**: EmptyPolicy

**前置条件**：
- DynamoDB Request 表中有记录：
  ```json
  {
    "request_id": "test-123",
    "status": "pending",
    "total_frames": 100,
    "frame_stats": {"total": 100, "completed": 0, "failed": 0, "pending": 100},
    "version": 1
  }
  ```
- DynamoDB Frame 表中无 frame_index=0 的记录
- Mock HTTP 返回测试图片数据
- 配置 `ENABLED_POLICIES=empty`

**输入 SQS 消息**：
```json
{
  "request_id": "test-123",
  "request_name": "my-video",
  "frame_index": 0,
  "target_frame_url": "https://example.com/frame-0.jpg",
  "before_frame_urls": [],
  "after_frame_urls": ["https://example.com/frame-1.jpg"]
}
```

**验证点**：
1. Frame 表新增记录：
   - request_id = "test-123"
   - frame_index = 0
   - frame_url = "https://example.com/frame-0.jpg"
   - status = "completed"
   - policy_results = {"empty_result": "static_value", "empty_frame_index": 0}
   - policy_status = {"empty": "completed"}
   - retry_count = 0
   - created_at 在当前时间前后 60 秒内
   - completed_at 在当前时间前后 60 秒内
   - completed_at >= created_at

2. Request 表更新：
   - status = "running"（从 pending 转换）
   - last_activity_at 在当前时间前后 60 秒内
   - frame_stats = {"total": 100, "completed": 1, "failed": 0, "pending": 99}
   - version = 2（乐观锁递增）

---

#### FP-COMP-002: 幂等性 - 跳过已完成的帧

**测试目标**: `FrameProcessor.handler()` - 幂等性保证  
**测试层级**: Component Test  
**Mock**: DynamoDB (使用 moto), HTTP 请求 (使用 responses)  
**使用策略**: EmptyPolicy

**前置条件**：
- DynamoDB Request 表中有记录
- DynamoDB Frame 表中已有记录：
  ```json
  {
    "request_id": "test-123",
    "frame_index": 0,
    "status": "completed",
    "policy_results": {"empty_result": "static_value", "empty_frame_index": 0},
    "policy_status": {"empty": "completed"},
    "completed_at": "2025-01-01T10:00:00Z"
  }
  ```
- 配置 `ENABLED_POLICIES=empty`

**输入 SQS 消息**：
```json
{
  "request_id": "test-123",
  "request_name": "my-video",
  "frame_index": 0,
  "target_frame_url": "https://example.com/frame-0.jpg",
  "before_frame_urls": [],
  "after_frame_urls": []
}
```

**验证点**：
1. 不发起 HTTP 请求下载图片
2. 不调用 Policy
3. Frame 记录保持不变：
   - policy_results = {"empty_result": "static_value", "empty_frame_index": 0}
   - completed_at = "2025-01-01T10:00:00Z"（未更新）
4. Request.frame_stats 不变

---

#### FP-COMP-003: 重试失败的帧 - 更新 retry_count

**测试目标**: `FrameProcessor.handler()` - 重试逻辑  
**测试层级**: Component Test  
**Mock**: DynamoDB (使用 moto), HTTP 请求 (使用 responses)  
**使用策略**: EmptyPolicy

**前置条件**：
- DynamoDB Request 表中有记录：
  ```json
  {
    "request_id": "test-123",
    "status": "running",
    "total_frames": 100,
    "frame_stats": {"total": 100, "completed": 50, "failed": 1, "pending": 49},
    "version": 1
  }
  ```
- DynamoDB Frame 表中已有失败记录：
  ```json
  {
    "request_id": "test-123",
    "frame_index": 0,
    "status": "failed",
    "retry_count": 1,
    "policy_status": {"empty": "failed"}
  }
  ```
- Mock HTTP 返回测试图片数据
- 配置 `ENABLED_POLICIES=empty`

**输入 SQS 消息**：
```json
{
  "request_id": "test-123",
  "request_name": "my-video",
  "frame_index": 0,
  "target_frame_url": "https://example.com/frame-0.jpg",
  "before_frame_urls": [],
  "after_frame_urls": []
}
```

**验证点**：
1. Frame 记录更新：
   - status = "completed"
   - retry_count = 2（递增）
   - policy_status = {"empty": "completed"}
   - completed_at 在当前时间前后 60 秒内

2. Request.frame_stats 更新（重试成功场景）：
   - failed = 0（从 1 减 1）
   - completed = 51（从 50 加 1）
   - pending = 49（保持不变，因为是重试而非新帧）
   - version = 2（乐观锁递增）

---

### 2.2 Request 状态转换

#### FP-COMP-004: Request 状态从 pending 转为 running

**测试目标**: `FrameProcessor.handler()` - Request 状态转换  
**测试层级**: Component Test  
**Mock**: DynamoDB (使用 moto), HTTP 请求 (使用 responses)

**前置条件**：
- Request.status = "pending"
- Frame 表中无记录

**输入 SQS 消息**：处理第一个帧

**验证点**：
1. Request.status = "running"
2. Request.last_activity_at 被更新

---

#### FP-COMP-005: Request 状态保持 running

**测试目标**: `FrameProcessor.handler()` - Request 状态保持  
**测试层级**: Component Test  
**Mock**: DynamoDB (使用 moto), HTTP 请求 (使用 responses)  
**使用策略**: EmptyPolicy

**前置条件**：
- DynamoDB Request 表中有记录：
  ```json
  {
    "request_id": "test-123",
    "status": "running",
    "total_frames": 100,
    "frame_stats": {"total": 100, "completed": 50, "failed": 0, "pending": 50},
    "version": 5
  }
  ```
- DynamoDB Frame 表中无 frame_index=60 的记录
- Mock HTTP 返回测试图片数据
- 配置 `ENABLED_POLICIES=empty`

**输入 SQS 消息**：
```json
{
  "request_id": "test-123",
  "request_name": "test-video",
  "frame_index": 60,
  "target_frame_url": "https://example.com/frame-60.jpg",
  "before_frame_urls": [],
  "after_frame_urls": []
}
```

**验证点**：
1. Request.status 保持 "running"（不变）
2. Request.last_activity_at 在当前时间前后 60 秒内
3. Request.frame_stats = {"total": 100, "completed": 51, "failed": 0, "pending": 49}
4. Request.version = 6（乐观锁递增）
5. Frame 表新增记录：
   - request_id = "test-123"
   - frame_index = 60
   - status = "completed"
   - policy_status = {"empty": "completed"}

---

### 2.3 frame_stats 统计更新

#### FP-COMP-006: frame_stats 正确递增 completed

**测试目标**: `FrameProcessor.update_frame_stats()` - 统计更新  
**测试层级**: Component Test  
**Mock**: DynamoDB (使用 moto), HTTP 请求 (使用 responses)  
**使用策略**: EmptyPolicy

**前置条件**：
- DynamoDB Request 表中有记录：
  ```json
  {
    "request_id": "test-123",
    "status": "running",
    "total_frames": 100,
    "frame_stats": {"total": 100, "completed": 50, "failed": 5, "pending": 45},
    "version": 10
  }
  ```
- DynamoDB Frame 表中无 frame_index=70 的记录
- Mock HTTP 返回测试图片数据
- 配置 `ENABLED_POLICIES=empty`

**输入 SQS 消息**：
```json
{
  "request_id": "test-123",
  "request_name": "test-video",
  "frame_index": 70,
  "target_frame_url": "https://example.com/frame-70.jpg",
  "before_frame_urls": [],
  "after_frame_urls": []
}
```

**验证点**：
1. Frame 表新增记录：
   - request_id = "test-123"
   - frame_index = 70
   - status = "completed"
   - policy_status = {"empty": "completed"}
2. Request.frame_stats = {"total": 100, "completed": 51, "failed": 5, "pending": 44}
3. Request.version = 11（乐观锁递增）

---

#### FP-COMP-007: frame_stats 正确递增 failed

**测试目标**: `FrameProcessor.update_frame_stats()` - 失败统计  
**测试层级**: Component Test  
**Mock**: DynamoDB (使用 moto), HTTP 请求 (使用 responses)  
**使用策略**: EmptyPolicy（mock analyze 方法抛出异常）

**前置条件**：
- DynamoDB Request 表中有记录：
  ```json
  {
    "request_id": "test-123",
    "status": "running",
    "total_frames": 100,
    "frame_stats": {"total": 100, "completed": 50, "failed": 5, "pending": 45},
    "version": 10
  }
  ```
- DynamoDB Frame 表中无 frame_index=70 的记录
- Mock HTTP 返回测试图片数据
- Mock EmptyPolicy.analyze 抛出异常
- 配置 `ENABLED_POLICIES=empty`

**输入 SQS 消息**：
```json
{
  "request_id": "test-123",
  "request_name": "test-video",
  "frame_index": 70,
  "target_frame_url": "https://example.com/frame-70.jpg",
  "before_frame_urls": [],
  "after_frame_urls": []
}
```

**验证点**：
1. Frame 表新增记录：
   - request_id = "test-123"
   - frame_index = 70
   - status = "failed"
   - policy_status = {"empty": "failed"}
2. Request.frame_stats = {"total": 100, "completed": 50, "failed": 6, "pending": 44}
3. Request.version = 11（乐观锁递增）

---

#### FP-COMP-008: frame_stats 乐观锁更新成功

**测试目标**: `FrameProcessor.update_frame_stats()` - 乐观锁正常更新  
**测试层级**: Component Test  
**Mock**: DynamoDB (使用 moto), HTTP 请求 (使用 responses)  
**使用策略**: EmptyPolicy

**前置条件**：
- DynamoDB Request 表中有记录：
  ```json
  {
    "request_id": "test-123",
    "status": "running",
    "total_frames": 100,
    "frame_stats": {"total": 100, "completed": 50, "failed": 0, "pending": 50},
    "version": 10
  }
  ```
- DynamoDB Frame 表中无 frame_index=60 的记录
- Mock HTTP 返回测试图片数据
- 配置 `ENABLED_POLICIES=empty`

**输入 SQS 消息**：
```json
{
  "request_id": "test-123",
  "request_name": "test-video",
  "frame_index": 60,
  "target_frame_url": "https://example.com/frame-60.jpg",
  "before_frame_urls": [],
  "after_frame_urls": []
}
```

**验证点**：
1. Frame 表新增记录：
   - request_id = "test-123"
   - frame_index = 60
   - status = "completed"
2. Request.frame_stats = {"total": 100, "completed": 51, "failed": 0, "pending": 49}
3. Request.version = 11（乐观锁递增）

**说明**：
- 此测试验证乐观锁正常更新场景
- 真正的并发冲突测试需要更复杂的 mock 机制（如 mock DynamoDB 条件更新失败），属于高级测试场景

---

### 2.4 策略执行与状态记录

#### FP-COMP-009: 策略执行成功 - 结果正确保存

**测试目标**: `FrameProcessor.execute_policy()` - 策略执行与结果保存  
**测试层级**: Component Test  
**Mock**: DynamoDB (使用 moto), HTTP 请求 (使用 responses)  
**使用策略**: EmptyPolicy

**前置条件**：
- DynamoDB Request 表中有记录：
  ```json
  {
    "request_id": "test-123",
    "status": "running",
    "total_frames": 100,
    "frame_stats": {"total": 100, "completed": 50, "failed": 0, "pending": 50},
    "version": 1
  }
  ```
- DynamoDB Frame 表中无 frame_index=60 的记录
- Mock HTTP 返回测试图片数据
- 配置 `ENABLED_POLICIES=empty`

**输入 SQS 消息**：
```json
{
  "request_id": "test-123",
  "request_name": "test-video",
  "frame_index": 60,
  "target_frame_url": "https://example.com/frame-60.jpg",
  "before_frame_urls": [],
  "after_frame_urls": []
}
```

**验证点**：
1. Frame.status = "completed"
2. Frame.policy_status = {"empty": "completed"}
3. Frame.policy_results 包含策略结果：
   - empty_result = "static_value"
   - empty_frame_index = 60

**说明**：
- 此测试使用单策略验证策略执行和结果保存的核心逻辑
- 多策略场景的测试需要 mock Bedrock，可作为扩展测试

---

#### FP-COMP-010: 策略 shouldProcess 返回 False - 标记为 skipped

**测试目标**: `FrameProcessor.execute_policy()` - 策略跳过  
**测试层级**: Component Test  
**Mock**: DynamoDB (使用 moto), HTTP 请求 (使用 responses)  
**使用策略**: IntervalPolicy

**前置条件**：
- 配置 `ENABLED_POLICIES=interval`
- frame_index = 5（不是 10 的倍数，IntervalPolicy 会跳过）

**输入 SQS 消息**：frame_index = 5

**验证点**：
1. Frame.policy_status = {"interval": "skipped"}
2. Frame.policy_results 不包含 interval 策略的结果（无 interval_objects 字段）
3. Frame.status = "completed"
4. 不调用 IntervalPolicy 的 analyze 方法（不调用 Bedrock）

---

#### FP-COMP-011: 单策略成功 - Frame 标记为 completed

**测试目标**: `FrameProcessor.execute_policy()` - 策略成功场景  
**测试层级**: Component Test  
**Mock**: DynamoDB (使用 moto), HTTP 请求 (使用 responses)  
**使用策略**: EmptyPolicy

**前置条件**：
- DynamoDB Request 表中有记录：
  ```json
  {
    "request_id": "test-123",
    "status": "running",
    "total_frames": 100,
    "frame_stats": {"total": 100, "completed": 50, "failed": 0, "pending": 50},
    "version": 1
  }
  ```
- DynamoDB Frame 表中无 frame_index=60 的记录
- Mock HTTP 返回测试图片数据
- 配置 `ENABLED_POLICIES=empty`

**输入 SQS 消息**：
```json
{
  "request_id": "test-123",
  "request_name": "test-video",
  "frame_index": 60,
  "target_frame_url": "https://example.com/frame-60.jpg",
  "before_frame_urls": [],
  "after_frame_urls": []
}
```

**验证点**：
1. Frame.status = "completed"
2. Frame.policy_status = {"empty": "completed"}

**说明**：
- 此测试验证单策略成功时 Frame 正确标记为 completed
- 多策略部分失败场景需要 mock 多个策略，可作为扩展测试

---

#### FP-COMP-012: 策略执行失败 - Frame 标记为 failed

**测试目标**: `FrameProcessor.execute_policy()` - 策略失败场景  
**测试层级**: Component Test  
**Mock**: DynamoDB (使用 moto), HTTP 请求 (使用 responses)  
**使用策略**: EmptyPolicy（mock analyze 方法抛出异常）

**前置条件**：
- DynamoDB Request 表中有记录：
  ```json
  {
    "request_id": "test-123",
    "status": "running",
    "total_frames": 100,
    "frame_stats": {"total": 100, "completed": 50, "failed": 0, "pending": 50},
    "version": 1
  }
  ```
- DynamoDB Frame 表中无 frame_index=60 的记录
- Mock HTTP 返回测试图片数据
- Mock EmptyPolicy.analyze 抛出异常
- 配置 `ENABLED_POLICIES=empty`

**输入 SQS 消息**：
```json
{
  "request_id": "test-123",
  "request_name": "test-video",
  "frame_index": 60,
  "target_frame_url": "https://example.com/frame-60.jpg",
  "before_frame_urls": [],
  "after_frame_urls": []
}
```

**验证点**：
1. Frame.status = "failed"
2. Frame.policy_status = {"empty": "failed"}
3. Frame.policy_results = {}（空，因为策略失败）

**说明**：
- 此测试通过 mock 策略的 analyze 方法抛出异常来模拟策略失败
- 验证策略失败时 Frame 正确标记为 failed

---

### 2.5 上下文帧加载

#### FP-COMP-013: 正常加载前后上下文帧

**测试目标**: `FrameProcessor.handler()` - 上下文加载  
**测试层级**: Component Test  
**Mock**: DynamoDB (使用 moto), HTTP 请求 (使用 responses)  
**使用策略**: ContextAwarePolicy

**前置条件**：
- DynamoDB Request 表中有记录：
  ```json
  {
    "request_id": "test-req-013",
    "status": "running",
    "total_frames": 100,
    "frame_stats": {"total": 100, "completed": 50, "failed": 0, "pending": 50},
    "version": 1
  }
  ```
- DynamoDB Frame 表中无 frame_index=50 的记录
- Mock HTTP 为每个 URL 返回不同的图片数据
- 配置 `ENABLED_POLICIES=context_aware`

**输入 SQS 消息**：
```json
{
  "request_id": "test-req-013",
  "request_name": "test-video",
  "frame_index": 50,
  "target_frame_url": "https://example.com/frame-50.jpg",
  "before_frame_urls": ["https://example.com/frame-49.jpg", "https://example.com/frame-48.jpg"],
  "after_frame_urls": ["https://example.com/frame-51.jpg", "https://example.com/frame-52.jpg"]
}
```

**验证点**：
1. 发起 5 次 HTTP GET 请求（1 目标帧 + 2 前帧 + 2 后帧）
2. Frame.status = "completed"
3. Frame.policy_status = {"context_aware": "completed"}

---

#### FP-COMP-014: 跳过 null 的上下文帧（丢帧场景）

**测试目标**: `FrameProcessor.handler()` - 丢帧处理  
**测试层级**: Component Test  
**Mock**: DynamoDB (使用 moto), HTTP 请求 (使用 responses)  
**使用策略**: EmptyPolicy

**前置条件**：
- DynamoDB Request 表中有记录：
  ```json
  {
    "request_id": "test-req-014",
    "status": "running",
    "total_frames": 100,
    "frame_stats": {"total": 100, "completed": 50, "failed": 0, "pending": 50},
    "version": 1
  }
  ```
- DynamoDB Frame 表中无 frame_index=50 的记录
- Mock HTTP 返回测试图片数据
- 配置 `ENABLED_POLICIES=empty`

**输入 SQS 消息**：
```json
{
  "request_id": "test-req-014",
  "request_name": "test-video",
  "frame_index": 50,
  "target_frame_url": "https://example.com/frame-50.jpg",
  "before_frame_urls": ["https://example.com/frame-49.jpg", null, "https://example.com/frame-47.jpg"],
  "after_frame_urls": [null, "https://example.com/frame-52.jpg"]
}
```

**验证点**：
1. 发起 1 次 HTTP GET 请求（empty 策略 context_range=(0,0)，只下载目标帧）
2. Frame.status = "completed"

**说明**：
- EmptyPolicy 的 get_context_range 返回 (0, 0)，不需要上下文帧
- 因此即使 SQS 消息中包含上下文 URL，也不会下载

---

#### FP-COMP-015: 边界场景 - 第一帧（无前帧）

**测试目标**: `FrameProcessor.handler()` - 边界处理  
**测试层级**: Component Test  
**Mock**: DynamoDB (使用 moto), HTTP 请求 (使用 responses)  
**使用策略**: ContextAwarePolicy

**前置条件**：
- DynamoDB Request 表中有记录：
  ```json
  {
    "request_id": "test-req-015",
    "status": "running",
    "total_frames": 100,
    "frame_stats": {"total": 100, "completed": 0, "failed": 0, "pending": 100},
    "version": 1
  }
  ```
- DynamoDB Frame 表中无 frame_index=0 的记录
- Mock HTTP 返回测试图片数据
- 配置 `ENABLED_POLICIES=context_aware`

**输入 SQS 消息**：
```json
{
  "request_id": "test-req-015",
  "request_name": "test-video",
  "frame_index": 0,
  "target_frame_url": "https://example.com/frame-0.jpg",
  "before_frame_urls": [],
  "after_frame_urls": ["https://example.com/frame-1.jpg", "https://example.com/frame-2.jpg"]
}
```

**验证点**：
1. 发起 3 次 HTTP GET 请求（1 目标帧 + 2 后帧）
2. Frame.status = "completed"
3. Frame.policy_status = {"context_aware": "completed"}

---

#### FP-COMP-016: 边界场景 - 最后一帧（无后帧）

**测试目标**: `FrameProcessor.handler()` - 边界处理  
**测试层级**: Component Test  
**Mock**: DynamoDB (使用 moto), HTTP 请求 (使用 responses)  
**使用策略**: ContextAwarePolicy

**前置条件**：
- DynamoDB Request 表中有记录：
  ```json
  {
    "request_id": "test-req-016",
    "status": "running",
    "total_frames": 100,
    "frame_stats": {"total": 100, "completed": 98, "failed": 0, "pending": 2},
    "version": 1
  }
  ```
- DynamoDB Frame 表中无 frame_index=99 的记录
- Mock HTTP 返回测试图片数据
- 配置 `ENABLED_POLICIES=context_aware`

**输入 SQS 消息**：
```json
{
  "request_id": "test-req-016",
  "request_name": "test-video",
  "frame_index": 99,
  "target_frame_url": "https://example.com/frame-99.jpg",
  "before_frame_urls": ["https://example.com/frame-98.jpg", "https://example.com/frame-97.jpg"],
  "after_frame_urls": []
}
```

**验证点**：
1. 发起 3 次 HTTP GET 请求（1 目标帧 + 2 前帧）
2. Frame.status = "completed"
3. Frame.policy_status = {"context_aware": "completed"}

---

#### FP-COMP-017: 极端场景 - 孤立帧（无上下文）

**测试目标**: `FrameProcessor.handler()` - 极端处理  
**测试层级**: Component Test  
**Mock**: DynamoDB (使用 moto), HTTP 请求 (使用 responses)  
**使用策略**: ContextAwarePolicy

**前置条件**：
- DynamoDB Request 表中有记录（单帧视频）：
  ```json
  {
    "request_id": "test-req-017",
    "status": "pending",
    "total_frames": 1,
    "frame_stats": {"total": 1, "completed": 0, "failed": 0, "pending": 1},
    "version": 1
  }
  ```
- DynamoDB Frame 表中无 frame_index=0 的记录
- Mock HTTP 返回测试图片数据
- 配置 `ENABLED_POLICIES=context_aware`

**输入 SQS 消息**：
```json
{
  "request_id": "test-req-017",
  "request_name": "test-video",
  "frame_index": 0,
  "target_frame_url": "https://example.com/frame-0.jpg",
  "before_frame_urls": [],
  "after_frame_urls": []
}
```

**验证点**：
1. 发起 1 次 HTTP GET 请求（仅目标帧）
2. Frame.status = "completed"
3. Frame.policy_status = {"context_aware": "completed"}

---

### 2.6 完成检测与触发

#### FP-COMP-018: 最后一帧完成 - 触发 Completion Handler

**测试目标**: `FrameProcessor.check_all_frames_completed()` + `trigger_completion_handler()` - 完成检测  
**测试层级**: Component Test  
**Mock**: DynamoDB (使用 moto), HTTP 请求 (使用 responses), Lambda (使用 moto)  
**使用策略**: EmptyPolicy

**前置条件**：
- DynamoDB Request 表中有记录：
  ```json
  {
    "request_id": "test-req-018",
    "status": "running",
    "total_frames": 100,
    "frame_stats": {"total": 100, "completed": 99, "failed": 0, "pending": 1},
    "version": 99
  }
  ```
- DynamoDB Frame 表中无 frame_index=99 的记录
- Mock HTTP 返回测试图片数据
- 配置 `ENABLED_POLICIES=empty`
- 配置 `COMPLETION_HANDLER_NAME=completion-handler`

**输入 SQS 消息**：
```json
{
  "request_id": "test-req-018",
  "request_name": "test-video",
  "frame_index": 99,
  "target_frame_url": "https://example.com/frame-99.jpg",
  "before_frame_urls": [],
  "after_frame_urls": []
}
```

**验证点**：
1. Request.frame_stats = {"total": 100, "completed": 100, "failed": 0, "pending": 0}
2. Lambda invoke 被调用，FunctionName = "completion-handler"
3. Lambda invoke 的 Payload 包含 request_id = "test-req-018"
4. Lambda invoke 的 InvocationType = "Event"（异步调用）

---

#### FP-COMP-019: 非最后一帧 - 不触发 Completion Handler

**测试目标**: `FrameProcessor.check_all_frames_completed()` - 未完成检测  
**测试层级**: Component Test  
**Mock**: DynamoDB (使用 moto), HTTP 请求 (使用 responses), Lambda (使用 moto)  
**使用策略**: EmptyPolicy

**前置条件**：
- DynamoDB Request 表中有记录：
  ```json
  {
    "request_id": "test-req-019",
    "status": "running",
    "total_frames": 100,
    "frame_stats": {"total": 100, "completed": 50, "failed": 0, "pending": 50},
    "version": 50
  }
  ```
- DynamoDB Frame 表中无 frame_index=60 的记录
- Mock HTTP 返回测试图片数据
- 配置 `ENABLED_POLICIES=empty`
- 配置 `COMPLETION_HANDLER_NAME=completion-handler`

**输入 SQS 消息**：
```json
{
  "request_id": "test-req-019",
  "request_name": "test-video",
  "frame_index": 60,
  "target_frame_url": "https://example.com/frame-60.jpg",
  "before_frame_urls": [],
  "after_frame_urls": []
}
```

**验证点**：
1. Request.frame_stats = {"total": 100, "completed": 51, "failed": 0, "pending": 49}
2. Lambda invoke 未被调用（不触发 Completion Handler）

---

#### FP-COMP-020: 最后一帧失败 - 仍触发 Completion Handler

**测试目标**: `FrameProcessor.check_all_frames_completed()` + `trigger_completion_handler()` - 失败完成  
**测试层级**: Component Test  
**Mock**: DynamoDB (使用 moto), HTTP 请求 (使用 responses), Lambda (使用 moto)  
**使用策略**: EmptyPolicy

**前置条件**：
- DynamoDB Request 表中有记录：
  ```json
  {
    "request_id": "test-req-020",
    "status": "running",
    "total_frames": 100,
    "frame_stats": {"total": 100, "completed": 90, "failed": 9, "pending": 1},
    "version": 99
  }
  ```
- DynamoDB Frame 表中无 frame_index=99 的记录
- Mock HTTP 返回 500 错误（导致帧处理失败）
- 配置 `ENABLED_POLICIES=empty`
- 配置 `COMPLETION_HANDLER_NAME=completion-handler`

**输入 SQS 消息**：
```json
{
  "request_id": "test-req-020",
  "request_name": "test-video",
  "frame_index": 99,
  "target_frame_url": "https://example.com/frame-99.jpg",
  "before_frame_urls": [],
  "after_frame_urls": []
}
```

**验证点**：
1. Frame.status = "failed"
2. Frame.policy_status = {"empty": "failed"}
3. Request.frame_stats = {"total": 100, "completed": 90, "failed": 10, "pending": 0}
4. Lambda invoke 被调用（即使最后一帧失败，仍触发 Completion Handler）
5. Lambda invoke 的 Payload 包含 request_id = "test-req-020"

---

### 2.7 错误处理

#### FP-COMP-021: HTTP 下载失败 - Frame 标记为 failed

**测试目标**: `FrameProcessor.handler()` - 下载错误处理  
**测试层级**: Component Test  
**Mock**: DynamoDB (使用 moto), HTTP 请求 (使用 responses)  
**使用策略**: EmptyPolicy

**前置条件**：
- DynamoDB Request 表中有记录：
  ```json
  {
    "request_id": "test-req-021",
    "status": "running",
    "total_frames": 100,
    "frame_stats": {"total": 100, "completed": 50, "failed": 5, "pending": 45},
    "version": 10
  }
  ```
- DynamoDB Frame 表中无 frame_index=70 的记录
- Mock HTTP 返回 404 错误
- 配置 `ENABLED_POLICIES=empty`

**输入 SQS 消息**：
```json
{
  "request_id": "test-req-021",
  "request_name": "test-video",
  "frame_index": 70,
  "target_frame_url": "https://example.com/frame-70.jpg",
  "before_frame_urls": [],
  "after_frame_urls": []
}
```

**验证点**：
1. Frame 记录被创建：
   - request_id = "test-req-021"
   - frame_index = 70
   - status = "failed"
   - policy_status = {"empty": "failed"}
2. Request.frame_stats = {"total": 100, "completed": 50, "failed": 6, "pending": 44}
3. 不抛出异常（HTTP 错误被捕获）

---

#### FP-COMP-022: Request 不存在 - 记录错误并跳过

**测试目标**: `FrameProcessor.handler()` - Request 不存在  
**测试层级**: Component Test  
**Mock**: DynamoDB (使用 moto)  
**使用策略**: EmptyPolicy

**前置条件**：
- DynamoDB Request 表中无对应记录
- DynamoDB Frame 表为空
- 配置 `ENABLED_POLICIES=empty`

**输入 SQS 消息**：
```json
{
  "request_id": "non-existent-request",
  "request_name": "test-video",
  "frame_index": 0,
  "target_frame_url": "https://example.com/frame-0.jpg",
  "before_frame_urls": [],
  "after_frame_urls": []
}
```

**验证点**：
1. 不创建 Frame 记录
2. 不发起 HTTP 请求
3. 不抛出异常（避免 SQS 无限重试）

---

### 2.8 多策略场景

#### FP-COMP-023: 多策略结果合并 - key-value 正确合并

**测试目标**: `FrameProcessor.merge_policy_results()` - 多策略结果合并  
**测试层级**: Component Test  
**Mock**: DynamoDB (使用 moto), HTTP 请求 (使用 responses)  
**使用策略**: EmptyPolicy + IntervalPolicy（mock Bedrock）

**前置条件**：
- DynamoDB Request 表中有记录：
  ```json
  {
    "request_id": "test-req-023",
    "status": "running",
    "total_frames": 100,
    "frame_stats": {"total": 100, "completed": 50, "failed": 0, "pending": 50},
    "version": 1
  }
  ```
- DynamoDB Frame 表中无 frame_index=10 的记录
- Mock HTTP 返回测试图片数据
- Mock IntervalPolicy 的 Bedrock 调用返回 `{"interval_objects": ["cup", "person"]}`
- 配置 `ENABLED_POLICIES=empty,interval`
- frame_index = 10（是 10 的倍数，IntervalPolicy 会处理）

**输入 SQS 消息**：
```json
{
  "request_id": "test-req-023",
  "request_name": "test-video",
  "frame_index": 10,
  "target_frame_url": "https://example.com/frame-10.jpg",
  "before_frame_urls": [],
  "after_frame_urls": []
}
```

**验证点**：
1. Frame.status = "completed"
2. Frame.policy_status = {"empty": "completed", "interval": "completed"}
3. Frame.policy_results 包含两个策略的结果合并：
   - empty_result = "static_value"
   - empty_frame_index = 10
   - interval_objects = ["cup", "person"]

---

#### FP-COMP-024: 多策略部分成功部分失败 - 保留成功策略结果

**测试目标**: `FrameProcessor.execute_policy()` - 多策略部分失败  
**测试层级**: Component Test  
**Mock**: DynamoDB (使用 moto), HTTP 请求 (使用 responses)  
**使用策略**: EmptyPolicy + FailingPolicy

**前置条件**：
- DynamoDB Request 表中有记录：
  ```json
  {
    "request_id": "test-req-024",
    "status": "running",
    "total_frames": 100,
    "frame_stats": {"total": 100, "completed": 50, "failed": 0, "pending": 50},
    "version": 1
  }
  ```
- DynamoDB Frame 表中无 frame_index=60 的记录
- Mock HTTP 返回测试图片数据
- 配置 `ENABLED_POLICIES=empty,failing`

**输入 SQS 消息**：
```json
{
  "request_id": "test-req-024",
  "request_name": "test-video",
  "frame_index": 60,
  "target_frame_url": "https://example.com/frame-60.jpg",
  "before_frame_urls": [],
  "after_frame_urls": []
}
```

**验证点**：
1. Frame.status = "failed"（因为有策略失败）
2. Frame.policy_status = {"empty": "completed", "failing": "failed"}
3. Frame.policy_results 包含成功策略的结果：
   - empty_result = "static_value"
   - empty_frame_index = 60
   - 不包含 failing 策略的任何 key

---

### 2.9 乐观锁并发处理

#### FP-COMP-025: 乐观锁冲突重试 - 更新 frame_stats

**测试目标**: `FrameProcessor.update_frame_stats()` - 乐观锁冲突重试  
**测试层级**: Component Test  
**Mock**: DynamoDB (使用 moto，mock 条件更新失败), HTTP 请求 (使用 responses)  
**使用策略**: EmptyPolicy

**前置条件**：
- DynamoDB Request 表中有记录：
  ```json
  {
    "request_id": "test-req-025",
    "status": "running",
    "total_frames": 100,
    "frame_stats": {"total": 100, "completed": 50, "failed": 0, "pending": 50},
    "version": 10
  }
  ```
- DynamoDB Frame 表中无 frame_index=60 的记录
- Mock HTTP 返回测试图片数据
- 配置 `ENABLED_POLICIES=empty`

**Mock 设置**：
```python
from botocore.exceptions import ClientError

# Mock DynamoDB 条件更新：第一次失败（ConditionalCheckFailedException），第二次成功
mock_update_item_responses = [
    ClientError(
        {'Error': {'Code': 'ConditionalCheckFailedException', 'Message': 'Version mismatch'}},
        'UpdateItem'
    ),
    {'Attributes': {'version': {'N': '12'}}}  # 第二次成功
]
```

**输入 SQS 消息**：
```json
{
  "request_id": "test-req-025",
  "request_name": "test-video",
  "frame_index": 60,
  "target_frame_url": "https://example.com/frame-60.jpg",
  "before_frame_urls": [],
  "after_frame_urls": []
}
```

**验证点**：
1. Frame.status = "completed"
2. DynamoDB update_item 被调用 2 次（第一次失败，第二次成功）
3. 最终 Request.frame_stats 正确更新
4. 不抛出异常

**说明**：
- 此测试通过 mock DynamoDB 的 update_item 方法，模拟第一次条件更新失败（版本冲突），第二次成功
- 验证代码的乐观锁重试逻辑是否正确实现

---

### 2.10 HTTP 错误场景

#### FP-COMP-026: HTTP 连接超时 - Frame 标记为 failed

**测试目标**: `FrameProcessor.handler()` - HTTP 超时处理  
**测试层级**: Component Test  
**Mock**: DynamoDB (使用 moto), HTTP 请求 (使用 responses)  
**使用策略**: EmptyPolicy

**前置条件**：
- DynamoDB Request 表中有记录：
  ```json
  {
    "request_id": "test-req-026",
    "status": "running",
    "total_frames": 100,
    "frame_stats": {"total": 100, "completed": 50, "failed": 5, "pending": 45},
    "version": 10
  }
  ```
- DynamoDB Frame 表中无 frame_index=70 的记录
- 配置 `ENABLED_POLICIES=empty`

**Mock 设置**：
```python
import responses
from requests.exceptions import Timeout

@responses.activate
def test_http_timeout():
    # Mock HTTP 请求超时
    responses.add(
        responses.GET,
        "https://example.com/frame-70.jpg",
        body=Timeout("Connection timed out")
    )
```

**输入 SQS 消息**：
```json
{
  "request_id": "test-req-026",
  "request_name": "test-video",
  "frame_index": 70,
  "target_frame_url": "https://example.com/frame-70.jpg",
  "before_frame_urls": [],
  "after_frame_urls": []
}
```

**验证点**：
1. Frame 记录被创建：
   - request_id = "test-req-026"
   - frame_index = 70
   - status = "failed"
   - policy_status = {"empty": "failed"}
2. Request.frame_stats = {"total": 100, "completed": 50, "failed": 6, "pending": 44}
3. 不抛出异常（超时错误被捕获）

---

### 2.11 配置错误场景

#### FP-COMP-027: ENABLED_POLICIES 为空 - 跳过策略执行

**测试目标**: `FrameProcessor.handler()` - 空策略配置  
**测试层级**: Component Test  
**Mock**: DynamoDB (使用 moto), HTTP 请求 (使用 responses)

**前置条件**：
- DynamoDB Request 表中有记录：
  ```json
  {
    "request_id": "test-req-027",
    "status": "running",
    "total_frames": 100,
    "frame_stats": {"total": 100, "completed": 50, "failed": 0, "pending": 50},
    "version": 1
  }
  ```
- DynamoDB Frame 表中无 frame_index=60 的记录
- Mock HTTP 返回测试图片数据
- 配置 `ENABLED_POLICIES=`（空字符串）或不设置

**输入 SQS 消息**：
```json
{
  "request_id": "test-req-027",
  "request_name": "test-video",
  "frame_index": 60,
  "target_frame_url": "https://example.com/frame-60.jpg",
  "before_frame_urls": [],
  "after_frame_urls": []
}
```

**验证点**：
1. Frame.status = "completed"（无策略执行，直接完成）
2. Frame.policy_status = {}（空）
3. Frame.policy_results = {}（空）
4. Request.frame_stats 正确更新

---

#### FP-COMP-028: 策略名不存在 - 记录错误并跳过该策略

**测试目标**: `FrameProcessor.handler()` - 无效策略名  
**测试层级**: Component Test  
**Mock**: DynamoDB (使用 moto), HTTP 请求 (使用 responses)

**前置条件**：
- DynamoDB Request 表中有记录：
  ```json
  {
    "request_id": "test-req-028",
    "status": "running",
    "total_frames": 100,
    "frame_stats": {"total": 100, "completed": 50, "failed": 0, "pending": 50},
    "version": 1
  }
  ```
- DynamoDB Frame 表中无 frame_index=60 的记录
- Mock HTTP 返回测试图片数据
- 配置 `ENABLED_POLICIES=empty,non_existent_policy`

**输入 SQS 消息**：
```json
{
  "request_id": "test-req-028",
  "request_name": "test-video",
  "frame_index": 60,
  "target_frame_url": "https://example.com/frame-60.jpg",
  "before_frame_urls": [],
  "after_frame_urls": []
}
```

**验证点**：
1. Frame.status = "completed"（有效策略执行成功）
2. Frame.policy_status = {"empty": "completed", "non_existent_policy": "failed"}
3. Frame.policy_results 包含 empty 策略的结果：
   - empty_result = "static_value"
   - empty_frame_index = 60
4. 日志中记录策略加载失败的警告

---

## 测试覆盖总结

| 类别 | 测试用例数 | 覆盖内容 |
|------|-----------|---------|
| Layer 1: 消息解析 | 4 | SQS 消息格式验证、错误处理 |
| Layer 2: Frame 记录管理 | 3 | 创建、幂等性、重试 |
| Layer 2: Request 状态转换 | 2 | pending→running、状态保持 |
| Layer 2: frame_stats 统计 | 3 | completed/failed 递增、乐观锁 |
| Layer 2: 策略执行 | 4 | 成功、跳过、失败 |
| Layer 2: 上下文帧加载 | 5 | 正常、丢帧、边界场景 |
| Layer 2: 完成检测 | 3 | 触发/不触发 Completion Handler |
| Layer 2: 错误处理 | 2 | HTTP 失败、Request 不存在 |
| Layer 2: 多策略场景 | 2 | 结果合并、部分成功部分失败 |
| Layer 2: 乐观锁并发处理 | 1 | 冲突重试 |
| Layer 2: HTTP 错误场景 | 1 | 连接超时 |
| Layer 2: 配置错误场景 | 2 | 空策略、无效策略名 |

**总计**: 32 个测试用例

## 附录：测试策略

测试中使用专门的测试策略，详见 [tech.md - 测试策略](../../.kiro/steering/tech.md#测试策略)。

### 测试策略概览

| 策略类 | get_name() | should_process | get_context_range | 调用 Bedrock | 用途 |
|--------|------------|----------------|-------------------|-------------|------|
| EmptyPolicy | `'empty'` | 总是 True | (0, 0) | 否 | 验证框架逻辑，返回静态数据 |
| FailingPolicy | `'failing'` | 总是 True | (0, 0) | 否 | 验证策略失败场景，总是抛出异常 |

测试中如需使用业务策略（IntervalPolicy、ContextAwarePolicy），需要 mock Bedrock 调用。

### 测试配置示例

```python
import os

# 单策略测试（推荐用于大多数组件测试）
os.environ['ENABLED_POLICIES'] = 'empty'

# 多策略测试
os.environ['ENABLED_POLICIES'] = 'empty,interval'

# 验证跳过逻辑
os.environ['ENABLED_POLICIES'] = 'interval'  # frame_index=5 时会跳过

# 验证上下文加载
os.environ['ENABLED_POLICIES'] = 'context_aware'  # 需要 mock bedrock_client

# 验证策略失败场景
os.environ['ENABLED_POLICIES'] = 'failing'  # 总是抛出异常

# 验证多策略部分成功部分失败
os.environ['ENABLED_POLICIES'] = 'empty,failing'  # empty 成功，failing 失败
```

### Mock Bedrock 示例

对于需要调用 Bedrock 的策略（interval、context_aware），使用 unittest.mock：

```python
from unittest.mock import patch, MagicMock

# Mock bedrock_client.invoke 返回固定结果
mock_bedrock = MagicMock()
mock_bedrock.invoke.return_value = {
    'output': {'message': {'content': [{'text': '{"objects": ["cup", "person"]}'}]}}
}

with patch('lambda.handlers.frame_processor.bedrock_client', mock_bedrock):
    result = frame_processor.handler(event, {})

# 验证 Bedrock 被调用
mock_bedrock.invoke.assert_called_once()
```

### EmptyPolicy 返回结果

EmptyPolicy 不调用 Bedrock，返回固定结果：

```python
{
    'empty_result': 'static_value',
    'empty_frame_index': <frame_index>  # 当前帧索引
}
```

### FailingPolicy 行为

FailingPolicy 不调用 Bedrock，总是抛出 RuntimeError：

```python
raise RuntimeError(f"FailingPolicy intentionally failed for frame {frame_index}")
```

用于测试：
- 单策略失败场景
- 多策略部分成功部分失败场景
- 策略异常处理逻辑
