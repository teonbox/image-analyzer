# 处理流程文档

## 处理流程

### 时序图：提交请求

```mermaid
sequenceDiagram
    participant Client
    participant API Gateway
    participant Request Handler
    participant DynamoDB
    participant SQS
    
    Client->>API Gateway: POST /requests
    API Gateway->>Request Handler: 触发 Lambda
    Request Handler->>Request Handler: 验证参数
    Request Handler->>Request Handler: 列出所有图片
    Request Handler->>Request Handler: 检测前缀并排序
    Request Handler->>DynamoDB: 创建 Request 记录
    Request Handler->>Request Handler: 计算上下文范围
    loop 每个 Frame
        Request Handler->>SQS: 发送 Frame 消息
    end
    Request Handler->>Client: 返回 request_id
```

### Request Handler 流程

```mermaid
flowchart TD
    Start[接收请求] --> Validate[验证参数]
    Validate --> ListImages[列出所有图片]
    ListImages -->|超时| Error[返回错误]
    ListImages -->|成功| DetectPrefix[检测前缀]
    DetectPrefix -->|多个前缀| Error
    DetectPrefix -->|单一前缀| Sort[按编号排序]
    Sort --> CreateReq[创建 Request 记录]
    CreateReq --> LoopFrames[遍历所有 Frame]
    LoopFrames --> CalcContext[计算上下文范围]
    CalcContext --> SendSQS[发送 Frame 消息到 SQS]
    SendSQS --> LoopFrames
    LoopFrames --> Return[返回 request_id]
```

**关键点：**
- 不创建 Frame 记录，由 Frame Processor 按需创建
- 每个 Frame 一条 SQS 消息
- SQS 消息包含：`{request_id, frame_index, target_frame_url, before_frame_urls, after_frame_urls}`
- before_frame_urls 和 after_frame_urls 最多各包含 CONTEXT_MAX_FRAMES 个 URL

### 时序图：处理单个 Frame

```mermaid
sequenceDiagram
    participant SQS
    participant Frame Processor
    participant DynamoDB
    participant Storage
    participant Bedrock
    participant Completion Handler
    
    SQS->>Frame Processor: 触发 Lambda
    Frame Processor->>DynamoDB: 加载 Request 信息
    Frame Processor->>DynamoDB: 创建/加载 Frame 记录
    Frame Processor->>DynamoDB: 更新 last_activity_at
    
    loop 每个策略
        Frame Processor->>Frame Processor: shouldProcess?
        alt 需要处理
            Frame Processor->>Storage: 加载目标图片
            Frame Processor->>Storage: 加载上下文图片
            Frame Processor->>Bedrock: 调用分析
            Bedrock-->>Frame Processor: 返回结果
            Frame Processor->>DynamoDB: 合并结果到 policy_results
            Frame Processor->>DynamoDB: 更新 policy_status
        else 跳过
            Frame Processor->>DynamoDB: 标记策略为 skipped
        end
    end
    
    Frame Processor->>DynamoDB: 标记 Frame 为 completed
    Frame Processor->>DynamoDB: 更新 Request.frame_stats
    Frame Processor->>Frame Processor: 检查是否所有 Frame 完成
    alt 所有 Frame 完成
        Frame Processor->>Completion Handler: 触发完成处理
    end
```

### Frame Processor 流程

```mermaid
flowchart TD
    Start[接收 SQS 消息] --> ParseMsg[解析 Frame 信息]
    ParseMsg --> LoadRequest[加载 Request 信息]
    LoadRequest --> UpdateActivity[更新 last_activity_at]
    UpdateActivity --> CheckFrame{Frame 存在?}
    CheckFrame -->|否| CreateFrame[创建 Frame 记录]
    CheckFrame -->|是| LoadFrame[加载 Frame]
    CreateFrame --> LoadFrame
    LoadFrame --> LoopPolicy[遍历策略]
    
    LoopPolicy --> ShouldProcess{策略需要处理?}
    ShouldProcess -->|否| SkipPolicy[标记策略为 skipped]
    SkipPolicy --> LoopPolicy
    ShouldProcess -->|是| LoadTarget[加载目标图片]
    LoadTarget --> LoadContext[加载上下文图片]
    LoadContext --> CallBedrock[调用 Bedrock]
    CallBedrock --> Retry{失败?}
    Retry -->|是| CheckRetry{达到最大重试?}
    CheckRetry -->|否| Delay[延迟重试]
    Delay --> CallBedrock
    CheckRetry -->|是| MarkFailed[标记策略为 failed]
    MarkFailed --> LoopPolicy
    Retry -->|否| MergeResult[合并结果到 policy_results]
    MergeResult --> MarkSuccess[标记策略为 completed]
    MarkSuccess --> LoopPolicy
    
    LoopPolicy --> UpdateFrame[更新 Frame 状态]
    UpdateFrame --> UpdateStats[更新 Request.frame_stats]
    UpdateStats --> CheckComplete{所有 Frame 完成?}
    CheckComplete -->|是| TriggerCallback[触发 Completion Handler]
    CheckComplete -->|否| End[结束]
    TriggerCallback --> End
```

