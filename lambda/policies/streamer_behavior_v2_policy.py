"""
直播主播行为检测策略 V2 - 两阶段分析

策略：
1. 第一阶段：使用 Nova Lite 详细描述图片内容
2. 第二阶段：使用 Claude 4.5 Sonnet 基于描述进行标签判定

Role: 直播平台运营检测人员，负责监测主播们的行为表现

检测内容：
- 是否看着观众（面向镜头）
- 是否对着墙壁（身后一堵墙）
- 是否躺着
- 是否在户外
"""
import json
from decimal import Decimal
from typing import Dict, Any, List, Tuple

import sys
sys.path.append('/opt/python')
from policies.base import AnalysisPolicy, get_model_id


class StreamerBehaviorV2Policy(AnalysisPolicy):
    """
    直播主播行为检测策略 V2 - 两阶段分析
    
    第一阶段：Nova Lite 图片描述
    第二阶段：Claude 4.5 Sonnet 标签判定
    """
    
    def get_name(self) -> str:
        return 'streamer_behavior_v2'
    
    def should_process(self, frame_index: int, total_frames: int) -> bool:
        return True
    
    def get_context_range(self, frame_index: int, total_frames: int) -> Tuple[int, int]:
        return (0, 0)
    
    def analyze(
        self,
        target_frame: Dict[str, Any],
        context_frames: List[Dict[str, Any]],
        bedrock_client: Any,
        storage_helper: Any
    ) -> Dict[str, Any]:
        images = [target_frame['data']]
        
        # 第一阶段：Nova Lite 详细描述图片
        description = self._stage1_describe(bedrock_client, images)
        
        # 第二阶段：Claude 4.5 Sonnet 打标签
        result = self._stage2_label(bedrock_client, description)
        
        # 添加描述到结果
        result['description'] = description
        
        return self._format_result(result)
    
    def _stage1_describe(self, bedrock_client: Any, images: list) -> str:
        """第一阶段：使用 Nova Lite 详细描述图片内容"""
        prompt = """You are a professional image analyst. Please provide a detailed description of this live streaming image.

Focus on the following aspects and describe them in detail:

1. **Person Description**
   - Face direction: Where is the person looking? (at camera, away, sideways, up, down)
   - Body posture: How is the person positioned? (sitting upright, lying down, standing, leaning)
   - Expression and engagement: Does the person appear engaged, distracted, tired?

2. **Background Environment**
   - Location type: Is this indoors or outdoors?
   - If indoors: Describe the room (bedroom, living room, studio, etc.)
   - Background elements: What's behind the person? (wall, furniture, window, decorations, nature, street)
   - Wall description: If there's a wall, is it plain/blank or decorated?

3. **Streaming Setup**
   - Camera angle: How is the camera positioned relative to the person?
   - Lighting: How is the lighting? (good, dim, natural, artificial)
   - Any visible streaming equipment?

4. **Overall Scene**
   - General atmosphere of the stream
   - Any notable activities or objects

Please provide a comprehensive description in 3-5 paragraphs. Be specific and detailed."""

        response = bedrock_client.invoke(
            get_model_id('nova-lite'),
            prompt,
            images
        )
        
        return response['output']['message']['content'][0]['text']
    
    def _stage2_label(self, bedrock_client: Any, description: str) -> dict:
        """第二阶段：使用 Claude 4.5 Sonnet 基于描述打标签"""
        prompt = f"""You are a live streaming platform operations inspector. Based on the following image description, determine the streamer's behavior labels.

## Image Description:
{description}

## Your Task:
Analyze the description and determine the following:

### 1. Looking at Audience (looking_at_audience)
Based on the face direction and engagement described:
- true: Person is facing camera, looking at viewers, making eye contact
- false: Person is looking away, turned sideways, not engaging with camera

### 2. Facing Wall (facing_wall)
Based on the background description:
- true: There is a plain/blank wall directly behind the person (minimal decoration, solid color)
- false: Background has furniture, windows, decorations, or is not a plain wall

### 3. Lying Down (lying_down)
Based on the body posture described:
- true: Person is lying down, reclining, or in horizontal position
- false: Person is sitting upright, standing, or in normal streaming posture

### 4. Outdoors (outdoors)
Based on the location and environment described:
- true: Person is outside (street, park, nature, outdoor venue)
- false: Person is indoors (room, studio, indoor venue)

### 5. Behavior Tags (behavior_tags)
Select ALL applicable tags based on the description:

Engagement:
- engaged: Actively engaging with audience
- distracted: Not focused on streaming
- interactive: Responding to chat/comments

Posture:
- sitting: Sitting position
- standing: Standing position
- lying: Lying/reclining position
- moving: In motion/walking

Environment:
- home_setup: Typical home streaming setup
- professional_studio: Professional studio environment
- plain_background: Plain/minimal background
- decorated_background: Decorated/busy background
- outdoor_street: Outdoor street/urban area
- outdoor_nature: Outdoor nature/park area

**IMPORTANT:**
- Base your judgment ONLY on the provided description
- If the description is unclear about something, make your best inference
- Return results in JSON format

Return results strictly in the following JSON format (no additional text):
{{
  "looking_at_audience": true,
  "facing_wall": false,
  "lying_down": false,
  "outdoors": false,
  "behavior_tags": ["engaged", "sitting", "home_setup"],
  "confidence": 0.85,
  "reasoning": "Brief explanation of your judgment"
}}
"""

        response = bedrock_client.invoke(
            get_model_id('claude-4.5-sonnet'),
            prompt,
            []  # 不传图片，只用文本
        )
        
        response_text = response['output']['message']['content'][0]['text']
        return self._parse_response(response_text)
    
    def _parse_response(self, response_text: str) -> dict:
        """解析模型响应"""
        if '```json' in response_text:
            json_start = response_text.find('```json') + 7
            json_end = response_text.find('```', json_start)
            response_text = response_text[json_start:json_end].strip()
        elif '```' in response_text:
            json_start = response_text.find('```') + 3
            json_end = response_text.find('```', json_start)
            response_text = response_text[json_start:json_end].strip()
        
        try:
            return json.loads(response_text)
        except json.JSONDecodeError:
            return {
                'looking_at_audience': None,
                'facing_wall': None,
                'lying_down': None,
                'outdoors': None,
                'behavior_tags': [],
                'confidence': 0.0,
                'error': f'Failed to parse response: {response_text[:100]}'
            }
    
    def _format_result(self, result: dict) -> Dict[str, Any]:
        """格式化输出结果，使用 v2 前缀区分"""
        confidence = result.get('confidence', 0.0)
        if isinstance(confidence, float):
            confidence = Decimal(str(confidence))
        
        output = {
            'streamer_v2_looking_at_audience': result.get('looking_at_audience'),
            'streamer_v2_facing_wall': result.get('facing_wall'),
            'streamer_v2_lying_down': result.get('lying_down'),
            'streamer_v2_outdoors': result.get('outdoors'),
            'streamer_v2_behavior_tags': result.get('behavior_tags', []),
            'streamer_v2_confidence': confidence,
            'streamer_v2_description': result.get('description', ''),
            'streamer_v2_reasoning': result.get('reasoning', ''),
        }
        
        if 'error' in result:
            output['streamer_v2_error'] = result['error']
        
        return output
