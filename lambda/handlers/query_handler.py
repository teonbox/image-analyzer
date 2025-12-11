"""
Query Handler Lambda
查询 Request 状态和进度
"""
import json
import boto3
import os
import re
import logging
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


def query_by_request_id(request_id: str) -> dict | None:
    """通过 request_id 查询请求"""
    return request_table.get_request(request_id)


def query_by_name(name: str) -> list[dict]:
    """通过 name 查询请求列表"""
    return request_table.query_by_name(name)


def get_latest_request(requests: list[dict]) -> dict:
    """获取最新的请求"""
    return requests[0] if requests else None


def refresh_presigned_url(request: dict) -> tuple[str | None, str | None]:
    """
    刷新预签名 URL 并写回 DynamoDB
    
    Returns:
        tuple: (presigned_url, url_expiration) 或 (None, None)
    """
    from datetime import datetime, timedelta
    
    result_s3_key = request.get('result_s3_key')
    request_id = request.get('request_id')
    if not result_s3_key or not request_id:
        return None, None
    
    try:
        bucket = request.get('result_s3_bucket', Config.RESULTS_S3_BUCKET)
        presigned_url = s3_client.generate_presigned_url(
            'get_object',
            Params={'Bucket': bucket, 'Key': result_s3_key},
            ExpiresIn=Config.RESULTS_PRESIGNED_URL_EXPIRATION
        )
        url_expiration = (datetime.utcnow() + timedelta(seconds=Config.RESULTS_PRESIGNED_URL_EXPIRATION)).isoformat()
        
        # 写回 DynamoDB
        request_table.update_request(request_id, {
            'result_presigned_url': presigned_url,
            'result_url_expiration': url_expiration
        })
        
        return presigned_url, url_expiration
    except Exception as e:
        logger.error(f"Failed to refresh presigned URL: {e}")
        return None, None


def calculate_progress(frame_stats: dict) -> dict:
    """计算进度百分比"""
    total = frame_stats.get('total', 0)
    completed = frame_stats.get('completed', 0)
    failed = frame_stats.get('failed', 0)
    
    if total == 0:
        return {'percentage': 0, 'completed_rate': 0, 'failed_rate': 0}
    
    processed = completed + failed
    return {
        'percentage': round((processed / total) * 100, 2),
        'completed_rate': round((completed / total) * 100, 2),
        'failed_rate': round((failed / total) * 100, 2)
    }


def convert_decimals(obj):
    """递归转换 Decimal 类型为 int 或 float"""
    if isinstance(obj, Decimal):
        return int(obj) if obj % 1 == 0 else float(obj)
    elif isinstance(obj, dict):
        return {k: convert_decimals(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [convert_decimals(i) for i in obj]
    return obj


def build_response_data(request: dict, multiple_requests: bool = False) -> dict:
    """构建响应数据"""
    frame_stats = request.get('frame_stats', {})
    progress = calculate_progress(frame_stats)
    
    response_data = {
        'request_id': request.get('request_id'),
        'name': request.get('name'),
        'status': request.get('status'),
        'total_frames': request.get('total_frames'),
        'frame_stats': frame_stats,
        'progress': progress,
        'created_at': request.get('created_at'),
        'last_activity_at': request.get('last_activity_at')
    }
    
    if request.get('completed_at'):
        response_data['completed_at'] = request.get('completed_at')
    
    # 添加结果相关字段
    if request.get('result_s3_key'):
        response_data['result_s3_bucket'] = request.get('result_s3_bucket')
        response_data['result_s3_key'] = request.get('result_s3_key')
        response_data['result_presigned_url'] = request.get('result_presigned_url')
        response_data['result_url_expiration'] = request.get('result_url_expiration')
    
    if multiple_requests:
        response_data['multiple_requests'] = True
    
    return response_data


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
        
        logger.info(f"Query request: {id_or_name}")
        
        if is_uuid(id_or_name):
            request = query_by_request_id(id_or_name)
            if not request:
                return {
                    'statusCode': 404,
                    'body': json.dumps({
                        'success': False,
                        'error': {'code': 'REQUEST_NOT_FOUND', 'message': '未找到指定的请求', 'details': {'id_or_name': id_or_name}}
                    }, ensure_ascii=False)
                }
            response_data = build_response_data(request)
        else:
            requests = query_by_name(id_or_name)
            if not requests:
                return {
                    'statusCode': 404,
                    'body': json.dumps({
                        'success': False,
                        'error': {'code': 'REQUEST_NOT_FOUND', 'message': '未找到指定的请求', 'details': {'id_or_name': id_or_name}}
                    }, ensure_ascii=False)
                }
            latest_request = get_latest_request(requests)
            response_data = build_response_data(latest_request, len(requests) > 1)
        
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
