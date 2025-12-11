"""API 客户端封装"""
import requests
import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)


class APIClient:
    """API 客户端封装，处理所有 API 调用"""

    def __init__(self, base_url: str, api_key: str):
        self.base_url = base_url.rstrip('/')
        self.api_key = api_key
        self.session = requests.Session()
        self.session.headers.update({
            'x-api-key': api_key,
            'Content-Type': 'application/json'
        })

    def submit_request(
        self,
        name: str,
        urls: list,
        callback_url: str = 'https://webhook.site/test'
    ) -> Dict[str, Any]:
        """提交分析请求（URL 列表方式）"""
        logger.info(f"Submitting request: {name} with {len(urls)} frames")
        response = self.session.post(
            f'{self.base_url}/requests',
            json={
                'name': name,
                'type': 'http',
                'urls': urls,
                'callback_url': callback_url
            }
        )
        response.raise_for_status()
        return response.json()

    def submit_request_s3(
        self,
        name: str,
        bucket: str,
        prefix: str,
        region: str = 'us-east-1',
        callback_url: str = 'https://webhook.site/test'
    ) -> Dict[str, Any]:
        """提交分析请求（S3 方式）"""
        logger.info(f"Submitting S3 request: {name}, bucket={bucket}, prefix={prefix}")
        response = self.session.post(
            f'{self.base_url}/requests',
            json={
                'name': name,
                'type': 's3',
                'bucket': bucket,
                'prefix': prefix,
                'region': region,
                'callback_url': callback_url
            }
        )
        response.raise_for_status()
        return response.json()

    def get_request_status(self, request_id: str) -> Dict[str, Any]:
        """查询请求状态"""
        response = self.session.get(f'{self.base_url}/requests/{request_id}')
        response.raise_for_status()
        return response.json()

    def get_request_results(self, request_id: str) -> Dict[str, Any]:
        """获取请求结果（从 S3 预签名 URL）"""
        # 先获取请求状态，其中包含 result_presigned_url
        status_response = self.get_request_status(request_id)
        if not status_response.get('success'):
            return status_response
        
        data = status_response.get('data', {})
        
        # 如果有 result_s3_key，说明结果已生成，需要从 S3 获取
        if data.get('result_s3_key'):
            # 使用预签名 URL 获取完整结果
            presigned_url = data.get('result_presigned_url')
            if presigned_url:
                result_response = requests.get(presigned_url)
                result_response.raise_for_status()
                result_data = result_response.json()
                return {'success': True, 'data': result_data}
        
        # 如果没有结果文件，返回状态信息
        return status_response
