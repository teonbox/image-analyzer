"""
Result Handler Lambda
获取 Request 结果 - GET /requests/{id_or_name}/results
"""
import json
import boto3
import os
import re
import logging
from datetime import datetime, timedelta
from decimal import Decimal
import sys
sys.path.append('/opt/python')

from shared.db import RequestTable
from shared.config import Config

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

request_table = None
s3_client = None


def _init_resources():
    """初始化 AWS 资源"""
    global request_table, s3_client
    if request_table is None:
        request_table = RequestTable(os.environ.get('REQUEST_TABLE', ''))
        s3_client = boto3.client('s3')


def is_uuid(id_or_name: str) -> bool:
    """判断字符串是否为 UUID 格式"""
    uuid_pattern = r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
    return bool(re.match(uuid_pattern, id_or_name, re.IGNORECASE))


def convert_decimals(obj):
    """递归转换 Decimal 类型为 int 或 float"""
    if isinstance(obj, Decimal):
        return int(obj) if obj % 1 == 0 else float(obj)
    elif isinstance(obj, dict):
        return {k: convert_decimals(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [convert_decimals(i) for i in obj]
    return obj


def refresh_presigned_url(s3_key: str, bucket: str = None) -> tuple[str, str]:
    """生成新的预签名 URL，返回 (url, expiration)"""
    bucket = bucket or Config.RESULTS_S3_BUCKET
    url = s3_client.generate_presigned_url(
        'get_object',
        Params={'Bucket': bucket, 'Key': s3_key},
        ExpiresIn=Config.RESULTS_PRESIGNED_URL_EXPIRATION
    )
    expiration = (datetime.utcnow() + timedelta(seconds=Config.RESULTS_PRESIGNED_URL_EXPIRATION)).isoformat()
    return url, expiration


def is_completed_status(status: str) -> bool:
    """判断是否为完成状态"""
    return status in ('completed', 'failed', 'partial_complete', 'partial_failed')


def handler(event, context):
    """Lambda 入口函数"""
    _init_resources()
    
    try:
        path_params = event.get('pathParameters', {})
        id_or_name = path_params.get('id_or_name', '')
        
        if not id_or_name:
            return {
                'statusCode': 400,
                'body': json.dumps({
                    'success': False,
                    'error': {'code': 'MISSING_REQUIRED_FIELD', 'message': 'Missing required path parameter: id_or_name'}
                }, ensure_ascii=False)
            }
        
        logger.info(f"Get results for: {id_or_name}")
        
        # 查询 Request
        if is_uuid(id_or_name):
            request = request_table.get_request(id_or_name)
        else:
            requests = request_table.query_by_name(id_or_name)
            request = requests[0] if requests else None
        
        if not request:
            return {
                'statusCode': 404,
                'body': json.dumps({
                    'success': False,
                    'error': {'code': 'REQUEST_NOT_FOUND', 'message': '未找到指定的请求', 'details': {'id_or_name': id_or_name}}
                }, ensure_ascii=False)
            }
        
        # 检查是否已完成
        status = request.get('status', '')
        if not is_completed_status(status):
            frame_stats = request.get('frame_stats', {})
            total = frame_stats.get('total', 0)
            completed = frame_stats.get('completed', 0)
            failed = frame_stats.get('failed', 0)
            progress = round(((completed + failed) / total * 100), 2) if total > 0 else 0
            
            return {
                'statusCode': 400,
                'body': json.dumps({
                    'success': False,
                    'error': {
                        'code': 'REQUEST_NOT_COMPLETED',
                        'message': '请求尚未完成，无法获取结果',
                        'details': {
                            'request_id': request.get('request_id'),
                            'current_status': status,
                            'progress': progress
                        }
                    }
                }, ensure_ascii=False)
            }
        
        # 获取结果信息
        result_s3_key = request.get('result_s3_key')
        result_s3_bucket = request.get('result_s3_bucket', Config.RESULTS_S3_BUCKET)
        
        if not result_s3_key:
            return {
                'statusCode': 500,
                'body': json.dumps({
                    'success': False,
                    'error': {'code': 'INTERNAL_ERROR', 'message': '结果文件不存在'}
                }, ensure_ascii=False)
            }
        
        # 每次调用都生成新的预签名 URL
        presigned_url, url_expiration = refresh_presigned_url(result_s3_key, result_s3_bucket)
        
        response_data = {
            'request_id': request.get('request_id'),
            'name': request.get('name'),
            'status': status,
            'total_frames': request.get('total_frames'),
            'frame_stats': request.get('frame_stats', {}),
            'result_s3_bucket': result_s3_bucket,
            'result_s3_key': result_s3_key,
            'result_presigned_url': presigned_url,
            'result_url_expiration': url_expiration,
            'note': '预签名 URL 将在 1 天后过期，建议使用 result_s3_bucket 和 result_s3_key 直接访问以获得长期有效性'
        }
        
        response_data = convert_decimals(response_data)
        
        return {
            'statusCode': 200,
            'body': json.dumps({'success': True, 'data': response_data}, ensure_ascii=False)
        }
    
    except Exception as e:
        logger.error(f"Unexpected error: {e}", exc_info=True)
        return {
            'statusCode': 500,
            'body': json.dumps({
                'success': False,
                'error': {'code': 'INTERNAL_ERROR', 'message': str(e)}
            }, ensure_ascii=False)
        }
