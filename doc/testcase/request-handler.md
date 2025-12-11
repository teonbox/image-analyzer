# Request Handler 测试用例

## 概述

Request Handler 负责接收用户请求，验证参数，创建 Request 记录，并触发 Frame 消息发送。

**核心组件**：
- `validate_request_input()` - 参数验证
- `handler()` - Lambda 入口函数

---

## Layer 1: 单元测试

### 1.1 参数验证测试

#### REQ-001: 缺少必需字段 - name

**测试目标**: `validate_request_input()` - 缺少 name 字段  
**测试层级**: Unit Test  
**Mock**: 无需 AWS 服务

**输入**：
```json
{
  "type": "s3",
  "bucket": "my-bucket",
  "region": "us-east-1",
  "callback_url": "https://example.com/callback"
}
```

**预期结果**：
- 返回 `(False, "Missing required field: name")`

---

#### REQ-002: 缺少必需字段 - callback_url

**测试目标**: `validate_request_input()` - 缺少 callback_url 字段  
**测试层级**: Unit Test  
**Mock**: 无需 AWS 服务

**输入**：
```json
{
  "type": "s3",
  "bucket": "my-bucket",
  "region": "us-east-1",
  "name": "test-video"
}
```

**预期结果**：
- 返回 `(False, "Missing required field: callback_url")`

---

#### REQ-003: 无效的存储类型

**测试目标**: `validate_request_input()` - 无效的 type 值  
**测试层级**: Unit Test  
**Mock**: 无需 AWS 服务

**输入**：
```json
{
  "type": "invalid_type",
  "name": "test",
  "callback_url": "https://example.com/callback"
}
```

**预期结果**：
- 返回 `(False, "Invalid type: invalid_type. Must be s3, oss, or url_list")`

---

#### REQ-004: S3 类型缺少 bucket

**测试目标**: `validate_request_input()` - S3 类型缺少必需字段  
**测试层级**: Unit Test  
**Mock**: 无需 AWS 服务

**输入**：
```json
{
  "type": "s3",
  "region": "us-east-1",
  "name": "test-video",
  "callback_url": "https://example.com/callback"
}
```

**预期结果**：
- 返回 `(False, "Missing required field for s3: bucket")`

---

#### REQ-005: S3 类型缺少 region

**测试目标**: `validate_request_input()` - S3 类型缺少 region  
**测试层级**: Unit Test  
**Mock**: 无需 AWS 服务

**输入**：
```json
{
  "type": "s3",
  "bucket": "my-bucket",
  "name": "test-video",
  "callback_url": "https://example.com/callback"
}
```

**预期结果**：
- 返回 `(False, "Missing required field for s3: region")`

---

#### REQ-006: url_list 类型缺少 urls

**测试目标**: `validate_request_input()` - url_list 类型缺少必需字段  
**测试层级**: Unit Test  
**Mock**: 无需 AWS 服务

**输入**：
```json
{
  "type": "url_list",
  "name": "test-video",
  "callback_url": "https://example.com/callback"
}
```

**预期结果**：
- 返回 `(False, "Missing required field for url_list: urls")`

---

#### REQ-007: url_list 类型 urls 为空数组

**测试目标**: `validate_request_input()` - urls 为空数组  
**测试层级**: Unit Test  
**Mock**: 无需 AWS 服务

**输入**：
```json
{
  "type": "url_list",
  "urls": [],
  "name": "test-video",
  "callback_url": "https://example.com/callback"
}
```

**预期结果**：
- 返回 `(False, "urls cannot be empty")`

---

#### REQ-008: 有效的 S3 请求参数

**测试目标**: `validate_request_input()` - 有效的 S3 请求  
**测试层级**: Unit Test  
**Mock**: 无需 AWS 服务

**输入**：
```json
{
  "type": "s3",
  "bucket": "my-bucket",
  "region": "ap-northeast-2",
  "name": "test-video",
  "callback_url": "https://example.com/callback"
}
```

**预期结果**：
- 返回 `(True, None)`

---

#### REQ-009: 有效的 url_list 请求参数

**测试目标**: `validate_request_input()` - 有效的 url_list 请求  
**测试层级**: Unit Test  
**Mock**: 无需 AWS 服务

**输入**：
```json
{
  "type": "url_list",
  "urls": ["https://example.com/frame-1.jpg", "https://example.com/frame-2.jpg"],
  "name": "test-video",
  "callback_url": "https://example.com/callback"
}
```

**预期结果**：
- 返回 `(True, None)`

---

## Layer 2: 组件测试

### 2.1 完整流程测试

#### REQ-COMP-001: S3 存储 - 完整流程

**测试目标**: `handler()` - 完整流程（S3 存储）  
**测试层级**: Component Test  
**Mock**: S3 (moto), DynamoDB (moto), SQS (moto)

**输入**：
```json
{
  "body": "{\"type\": \"s3\", \"bucket\": \"test-bucket\", \"prefix\": \"video/\", \"region\": \"us-east-1\", \"name\": \"test-video\", \"callback_url\": \"https://example.com/callback\"}"
}
```

