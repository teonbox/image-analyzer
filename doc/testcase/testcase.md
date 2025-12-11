# 测试用例文档总览

## 测试策略

本项目采用四层测试策略，从快速反馈的单元测试到完整的端到端测试：

**Layer 1: 单元测试**
- 环境：本地
- 执行时间：秒级
- 目标：验证核心业务逻辑
- 工具：pytest + moto

**Layer 2: 组件测试**
- 环境：本地 + Mock
- 执行时间：分钟级
- 目标：验证 Lambda 完整流程
- 工具：pytest + moto

**Layer 3: 集成测试**
- 环境：云上
- 执行时间：分钟级
- 目标：验证 API 和资源交互
- 工具：pytest + boto3

**Layer 4: 端到端测试**
- 环境：云上
- 执行时间：小时级
- 目标：验证完整业务流程
- 工具：Shell 脚本 + curl

## 测试文件组织

```
doc/testcase/
├── testcase.md                          # 本文件：总览和测试策略
├── request-handler.md                   # Request Handler 测试（Layer 1-2）
├── sqs-message-builder.md               # SQS Message Builder 测试（Layer 1）
├── frame-processor.md                   # Frame Processor 测试（Layer 1-2）
├── completion-handler.md                # Completion Handler 测试（Layer 1-2）
├── query-handler.md                     # Query Handler 测试（Layer 1-2）
├── health-check.md                      # Health Check 测试（Layer 1-2）
├── drinking-detection-policy.md         # Drinking Detection Policy 测试（Layer 1-2）
└── integration-tests.md                 # 集成测试（Layer 3）
```

### 各文档说明

**Lambda 函数测试文档（Layer 1-2）**

**[request-handler.md](request-handler.md)**
- Layer 1: 9 个单元测试（参数验证）
- Layer 2: 5 个组件测试（URL 列表和 S3 方式完整流程、错误处理）

**[sqs-message-builder.md](sqs-message-builder.md)**
- Layer 1: 12 个单元测试（单个消息构造、批量消息构造、边界场景、丢帧处理）

**[frame-processor.md](frame-processor.md)**
- Layer 1: 7 个单元测试（消息解析、5 种上下文场景）
- Layer 2: 8 个组件测试（5 种上下文场景完整流程、策略执行、幂等性）

**[drinking-detection-policy.md](drinking-detection-policy.md)**
- Layer 1: 3 个单元测试（策略基本功能、上下文帧选择）
- Layer 2: 15 个组件测试（3 种场景 × 5 种上下文场景）

**[completion-handler.md](completion-handler.md)**
- Layer 1: 4 个单元测试（结果聚合、S3 路径、预签名 URL）
- Layer 2: 3 个组件测试（完整流程、回调失败、重试）

**[query-handler.md](query-handler.md)**
- Layer 1: 3 个单元测试（UUID/name 识别、预签名 URL）
- Layer 2: 6 个组件测试（查询状态、获取结果）

**[health-check.md](health-check.md)**
- Layer 1: 4 个单元测试（超时检测、状态更新）
- Layer 2: 3 个组件测试（超时处理、多个超时）

**集成测试文档（Layer 3）**

**[integration-tests.md](integration-tests.md)**
- 16 个集成测试用例，覆盖完整的端到端流程
- API 提交流程测试（4 个用例）
- Frame 处理流程测试（2 个用例）
- 查询流程测试（6 个用例）
- 完成流程测试（2 个用例）
- 超时和重试测试（2 个用例）

---

## Mock 工具说明

### Moto（用于 Layer 1-2）

Moto 可以在本地 mock AWS 服务，无需真实的 AWS 资源：

```python
from moto import mock_dynamodb, mock_sqs, mock_s3
import boto3

@mock_dynamodb
@mock_sqs
@mock_s3
def test_example():
    # 创建 mock 的 DynamoDB 表
    dynamodb = boto3.resource('dynamodb', region_name='us-east-1')
    table = dynamodb.create_table(...)
    
    # 创建 mock 的 SQS 队列
    sqs = boto3.client('sqs', region_name='us-east-1')
    queue = sqs.create_queue(QueueName='test-queue')
    
    # 创建 mock 的 S3 桶
    s3 = boto3.client('s3', region_name='us-east-1')
    s3.create_bucket(Bucket='test-bucket')
    
    # 执行测试...
    
    # Assert mock 的数据
    response = table.get_item(Key={'id': '123'})
    assert response['Item']['status'] == 'completed'
```

**优势：**
- 完全在内存中运行，测试完自动清理
- 可以 assert DynamoDB、SQS、S3 的值
- 不需要真实的 AWS 资源
- 测试速度快

## 测试执行

### 本地测试（Layer 1-2）
```bash
# 安装依赖
pip install pytest moto boto3

# 运行所有单元测试
pytest test/unit/

# 运行组件测试
pytest test/component/

# 查看覆盖率
pytest --cov=lambda test/unit/
```

### 集成测试（Layer 3）
```bash
# 设置环境变量
export API_URL="https://xxx.execute-api.ap-northeast-2.amazonaws.com/prod"
export API_KEY="your-api-key"

# 运行集成测试
pytest test/integration/
```

### 端到端测试（Layer 4）
```bash
# 准备测试数据
./test/scripts/upload-test-data.sh

# 运行端到端测试
./test/e2e/small-video.test.sh
```

## 测试覆盖目标

- **单元测试覆盖率**: > 80%
- **组件测试覆盖率**: 核心流程 100%
- **集成测试**: 所有 API 端点
- **端到端测试**: 关键业务场景

## 测试原则

1. **快速反馈**: 单元测试应在秒级完成
2. **隔离性**: 测试之间互不影响
3. **可重复**: 测试结果稳定可靠
4. **易维护**: 测试代码清晰易懂
5. **真实性**: 集成测试使用真实环境
