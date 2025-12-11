# 图像分析系统

基于 AWS Bedrock 的无服务器批量图像分析解决方案，用于视频帧分析。

## 特性

- **批次化处理**: 自动将大规模视频帧拆分为批次，避免超时
- **多策略支持**: 支持多种分析策略并行执行，灵活配置
- **上下文感知**: 分析时可访问前后帧作为参考，提升分析质量
- **容错机制**: 单帧失败不影响整体，支持自动重试
- **异步处理**: 提交后立即返回，通过回调或查询获取结果
- **可扩展**: 轻松添加自定义分析策略

## 快速开始

### 部署

```bash
./deploy.sh
```

### 测试

```bash
./test-api.sh
```

### 使用 API

```bash
# 提交分析请求
curl -X POST "https://your-api-url/prod/requests" \
  -H "x-api-key: YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "type": "s3",
    "bucket": "my-bucket",
    "prefix": "video-frames/",
    "region": "ap-northeast-2",
    "name": "my-video-analysis",
    "callback_url": "https://example.com/callback"
  }'

# 查询状态
curl -X GET "https://your-api-url/prod/requests/my-video-analysis" \
  -H "x-api-key: YOUR_API_KEY"

# 获取结果
curl -X GET "https://your-api-url/prod/requests/my-video-analysis/results" \
  -H "x-api-key: YOUR_API_KEY"
```

## 文档

### 用户文档

- **[API 使用文档](doc/api.md)** - API 接口说明、参数、响应格式、使用示例
- **[部署文档](doc/deployment.md)** - 部署流程、配置说明、运维管理

### 开发文档

- **[策略开发文档](doc/policy.md)** - 自定义分析策略开发指南
- **[产品需求文档](spec/product.md)** - 产品功能和业务场景
- **[技术设计文档](spec/tech.md)** - 系统架构和技术实现
- **[任务计划](spec/task.md)** - 开发任务和进度

## 架构

```
客户端
  ↓ POST /requests
API Gateway → Request Handler Lambda
  ↓ 创建批次消息
SQS Queue
  ↓ 触发（并发=10）
Batch Processor Lambda (多实例)
  ↓ 分析图像
AWS Bedrock (Nova Lite)
  ↓ 存储结果
DynamoDB (Request + Frame)
  ↓ 所有批次完成
Completion Handler Lambda
  ↓ 聚合结果
S3 Results Bucket
  ↓ 回调通知
客户端 Webhook
```

## 核心组件

### Lambda 函数

| 函数 | 说明 | 触发器 |
|------|------|--------|
| Request Handler | 处理请求提交，计算批次划分 | API Gateway |
| Batch Processor | 执行批次分析，调用 Bedrock | SQS |
| Completion Handler | 聚合结果，生成回调 | Lambda Invoke |
| Query Handler | 处理状态和结果查询 | API Gateway |
| Health Check | 超时检测和强制完成 | EventBridge |

### 数据存储

| 资源 | 说明 |
|------|------|
| Request Table | 存储请求信息、状态、统计 |
| Frame Table | 存储每帧的分析结果 |
| Results Bucket | 存储完整的 JSON 结果文件 |
| Batch Queue | 批次消息队列 |

### 分析策略

| 策略 | 说明 |
|------|------|
| Sequential | 逐帧分析，生成图像描述 |
| Interval | 间隔采样，每 10 帧分析一次 |
| Context-Aware | 使用前后帧作为上下文分析运动 |

## 项目结构

```
image-analyzer/
├── deploy.sh              # 部署脚本
├── test-api.sh            # API 测试脚本
│
├── lambda/                # Lambda 源代码
│   ├── handlers/          # Lambda 处理器
│   │   ├── request-handler.ts
│   │   ├── batch-processor.ts
│   │   ├── completion-handler.ts
│   │   ├── query-handler.ts
│   │   └── health-check.ts
│   ├── shared/            # 共享工具类
│   │   ├── config.ts
│   │   ├── enums.ts
│   │   ├── models.ts
│   │   ├── request-table.ts
│   │   ├── frame-table.ts
│   │   ├── bedrock-client.ts
│   │   └── policy-registry.ts
│   ├── policies/          # 分析策略
│   │   ├── sequential-policy.ts
│   │   ├── interval-policy.ts
│   │   └── context-aware-policy.ts
│   └── dist/              # 编译输出
│
├── infrastructure/        # CDK 基础设施代码
│   ├── lib/
│   │   └── infrastructure-stack.ts
│   └── bin/
│       └── infrastructure.ts
│
├── doc/                   # 用户文档
│   ├── api.md             # API 使用文档
│   ├── deployment.md      # 部署文档
│   └── policy.md          # 策略开发文档
│
└── spec/                  # 设计文档
    ├── product.md         # 产品需求
    ├── tech.md            # 技术设计
    └── task.md            # 任务计划
```

