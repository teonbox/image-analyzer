# Drinking Detection Policy 测试用例

> **说明**: 本文档中的测试用例对应 [tech.md - 策略接口设计](../tech.md#策略接口设计) 中定义的 `AnalysisPolicy` 接口。

## 测试图片准备

### 图片集说明

为了测试喝东西检测策略，需要准备 3 组图片，每组 3 张连续帧：

**组 1: 正在喝东西（drinking）**
- `image1.jpg`: 杯子在桌上或手中
- `image2.jpg`: 杯子移动向嘴部
- `image3.jpg`: 杯子倾斜送入口中，正在饮用

**组 2: 拿着饮品但不在喝（holding）**
- `image1.jpg`: 手持杯子展示
- `image2.jpg`: 手持杯子讲解（杯子位置不变）
- `image3.jpg`: 继续展示杯子（杯子位置不变）

**组 3: 完全没在喝东西（no-drinking）**
- `image1.jpg`: 人物在说话
- `image2.jpg`: 人物在做手势
- `image3.jpg`: 人物在讲解

### 图片存储位置
```
test/fixtures/drinking-detection/
├── drinking/
│   ├── image1.jpg
│   ├── image2.jpg
│   └── image3.jpg
├── holding/
│   ├── image1.jpg
│   ├── image2.jpg
│   └── image3.jpg
└── no-drinking/
    ├── image1.jpg
    ├── image2.jpg
    └── image3.jpg
```

## Layer 1: 单元测试

### 1.1 策略基本功能测试


#### DRINK-001: shouldProcess 总是返回 True

**测试目标**: `DrinkingDetectionPolicy.should_process()`  
**测试层级**: Unit Test  
**Mock**: 无需 AWS 服务

**输入**：
- frame_index = 任意值 (0, 10, 50, 99)
- total_frames = 100

**预期结果**：
- shouldProcess 返回 True

**验证点**：
- 策略处理所有帧

---

#### DRINK-002: getName 返回正确的策略名称

**测试目标**: `DrinkingDetectionPolicy.get_name()`  
**测试层级**: Unit Test  
**Mock**: 无需 AWS 服务

**预期结果**：
- getName() 返回 "drinking_detection"

**验证点**：
- 策略标识符正确

---

### 1.2 上下文范围声明测试

#### DRINK-003: 声明需要前后各 1 帧

**测试目标**: `DrinkingDetectionPolicy.get_context_range()`  
**测试层级**: Unit Test  
**Mock**: 无需 AWS 服务

**输入**：
- frame_index = 任意值 (0, 50, 99)
- total_frames = 100

**预期结果**：
- get_context_range() 返回 (-1, 1)

**验证点**：
- 策略声明的上下文范围正确

---

## Layer 2: 组件测试

### 2.1 正在喝东西场景测试


#### DRINK-COMP-001: 正在喝东西 + 有前后帧

**测试目标**: `DrinkingDetectionPolicy.analyze()` - 完整上下文场景  
**测试层级**: Component Test  
**Mock**: S3, Bedrock (使用 moto)

**场景说明**：
- 使用 drinking 组图片
- 目标帧是 drinking-002.jpg（中间帧）
- 有前后各 1 帧

**前置条件**：
- Mock S3 中有图片: drinking-001.jpg, drinking-002.jpg, drinking-003.jpg
- Mock Bedrock 响应

**输入**：
- targetFrame: {index: 1, key: "drinking/drinking-002.jpg"}
- contextFrames: [{index: 0, key: "drinking/drinking-001.jpg"}, {index: 1, key: "drinking/drinking-002.jpg"}, {index: 2, key: "drinking/drinking-003.jpg"}]

**预期结果**：
```json
{
  "drinking_is_drinking": true,
  "drinking_confidence": > 0.8,
  "drinking_details": "人物正在将杯子倾斜送入口中饮用..."
}
```

**验证点**：
1. 加载了 3 张图片
2. 调用了 Bedrock Nova Lite
3. 返回结果包含 drinking_is_drinking, drinking_confidence, drinking_details
4. drinking_is_drinking = true
5. drinking_confidence 较高（> 0.8）

---

#### DRINK-COMP-002: 正在喝东西 + 只有前帧无后帧

**测试目标**: `DrinkingDetectionPolicy.analyze()` - 边界场景（最后一帧）  
**测试层级**: Component Test  
**Mock**: S3, Bedrock (使用 moto)

**场景说明**：
- 使用 drinking 组图片
- 目标帧是 drinking-003.jpg（最后一帧）
- 只有前 2 帧，没有后帧

**前置条件**：
- Mock S3 中有图片: drinking-001.jpg, drinking-002.jpg, drinking-003.jpg

**输入**：
- targetFrame: {index: 2, key: "drinking/drinking-003.jpg"}
- contextFrames: [{index: 0, key: "drinking/drinking-001.jpg"}, {index: 1, key: "drinking/drinking-002.jpg"}, {index: 2, key: "drinking/drinking-003.jpg"}]

**预期结果**：
```json
{
  "drinking_is_drinking": true,
  "drinking_confidence": > 0.7,
  "drinking_details": "..."
}
```

**验证点**：
1. 只加载了 2 张图片（前1帧 + 目标帧）
2. 没有尝试加载不存在的后帧
3. drinking_is_drinking = true
4. 策略能够基于 2 张图片做出判断

---

#### DRINK-COMP-003: 正在喝东西 + 只有后帧无前帧

**测试目标**: `DrinkingDetectionPolicy.analyze()` - 边界场景（第一帧）  
**测试层级**: Component Test  
**Mock**: S3, Bedrock (使用 moto)

**场景说明**：
- 使用 drinking 组图片
- 目标帧是 drinking-001.jpg（第一帧）
- 只有后 2 帧，没有前帧

**前置条件**：
- Mock S3 中有图片: drinking-001.jpg, drinking-002.jpg, drinking-003.jpg

**输入**：
- targetFrame: {index: 0, key: "drinking/drinking-001.jpg"}
- contextFrames: [{index: 0, key: "drinking/drinking-001.jpg"}, {index: 1, key: "drinking/drinking-002.jpg"}, {index: 2, key: "drinking/drinking-003.jpg"}]

**预期结果**：
```json
{
  "drinking_is_drinking": true,
  "drinking_confidence": > 0.7,
  "drinking_details": "..."
}
```

**验证点**：
1. 只加载了 2 张图片（目标帧 + 后1帧）
2. drinking_is_drinking = true

---

#### DRINK-COMP-004: 正在喝东西 + 相邻帧丢失

**测试目标**: `DrinkingDetectionPolicy.analyze()` - 容错场景（丢帧）  
**测试层级**: Component Test  
**Mock**: S3, Bedrock (使用 moto)

**场景说明**：
- 使用 drinking 组图片
- 目标帧是 drinking-002.jpg
- 前一帧 drinking-001.jpg 丢失

**前置条件**：
- Mock S3 中只有图片: drinking-002.jpg, drinking-003.jpg
- 缺少: drinking-001.jpg

**输入**：
- targetFrame: {index: 1, key: "drinking/drinking-002.jpg"}
- contextFrames: [{index: 1, key: "drinking/drinking-002.jpg"}, {index: 2, key: "drinking/drinking-003.jpg"}]

**预期结果**：
```json
{
  "drinking_is_drinking": true,
  "drinking_confidence": > 0.6,
  "drinking_details": "..."
}
```

**验证点**：
1. 只加载了 2 张图片（目标帧 + 后1帧）
2. 跳过了丢失的前帧
3. drinking_is_drinking = true
4. 策略能够处理丢帧情况

---

#### DRINK-COMP-005: 正在喝东西 + 孤立帧

**测试目标**: `DrinkingDetectionPolicy.analyze()` - 极端场景（无上下文）  
**测试层级**: Component Test  
**Mock**: S3, Bedrock (使用 moto)

**场景说明**：
- 使用 drinking 组图片
- 只有目标帧 drinking-002.jpg
- 没有任何上下文帧

**前置条件**：
- Mock S3 中只有图片: drinking-002.jpg

**输入**：
- targetFrame: {index: 0, key: "drinking/drinking-002.jpg"}
- contextFrames: [{index: 0, key: "drinking/drinking-002.jpg"}]

**预期结果**：
```json
{
  "drinking_is_drinking": true 或 false,
  "drinking_confidence": 可能较低,
  "drinking_details": "..."
}
```

**验证点**：
1. 只加载了 1 张图片（目标帧）
2. 策略能够处理单帧情况
3. 返回结果（但置信度可能较低）

---

### 2.2 拿着饮品但不在喝场景测试


#### DRINK-COMP-006: 拿着饮品不在喝 + 有前后帧

**测试目标**: `DrinkingDetectionPolicy.analyze()` - 区分"拿着"和"喝"  
**测试层级**: Component Test  
**Mock**: S3, Bedrock (使用 moto)

**场景说明**：
- 使用 holding 组图片
- 目标帧是 holding-002.jpg（中间帧）
- 有前后各 1 帧

**前置条件**：
- Mock S3 中有图片: holding-001.jpg, holding-002.jpg, holding-003.jpg
- Mock Bedrock 响应

**输入**：
- targetFrame: {index: 1, key: "holding/holding-002.jpg"}
- contextFrames: [{index: 0, key: "holding/holding-001.jpg"}, {index: 1, key: "holding/holding-002.jpg"}, {index: 2, key: "holding/holding-003.jpg"}]

**预期结果**：
```json
{
  "drinking_is_drinking": false,
  "drinking_confidence": > 0.8,
  "drinking_details": "人物只是手持饮品在讲解，饮品位置未变化，未观察到进食动作"
}
```

**验证点**：
1. 加载了 3 张图片
2. drinking_is_drinking = false
3. drinking_confidence 较高（> 0.8）
4. 能够区分"拿着饮品"和"正在吃"

---

#### DRINK-COMP-007: 拿着饮品不在喝 + 只有前帧无后帧

**测试目标**: `DrinkingDetectionPolicy.analyze()` - 区分"拿着"和"喝"（边界场景）  
**测试层级**: Component Test  
**Mock**: S3, Bedrock (使用 moto)

**场景说明**：
- 使用 holding 组图片
- 目标帧是 holding-003.jpg（最后一帧）
- 只有前 2 帧，没有后帧

**前置条件**：
- Mock S3 中有图片: holding-001.jpg, holding-002.jpg, holding-003.jpg

**输入**：
- targetFrame: {index: 2, key: "holding/holding-003.jpg"}
- contextFrames: [{index: 0, key: "holding/holding-001.jpg"}, {index: 1, key: "holding/holding-002.jpg"}, {index: 2, key: "holding/holding-003.jpg"}]

**预期结果**：
```json
{
  "drinking_is_drinking": false,
  "drinking_confidence": > 0.7,
  "drinking_details": "..."
}
```

**验证点**：
1. drinking_is_drinking = false
2. 策略能够基于 2 张图片做出判断

---

#### DRINK-COMP-008: 拿着饮品不在喝 + 只有后帧无前帧

**测试目标**: `DrinkingDetectionPolicy.analyze()` - 区分"拿着"和"喝"（边界场景）  
**测试层级**: Component Test  
**Mock**: S3, Bedrock (使用 moto)

**场景说明**：
- 使用 holding 组图片
- 目标帧是 holding-001.jpg（第一帧）
- 只有后 2 帧，没有前帧

**前置条件**：
- Mock S3 中有图片: holding-001.jpg, holding-002.jpg, holding-003.jpg

**输入**：
- targetFrame: {index: 0, key: "holding/holding-001.jpg"}
- contextFrames: [{index: 0, key: "holding/holding-001.jpg"}, {index: 1, key: "holding/holding-002.jpg"}, {index: 2, key: "holding/holding-003.jpg"}]

**预期结果**：
```json
{
  "drinking_is_drinking": false,
  "drinking_confidence": > 0.7,
  "drinking_details": "..."
}
```

**验证点**：
1. drinking_is_drinking = false

---

#### DRINK-COMP-009: 拿着饮品不在喝 + 相邻帧丢失

**测试目标**: `DrinkingDetectionPolicy.analyze()` - 区分"拿着"和"喝"（容错场景）  
**测试层级**: Component Test  
**Mock**: S3, Bedrock (使用 moto)

**场景说明**：
- 使用 holding 组图片
- 目标帧是 holding-002.jpg
- 前一帧 holding-001.jpg 丢失

**前置条件**：
- Mock S3 中只有图片: holding-002.jpg, holding-003.jpg

**输入**：
- targetFrame: {index: 1, key: "holding/holding-002.jpg"}
- contextFrames: [{index: 1, key: "holding/holding-002.jpg"}, {index: 2, key: "holding/holding-003.jpg"}]

**预期结果**：
```json
{
  "drinking_is_drinking": false,
  "drinking_confidence": > 0.6,
  "drinking_details": "..."
}
```

**验证点**：
1. drinking_is_drinking = false
2. 策略能够处理丢帧情况

---

#### DRINK-COMP-010: 拿着饮品不在喝 + 孤立帧

**测试目标**: `DrinkingDetectionPolicy.analyze()` - 区分"拿着"和"喝"（极端场景）  
**测试层级**: Component Test  
**Mock**: S3, Bedrock (使用 moto)

**场景说明**：
- 使用 holding 组图片
- 只有目标帧 holding-002.jpg

**前置条件**：
- Mock S3 中只有图片: holding-002.jpg

**输入**：
- targetFrame: {index: 0, key: "holding/holding-002.jpg"}
- contextFrames: [{index: 0, key: "holding/holding-002.jpg"}]

**预期结果**：
```json
{
  "drinking_is_drinking": false 或 true,
  "drinking_confidence": 可能较低,
  "drinking_details": "..."
}
```

**验证点**：
1. 策略能够处理单帧情况
2. 返回结果（但置信度可能较低，因为无法观察动作变化）

---

### 2.3 完全没在喝东西场景测试

#### DRINK-COMP-011: 完全没在喝东西 + 有前后帧

**测试目标**: `DrinkingDetectionPolicy.analyze()` - 识别无饮品场景  
**测试层级**: Component Test  
**Mock**: S3, Bedrock (使用 moto)

**场景说明**：
- 使用 no-drinking 组图片
- 目标帧是 no-drinking-002.jpg（中间帧）
- 有前后各 1 帧

**前置条件**：
- Mock S3 中有图片: no-drinking-001.jpg, no-drinking-002.jpg, no-drinking-003.jpg
- Mock Bedrock 响应

**输入**：
- targetFrame: {index: 1, key: "no-drinking/no-drinking-002.jpg"}
- contextFrames: [{index: 0, key: "no-drinking/no-drinking-001.jpg"}, {index: 1, key: "no-drinking/no-drinking-002.jpg"}, {index: 2, key: "no-drinking/no-drinking-003.jpg"}]

**预期结果**：
```json
{
  "drinking_is_drinking": false,
  "drinking_confidence": > 0.9,
  "drinking_details": "画面中没有饮品，人物在说话或做手势"
}
```

**验证点**：
1. 加载了 3 张图片
2. drinking_is_drinking = false
3. drinking_confidence 很高（> 0.9）
4. 能够识别无饮品场景

---

#### DRINK-COMP-012: 完全没在喝东西 + 只有前帧无后帧

**测试目标**: `DrinkingDetectionPolicy.analyze()` - 识别无饮品场景（边界场景）  
**测试层级**: Component Test  
**Mock**: S3, Bedrock (使用 moto)

**场景说明**：
- 使用 no-drinking 组图片
- 目标帧是 no-drinking-003.jpg（最后一帧）
- 只有前 2 帧，没有后帧

**前置条件**：
- Mock S3 中有图片: no-drinking-001.jpg, no-drinking-002.jpg, no-drinking-003.jpg

**输入**：
- targetFrame: {index: 2, key: "no-drinking/no-drinking-003.jpg"}
- contextFrames: [{index: 0, key: "no-drinking/no-drinking-001.jpg"}, {index: 1, key: "no-drinking/no-drinking-002.jpg"}, {index: 2, key: "no-drinking/no-drinking-003.jpg"}]

**预期结果**：
```json
{
  "drinking_is_drinking": false,
  "drinking_confidence": > 0.9,
  "drinking_details": "..."
}
```

**验证点**：
1. drinking_is_drinking = false
2. 策略能够基于 2 张图片做出判断

---

#### DRINK-COMP-013: 完全没在喝东西 + 只有后帧无前帧

**测试目标**: `DrinkingDetectionPolicy.analyze()` - 识别无饮品场景（边界场景）  
**测试层级**: Component Test  
**Mock**: S3, Bedrock (使用 moto)

**场景说明**：
- 使用 no-drinking 组图片
- 目标帧是 no-drinking-001.jpg（第一帧）
- 只有后 2 帧，没有前帧

**前置条件**：
- Mock S3 中有图片: no-drinking-001.jpg, no-drinking-002.jpg, no-drinking-003.jpg

**输入**：
- targetFrame: {index: 0, key: "no-drinking/no-drinking-001.jpg"}
- contextFrames: [{index: 0, key: "no-drinking/no-drinking-001.jpg"}, {index: 1, key: "no-drinking/no-drinking-002.jpg"}, {index: 2, key: "no-drinking/no-drinking-003.jpg"}]

**预期结果**：
```json
{
  "drinking_is_drinking": false,
  "drinking_confidence": > 0.9,
  "drinking_details": "..."
}
```

**验证点**：
1. drinking_is_drinking = false

---

#### DRINK-COMP-014: 完全没在喝东西 + 相邻帧丢失

**测试目标**: `DrinkingDetectionPolicy.analyze()` - 识别无饮品场景（容错场景）  
**测试层级**: Component Test  
**Mock**: S3, Bedrock (使用 moto)

**场景说明**：
- 使用 no-drinking 组图片
- 目标帧是 no-drinking-002.jpg
- 前一帧 no-drinking-001.jpg 丢失

**前置条件**：
- Mock S3 中只有图片: no-drinking-002.jpg, no-drinking-003.jpg

**输入**：
- targetFrame: {index: 1, key: "no-drinking/no-drinking-002.jpg"}
- contextFrames: [{index: 1, key: "no-drinking/no-drinking-002.jpg"}, {index: 2, key: "no-drinking/no-drinking-003.jpg"}]

**预期结果**：
```json
{
  "drinking_is_drinking": false,
  "drinking_confidence": > 0.9,
  "drinking_details": "..."
}
```

**验证点**：
1. drinking_is_drinking = false
2. 策略能够处理丢帧情况

---

#### DRINK-COMP-015: 完全没在喝东西 + 孤立帧

**测试目标**: `DrinkingDetectionPolicy.analyze()` - 识别无饮品场景（极端场景）  
**测试层级**: Component Test  
**Mock**: S3, Bedrock (使用 moto)

**场景说明**：
- 使用 no-drinking 组图片
- 只有目标帧 no-drinking-002.jpg

**前置条件**：
- Mock S3 中只有图片: no-drinking-002.jpg

**输入**：
- targetFrame: {index: 0, key: "no-drinking/no-drinking-002.jpg"}
- contextFrames: [{index: 0, key: "no-drinking/no-drinking-002.jpg"}]

**预期结果**：
```json
{
  "drinking_is_drinking": false,
  "drinking_confidence": > 0.8,
  "drinking_details": "..."
}
```

**验证点**：
1. drinking_is_drinking = false
2. 策略能够处理单帧情况

---

## Layer 3: 集成测试

### 3.1 真实 Bedrock 测试

#### DRINK-INT-001: 使用真实图片和 Bedrock（正在喝东西）

**测试目标**: `DrinkingDetectionPolicy.analyze()` - 真实 Bedrock 集成  
**测试层级**: Integration Test  
**环境**: 真实 AWS 资源

**前置条件**：
- 真实测试图片已上传到 S3: drinking-001.jpg, drinking-002.jpg, drinking-003.jpg
- 真实 Bedrock 服务可用

**执行步骤**：
1. 从 S3 加载图片
2. 调用真实的 Bedrock Nova Lite
3. 验证返回结果

**验证点**：
1. Bedrock 调用成功
2. drinking_is_drinking = true
3. drinking_confidence > 0.7
4. drinking_details 包含合理的描述

---

#### DRINK-INT-002: 使用真实图片和 Bedrock（拿着饮品不在喝）

**测试目标**: `DrinkingDetectionPolicy.analyze()` - 真实 Bedrock 集成（区分场景）  
**测试层级**: Integration Test  
**环境**: 真实 AWS 资源

**前置条件**：
- 真实测试图片已上传到 S3: holding-001.jpg, holding-002.jpg, holding-003.jpg

**执行步骤**：
1. 从 S3 加载图片
2. 调用真实的 Bedrock Nova Lite
3. 验证返回结果

**验证点**：
1. Bedrock 调用成功
2. drinking_is_drinking = false
3. drinking_confidence > 0.7
4. 能够区分"拿着饮品"和"正在吃"

---

#### DRINK-INT-003: 使用真实图片和 Bedrock（完全没在喝东西）

**测试目标**: `DrinkingDetectionPolicy.analyze()` - 真实 Bedrock 集成（无饮品场景）  
**测试层级**: Integration Test  
**环境**: 真实 AWS 资源

**前置条件**：
- 真实测试图片已上传到 S3: no-drinking-001.jpg, no-drinking-002.jpg, no-drinking-003.jpg

**执行步骤**：
1. 从 S3 加载图片
2. 调用真实的 Bedrock Nova Lite
3. 验证返回结果

**验证点**：
1. Bedrock 调用成功
2. drinking_is_drinking = false
3. drinking_confidence > 0.8
4. 能够识别无饮品场景

---

## 测试数据

### 组件测试图片

组件测试需要准备测试图片（可以是小的测试图片，用于 Mock S3）：

```
test/fixtures/component/drinking-detection/
├── drinking/
│   ├── drinking-001.jpg
│   ├── drinking-002.jpg
│   └── drinking-003.jpg
├── holding/
│   ├── holding-001.jpg
│   ├── holding-002.jpg
│   └── holding-003.jpg
└── no-drinking/
    ├── no-drinking-001.jpg
    ├── no-drinking-002.jpg
    └── no-drinking-003.jpg
```

### 集成测试图片

集成测试需要真实测试图片（需上传到 S3）：

```
test/fixtures/integration/drinking-detection/
├── drinking/
│   ├── drinking-001.jpg
│   ├── drinking-002.jpg
│   └── drinking-003.jpg
├── holding/
│   ├── holding-001.jpg
│   ├── holding-002.jpg
│   └── holding-003.jpg
└── no-drinking/
    ├── no-drinking-001.jpg
    ├── no-drinking-002.jpg
    └── no-drinking-003.jpg
```

上传到 S3：
```bash
aws s3 cp test/fixtures/integration/drinking-detection/ s3://test-bucket/drinking-detection/ --recursive
```

---

## 测试覆盖总结

**Layer 1 单元测试**: 3 个测试用例
- 策略基本功能（shouldProcess, getName）
- 上下文帧选择逻辑

**Layer 2 组件测试**: 15 个测试用例
- 正在喝东西场景 × 5 种上下文场景 = 5 个
- 拿着饮品不在吃场景 × 5 种上下文场景 = 5 个
- 完全没在喝东西场景 × 5 种上下文场景 = 5 个

**Layer 3 集成测试**: 3 个测试用例
- 3 种场景 × 真实 Bedrock = 3 个

**总计**: 21 个测试用例

## Mock 示例代码

### 组件测试 Mock 示例

```python
from moto import mock_s3
import boto3
import json

@mock_s3
def test_drinking_detection_with_context():
    # 创建 mock S3 桶
    s3 = boto3.client('s3', region_name='us-east-1')
    s3.create_bucket(Bucket='test-bucket')
    
    # 上传测试图片
    with open('test/fixtures/component/drinking-detection/mock-images/drinking/drinking-001.jpg', 'rb') as f:
        s3.put_object(Bucket='test-bucket', Key='drinking/drinking-001.jpg', Body=f.read())
    with open('test/fixtures/component/drinking-detection/mock-images/drinking/drinking-002.jpg', 'rb') as f:
        s3.put_object(Bucket='test-bucket', Key='drinking/drinking-002.jpg', Body=f.read())
    with open('test/fixtures/component/drinking-detection/mock-images/drinking/drinking-003.jpg', 'rb') as f:
        s3.put_object(Bucket='test-bucket', Key='drinking/drinking-003.jpg', Body=f.read())
    
    # Mock Bedrock 响应
    mock_bedrock_response = {
        "is_drinking": True,
        "confidence": 0.92,
        "details": "人物正在将杯子倾斜送入口中饮用，正在饮用准备饮用"
    }
    
    # 调用策略
    policy = EatingDetectionPolicy()
    target_frame = FrameInfo(index=1, key='drinking/drinking-002.jpg')
    context_frames = [
        FrameInfo(index=0, key='drinking/drinking-001.jpg'),
        FrameInfo(index=1, key='drinking/drinking-002.jpg'),
        FrameInfo(index=2, key='drinking/drinking-003.jpg')
    ]
    
    # 使用 Mock Bedrock Client
    bedrock_client = MockBedrockClient(mock_bedrock_response)
    storage_helper = StorageHelper(s3_client=s3)
    
    result = policy.analyze(target_frame, context_frames, bedrock_client, storage_helper)
    
    # Assert 结果
    assert result['drinking_is_drinking'] == True
    assert result['drinking_confidence'] > 0.8
    assert 'drinking_details' in result
```
