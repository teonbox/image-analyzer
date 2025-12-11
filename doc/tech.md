# 图片分析系统设计文档

## 概述

基于 AWS Bedrock 的无服务器批量图片分析解决方案，用于视频帧分析。

## 核心概念

本系统的核心设计理念：
- **帧级处理**：每个 Frame 作为独立的工作单元，通过 SQS 消息触发处理
- **上下文窗口**：每帧分析时可访问前后帧作为参考，窗口大小可配置（最大前后各60帧）
- **策略顺序执行**：单个 Lambda 处理一个 Frame，遍历所有策略顺序执行
- **容错设计**：单帧失败不影响其他帧，支持帧级别重试

### 关键术语

| 术语 | 说明 |
|------|------|
| Request | 用户提交的一次分析请求，对应一个视频的所有帧 |
| Frame | 视频中的单张图片，每个 Frame 是一个独立的工作单元 |
| Policy | 分析策略，定义如何分析帧（顺序、间隔、上下文感知等） |
| Context Frames | 当前帧的上下文参考帧（前后各最多60帧） |

### 处理流程说明

**SQS 消息粒度：**
- 每个 Frame 对应一条 SQS 消息
- 消息内容：`{request_id, frame_index, frame_key, context_frame_range}`
- context_frame_range 示例：`[max(0, frame_index-60), min(total_frames-1, frame_index+60)]`

**示例（3600 帧视频）：**
```
Frame 0:   context_range=[0, 60]
Frame 1:   context_range=[0, 61]
Frame 60:  context_range=[0, 120]
Frame 100: context_range=[40, 160]
...
Frame 3599: context_range=[3539, 3599]

总 SQS 消息数：3600 条
```

**配置：**
```
CONTEXT_MAX_FRAMES=60           # 最大上下文帧数（前后各60）
WORKER_CONCURRENCY=10           # Lambda 并发实例数
```

## 架构设计

### Lambda 职责说明

| Lambda | 触发方式 | 职责 | 输入 | 输出 |
|--------|---------|------|------|------|
| Request Handler | API Gateway | 接收用户请求，列出图片，创建 Request 记录，异步触发 Message Dispatcher | 用户请求（type, bucket/urls, name, callback_url） | request_id（立即返回） |
| Message Dispatcher | Request Handler 异步调用 | 构建并并行发送 Frame 消息到 SQS | request_id, frame_keys, storage_config | 发送统计 |
| Frame Processor | SQS 消息 | 处理单个 Frame，遍历所有策略顺序执行，保存结果 | SQS 消息（request_id, frame_index, target_frame_url, context_urls） | 更新 Frame 和 Request 状态 |
| Completion Handler | Frame Processor 触发 | 聚合所有 Frame 结果，保存到 S3，回调用户 | request_id | 回调通知 |
| Query Handler | API Gateway | 查询 Request 状态和结果 | request_id 或 name | Request 信息和结果 |
| Health Check | EventBridge 定时 | 检查超时 Request，强制完成 | 无 | 标记超时 Request |

### 系统架构图

```mermaid
graph TB
    Client[客户端] -->|POST /requests| APIGW[API Gateway]
    APIGW --> ReqHandler[Lambda: Request Handler]
    ReqHandler -->|列出图片| S3Source[S3/HTTP 图片源]
    ReqHandler -->|创建 Request 记录| DDB[(DynamoDB)]
    ReqHandler -->|异步调用| MsgDispatcher[Lambda: Message Dispatcher]
    ReqHandler -->|立即返回 request_id| APIGW
    
    MsgDispatcher -->|并行发送 Frame 消息| SQS[SQS: Frame Queue]
    
    SQS -->|触发 MaxConcurrency=100| FrameProc1[Lambda: Frame Processor 1]
    SQS -->|触发| FrameProc2[Lambda: Frame Processor 2]
    SQS -->|触发| FrameProc3[Lambda: Frame Processor N]
    
    FrameProc1 -->|创建/更新 Frame| DDB
    FrameProc1 -->|下载图片 HTTP/S3| S3Source
    FrameProc1 -->|遍历策略分析| Bedrock[AWS Bedrock]
    FrameProc1 -->|存储结果| DDB
    
    DDB -->|所有 Frame 完成| CompHandler[Lambda: Completion Handler]
    CompHandler -->|聚合结果| DDB
    CompHandler -->|保存结果 JSON| S3Results[S3: Results Bucket]
    CompHandler -->|生成预签名 URL| S3Results
    CompHandler -->|POST| Callback[Callback URL]
    CompHandler -->|失败重试| EventBridge[EventBridge]
    EventBridge -->|延迟触发| CompHandler
    
    EventBridge -->|每5分钟| HealthCheck[Lambda: Health Check]
    HealthCheck -->|检查超时 Request| DDB
    HealthCheck -->|标记超时为完成| DDB
    HealthCheck -->|触发回调| CompHandler
    
    Client -->|GET /requests/:id| APIGW
    APIGW --> QueryHandler[Lambda: Query Handler]
    QueryHandler -->|查询| DDB
    QueryHandler -->|生成预签名 URL| S3Results
```

