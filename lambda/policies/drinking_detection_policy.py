import json
from decimal import Decimal
from typing import Dict, Any, List, Tuple
import sys
sys.path.append('/opt/python')
from policies.base import AnalysisPolicy, get_model_id

class DrinkingDetectionPolicy(AnalysisPolicy):
    """
    喝东西检测策略
    
    使用 AWS Bedrock Nova Lite 模型检测视频帧中的人物是否在喝东西。
    通过分析目标帧及其前后各1帧（共3帧）的连续动作来提高检测准确性。
    """
    
    def get_name(self) -> str:
        return 'drinking_detection'
    
    def should_process(self, frame_index: int, total_frames: int) -> bool:
        # 处理所有帧
        return True
    
    def get_context_range(self, frame_index: int, total_frames: int) -> Tuple[int, int]:
        # 需要前后各1帧
        return (-1, 1)
    
    def analyze(
        self,
        target_frame: Dict[str, Any],
        context_frames: List[Dict[str, Any]],
        bedrock_client: Any,
        storage_helper: Any
    ) -> Dict[str, Any]:
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
You are an expert in image labeling. I will provide you with consecutive video frames. Please analyze whether the person in the target frame (middle one) is drinking.

Important distinction:
- "Drinking": Beverage is being brought to mouth, tilting cup/bottle to drink, swallowing, etc.
- "Holding beverage": Just holding cup/bottle, showing beverage, introducing product, but NOT drinking

Analysis points:
1. Observe hand movements (is cup/bottle moving towards mouth?)
2. Observe mouth movements (is mouth open, any drinking action?)
3. Observe container tilt angle (is it tilted to pour liquid?)
4. Use previous/next frames to judge action continuity and changes
5. Distinguish between "drinking" and "holding beverage while talking/presenting"

**Important: You MUST return results in JSON format regardless of image content. If image cannot be analyzed (e.g., solid color background, no person), set is_drinking to false and confidence to 0.0.**

Return results strictly in the following JSON format (no additional text):
{
  "is_drinking": true/false,
  "confidence": 0.0-1.0,
  "details": "Brief description of what you observed"
}
"""
        
        # 调用 Bedrock Nova Lite
        response = bedrock_client.invoke(
            get_model_id('nova-lite'),
            prompt,
            images
        )
        
        # 解析结果
        response_text = response['output']['message']['content'][0]['text']
        
        # 处理 markdown 代码块
        if '```json' in response_text:
            # 提取 JSON 部分
            json_start = response_text.find('```json') + 7
            json_end = response_text.find('```', json_start)
            response_text = response_text[json_start:json_end].strip()
        elif '```' in response_text:
            # 提取代码块
            json_start = response_text.find('```') + 3
            json_end = response_text.find('```', json_start)
            response_text = response_text[json_start:json_end].strip()
        
        # 尝试解析 JSON
        try:
            result = json.loads(response_text)
        except json.JSONDecodeError:
            # 如果解析失败，返回默认值
            result = {
                'is_drinking': False,
                'confidence': 0.0,
                'details': f'无法解析模型响应: {response_text[:100]}'
            }
        
        # 返回 key-value 结果（使用策略名作为前缀避免冲突）
        # 注意：DynamoDB 不支持 float，需要转换为 Decimal
        confidence = result.get('confidence', 0.0)
        if isinstance(confidence, float):
            confidence = Decimal(str(confidence))
        
        return {
            'drinking_is_drinking': result.get('is_drinking', False),
            'drinking_confidence': confidence,
            'drinking_details': result.get('details', '')
        }
