# 测试架构文档

## 测试框架选择

本项目采用 Python 作为测试语言，原因如下：
- Lambda 当前使用 TypeScript，但未来计划迁移到 Python
- Python 简洁易读，适合快速编写测试
- pytest 功能强大，生态丰富
- moto 支持完整的 AWS 服务 Mock

## 本地测试方案

为了在本地快速测试涉及 Lambda、DynamoDB、SQS、S3 的代码，系统采用以下方案：

**方案选择：Moto + 真实 Bedrock（推荐用于 Layer 1-2）**

Moto 是 Python 的 AWS 服务 Mock 库，可以在内存中模拟 DynamoDB、SQS、S3 等服务。优势：
- 轻量级，启动快，无需额外进程
- 完全在内存中运行，测试完自动清理
- 支持 decorator 方式，测试代码简洁
- 可以 assert DynamoDB 和 SQS 的值

**重要说明：**
- **DynamoDB、SQS、S3**：使用 moto mock（Layer 1-2）
- **Bedrock**：moto 不支持，必须使用真实服务（所有测试层级）

**使用示例：**

```python
from moto import mock_dynamodb, mock_sqs, mock_s3
import boto3
import json

@mock_dynamodb
@mock_sqs
@mock_s3
def test_frame_processor():
    # 创建 mock 的 DynamoDB 表
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
    
    # 创建 mock 的 SQS 队列
    sqs = boto3.client('sqs', region_name='us-east-1')
    queue = sqs.create_queue(QueueName='frame-queue')
    queue_url = queue['QueueUrl']
    
    # 创建 mock 的 S3 桶
    s3 = boto3.client('s3', region_name='us-east-1')
    s3.create_bucket(Bucket='test-bucket')
    
    # 准备测试数据
    request_table.put_item(Item={
        'request_id': 'test-123',
        'status': 'running',
        'total_frames': 10
    })
    
    # 调用 Lambda handler
    event = {
        'Records': [{
            'body': json.dumps({
                'request_id': 'test-123',
                'frame_index': 0,
                'frame_key': 'video/frame-001.jpg',
                'context_frame_range': [0, 60]
            })
        }]
    }
    result = frame_processor_handler(event, {})
    
    # Assert DynamoDB 数据
    response = frame_table.get_item(
        Key={'request_id': 'test-123', 'frame_index': 0}
    )
    assert response['Item']['status'] == 'completed'
    assert 'policy_results' in response['Item']
    
    # Assert SQS 消息（如果有发送新消息）
    messages = sqs.receive_message(QueueUrl=queue_url)
    if 'Messages' in messages:
        assert len(messages['Messages']) > 0
```

## Bedrock 测试认证方式

由于 Bedrock 必须使用真实服务，测试时需要配置 AWS 凭证。使用 AWS CLI 配置文件方式：

```bash
# ~/.aws/credentials
[default]
aws_access_key_id = YOUR_ACCESS_KEY
aws_secret_access_key = YOUR_SECRET_KEY

# ~/.aws/config
[default]
region = us-east-1
```

测试代码会自动使用默认凭证：
```python
# 无需额外配置，boto3 自动读取 ~/.aws/credentials
bedrock_client = boto3.client('bedrock-runtime', region_name='us-east-1')
```

## 测试成本控制

- Bedrock 调用会产生实际费用
- 建议使用 Nova Lite 模型（成本最低）
- 限制测试图片大小和数量
- 使用 pytest markers 区分需要 Bedrock 的测试：
  ```python
  @pytest.mark.bedrock  # 标记需要真实 Bedrock 的测试
  def test_with_real_bedrock():
      pass
  
  # 运行时跳过 Bedrock 测试
  pytest -m "not bedrock"
  ```

## 其他可选方案

1. **LocalStack**（适合更接近真实环境的测试）
   - 通过 Docker 提供本地 AWS 服务模拟器
   - 更接近真实 AWS 行为
   - 需要额外的 Docker 进程
   - 适合 Layer 3 集成测试的本地验证

2. **DynamoDB Local + ElasticMQ**（适合特定服务的深度测试）
   - DynamoDB Local: AWS 官方提供
   - ElasticMQ: 开源 SQS 兼容服务
   - 需要单独启动服务进程
   - 适合需要持久化数据的场景

## 测试层级与方案映射

| 层级 | 方案 | 说明 |
|------|------|------|
| Layer 1 (单元测试) | Moto + Mock/EmptyPolicy | 测试单个函数和模块，快速执行，完全隔离 |
| Layer 2 (组件测试) | Moto + EmptyPolicy | 测试完整的 Handler 流程，验证框架逻辑 |
| Layer 2 (策略组件测试) | Moto + 真实 Bedrock | 测试完整的 Policy 流程，验证模型调用 |
| Layer 3 (集成测试) | 真实 AWS 资源 | 验证真实环境行为，测试 API 和资源交互 |
| Layer 4 (端到端测试) | 真实 AWS 资源 | 完整业务流程验证 |