### 数据模型 ER 图

```mermaid
erDiagram
    REQUEST ||--o{ FRAME : contains
    
    REQUEST {
        string request_id
        string name
        string status
        json input_config
        string callback_url
        int total_frames
        json frame_stats
        timestamp last_activity_at
        string result_s3_key
        timestamp result_url_expiration
        timestamp created_at
        timestamp completed_at
        int version
    }
    
    FRAME {
        string request_id
        int frame_index
        string frame_url
        json policy_results
        json policy_status
        string status
        int retry_count
        timestamp created_at
        timestamp completed_at
    }
```

### 关键表结构

**Request 表**
- PK: request_id
- GSI: name-created_at-index（支持按 name 查询）
- 关键字段: 
  - name: 请求名称（用户指定）
  - status: pending | running | completed | failed
  - input_config: 客户端原始请求参数（JSON），包含 type、bucket/urls、region 等
  - total_frames: 总帧数
  - frame_stats: `{total, completed, failed, pending}` 帧统计
  - callback_url: 完成后回调地址
  - last_activity_at: 最后活动时间（用于超时检测）
  - result_s3_key: 结果文件 S3 路径
  - result_url_expiration: 预签名 URL 过期时间
  - version: 乐观锁版本号（用于并发更新）

**Frame 表**
- PK: request_id
- SK: frame_index
- 关键字段:
  - frame_url: 目标帧的下载地址
  - policy_results: `{key: value}` 所有策略的结果合并
  - policy_status: `{policy_name: status}` 每个策略的状态
  - status: pending | processing | completed | failed
  - retry_count: 重试次数
  - created_at: 创建时间
  - completed_at: 完成时间

**设计说明：**
- Request 表的 input_config 存储客户端原始请求，不存储图片列表
- Frame 表使用复合键（request_id + frame_index），支持高效的范围查询
- Frame 表的 policy_results 存储所有策略的结果（JSON 格式），所有策略的 key-value 结果合并在一起
- Frame 表的 policy_status 记录每个策略的执行状态（completed | skipped | failed）
- 策略应确保操作不同的 key，如果覆盖彼此的 key，那是策略的错误
- Request.version 用于乐观锁，防止并发更新 frame_stats 时的冲突

### SQS 消息格式

**Frame 消息格式**：

每个 Frame 对应一条 SQS 消息，消息包含目标帧和上下文帧的 URL。

**消息结构**：

```json
{
  "request_id": "abc-123-def-456",
  "request_name": "my-video-analysis",
  "frame_index": 100,
  "target_frame_url": "https://example.com/video/frame-100.jpg",
  "before_frame_urls": [
    "https://example.com/video/frame-99.jpg",
    "https://example.com/video/frame-98.jpg",
    null,
    "https://example.com/video/frame-96.jpg"
  ],
  "after_frame_urls": [
    "https://example.com/video/frame-101.jpg",
    "https://example.com/video/frame-102.jpg"
  ]
}
```

**字段说明**：

| 字段 | 类型 | 说明 |
|------|------|------|
| request_id | string | 请求 ID（UUID） |
| request_name | string | 请求名称（用户指定） |
| frame_index | integer | 目标帧索引（从 0 开始） |
| target_frame_url | string | 目标帧的 HTTP/HTTPS URL |
| before_frame_urls | array | 前序帧 URL 列表（倒序，最近的在前） |
| after_frame_urls | array | 后续帧 URL 列表（正序） |

**上下文帧说明**：
- `before_frame_urls`：最多包含 CONTEXT_MAX_FRAMES 个前序帧，按时间倒序排列
  - `[0]` 是紧邻的前一帧（frame_index - 1）
  - `[1]` 是前两帧（frame_index - 2）
  - 以此类推
- `after_frame_urls`：最多包含 CONTEXT_MAX_FRAMES 个后续帧，按时间正序排列
  - `[0]` 是紧邻的后一帧（frame_index + 1）
  - `[1]` 是后两帧（frame_index + 2）
  - 以此类推
- 如果某帧缺失（视频丢帧），对应位置为 `null`
- 数组长度可能小于 CONTEXT_MAX_FRAMES（视频开头或结尾）

