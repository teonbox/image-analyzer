# 策略接口设计文档

## 策略接口设计

策略需要实现以下接口：

```python
class AnalysisPolicy:
    # 策略标识符
    def get_name(self) -> str:
        pass
    
    # 判断是否处理此帧
    # 返回 False 时，框架会跳过该帧并标记为 skipped
    def should_process(self, frame_index: int, total_frames: int) -> bool:
        pass
    
    # 声明需要的上下文范围
    # 返回：(start_offset, end_offset)，相对于当前帧的偏移量
    # 例如：(-1, 1) 表示需要前1帧和后1帧
    # 框架会根据此范围加载上下文帧，避免加载不必要的数据
    def get_context_range(self, frame_index: int, total_frames: int) -> tuple[int, int]:
        pass
    
    # 分析图片
    # target_frame: 当前要分析的帧信息
    #   - 格式: {'index': int, 'url': str, 'data': bytes}
    #   - 'data' 是图片的二进制数据（已通过 HTTP GET 下载到内存）
    #   - 策略不需要关心图片来源，只处理 bytes 数据
    # context_frames: 上下文帧信息数组
    #   - 格式: [{'index': int, 'url': str, 'data': bytes}, ...]（已按 index 排序）
    #   - 同样，'data' 是图片的二进制数据
    # bedrock_client: 框架提供的 Bedrock 客户端（处理重试、限流）
    # 返回：key-value 格式的结果，将合并到 Frame.policy_results 中
    def analyze(
        self,
        target_frame: dict,
        context_frames: list[dict],
        bedrock_client: BedrockClient
    ) -> dict:
        pass
```

## Policy 自动发现和加载

### 目录结构

```
lambda/policies/
├── __init__.py              # Policy 注册和加载逻辑
├── base.py                  # AnalysisPolicy 基类
├── drinking_detection_policy.py  # Production policy
├── other_policy.py          # Production policy
└── test/                    # Test policies 目录
    ├── __init__.py
    ├── empty_policy.py      # Test policy
    └── failing_policy.py    # Test policy
```

### 加载规则

1. `lambda/policies/` 目录下的 `*_policy.py` 文件是 **Production Policy**
2. `lambda/policies/test/` 目录下的是 **Test Policy**

### 加载逻辑

| 场景 | ENABLED_POLICIES | 加载的 policies |
|------|------------------|-----------------|
| Prod 环境（默认） | 不设置 | 只加载 production policies |
| Test 环境 | 不设置 | 加载所有 policies（包括 test） |
| 指定 policy | `drinking_detection` | 只加载指定的 |
| 指定多个 | `policy1,policy2` | 加载指定的多个 |

### 环境判断

通过 `ENVIRONMENT` 环境变量判断是否为测试环境：
- `test`、`testing`、`dev`、`development`、`local` → 测试环境
- 其他值或不设置 → 生产环境

### 新增 Policy

**当前已注册的 Production Policy：**
- `DrinkingDetectionPolicy` - 喝东西检测
- `PersonAppearancePolicy` - 人物外观特征分析
- `StreamerBehaviorPolicy` - 直播主播行为检测（单阶段）
- `StreamerBehaviorV2Policy` - 直播主播行为检测（两阶段：Nova Lite 描述 + Claude 4.5 打标签）
- `StreamQualityPolicy` - 直播质量检测（连续5帧分析）

**新增 Production Policy：**
1. 在 `lambda/policies/` 目录下创建 `new_policy.py`
2. 实现 `AnalysisPolicy` 接口
3. 在 `__init__.py` 中导入并在 `_init_registry()` 中注册：
   ```python
   from .new_policy import NewPolicy
   _register_policy(NewPolicy, is_test=False)
   ```

**新增 Test Policy：**
1. 在 `lambda/policies/test/` 目录下创建 `new_test_policy.py`
2. 实现 `AnalysisPolicy` 接口
3. 在 `__init__.py` 的 `_init_registry()` 中注册：
   ```python
   _register_policy(NewTestPolicy, is_test=True)
   ```

### 代码示例

