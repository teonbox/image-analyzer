"""
Stream Quality Detection Policy

Analyzes 5 consecutive frames (5 seconds) to detect:
- Camera quality issues (blur, shake, exposure)
- Network quality issues (artifacts, freezing, pixelation)

Uses Nova Lite model with multi-frame context for accurate detection.
"""
import json
from decimal import Decimal
from typing import Dict, Any, List, Tuple

import sys
sys.path.append('/opt/python')
from policies.base import AnalysisPolicy, get_model_id


class StreamQualityPolicy(AnalysisPolicy):
    """
    Stream Quality Detection Policy
    
    Analyzes 5 consecutive frames to detect camera and network quality issues.
    Single frame issues don't indicate problems - consistent issues across
    multiple frames indicate real quality problems.
    """
    
    def get_name(self) -> str:
        return 'stream_quality'
    
    def should_process(self, frame_index: int, total_frames: int) -> bool:
        # Only process frames that have enough context (2 before, 2 after)
        return frame_index >= 2 and frame_index < total_frames - 2
    
    def get_context_range(self, frame_index: int, total_frames: int) -> Tuple[int, int]:
        # Need 2 frames before and 2 frames after (total 5 frames including target)
        return (-2, 2)
    
    def analyze(
        self,
        target_frame: Dict[str, Any],
        context_frames: List[Dict[str, Any]],
        bedrock_client: Any,
        storage_helper: Any
    ) -> Dict[str, Any]:
        # Build ordered list: 2 prev + target + 2 next
        all_frames = []
        
        # Sort context frames by index
        prev_frames = sorted(
            [f for f in context_frames if f['index'] < target_frame['index']],
            key=lambda x: x['index']
        )
        next_frames = sorted(
            [f for f in context_frames if f['index'] > target_frame['index']],
            key=lambda x: x['index']
        )
        
        all_frames = prev_frames + [target_frame] + next_frames
        images = [f['data'] for f in all_frames]
        
        prompt = self._build_prompt()
        
        # Call Bedrock Nova Lite with all 5 images
        response = bedrock_client.invoke(
            get_model_id('nova-lite'),
            prompt,
            images
        )
        
        response_text = response['output']['message']['content'][0]['text']
        result = self._parse_response(response_text)
        
        return self._format_result(result)
    
    def _build_prompt(self) -> str:
        return """You are a live streaming quality inspector. Analyze these 5 consecutive frames (representing 5 seconds of streaming) to detect quality issues.

## Important Context
- These are 5 consecutive frames from a live stream (1 frame per second)
- A single bad frame doesn't indicate a problem
- Consistent issues across multiple frames indicate real quality problems
- Compare frames to detect changes, freezing, or degradation

## Camera Quality Issues (camera_quality)
Evaluate the camera/video quality:
- excellent: Sharp, well-lit, stable across all frames
- good: Minor issues in 1-2 frames, generally acceptable
- fair: Noticeable issues in 3+ frames but still watchable
- poor: Significant issues throughout most frames

Camera issues to look for:
- blur: Image is out of focus or motion blur
- shake: Camera is unstable/shaky (compare frame positions)
- overexposed: Too bright, washed out
- underexposed: Too dark, hard to see details
- low_resolution: Pixelated or low quality image

## Network Quality Issues (network_quality)
Evaluate network-related quality:
- excellent: Smooth, no artifacts across all frames
- good: Minor artifacts in 1-2 frames
- fair: Noticeable artifacts in 3+ frames
- poor: Severe artifacts or freezing throughout

Network issues to look for:
- frozen: Same frame repeated (compare consecutive frames)
- pixelation: Block artifacts from compression
- artifacts: Visual glitches, color banding
- frame_drop: Missing frames or jumpy motion
- buffering: Signs of stream buffering

## Detected Issues (issues)
List ALL specific issues detected. Select from:

Camera Issues:
- blur
- shake
- overexposed
- underexposed
- low_resolution
- bad_framing

Network Issues:
- frozen
- pixelation
- artifacts
- frame_drop
- buffering
- lag

## Overall Stream Quality (overall_quality)
Based on both camera and network quality:
- excellent: Professional quality, no issues
- good: Minor issues, enjoyable viewing experience
- fair: Some issues but acceptable
- poor: Significant issues affecting viewing experience
- unwatchable: Severe issues, stream is not viewable

**IMPORTANT:**
- Compare all 5 frames to detect patterns
- A single blurry frame is normal; 5 blurry frames indicate camera issues
- Identical consecutive frames indicate freezing/network issues
- Return results in JSON format

Return results strictly in the following JSON format (no additional text):
{
  "camera_quality": "good",
  "network_quality": "excellent",
  "overall_quality": "good",
  "issues": ["blur"],
  "frame_analysis": {
    "consistent_issues": ["none or list issues seen in 3+ frames"],
    "intermittent_issues": ["issues seen in 1-2 frames"],
    "frozen_detected": false
  },
  "confidence": 0.85
}
"""
    
    def _parse_response(self, response_text: str) -> dict:
        """Parse model response"""
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
                'camera_quality': None,
                'network_quality': None,
                'overall_quality': None,
                'issues': [],
                'frame_analysis': {},
                'confidence': 0.0,
                'error': f'Failed to parse response: {response_text[:100]}'
            }
    
    def _format_result(self, result: dict) -> Dict[str, Any]:
        """Format output with policy prefix"""
        confidence = result.get('confidence', 0.0)
        if isinstance(confidence, float):
            confidence = Decimal(str(confidence))
        
        frame_analysis = result.get('frame_analysis', {})
        
        output = {
            'quality_camera': result.get('camera_quality'),
            'quality_network': result.get('network_quality'),
            'quality_overall': result.get('overall_quality'),
            'quality_issues': result.get('issues', []),
            'quality_consistent_issues': frame_analysis.get('consistent_issues', []),
            'quality_intermittent_issues': frame_analysis.get('intermittent_issues', []),
            'quality_frozen_detected': frame_analysis.get('frozen_detected', False),
            'quality_confidence': confidence,
        }
        
        if 'error' in result:
            output['quality_error'] = result['error']
        
        return output
