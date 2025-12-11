# API 设计文档

## API 设计

### 1. 提交请求
```
POST /requests
Body: {
  "type": "url_list",
  "urls": ["https://...", "https://...", ...],
  "name": "my-video",
  "callback_url": "https://..."
}
Response: {request_id, status}
```

**输入类型：**
- **url_list**（当前支持）：直接提供图片 URL 列表
- **s3/oss**（未来支持）：提供存储桶信息，系统自动列出图片

**说明：**
- 当前版本只实现 `url_list` 类型
- 对 `s3`/`oss` 类型返回 "暂不支持" 错误
- 设计上预留了扩展性，未来可添加 S3/OSS 支持

### 2. 查询状态
```
GET /requests/{id_or_name}
Response: {request_id, name, status, progress, batches, multiple_requests}
```

**查询逻辑：**
- UUID 格式：按 request_id 查询
- 字符串：按 name 查询（GSI）
  - 单个匹配：返回结果
  - 多个匹配：返回最新的，设置 `multiple_requests: true`
  - 无匹配：404

### 3. 获取结果
```
GET /requests/{id_or_name}/results
Response: {
  request_id, 
  name, 
  status, 
  results,
  error_frames,
  result_s3_bucket,
  result_s3_key,
  result_presigned_url,
  result_url_expiration
}
```

**说明：**
- 每次调用此 API 都会生成新的预签名 URL（1天有效期）
- 建议用户使用 bucket 和 key 直接访问（长期有效）

### 4. 回调通知
```
POST {callback_url}
Body: {
  request_id, 
  name, 
  status, 
  statistics,
  result_s3_bucket,
  result_s3_key,
  result_presigned_url,
  result_url_expiration,
  note
}
```

**结果存储：**
- 完整结果保存到 S3（JSON 格式）
- 回调中提供预签名 URL（1天有效期）
- 建议用户使用 bucket 和 key 直接访问（长期有效）
- 每帧的结果格式：所有策略的 key-value 结果合并在一起
  ```json
  {
    "frame_index": 0,
    "frame_key": "video/frame-001.jpg",
    "status": "completed",
    "results": {
      "policy1_attr_a": "value_a",
      "policy1_attr_b": "value_b",
      "policy2_attr_c": "value_c"
    }
  }
  ```
- 策略应确保操作不同的 key，如果覆盖彼此的 key，那是策略的错误
- 如果帧部分完成（某些策略成功，某些失败），results 只包含成功策略的结果

## API 响应结构

### 成功响应格式

所有成功的 API 响应遵循统一格式：

```json
{
  "success": true,
  "data": {
    // 具体的响应数据
  }
}
```

**HTTP 状态码**: 200

### 错误响应格式

所有错误响应遵循统一格式：

```json
{
  "success": false,
  "error": {
    "code": "ERROR_CODE",
    "message": "人类可读的错误描述",
    "details": {
      // 可选的详细错误信息
    }
  }
}
```

### 错误码列表

#### 客户端错误（4xx）

| 错误码 | HTTP 状态码 | 说明 | 示例场景 |
|--------|------------|------|---------|
| `MISSING_REQUIRED_FIELD` | 400 | 缺少必需字段 | 请求体缺少 name 字段 |
| `INVALID_FIELD_VALUE` | 400 | 字段值无效 | type 字段值不是 s3 或 url_list |
| `INVALID_STORAGE_TYPE` | 400 | 不支持的存储类型 | storage.type 不是 s3 或 oss |
| `INVALID_FRAME_NAMING` | 400 | 图片命名格式错误 | 帧后缀不是数字 |
| `MULTIPLE_PREFIXES_DETECTED` | 400 | 检测到多个前缀 | 图片列表包含多个不同前缀 |
| `EMPTY_IMAGE_LIST` | 400 | 图片列表为空 | urls 数组为空或 bucket 中无图片 |
| `LIST_IMAGES_TIMEOUT` | 400 | 列出图片超时 | S3 ListObjects 超过 30 秒 |
| `REQUEST_NOT_FOUND` | 404 | 请求不存在 | 查询的 request_id 或 name 不存在 |
| `REQUEST_NOT_COMPLETED` | 400 | 请求未完成 | 尝试获取未完成请求的结果 |
| `UNAUTHORIZED` | 403 | 未授权 | 缺少或无效的 API Key |

#### 服务端错误（5xx）

