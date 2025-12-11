"""
直播主播行为检测策略

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


class StreamerBehaviorPolicy(AnalysisPolicy):
    """
    直播主播行为检测策略
    
    作为直播平台运营检测人员，监测主播的行为表现，
    检测主播是否看着观众、是否对着墙壁、是否躺着、是否在户外。
    """
    
    def get_name(self) -> str:
        return 'streamer_behavior'
    
    def should_process(self, frame_index: int, total_frames: int) -> bool:
        return True
    
    def get_context_range(self, frame_index: int, total_frames: int) -> Tuple[int, int]:
        # 不需要上下文帧，单帧分析即可
        return (0, 0)
    
    def analyze(
        self,
        target_frame: Dict[str, Any],
        context_frames: List[Dict[str, Any]],
        bedrock_client: Any,
        storage_helper: Any
    ) -> Dict[str, Any]:
        # 只使用目标帧
        images = [target_frame['data']]
        
        prompt = self._build_prompt()
        
        # 调用 Bedrock Nova Lite
        response = bedrock_client.invoke(
            get_model_id('nova-lite'),
            prompt,
            images
        )
        
        # 解析结果
        response_text = response['output']['message']['content'][0]['text']
        result = self._parse_response(response_text)
        
        # 转换为输出格式
        return self._format_result(result)
    
    def _build_prompt(self) -> str:
        return """You are a live streaming platform operations inspector responsible for monitoring streamer behavior.

Analyze this image and detect the following behaviors of the streamer:

## 1. Looking at Audience (looking_at_audience)
Determine if the streamer is facing and looking at the camera/audience:
- true: Streamer is facing the camera, making eye contact or looking towards viewers
- false: Streamer is looking away, turned sideways, or not engaging with camera

## 2. Facing Wall (facing_wall)
Determine if there is a plain wall directly behind the streamer:
- true: There is a plain/blank wall behind the streamer (minimal decoration, solid color wall)
- false: Background has furniture, windows, decorations, or is not a plain wall

## 3. Lying Down (lying_down)
Determine if the streamer is in a lying/reclining position:
- true: Streamer is lying down, reclining on bed/couch, or in horizontal position
- false: Streamer is sitting upright, standing, or in normal streaming posture

## 4. Outdoors (outdoors)
Determine if the streamer is in an outdoor environment:
- true: Streamer is outside (street, park, nature, outdoor venue, etc.)
- false: Streamer is indoors (room, studio, indoor venue, etc.)

## Behavior Tags (behavior_tags)
Based on your analysis, select ALL applicable tags from:

Engagement:
- engaged: Actively engaging with audience (looking at camera, animated)
- distracted: Not focused on streaming (looking elsewhere, doing other things)
- interactive: Appears to be responding to chat/comments

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
- You MUST return results in JSON format regardless of image content
- If no person/streamer is visible, set all boolean fields to null and confidence to 0.0
- behavior_tags should be an array (can be empty if nothing applies)

Return results strictly in the following JSON format (no additional text):
{
  "looking_at_audience": true,
  "facing_wall": false,
  "lying_down": false,
  "outdoors": false,
  "behavior_tags": ["engaged", "sitting", "home_setup"],
  "confidence": 0.85
}
"""
    
    def _parse_response(self, response_text: str) -> dict:
        """解析模型响应"""
        # 处理 markdown 代码块
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
                'error': f'Failed to parse model response: {response_text[:100]}'
            }
    
    def _format_result(self, result: dict) -> Dict[str, Any]:
        """格式化输出结果，添加策略前缀"""
        confidence = result.get('confidence', 0.0)
        if isinstance(confidence, float):
            confidence = Decimal(str(confidence))
        
        output = {
            'streamer_looking_at_audience': result.get('looking_at_audience'),
            'streamer_facing_wall': result.get('facing_wall'),
            'streamer_lying_down': result.get('lying_down'),
            'streamer_outdoors': result.get('outdoors'),
            'streamer_behavior_tags': result.get('behavior_tags', []),
            'streamer_confidence': confidence,
        }
        
        if 'error' in result:
            output['streamer_error'] = result['error']
        
        return output