**图片下载**：
- Frame Processor 使用 HTTP GET 下载图片
- 简单的 `requests.get(url)` 即可
- 不需要 S3/OSS SDK

**消息示例**（3600 帧视频，CONTEXT_MAX_FRAMES=60）：

```
Frame 0:    before=[], after=[url-1, url-2, ..., url-60]
Frame 1:    before=[url-0], after=[url-2, url-3, ..., url-61]
Frame 100:  before=[url-99, url-98, ..., url-40], after=[url-101, url-102, ..., url-160]
Frame 3599: before=[url-3598, url-3597, ..., url-3539], after=[]

总 SQS 消息数：3600 条
```

**消息处理流程**：
1. Request Handler 列出图片，创建 Request 记录
2. 异步调用 Message Dispatcher
3. Message Dispatcher 构造并并行发送 SQS 消息
4. Frame Processor 接收消息，下载图片（HTTP 或 S3）
5. 遍历所有策略顺序执行
6. 保存结果到 DynamoDB

## 异步架构设计

### 为什么需要异步架构

**问题**：API Gateway 最大超时 29 秒，但处理大量图片（5000+ 帧）需要：
- S3 列表：~6 秒
- 解析排序：~0.5 秒
- 构建消息：~1 秒
- 发送 SQS：~25 秒（5000+ 消息）
- **总计：~32 秒** → 超过 API Gateway 限制

**解决方案**：异步架构
1. Request Handler 快速返回（~2 秒）
2. Message Dispatcher 后台发送消息（最多 5 分钟）

### 异步流程

```
用户请求 → Request Handler (2s)
              ↓
         创建 Request 记录
              ↓
         异步调用 Message Dispatcher
              ↓
         立即返回 request_id ✓
              
Message Dispatcher (后台运行)
              ↓
         构建 SQS 消息
              ↓
         并行发送（20 workers）
              ↓
         完成（25s）
```

### 性能配置

| 组件 | 超时 | 内存 | 并发度 | 说明 |
|------|------|------|--------|------|
| Request Handler | 120s | 256MB | - | 列出图片 + 触发 dispatcher |
| Message Dispatcher | 5min | 512MB | 20 workers | 并行发送 SQS |
| Frame Processor | 15min | 1024MB | 100 | 处理单帧 |

## 跨账号 S3 访问

### 支持的存储类型

| 类型 | 说明 | 必需参数 | 凭证来源 |
|------|------|----------|----------|
| `http` | HTTP/HTTPS URL 列表 | urls | 无需凭证 |
| `s3` | AWS S3 存储 | bucket, region, prefix | Lambda 角色或环境变量 AKSK |
| `oss` | 阿里云 OSS | bucket, endpoint | 未实现 |

### S3 跨账号访问机制

**场景**：访问其他 AWS 账号的 S3 bucket（如 udemo-us-east-1）

**实现方式**：
1. 在 CDK 中配置目标账号的 AKSK 环境变量
2. Request Handler 和 Frame Processor 根据 bucket 名称自动选择凭证

**环境变量配置**：
```typescript
UDEMO_AWS_ACCESS_KEY_ID: 'AKIAIOSFODNN7EXAMPLE'
UDEMO_AWS_SECRET_ACCESS_KEY: 'wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY'
UDEMO_S3_BUCKET: 'udemo-us-east-1'
UDEMO_S3_REGION: 'us-east-1'
```

**注意**：实际部署时，AKSK 通过 CDK context 参数配置，不应硬编码在代码中。

**代码逻辑**：
```python
def _get_s3_client_for_bucket(bucket: str, region: str):
    # 检查是否是 UDEMO bucket
    if bucket == os.environ.get('UDEMO_S3_BUCKET'):
        # 使用 UDEMO 凭证
        return boto3.client('s3',
            region_name=os.environ.get('UDEMO_S3_REGION'),
            aws_access_key_id=os.environ.get('UDEMO_AWS_ACCESS_KEY_ID'),
            aws_secret_access_key=os.environ.get('UDEMO_AWS_SECRET_ACCESS_KEY')
        )
    # 默认使用 Lambda 执行角色
    return boto3.client('s3', region_name=region)
```

### S3 URL 格式

**Request Handler 输出**：`s3://bucket/key` 格式
- 示例：`s3://udemo-us-east-1/images/nocache/言奥博_20251117_204059/言奥博_20251117_204059-1.jpg`

**Frame Processor 处理**：
1. 识别 `s3://` 协议
2. 解析 bucket 和 key
3. 使用对应凭证下载

**优势**：
- 统一的 URL 格式（HTTP 和 S3）
- 自动选择凭证
- 支持多个跨账号 bucket（添加更多环境变量即可）