## 技术栈

- **语言**: TypeScript
- **运行时**: Node.js 20
- **基础设施**: AWS CDK
- **服务**: 
  - Lambda (计算)
  - DynamoDB (数据库)
  - SQS (消息队列)
  - S3 (对象存储)
  - API Gateway (API 网关)
  - Bedrock (AI 模型)
  - EventBridge (定时任务)

## 配置

### 环境变量

主要配置参数（在 `lambda/shared/config.ts` 中定义）：

```typescript
// Bedrock
BEDROCK_MODEL_ID: 'us.amazon.nova-lite-v1:0'
BEDROCK_REGION: 'us-east-1'

// 批次
BATCH_SIZE_COEFFICIENT: 1.0  // 批次大小系数
CONTEXT_MAX_FRAMES: 60       // 最大上下文帧数

// 并发
WORKER_CONCURRENCY: 10       // Lambda 并发数

// 超时
REQUEST_TIMEOUT: 7200        // 请求超时（2小时）

// 策略
ENABLED_POLICIES: 'sequential,interval,context_aware'
```

### 修改配置

1. 编辑 `infrastructure/lib/infrastructure-stack.ts` 中的环境变量
2. 或编辑 `lambda/shared/config.ts` 中的默认值
3. 重新部署：`./deploy.sh`

## 开发

### 添加新策略

1. 在 `lambda/policies/` 创建策略文件
2. 实现 `AnalysisPolicy` 接口
3. 在 `policy-registry.ts` 中注册
4. 更新 `ENABLED_POLICIES` 配置
5. 重新部署

详见[策略开发文档](doc/policy.md)。

### 本地开发

```bash
# 安装依赖
cd lambda && npm install

# 编译
npm run build

# 运行测试
npm test
```

## 运维

### 查看日志

```bash
# Batch Processor 日志
aws logs tail /aws/lambda/InfrastructureStack-BatchProcessor* --region ap-northeast-2 --follow
```

### 监控

在 CloudWatch 中查看：
- Lambda 调用次数、错误率、持续时间
- DynamoDB 读写容量、限流
- SQS 消息数量、处理延迟

### 故障排查

详见[部署文档 - 故障排查](doc/deployment.md#故障排查)。

## 成本估算

以 3600 帧视频为例（1小时，1fps）：

- **Lambda**: ~$0.50（10个并发，15分钟超时）
- **Bedrock**: ~$2.00（Nova Lite，3个策略）
- **DynamoDB**: ~$0.10（按需计费）
- **S3**: ~$0.01（结果存储）
- **其他**: ~$0.05（SQS, API Gateway）

**总计**: ~$2.66/视频

实际成本取决于：
- 视频长度和帧数
- 启用的策略数量
- Bedrock 模型选择
- 并发配置

## 限制

- **API 限流**: 10 req/s，突发 20 req/s
- **图像列表超时**: 30 秒
- **请求超时**: 2 小时
- **并发处理**: 10 个批次
- **预签名 URL**: 1 天有效期

## 安全

- API Key 认证
- IAM 角色最小权限
- DynamoDB 和 S3 加密
- CloudTrail 审计日志

## 许可证

MIT

## 支持

- 问题反馈：GitHub Issues
- 文档：[doc/](doc/)
- 设计文档：[spec/](spec/)

## 更新日志

### v1.0.0 (2025-11-24)

- ✅ 完整的批次处理流程
- ✅ 多策略支持（Sequential, Interval, Context-Aware）
- ✅ Amazon Nova Lite 模型集成
- ✅ 完整的 API（提交、查询、结果）
- ✅ 超时检测和强制完成
- ✅ 回调重试机制
- ✅ 完整的文档