```python
# lambda/policies/__init__.py

def get_policy_map(enabled_policies: list = None) -> dict:
    """
    根据配置返回要启用的 policy 实例
    
    加载逻辑：
    1. 如果 enabled_policies 非空，按指定的 policy 加载（优先级最高）
    2. 如果 enabled_policies 为空或 None：
       - 非 test 环境：加载所有 production policies
       - test 环境：加载所有 policies（包括 test）
    """
    # ... 实现逻辑
```

## 内置策略示例

### 1. 喝东西检测策略（DrinkingDetectionPolicy）

**策略说明：**
使用 AWS Bedrock Nova Lite 模型检测视频帧中的人物是否在喝东西。通过分析目标帧及其前后各1帧（共3帧）的连续动作来提高检测准确性。

**实现代码：**
```python
class DrinkingDetectionPolicy(AnalysisPolicy):
    def get_name(self) -> str:
        return 'drinking_detection'
    
    def should_process(self, frame_index: int, total_frames: int) -> bool:
        # 处理所有帧
        return True
    
    def get_context_range(self, frame_index: int, total_frames: int) -> tuple[int, int]:
        # 需要前后各1帧
        return (-1, 1)
    
    def analyze(
        self,
        target_frame: dict,
        context_frames: list[dict],
        bedrock_client: BedrockClient
    ) -> dict:
        # 选择前后各1帧作为上下文（共3帧）
        prev_frame = next((f for f in context_frames if f['index'] == target_frame['index'] - 1), None)
        next_frame = next((f for f in context_frames if f['index'] == target_frame['index'] + 1), None)
        
        # 准备图片数据
        images = []
        if prev_frame:
            images.append(prev_frame['data'])
        images.append(target_frame['data'])
        if next_frame:
            images.append(next_frame['data'])
        
        # 构建 prompt
        prompt = """
你是一个图片打标专家。我会给你提供连续的3张视频帧，请分析目标帧（中间那张）中的人物是否正在喝东西。
...
"""
        
        # 调用 Bedrock Nova Lite
        response = bedrock_client.invoke(
            'us.amazon.nova-lite-v1:0',
            prompt,
            images
        )
        
        # 解析结果
        result = json.loads(response['output']['message']['content'][0]['text'])
        
        # 返回 key-value 结果（使用策略名作为前缀避免冲突）
        return {
            'drinking_is_drinking': result['is_drinking'],
            'drinking_confidence': result['confidence'],
            'drinking_details': result['details']
        }
```

**结果示例：**
```json
{
  "frame_index": 100,
  "frame_key": "video/frame-100.jpg",
  "status": "completed",
  "results": {
    "drinking_is_drinking": true,
    "drinking_confidence": 0.92,
    "drinking_details": "人物正在将杯子倾斜送入口中饮用"
  }
}
```

### 2. 人物外观特征分析策略（PersonAppearancePolicy）

**策略说明：**
使用 AWS Bedrock Nova Lite 模型分析图片中人物的外观特征，包括年龄段、族裔、肤色深浅、颜值评级和外观特征标签。只需要单张图片，不需要前后帧上下文。

**标签定义：**

| 维度 | 字段名 | 可选值 |
|------|--------|--------|
| 年龄段 | age_group | infant(婴儿), child(儿童), teenager(青少年), young_adult(青年), middle_aged(中年), senior(老年) |
| 族裔 | ethnicity | east_asian(东亚), southeast_asian(东南亚), south_asian(南亚), caucasian(白人), african(黑人), latino(拉丁裔), middle_eastern(中东), mixed(混血) |
| 肤色 | skin_tone | very_fair(极白), fair(白皙), light(浅色), medium(中等), tan(小麦色), dark(深色), very_dark(极深) |
| 颜值 | overall_level | stunning(惊艳), attractive(好看), average(普通), below_avg(一般) |
| 特征 | features | 五官: sharp_features, soft_features, big_eyes, high_nose<br>脸型: oval_face, round_face, square_face, v_face<br>气质: elegant, cute, cool, mature, fresh |