**说明：**
- Layer 2 的 Policy 组件测试使用真实 Bedrock，因为需要验证 Prompt 构建、模型响应解析、结果格式
- Layer 3 的集成测试则是测试完整的 Lambda 函数和 API 交互

## 测试策略

测试中使用专门的测试策略来验证框架逻辑，这些策略位于 `lambda/policies/test/` 目录下。

**EmptyPolicy**：
- 不调用 Bedrock，返回静态数据
- 不需要上下文帧
- 处理所有帧
- 返回结果：`{'empty_result': 'static_value', 'empty_frame_index': <frame_index>}`

**使用方式**：
```python
# 在测试中配置使用 EmptyPolicy
os.environ['ENABLED_POLICIES'] = 'empty'
```

**Mock Bedrock**：
```python
from unittest.mock import patch, MagicMock

mock_bedrock = MagicMock()
mock_bedrock.invoke.return_value = {
    'output': {'message': {'content': [{'text': 'mocked response'}]}}
}

with patch('lambda.handlers.frame_processor.bedrock_client', mock_bedrock):
    result = handler(event, {})
```

## 测试分层实现

| 层级 | 语言 | 框架 | 执行环境 |
|------|------|------|---------|
| Layer 1-2（本地测试） | Python 3.12 | pytest + moto | 本地开发机 |
| Layer 3（集成测试） | Python 3.12 | pytest + boto3 | 真实 AWS 资源 |
| Layer 4（端到端测试） | Shell 脚本 | curl, jq, aws-cli | 真实 AWS 资源 |

## 测试文件组织

```
test/
├── unit/                           # Layer 1: 单元测试
│   ├── test_request_handler.py
│   ├── test_batch_processor.py
│   └── policies/
│       └── test_*.py
│
├── component/                      # Layer 2: 组件测试
│   ├── test_request_handler_flow.py
│   ├── test_batch_processor_flow.py
│   └── test_completion_handler_flow.py
│
├── integration/                    # Layer 3: 集成测试
│   ├── test_api_submit.py
│   ├── test_api_query.py
│   └── test_e2e_drinking_detection.py
│
├── e2e/                            # Layer 4: 端到端测试
│   └── *.test.sh
│
├── fixtures/                       # 测试数据
│   ├── unit/
│   ├── component/
│   ├── integration/
│   └── e2e/
│
├── conftest.py                     # pytest 配置
└── README.md                       # 测试说明
```

## Moto 资源初始化规范

所有 AWS mock 资源的创建必须使用 `test/conftest.py` 中的公共方法，禁止在测试文件中独立创建。

**公共方法列表：**

| 方法 | 说明 |
|------|------|
| `setup_test_environment()` | 设置测试环境变量 |
| `create_request_table()` | 创建 DynamoDB Request 表 |
| `create_frame_table()` | 创建 DynamoDB Frame 表 |
| `create_frame_queue()` | 创建 SQS Frame 队列 |
| `create_results_bucket()` | 创建 S3 结果存储桶 |
| `create_s3_bucket_with_images()` | 创建带测试图片的 S3 桶 |
| `receive_all_sqs_messages()` | 接收并清空队列消息 |
| `assert_timestamp_recent()` | 验证时间戳在合理范围内 |

**使用示例：**

```python
from conftest import (
    setup_test_environment,
    create_request_table,
    create_frame_queue,
)

@mock_aws
def test_example(self):
    setup_test_environment()
    create_request_table()
    sqs, queue_url = create_frame_queue()
    # ... 测试逻辑
```

**规范要求：**
- 新增 AWS 资源类型时，应在 `conftest.py` 中添加对应的公共创建方法
- 测试文件中禁止直接调用 `boto3.resource()` 或 `boto3.client()` 创建资源
- 所有资源创建方法应返回必要的客户端和标识符（如 queue_url）

## 端到端集成测试框架

### 框架结构

```
test/integration/
├── helpers/
│   ├── api_client.py      # API 客户端封装
│   ├── waiter.py          # 等待策略（指数退避）
│   └── verifier.py        # 结果验证器
├── conftest.py            # pytest fixtures
└── test_e2e_*.py          # 测试用例

test/fixtures/integration/
└── test-cases/
    └── *.json             # 测试用例配置
```

### 核心组件

**APIClient**：封装所有 API 调用
- `submit_request(name, urls, callback_url)` - 提交分析请求
- `get_request_status(request_id)` - 查询请求状态
- `get_request_results(request_id)` - 获取结果（从 S3 预签名 URL）

**Waiter**：等待策略（指数退避）
- 初始等待 1 秒，最大 5 秒
- 退避因子 1.5
- 默认超时 60 秒