**关键点：**
- 每个 Lambda 实例处理一个 Frame
- 策略顺序执行（循环），不是并行
- 单个 Lambda 实例同时只调用 Bedrock 一次
- 按需创建 Frame 记录，避免初始化时大量写入
- 处理前检查 Frame.status，跳过已完成的帧（支持重试）
- 每次处理更新 Request.last_activity_at
- **图片加载**：Frame Processor 使用 HTTP GET 下载图片到内存，然后将 bytes 数据传给策略
- 上下文加载：根据 SQS 消息中的 before_frame_urls 和 after_frame_urls 下载上下文帧
- 结果合并：将策略的 key-value 结果合并到 Frame.policy_results 中
- 如果策略的 shouldProcess 返回 false，跳过该帧并标记为 skipped（对该策略）
- 完成检测：查询 Request.frame_stats，如果 completed + failed == total_frames 则触发 Completion Handler
- 使用乐观锁（version）更新 Request.frame_stats，防止并发冲突

### Completion Handler 流程

```mermaid
flowchart TD
    Start[触发] --> Query[查询所有 Frame 结果]
    Query --> Aggregate[聚合结果]
    Aggregate --> SaveS3[保存结果 JSON 到 S3]
    SaveS3 --> GenURL[生成预签名 URL 1天有效期]
    GenURL --> UpdateReq[更新 Request 状态和 S3 信息]
    UpdateReq --> Callback[POST callback_url]
    Callback --> Success{成功?}
    Success -->|是| End[结束]
    Success -->|否| CheckRetry{达到最大重试?}
    CheckRetry -->|否| Schedule[EventBridge 调度重试]
    Schedule --> End
    CheckRetry -->|是| MarkFailed[标记 callback_failed]
    MarkFailed --> End
```

**关键点：**
- 从 DynamoDB 查询所有 Frame 记录（按 request_id）
- 聚合结果：按策略和帧索引组织
- 保存到 S3：`results/{request_id}/result.json`
- 生成预签名 URL（1天有效期）
- 回调数据包含：S3 bucket、key、预签名 URL、过期时间
- 建议用户使用 bucket 和 key 直接访问（长期有效）

### 时序图：Health Check

```mermaid
sequenceDiagram
    participant EventBridge
    participant Health Check
    participant DynamoDB
    participant Completion Handler
    
    EventBridge->>Health Check: 每5分钟触发
    Health Check->>DynamoDB: 查询 running 状态的 Request
    loop 每个超时 Request
        Health Check->>DynamoDB: 标记 Request 为 completed
        Health Check->>DynamoDB: 标记未完成 Frame 为 failed
        Health Check->>Completion Handler: 触发完成处理
    end
```

### Health Check 流程

```mermaid
flowchart TD
    Start[EventBridge 每5分钟触发] --> Query[查询 running 状态的 Request]
    Query --> Loop[遍历 Request]
    Loop --> CheckActivity{last_activity_at 超过超时限制?}
    CheckActivity -->|否| Loop
    CheckActivity -->|是| MarkComplete[标记 Request 为 completed]
    MarkComplete --> MarkFailedFrames[标记所有未完成的 Frame 为 failed]
    MarkFailedFrames --> TriggerCallback[触发 Completion Handler]
    TriggerCallback --> Loop
    Loop --> End[结束]
```

**关键点：**
- 防止请求永久卡住
- 超时限制：REQUEST_TIMEOUT（默认 2 小时）
- 超时后强制标记为完成，允许部分帧失败
- 未完成的 Frame 标记为 failed，但保留已有的部分结果（如果某些策略已完成）
- 触发 Completion Handler 生成结果并回调
- 结果中包含失败的帧信息