**实现代码：**
```python
class PersonAppearancePolicy(AnalysisPolicy):
    def get_name(self) -> str:
        return 'person_appearance'
    
    def should_process(self, frame_index: int, total_frames: int) -> bool:
        return True
    
    def get_context_range(self, frame_index: int, total_frames: int) -> tuple[int, int]:
        # 不需要上下文帧
        return (0, 0)
    
    def analyze(
        self,
        target_frame: dict,
        context_frames: list[dict],
        bedrock_client: BedrockClient
    ) -> dict:
        images = [target_frame['data']]
        prompt = self._build_prompt()  # 包含完整标签定义的英文 Prompt
        
        response = bedrock_client.invoke(
            get_model_id('nova-lite'),
            prompt,
            images
        )
        
        result = self._parse_response(response)
        return self._format_result(result)
```

**结果示例：**
```json
{
  "person_age_group": "young_adult",
  "person_ethnicity": "east_asian",
  "person_skin_tone": "fair",
  "person_overall_level": "attractive",
  "person_features": ["big_eyes", "v_face", "fresh"],
  "person_confidence": 0.9
}
```

### 3. 其他策略示例

- **顺序策略**：
  - `should_process` 总是返回 True
  - `get_context_range` 返回 (0, 0)，不需要上下文
  - 只使用 target_frame
  
- **间隔策略**：
  - `should_process` 每 10 帧返回一次 True
  - `get_context_range` 返回 (0, 0)，不需要上下文
  - 只使用 target_frame
  
- **上下文策略**：
  - `should_process` 总是返回 True
  - `get_context_range` 返回 (-30, 30)，需要前后各30帧
  - 使用 target_frame 和 context_frames

## Model ID 管理

为了方便在策略中使用不同的 AI 模型，`base.py` 提供了 `get_model_id()` 函数，支持通过别名获取完整的 Bedrock Model ID。

### 使用方法

```python
from policies.base import get_model_id

# 完整名称
get_model_id('nova-lite')       # -> 'amazon.nova-lite-v1:0'
get_model_id('claude-4.5-sonnet')  # -> 'anthropic.claude-sonnet-4-5-20250929-v1:0'

# 简短别名
get_model_id('lite')    # -> nova-2-lite
get_model_id('sonnet')  # -> claude-4.5-sonnet
get_model_id('opus')    # -> claude-4.5-opus
```

### 支持的模型

**Nova 2 系列（最新）：**

| 别名 | Model ID |
|------|----------|
| nova-2-lite | amazon.nova-2-lite-v1:0 |
| nova-2-lite-256k | amazon.nova-2-lite-v1:0:256k |
| nova-2-sonic | amazon.nova-2-sonic-v1:0 |
| nova-2-embeddings | amazon.nova-2-multimodal-embeddings-v1:0 |

**Nova 1 系列：**

| 别名 | Model ID |
|------|----------|
| nova-premier | amazon.nova-premier-v1:0 |
| nova-premier-8k/20k/1000k/mm | amazon.nova-premier-v1:0:8k 等 |
| nova-pro | amazon.nova-pro-v1:0 |
| nova-pro-24k/300k | amazon.nova-pro-v1:0:24k 等 |
| nova-lite | amazon.nova-lite-v1:0 |
| nova-lite-24k/300k | amazon.nova-lite-v1:0:24k 等 |
| nova-micro | amazon.nova-micro-v1:0 |
| nova-micro-24k/128k | amazon.nova-micro-v1:0:24k 等 |
| nova-sonic | amazon.nova-sonic-v1:0 |
| nova-canvas | amazon.nova-canvas-v1:0 |
| nova-reel | amazon.nova-reel-v1:0 |

**Claude 3.x 系列：**

| 别名 | Model ID |
|------|----------|
| claude-3-haiku | anthropic.claude-3-haiku-20240307-v1:0 |
| claude-3-sonnet | anthropic.claude-3-sonnet-20240229-v1:0 |
| claude-3-opus | anthropic.claude-3-opus-20240229-v1:0 |
| claude-3.5-haiku | anthropic.claude-3-5-haiku-20241022-v1:0 |
| claude-3.5-sonnet | anthropic.claude-3-5-sonnet-20241022-v2:0 |
| claude-3.7-sonnet | anthropic.claude-3-7-sonnet-20250219-v1:0 |

