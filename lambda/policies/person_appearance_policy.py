"""
人物外观特征分析策略

分析单张图片中人物的：
- 年龄段
- 族裔
- 肤色深浅
- 颜值（总体评级 + 子类别标签）
"""
import json
from decimal import Decimal
from typing import Dict, Any, List, Tuple

import sys
sys.path.append('/opt/python')
from policies.base import AnalysisPolicy, get_model_id


class PersonAppearancePolicy(AnalysisPolicy):
    """
    人物外观特征分析策略
    
    使用 AWS Bedrock Nova Lite 模型分析图片中人物的外观特征。
    只需要单张图片，不需要前后帧上下文。
    """
    
    def get_name(self) -> str:
        return 'person_appearance'
    
    def should_process(self, frame_index: int, total_frames: int) -> bool:
        return True
    
    def get_context_range(self, frame_index: int, total_frames: int) -> Tuple[int, int]:
        # 不需要上下文帧
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
        return """You are an expert in human appearance analysis. Analyze the person in this image and provide the following attributes.

## Age Group (age_group)
Choose ONE from:
- infant: Baby (0-2 years old)
- child: Child (3-12 years old)
- teenager: Teenager (13-19 years old)
- young_adult: Young adult (20-35 years old)
- middle_aged: Middle-aged (36-55 years old)
- senior: Senior (56+ years old)

## Ethnicity (ethnicity)
Choose ONE from:
- east_asian: East Asian (Chinese, Japanese, Korean, etc.)
- southeast_asian: Southeast Asian (Thai, Vietnamese, Filipino, etc.)
- south_asian: South Asian (Indian, Pakistani, etc.)
- caucasian: Caucasian/White
- african: African/Black
- latino: Latino/Hispanic
- middle_eastern: Middle Eastern
- mixed: Mixed race

## Skin Tone (skin_tone)
Regardless of ethnicity, evaluate the actual skin color depth:
- very_fair: Very fair/pale (extremely light skin)
- fair: Fair (light skin, common in Northern Europeans or light-skinned East Asians)
- light: Light (slightly tanned but still light)
- medium: Medium (moderate skin tone)
- tan: Tan/Olive (wheat-colored, sun-tanned)
- dark: Dark (darker skin tone)
- very_dark: Very dark (very deep skin tone)

## Overall Appearance Level (overall_level)
Evaluate overall attractiveness:
- stunning: Stunning (model/celebrity level, exceptionally attractive)
- attractive: Attractive (noticeably above average)
- average: Average (typical appearance)
- below_avg: Below average

## Appearance Features (features)
Select ALL that apply from these categories:

Facial Features:
- sharp_features: Sharp/defined facial features (prominent bone structure)
- soft_features: Soft facial features (gentle, rounded features)
- big_eyes: Big eyes (noticeably large eyes)
- high_nose: High nose bridge (prominent nose bridge)

Face Shape:
- oval_face: Oval face (balanced proportions)
- round_face: Round face (circular, full cheeks)
- square_face: Square face (strong jawline)
- v_face: V-shaped face (narrow chin, wider forehead)

Vibe/Aura:
- elegant: Elegant (refined, sophisticated)
- cute: Cute (adorable, youthful charm)
- cool: Cool (stylish, edgy)
- mature: Mature (sophisticated, experienced look)
- fresh: Fresh (clean, natural, youthful)

**IMPORTANT:**
- You MUST return results in JSON format regardless of image content
- If no person is visible or face cannot be analyzed, set all fields to null and confidence to 0.0
- features should be an array (can be empty if no features apply)

Return results strictly in the following JSON format (no additional text):
{
  "age_group": "young_adult",
  "ethnicity": "east_asian",
  "skin_tone": "fair",
  "overall_level": "attractive",
  "features": ["big_eyes", "v_face", "fresh"],
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
                'age_group': None,
                'ethnicity': None,
                'skin_tone': None,
                'overall_level': None,
                'features': [],
                'confidence': 0.0,
                'error': f'Failed to parse model response: {response_text[:100]}'
            }
    
    def _format_result(self, result: dict) -> Dict[str, Any]:
        """格式化输出结果，添加策略前缀"""
        confidence = result.get('confidence', 0.0)
        if isinstance(confidence, float):
            confidence = Decimal(str(confidence))
        
        output = {
            'person_age_group': result.get('age_group'),
            'person_ethnicity': result.get('ethnicity'),
            'person_skin_tone': result.get('skin_tone'),
            'person_overall_level': result.get('overall_level'),
            'person_features': result.get('features', []),
            'person_confidence': confidence,
        }
        
        if 'error' in result:
            output['person_error'] = result['error']
        
        return output
