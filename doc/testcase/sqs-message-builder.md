# SQS Message Builder 测试用例

## 概述

SQS Message Builder 负责构造 Frame 处理所需的 SQS 消息，包含目标帧和上下文帧的 URL 信息。

**核心组件**：
- `SQSMessageBuilder.build_frame_message()` - 单个消息构造
- `SQSMessageBuilder.build_all_messages()` - 批量消息构造

---

## Layer 1: 单元测试

### 1.1 单个消息构造测试

#### MSG-001: 视频中间帧（完整上下文）

**测试目标**: `SQSMessageBuilder.build_frame_message()` - 正常场景  
**测试层级**: Unit Test  
**Mock**: 无需 AWS 服务

**输入**：
- request_id = "test-123"
- request_name = "test-video"
- frame_index = 50
- total_frames = 100
- frame_urls = ["url-0", "url-1", ..., "url-99"]（100 个 URL）
- protocol = "s3"
- CONTEXT_MAX_FRAMES = 60

**预期结果**：
```json
{
  "request_id": "test-123",
  "request_name": "test-video",
  "frame_index": 50,
  "protocol": "s3",
  "target_frame_url": "url-50",
  "before_frame_urls": ["url-49", "url-48", ..., "url-0"],
  "after_frame_urls": ["url-51", "url-52", ..., "url-99"]
}
```

**验证点**：
- `target_frame_url` = "url-50"
- `before_frame_urls` 长度为 50（实际可用帧数，小于 CONTEXT_MAX_FRAMES）
- `after_frame_urls` 长度为 49（实际可用帧数）
- `before_frame_urls[0]` = "url-49"（紧邻的前一帧）
- `after_frame_urls[0]` = "url-51"（紧邻的后一帧）

---

#### MSG-002: 视频第一帧（有后帧无前帧）

**测试目标**: `SQSMessageBuilder.build_frame_message()` - 边界场景（第一帧）  
**测试层级**: Unit Test  
**Mock**: 无需 AWS 服务

**输入**：
- request_id = "test-123"
- request_name = "test-video"
- frame_index = 0
- total_frames = 100
- frame_urls = ["url-0", "url-1", ..., "url-99"]
- protocol = "http"

**预期结果**：
```json
{
  "request_id": "test-123",
  "request_name": "test-video",
  "frame_index": 0,
  "protocol": "http",
  "target_frame_url": "url-0",
  "before_frame_urls": [],
  "after_frame_urls": ["url-1", "url-2", ..., "url-60"]
}
```

**验证点**：
- `before_frame_urls` 为空数组
- `after_frame_urls` 长度为 60（CONTEXT_MAX_FRAMES）
- `after_frame_urls[0]` = "url-1"

---

#### MSG-003: 视频最后一帧（有前帧无后帧）

**测试目标**: `SQSMessageBuilder.build_frame_message()` - 边界场景（最后一帧）  
**测试层级**: Unit Test  
**Mock**: 无需 AWS 服务

**输入**：
- request_id = "test-123"
- request_name = "test-video"
- frame_index = 99
- total_frames = 100
- frame_urls = ["url-0", "url-1", ..., "url-99"]
- protocol = "s3"

**预期结果**：
```json
{
  "request_id": "test-123",
  "request_name": "test-video",
  "frame_index": 99,
  "protocol": "s3",
  "target_frame_url": "url-99",
  "before_frame_urls": ["url-98", "url-97", ..., "url-39"],
  "after_frame_urls": []
}
```

**验证点**：
- `before_frame_urls` 长度为 60（CONTEXT_MAX_FRAMES）
- `after_frame_urls` 为空数组
- `before_frame_urls[0]` = "url-98"（紧邻的前一帧）

---

#### MSG-004: 相邻帧丢失（null 占位）

**测试目标**: `SQSMessageBuilder.build_frame_message()` - 容错场景（丢帧）  
**测试层级**: Unit Test  
**Mock**: 无需 AWS 服务

**输入**：
- request_id = "test-123"
- request_name = "test-video"
- frame_index = 50
- total_frames = 100
- frame_urls = ["url-0", ..., "url-48", null, "url-50", null, "url-52", ..., "url-99"]
  - frame 49 缺失
  - frame 51 缺失
- protocol = "s3"

**预期结果**：
```json
{
  "frame_index": 50,
  "target_frame_url": "url-50",
  "before_frame_urls": [null, "url-48", "url-47", ...],
  "after_frame_urls": [null, "url-52", "url-53", ...]
}
```

**验证点**：
- `before_frame_urls[0]` = `null`（frame 49 缺失）
- `after_frame_urls[0]` = `null`（frame 51 缺失）
- 数组长度不变，用 null 占位
- 缺失帧不影响其他帧的位置

---

#### MSG-005: 小视频（前后各 3 帧）

**测试目标**: `SQSMessageBuilder.build_frame_message()` - 小范围上下文  
**测试层级**: Unit Test  
**Mock**: 无需 AWS 服务

**输入**：
- request_id = "test-123"
- request_name = "test-video"
- frame_index = 3
- total_frames = 7
- frame_urls = ["url-0", "url-1", "url-2", "url-3", "url-4", "url-5", "url-6"]
- protocol = "http"
- CONTEXT_MAX_FRAMES = 60

**预期结果**：
```json
{
  "frame_index": 3,
  "target_frame_url": "url-3",
  "before_frame_urls": ["url-2", "url-1", "url-0"],
  "after_frame_urls": ["url-4", "url-5", "url-6"]
}
```