**Claude 4.x 系列：**

| 别名 | Model ID |
|------|----------|
| claude-4-sonnet | anthropic.claude-sonnet-4-20250514-v1:0 |
| claude-4.5-sonnet | anthropic.claude-sonnet-4-5-20250929-v1:0 |
| claude-4.5-haiku | anthropic.claude-haiku-4-5-20251001-v1:0 |
| claude-4-opus | anthropic.claude-opus-4-20250514-v1:0 |
| claude-4.1-opus | anthropic.claude-opus-4-1-20250805-v1:0 |
| claude-4.5-opus | anthropic.claude-opus-4-5-20251101-v1:0 |

### 简短别名

| 别名 | 指向 |
|------|------|
| lite | nova-2-lite |
| pro | nova-pro |
| premier | nova-premier |
| micro | nova-micro |
| haiku | claude-4.5-haiku |
| sonnet | claude-4.5-sonnet |
| opus | claude-4.5-opus |

## 职责划分

**策略开发者职责：**
- 实现策略接口
- 使用框架提供的 BedrockClient 调用模型（可选择不同模型）
- 返回 key-value 格式的结果，确保 key 不与其他策略冲突

**框架职责：**
- 提供 BedrockClient 库（处理重试、限流、错误）
- 下载图片并传递给策略（bytes 格式）
- 管理 Frame 状态
- 调度策略执行（顺序遍历）
- 合并所有策略的 key-value 结果到 Frame.policy_results 中
- 记录每个策略的执行状态到 Frame.policy_status 中

## 配置说明

```bash
# Bedrock
BEDROCK_MODEL_ID=anthropic.claude-3-sonnet-20240229-v1:0  # 默认模型
BEDROCK_RETRY_DELAYS=2,4,8      # 重试延迟（秒），数量即为最大重试次数

# Context
CONTEXT_MAX_FRAMES=60           # 最大上下文帧数（前后各60）

# Worker
WORKER_CONCURRENCY=10           # Lambda 并发实例数（通过 SQS MaximumConcurrency 配置）

# Callback（hardcode：每 30 秒重试一次，最多 5 次，在 Lambda 内完成）

# Frame
FRAME_MAX_RETRIES=3             # 单帧最大重试次数

# Policy
ENABLED_POLICIES=policy1,policy2,policy3  # 可选，不设置则使用默认加载逻辑
ENVIRONMENT=prod                          # 可选，用于判断是否为测试环境

# Health Check
HEALTH_CHECK_INTERVAL=300       # 健康检查间隔（秒）
REQUEST_TIMEOUT=7200            # 请求超时时间（秒，默认2小时）

# Results
RESULTS_S3_BUCKET=my-results-bucket
RESULTS_PRESIGNED_URL_EXPIRATION=86400  # 预签名 URL 有效期（秒，默认1天）
```

**配置说明：**
- `BEDROCK_RETRY_DELAYS`: 数组长度即为最大重试次数
- `WORKER_CONCURRENCY`: 通过 SQS Lambda 触发器的 MaximumConcurrency 配置
- `CONTEXT_MAX_FRAMES`: 每帧最多加载前后各60帧作为上下文
- `REQUEST_TIMEOUT`: Health Check 超时限制，超时后强制完成
- `ENABLED_POLICIES`: 可选，不设置则根据环境自动加载
- `ENVIRONMENT`: 可选，用于判断是否为测试环境
- 回调重试：hardcode 在代码中，每 30 秒重试一次，最多 5 次

### 4. 直播主播行为检测策略（StreamerBehaviorPolicy）

**策略说明：**
作为直播平台运营检测人员，监测主播的行为表现。使用 Nova Lite 模型单次调用完成检测。

**检测内容：**
- 是否看着观众（面向镜头）
- 是否对着墙壁（身后一堵墙）
- 是否躺着
- 是否在户外

