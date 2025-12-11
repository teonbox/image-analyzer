import json
import time
import base64
import boto3
from typing import List, Any, Dict
from .config import Config

class BedrockClient:
    def __init__(self, client=None):
        self.client = client or boto3.client('bedrock-runtime', region_name=Config.BEDROCK_REGION)
    
    def invoke(self, model_id: str, prompt: str, images: List[bytes]) -> Any:
        """
        调用 Bedrock 模型
        
        返回统一格式:
        {
            'output': {
                'message': {
                    'content': [{'text': '...'}]
                }
            }
        }
        """
        delays = Config.BEDROCK_RETRY_DELAYS
        last_error = None
        
        for attempt in range(len(delays) + 1):
            try:
                body = self._build_request_body(model_id, prompt, images)
                response = self.client.invoke_model(
                    modelId=model_id,
                    contentType='application/json',
                    accept='application/json',
                    body=json.dumps(body)
                )
                response_body = json.loads(response['body'].read())
                return self._normalize_response(model_id, response_body)
            except Exception as e:
                last_error = e
                if attempt < len(delays):
                    time.sleep(delays[attempt])
        
        raise last_error or Exception('Bedrock invocation failed')
    
    def _normalize_response(self, model_id: str, response: Dict) -> Dict:
        """统一不同模型的响应格式"""
        # Nova 模型已经是统一格式
        if model_id.startswith('us.amazon.nova') or model_id.startswith('amazon.nova'):
            return response
        
        # Claude 模型需要转换
        if model_id.startswith('anthropic.claude') or model_id.startswith('us.anthropic.claude'):
            text = response.get('content', [{}])[0].get('text', '')
            return {
                'output': {
                    'message': {
                        'content': [{'text': text}]
                    }
                }
            }
        
        return response
    
    def _build_request_body(self, model_id: str, prompt: str, images: List[bytes]) -> Dict[str, Any]:
        if model_id.startswith('us.amazon.nova') or model_id.startswith('amazon.nova'):
            content = [{'text': prompt}]
            for img in images:
                content.append({
                    'image': {
                        'format': 'jpeg',
                        'source': {'bytes': base64.b64encode(img).decode('utf-8')}
                    }
                })
            
            return {
                'schemaVersion': 'messages-v1',
                'messages': [{'role': 'user', 'content': content}],
                'inferenceConfig': {
                    'maxTokens': 1000,
                    'temperature': 0.7,
                    'topP': 0.9
                }
            }
        
        if model_id.startswith('anthropic.claude') or model_id.startswith('us.anthropic.claude'):
            content = []
            for img in images:
                content.append({
                    'type': 'image',
                    'source': {
                        'type': 'base64',
                        'media_type': 'image/jpeg',
                        'data': base64.b64encode(img).decode('utf-8')
                    }
                })
            content.append({'type': 'text', 'text': prompt})
            
            return {
                'anthropic_version': 'bedrock-2023-05-31',
                'max_tokens': 4096,
                'messages': [{'role': 'user', 'content': content}]
            }
        
        raise ValueError(f'Unsupported model: {model_id}')