**验证点**：
- `before_frame_urls` 长度为 3（实际可用帧数 < CONTEXT_MAX_FRAMES）
- `after_frame_urls` 长度为 3（实际可用帧数 < CONTEXT_MAX_FRAMES）
- 不会超出视频范围

---

#### MSG-006: 孤立帧（无上下文）

**测试目标**: `SQSMessageBuilder.build_frame_message()` - 极端场景（单帧视频）  
**测试层级**: Unit Test  
**Mock**: 无需 AWS 服务

**输入**：
- request_id = "test-123"
- request_name = "test-video"
- frame_index = 0
- total_frames = 1
- frame_urls = ["url-0"]
- protocol = "http"

**预期结果**：
```json
{
  "request_id": "test-123",
  "request_name": "test-video",
  "frame_index": 0,
  "protocol": "http",
  "target_frame_url": "url-0",
  "before_frame_urls": [],
  "after_frame_urls": []
}
```

**验证点**：
- `before_frame_urls` 为空数组
- `after_frame_urls` 为空数组
- 只有目标帧本身

---

#### MSG-007: 大视频中间帧（完整 60 帧上下文）

**测试目标**: `SQSMessageBuilder.build_frame_message()` - 大视频场景  
**测试层级**: Unit Test  
**Mock**: 无需 AWS 服务

**输入**：
- request_id = "test-123"
- request_name = "test-video"
- frame_index = 500
- total_frames = 1000
- frame_urls = ["url-0", "url-1", ..., "url-999"]（1000 个 URL）
- protocol = "s3"
- CONTEXT_MAX_FRAMES = 60

**预期结果**：
```json
{
  "frame_index": 500,
  "target_frame_url": "url-500",
  "before_frame_urls": ["url-499", "url-498", ..., "url-440"],
  "after_frame_urls": ["url-501", "url-502", ..., "url-560"]
}
```

**验证点**：
- `before_frame_urls` 长度正好为 60
- `after_frame_urls` 长度正好为 60
- `before_frame_urls[59]` = "url-440"
- `after_frame_urls[59]` = "url-560"

---

### 1.2 批量消息构造测试

#### MSG-008: 批量消息构造（正常场景）

**测试目标**: `SQSMessageBuilder.build_all_messages()` - 正常场景  
**测试层级**: Unit Test  
**Mock**: 无需 AWS 服务

**输入**：
- request_id = "test-123"
- request_name = "test-video"
- frame_urls = ["url-0", "url-1", "url-2", "url-3", "url-4"]
- protocol = "s3"

**预期结果**：
- 返回 5 条消息
- 消息 0: frame_index=0, target_frame_url="url-0"
- 消息 1: frame_index=1, target_frame_url="url-1"
- 消息 2: frame_index=2, target_frame_url="url-2"
- 消息 3: frame_index=3, target_frame_url="url-3"
- 消息 4: frame_index=4, target_frame_url="url-4"

**验证点**：
- 消息数量 = 5
- 每条消息的 frame_index 正确
- 每条消息的 protocol = "s3"
- 每条消息都包含完整的上下文 URL

---

#### MSG-009: 批量消息构造（跳过缺失帧）

**测试目标**: `SQSMessageBuilder.build_all_messages()` - 容错场景（丢帧）  
**测试层级**: Unit Test  
**Mock**: 无需 AWS 服务

**输入**：
- request_id = "test-123"
- request_name = "test-video"
- frame_urls = ["url-0", "url-1", null, "url-3", "url-4"]
  - frame 2 缺失
- protocol = "http"

**预期结果**：
- 返回 4 条消息（跳过 frame 2）
- 消息 0: frame_index=0
- 消息 1: frame_index=1
- 消息 2: frame_index=3（跳过了 2）
- 消息 3: frame_index=4

**验证点**：
- 消息数量 = 4（不包含缺失帧）
- 不为 null 帧生成消息
- 其他帧的上下文中包含 null 占位

---

#### MSG-010: 批量消息构造（多个连续缺失帧）

**测试目标**: `SQSMessageBuilder.build_all_messages()` - 容错场景（连续丢帧）  
**测试层级**: Unit Test  
**Mock**: 无需 AWS 服务

**输入**：
- request_id = "test-123"
- request_name = "test-video"
- frame_urls = ["url-0", null, null, null, "url-4", "url-5"]
  - frame 1, 2, 3 连续缺失
- protocol = "s3"

**预期结果**：
- 返回 3 条消息
- 消息 0: frame_index=0, after_frame_urls=[null, null, null, "url-4", "url-5"]
- 消息 1: frame_index=4, before_frame_urls=[null, null, null, "url-0"]
- 消息 2: frame_index=5

**验证点**：
- 消息数量 = 3
- 连续缺失帧在上下文中正确用 null 占位

---

#### MSG-011: 批量消息构造（空列表）

**测试目标**: `SQSMessageBuilder.build_all_messages()` - 边界场景（空列表）  
**测试层级**: Unit Test  
**Mock**: 无需 AWS 服务

**输入**：
- request_id = "test-123"
- request_name = "test-video"
- frame_urls = []
- protocol = "s3"

**预期结果**：
- 返回空数组 `[]`

**验证点**：
- 不抛出异常
- 返回空数组

---

#### MSG-012: 批量消息构造（全部缺失）

**测试目标**: `SQSMessageBuilder.build_all_messages()` - 极端场景（全部缺失）  
**测试层级**: Unit Test  
**Mock**: 无需 AWS 服务

**输入**：
- request_id = "test-123"
- request_name = "test-video"
- frame_urls = [null, null, null]
- protocol = "s3"

**预期结果**：
- 返回空数组 `[]`

**验证点**：
- 不抛出异常
- 返回空数组（没有有效帧可处理）