**标签定义：**

| 维度 | 字段名 | 类型 | 说明 |
|------|--------|------|------|
| 看着观众 | looking_at_audience | boolean | 主播是否面向镜头、与观众互动 |
| 对着墙壁 | facing_wall | boolean | 背景是否为纯色/简单墙壁 |
| 躺着 | lying_down | boolean | 主播是否躺着或斜靠 |
| 户外 | outdoors | boolean | 是否在户外环境 |
| 行为标签 | behavior_tags | array | 详细行为标签列表 |

**行为标签（behavior_tags）可选值：**

| 类别 | 标签 | 说明 |
|------|------|------|
| 互动 | engaged | 积极与观众互动 |
| 互动 | distracted | 注意力分散 |
| 互动 | interactive | 正在回复评论 |
| 姿态 | sitting | 坐着 |
| 姿态 | standing | 站着 |
| 姿态 | lying | 躺着 |
| 姿态 | moving | 移动中 |
| 环境 | home_setup | 家庭直播环境 |
| 环境 | professional_studio | 专业直播间 |
| 环境 | plain_background | 简单背景 |
| 环境 | decorated_background | 装饰背景 |
| 环境 | outdoor_street | 户外街道 |
| 环境 | outdoor_nature | 户外自然环境 |

**实现代码：**
```python
class StreamerBehaviorPolicy(AnalysisPolicy):
    def get_name(self) -> str:
        return 'streamer_behavior'
    
    def get_context_range(self, frame_index: int, total_frames: int) -> tuple[int, int]:
        return (0, 0)  # 不需要上下文帧
    
    def analyze(self, target_frame, context_frames, bedrock_client, storage_helper):
        images = [target_frame['data']]
        response = bedrock_client.invoke(get_model_id('nova-lite'), prompt, images)
        # 解析并返回结果
```

**结果示例：**
```json
{
  "streamer_looking_at_audience": true,
  "streamer_facing_wall": false,
  "streamer_lying_down": false,
  "streamer_outdoors": false,
  "streamer_behavior_tags": ["engaged", "sitting", "home_setup"],
  "streamer_confidence": 0.9
}
```

### 5. 直播主播行为检测策略 V2（StreamerBehaviorV2Policy）

**策略说明：**
两阶段分析策略，提供更详细的分析结果：
1. **第一阶段**：使用 Nova Lite 详细描述图片内容（人物朝向、姿态、背景环境等）
2. **第二阶段**：使用 Claude 4.5 Sonnet 基于描述进行标签判定

**优势：**
- 分离图像理解和逻辑判断
- 提供详细的图片描述和推理过程
- 更准确的标签判定

**实现代码：**
```python
class StreamerBehaviorV2Policy(AnalysisPolicy):
    def get_name(self) -> str:
        return 'streamer_behavior_v2'
    
    def analyze(self, target_frame, context_frames, bedrock_client, storage_helper):
        images = [target_frame['data']]
        
        # 第一阶段：Nova Lite 详细描述图片
        description = self._stage1_describe(bedrock_client, images)
        
        # 第二阶段：Claude 4.5 Sonnet 打标签
        result = self._stage2_label(bedrock_client, description)
        
        return self._format_result(result)
    
    def _stage1_describe(self, bedrock_client, images):
        # Nova Lite 描述图片内容
        response = bedrock_client.invoke(get_model_id('nova-lite'), describe_prompt, images)
        return response['output']['message']['content'][0]['text']
    
    def _stage2_label(self, bedrock_client, description):
        # Claude 4.5 Sonnet 基于描述打标签
        response = bedrock_client.invoke(get_model_id('claude-4.5-sonnet'), label_prompt, [])
        return self._parse_response(response)
```

**结果示例：**
```json
{
  "streamer_looking_at_audience": true,
  "streamer_facing_wall": false,
  "streamer_lying_down": false,
  "streamer_outdoors": false,
  "streamer_behavior_tags": ["engaged", "sitting", "home_setup", "decorated_background"],
  "streamer_confidence": 0.95,
  "streamer_description": "The image depicts a live streaming scene featuring a young woman...",
  "streamer_reasoning": "The streamer is explicitly described as looking directly at the camera..."
}
```