**Mock 数据**：
- S3 bucket `test-bucket` 包含 5 个对象：
  - video/frame-001.jpg
  - video/frame-002.jpg
  - video/frame-003.jpg
  - video/frame-004.jpg
  - video/frame-005.jpg

**预期结果**：
1. 返回 200 状态码
2. 响应体：
   ```json
   {
     "success": true,
     "data": {
       "request_id": "<uuid>",
       "status": "pending",
       "total_frames": 5,
       "created_at": "<timestamp>"
     }
   }
   ```
3. DynamoDB Request 表创建记录：
   - request_id = 响应中的 request_id
   - status = "pending"
   - total_frames = 5
   - name = "test-video"
   - callback_url = "https://example.com/callback"
   - input_config 包含原始请求参数
4. SQS 发送 5 条消息

**验证点**：
- Request 记录正确创建
- SQS 消息数量 = 5
- 响应格式符合 API 规范

---

#### REQ-COMP-002: URL 列表 - 完整流程

**测试目标**: `handler()` - 完整流程（URL 列表）  
**测试层级**: Component Test  
**Mock**: DynamoDB (moto), SQS (moto)

**输入**：
```json
{
  "body": "{\"type\": \"url_list\", \"urls\": [\"https://example.com/frame-1.jpg\", \"https://example.com/frame-2.jpg\", \"https://example.com/frame-3.jpg\"], \"name\": \"test-video\", \"callback_url\": \"https://example.com/callback\"}"
}
```

**预期结果**：
1. 返回 200 状态码
2. DynamoDB Request 表创建记录：
   - total_frames = 3
   - input_config.type = "url_list"
3. SQS 发送 3 条消息
4. 每条消息的 protocol = "http"

**验证点**：
- URL 列表直接使用
- protocol 正确设置为 "http"

---

#### REQ-COMP-003: 空图片列表 - 错误处理

**测试目标**: `handler()` - 错误处理（S3 prefix 下无图片）  
**测试层级**: Component Test  
**Mock**: S3 (moto), DynamoDB (moto)

**输入**：
```json
{
  "body": "{\"type\": \"s3\", \"bucket\": \"test-bucket\", \"prefix\": \"empty/\", \"region\": \"us-east-1\", \"name\": \"test-video\", \"callback_url\": \"https://example.com/callback\"}"
}
```

**Mock 数据**：
- S3 bucket 存在但 `empty/` prefix 下无对象

**预期结果**：
1. 返回 400 状态码
2. 响应体：
   ```json
   {
     "success": false,
     "error": {
       "code": "EMPTY_IMAGE_LIST",
       "message": "No images found in the specified location"
     }
   }
   ```
3. 不创建 Request 记录
4. 不发送 SQS 消息

**验证点**：
- 正确检测空图片列表
- 不创建无效的 Request
- 错误响应格式正确

---

#### REQ-COMP-004: 参数验证失败 - 错误处理

**测试目标**: `handler()` - 错误处理（参数验证失败）  
**测试层级**: Component Test  
**Mock**: 无需 AWS 服务

**输入**：
```json
{
  "body": "{\"type\": \"invalid\", \"name\": \"test\", \"callback_url\": \"https://example.com\"}"
}
```

**预期结果**：
1. 返回 400 状态码
2. 响应体：
   ```json
   {
     "success": false,
     "error": {
       "code": "INVALID_FIELD_VALUE",
       "message": "Invalid type: invalid. Must be s3, oss, or url_list"
     }
   }
   ```

**验证点**：
- 参数验证在 AWS 调用之前执行
- 错误响应格式正确

---

#### REQ-COMP-005: 无效 JSON body - 错误处理

**测试目标**: `handler()` - 错误处理（JSON 解析失败）  
**测试层级**: Component Test  
**Mock**: 无需 AWS 服务

**输入**：
```json
{
  "body": "invalid json {"
}
```

**预期结果**：
1. 返回 400 状态码
2. 响应体：
   ```json
   {
     "success": false,
     "error": {
       "code": "INVALID_FIELD_VALUE",
       "message": "Invalid JSON in request body"
     }
   }
   ```

**验证点**：
- JSON 解析错误被正确捕获
- 返回友好的错误信息

---

## 测试数据准备

### Mock S3 数据

**需要准备**：
- Bucket: `test-bucket`
- Region: `us-east-1`
- 对象列表：
  - `video/frame-001.jpg`
  - `video/frame-002.jpg`
  - `video/frame-003.jpg`
  - `video/frame-004.jpg`
  - `video/frame-005.jpg`

### Mock DynamoDB 表

**需要准备**：
- 表名: `Request`
- 主键: `request_id` (String, HASH)
- GSI: `name-created_at-index`
- 计费模式: PAY_PER_REQUEST

### Mock SQS 队列

**需要准备**：
- 队列名: `frame-queue`
- Region: `us-east-1`