| 错误码 | HTTP 状态码 | 说明 | 示例场景 |
|--------|------------|------|---------|
| `INTERNAL_ERROR` | 500 | 内部服务器错误 | 未预期的异常 |
| `DATABASE_ERROR` | 500 | 数据库操作失败 | DynamoDB 写入失败 |
| `STORAGE_ERROR` | 500 | 存储服务错误 | S3/OSS 访问失败 |
| `QUEUE_ERROR` | 500 | 队列服务错误 | SQS 发送消息失败 |
| `BEDROCK_ERROR` | 500 | Bedrock 调用失败 | 模型调用超时或限流 |
| `SERVICE_UNAVAILABLE` | 503 | 服务暂时不可用 | 依赖服务不可用 |

### API 响应示例

#### 1. 提交请求 - 成功

```json
{
  "success": true,
  "data": {
    "request_id": "abc-123-def-456",
    "status": "pending",
    "total_frames": 3600,
    "created_at": "2025-01-01T10:00:00Z"
  }
}
```

#### 2. 提交请求 - 失败（多个前缀）

```json
{
  "success": false,
  "error": {
    "code": "MULTIPLE_PREFIXES_DETECTED",
    "message": "检测到多个图片前缀，请确保所有图片使用相同的命名前缀",
    "details": {
      "detected_prefixes": ["video1/", "video2/"]
    }
  }
}
```

**HTTP 状态码**: 400

#### 3. 查询状态 - 成功

```json
{
  "success": true,
  "data": {
    "request_id": "abc-123-def-456",
    "name": "my-video-analysis",
    "status": "running",
    "total_frames": 3600,
    "frame_stats": {
      "total": 3600,
      "completed": 1200,
      "failed": 10,
      "pending": 2390
    },
    "progress": {
      "percentage": 33.6,
      "completed_rate": 33.3,
      "failed_rate": 0.3
    },
    "created_at": "2025-01-01T10:00:00Z",
    "last_activity_at": "2025-01-01T10:30:00Z"
  }
}
```

#### 4. 查询状态 - 失败（不存在）

```json
{
  "success": false,
  "error": {
    "code": "REQUEST_NOT_FOUND",
    "message": "未找到指定的请求",
    "details": {
      "id_or_name": "non-existent-request"
    }
  }
}
```

**HTTP 状态码**: 404

#### 5. 获取结果 - 成功

```json
{
  "success": true,
  "data": {
    "request_id": "abc-123-def-456",
    "name": "my-video-analysis",
    "status": "completed",
    "total_frames": 3600,
    "frame_stats": {
      "total": 3600,
      "completed": 3590,
      "failed": 10,
      "pending": 0
    },
    "result_s3_bucket": "my-results-bucket",
    "result_s3_key": "results/abc-123-def-456/result.json",
    "result_presigned_url": "https://s3.amazonaws.com/...",
    "result_url_expiration": "2025-01-02T10:00:00Z",
    "note": "预签名 URL 将在 1 天后过期，建议使用 result_s3_bucket 和 result_s3_key 直接访问以获得长期有效性"
  }
}
```

#### 6. 获取结果 - 失败（未完成）

```json
{
  "success": false,
  "error": {
    "code": "REQUEST_NOT_COMPLETED",
    "message": "请求尚未完成，无法获取结果",
    "details": {
      "request_id": "abc-123-def-456",
      "current_status": "running",
      "progress": 45.2
    }
  }
}
```

**HTTP 状态码**: 400

#### 7. 回调通知 - 成功

```json
{
  "request_id": "abc-123-def-456",
  "name": "my-video-analysis",
  "status": "completed",
  "statistics": {
    "total_frames": 3600,
    "completed_frames": 3590,
    "failed_frames": 10,
    "success_rate": 99.7
  },
  "result_s3_bucket": "my-results-bucket",
  "result_s3_key": "results/abc-123-def-456/result.json",
  "result_presigned_url": "https://s3.amazonaws.com/...",
  "result_url_expiration": "2025-01-02T10:00:00Z",
  "completed_at": "2025-01-01T11:00:00Z",
  "note": "预签名 URL 将在 1 天后过期，建议使用 result_s3_bucket 和 result_s3_key 直接访问以获得长期有效性"
}
```

### 错误处理最佳实践

**客户端应该：**
1. 检查 `success` 字段判断请求是否成功
2. 根据 `error.code` 进行特定的错误处理
3. 向用户展示 `error.message`（已本地化）
4. 记录 `error.details` 用于调试

**示例代码：**
```typescript
const response = await fetch('/requests', {
  method: 'POST',
  headers: { 'x-api-key': apiKey },
  body: JSON.stringify(requestData)
});

const result = await response.json();

if (result.success) {
  console.log('Request ID:', result.data.request_id);
} else {
  switch (result.error.code) {
    case 'MULTIPLE_PREFIXES_DETECTED':
      alert('图片前缀不一致，请检查图片命名');
      break;
    case 'UNAUTHORIZED':
      alert('API Key 无效，请重新登录');
      break;
    default:
      alert(result.error.message);
  }
}
```