### 6. 直播质量检测策略（StreamQualityPolicy）

**策略说明：**
使用连续 5 帧（5 秒）分析直播质量，检测摄像头和网络问题。单帧问题不代表真正的质量问题，只有连续多帧出现问题才表明存在实际问题。

**检测内容：**
- 摄像头质量（模糊、抖动、曝光）
- 网络质量（卡顿、花屏、丢帧）

**上下文配置：**
```python
def get_context_range(self, frame_index: int, total_frames: int) -> tuple[int, int]:
    return (-2, 2)  # 需要前后各2帧，共5帧
```

**质量等级：**

| 等级 | 说明 |
|------|------|
| excellent | 专业质量，无问题 |
| good | 轻微问题，观看体验良好 |
| fair | 有问题但可接受 |
| poor | 明显问题影响观看 |
| unwatchable | 严重问题，无法观看 |

**检测问题标签：**

| 类别 | 标签 | 说明 |
|------|------|------|
| 摄像头 | blur | 模糊/失焦 |
| 摄像头 | shake | 抖动/不稳定 |
| 摄像头 | overexposed | 过曝 |
| 摄像头 | underexposed | 欠曝 |
| 摄像头 | low_resolution | 低分辨率 |
| 摄像头 | bad_framing | 构图不佳 |
| 网络 | frozen | 画面冻结 |
| 网络 | pixelation | 马赛克/花屏 |
| 网络 | artifacts | 视觉伪影 |
| 网络 | frame_drop | 丢帧 |
| 网络 | buffering | 缓冲中 |
| 网络 | lag | 延迟 |

**实现代码：**
```python
class StreamQualityPolicy(AnalysisPolicy):
    def get_name(self) -> str:
        return 'stream_quality'
    
    def should_process(self, frame_index: int, total_frames: int) -> bool:
        # 只处理有足够上下文的帧
        return frame_index >= 2 and frame_index < total_frames - 2
    
    def get_context_range(self, frame_index: int, total_frames: int) -> tuple[int, int]:
        return (-2, 2)  # 前后各2帧
    
    def analyze(self, target_frame, context_frames, bedrock_client, storage_helper):
        # 构建有序帧列表：2 prev + target + 2 next
        all_frames = sorted_prev + [target_frame] + sorted_next
        images = [f['data'] for f in all_frames]
        
        response = bedrock_client.invoke(get_model_id('nova-lite'), prompt, images)
        return self._format_result(result)
```

**结果示例：**
```json
{
  "quality_camera": "excellent",
  "quality_network": "excellent",
  "quality_overall": "excellent",
  "quality_issues": [],
  "quality_consistent_issues": [],
  "quality_intermittent_issues": [],
  "quality_frozen_detected": false,
  "quality_confidence": 0.95
}
```

**问题检测示例（有问题时）：**
```json
{
  "quality_camera": "fair",
  "quality_network": "poor",
  "quality_overall": "poor",
  "quality_issues": ["blur", "pixelation", "frame_drop"],
  "quality_consistent_issues": ["pixelation"],
  "quality_intermittent_issues": ["blur", "frame_drop"],
  "quality_frozen_detected": false,
  "quality_confidence": 0.88
}
```

## 本地测试

使用 `test_policy_local.py` 脚本可以在本地测试 Policy：

```bash
# 1. 修改配置文件
vim test_policy_config.yaml

# 2. 运行测试
python test_policy_local.py
```

**配置文件示例（test_policy_config.yaml）：**
```yaml
# 要测试的 Policy 名称
policy: stream_quality

# AWS 区域
region: us-east-1

# 上下文帧数量
prev_count: 2
next_count: 2

# 步长
step: 1

# 图片列表
images:
  - /path/to/frame1.jpg
  - /path/to/frame2.jpg
  - /path/to/frame3.jpg
  - /path/to/frame4.jpg
  - /path/to/frame5.jpg
  - /path/to/frame6.jpg
```