**ResultVerifier**：结果验证器
- 支持精确匹配：`"key": value`
- 支持范围匹配：`"key_min": 0.7, "key_max": 1.0`
- 支持包含匹配：`"key_contains": "substring"`
- 支持不存在验证：`"not_expected": ["key1", "key2"]`

### 测试用例配置格式

```json
{
  "name": "test-case-name",
  "description": "测试描述",
  "enabled_policies": ["policy_name"],
  "frames": [
    {
      "url": "https://example.com/image.jpg",
      "description": "帧描述",
      "expected_results": {
        "field_exact": true,
        "field_range_min": 0.7,
        "field_range_max": 1.0,
        "field_contains": "substring"
      },
      "not_expected": ["field_should_not_exist"]
    }
  ]
}
```

### 测试用例编写规范

1. 使用 `@pytest.mark.e2e` 和 `@pytest.mark.bedrock` 标记
2. 通过 fixtures 注入依赖：`test_case_loader`, `api_client`, `request_waiter`, `verifier`
3. 测试数据由测试人员提前准备，存放在 `test/fixtures/integration/test-cases/`
4. 每个测试用例必须明确"测试目标"

### 验证规则

| 匹配类型 | 配置格式 | 说明 |
|---------|---------|------|
| 精确匹配 | `"key": value` | 值必须完全相等 |
| 范围匹配 | `"key_min": x, "key_max": y` | 值在 [x, y] 范围内 |
| 包含匹配 | `"key_contains": "str"` | 值包含指定字符串 |
| 不存在 | `"not_expected": ["key"]` | 字段不应存在 |

## Policy 本地测试工具

为了方便在本地快速测试和调试 Policy，项目提供了 `test_policy_local.py` 脚本，可以直接调用真实的 Bedrock 服务测试 Policy 效果。

### 文件结构

```
project/
├── test_policy_local.py       # 本地测试脚本
└── test_policy_config.yaml    # 测试配置文件
```

### 配置文件格式

```yaml
# test_policy_config.yaml

# 要测试的 Policy 名称
policy: person_appearance

# AWS 区域
region: us-east-1

# 上下文帧数量（不需要上下文的 Policy 设为 0）
prev_count: 0
next_count: 0

# 步长 - 每次滑动几帧
step: 1

# 图片列表 - 支持本地路径或 URL
images:
  - /path/to/local/image.jpg
  - https://example.com/remote/image.jpg
```

### 使用方法

```bash
# 1. 修改配置文件
vim test_policy_config.yaml

# 2. 运行测试
export PYTHONDONTWRITEBYTECODE=1
python test_policy_local.py
```

### 输出示例

```
📷 加载 3 张图片...
   [0] /path/to/image1.jpg (74845 bytes)
   [1] /path/to/image2.jpg (75284 bytes)
   [2] /path/to/image3.jpg (75105 bytes)

🔧 Policy: person_appearance
   prev_count: 0, next_count: 0, step: 1

==================================================
🎯 分析帧 [0]: /path/to/image1.jpg
   🔍 调用 Bedrock...

   📊 结果:
      person_age_group: young_adult
      person_ethnicity: east_asian
      person_skin_tone: fair
      person_overall_level: attractive
      person_features: ['big_eyes', 'v_face', 'fresh']
      person_confidence: 0.9

==================================================
📋 完成，共分析 3 帧
```

### 支持的 Policy

| Policy 名称 | 说明 | 需要上下文 |
|-------------|------|-----------|
| drinking_detection | 喝东西检测 | 是（前后各1帧） |
| person_appearance | 人物外观特征分析 | 否 |

### 配置说明

| 参数 | 说明 |
|------|------|
| policy | Policy 名称，对应 `get_name()` 返回值 |
| region | AWS 区域，需要有 Bedrock 访问权限 |
| prev_count | 目标帧前面取几帧作为上下文 |
| next_count | 目标帧后面取几帧作为上下文 |
| step | 滑动步长，1 表示每帧都分析 |
| images | 图片列表，支持本地路径和 HTTP/HTTPS URL |

### 注意事项

- 需要配置 AWS 凭证（`~/.aws/credentials`）
- 会产生真实的 Bedrock 调用费用
- 建议使用 Nova Lite 模型（成本最低）
- 图片支持 JPEG、PNG、GIF 格式

## 测试执行

**本地测试（Layer 1-2）**：
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

**集成测试（Layer 3）**：
```bash
# 设置环境变量
export API_URL="https://xxx.execute-api.us-east-1.amazonaws.com/prod"
export API_KEY="your-api-key"

# 运行集成测试
pytest test/integration/

# 只运行端到端测试
pytest test/integration/ -m e2e
```

**端到端测试（Layer 4）**：
```bash
# 准备测试数据
./test/scripts/upload-test-data.sh

# 运行端到端测试
./test/e2e/small-video.test.sh
```
