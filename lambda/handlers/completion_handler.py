"""
Completion Handler Lambda
聚合所有 Frame 结果，保存到 S3，回调用户
"""
import json
from decimal import Decimal
import boto3
import os
from datetime import datetime, timedelta
import sys
sys.path.append('/opt/python')


class DecimalEncoder(json.JSONEncoder):
    """处理 DynamoDB Decimal 类型的 JSON 编码器"""
    def default(self, obj):
        if isinstance(obj, Decimal):
            # 如果是整数则返回 int，否则返回 float
            if obj % 1 == 0:
                return int(obj)
            return float(obj)
        return super().default(obj)

from shared.db import RequestTable, FrameTable
from shared.config import Config

# 延迟初始化
request_table = None
frame_table = None
s3_client = None


def _init_resources():
    """初始化 AWS 资源"""
    global request_table, frame_table, s3_client
    if request_table is None:
        request_table = RequestTable(os.environ['REQUEST_TABLE'])
        frame_table = FrameTable(os.environ['FRAME_TABLE'])
        s3_client = boto3.client('s3')


def calculate_final_status(frame_stats: dict) -> str:
    """
    根据 frame_stats 计算最终状态
    - completed: 全部成功
    - failed: 全部失败
    - partial_complete: 大部分成功（completed >= failed）
    - partial_failed: 大部分失败（failed > completed）
    """
    total = frame_stats.get('total', 0)
    completed = frame_stats.get('completed', 0)
    failed = frame_stats.get('failed', 0)
    
    if total == 0:
        return 'completed'
    
    if failed == 0:
        return 'completed'
    elif completed == 0:
        return 'failed'
    elif completed >= failed:
        return 'partial_complete'
    else:
        return 'partial_failed'


def handler(event, context):
    """Completion Handler 主入口"""
    _init_resources()
    
    request_id = event['request_id']
    print(f"Completion Handler started: {request_id}")
    
    request = request_table.get_request(request_id)
    if not request:
        raise ValueError(f"Request not found: {request_id}")
    
    frames = frame_table.query_frames_by_request(request_id)
    print(f"Loaded frames: {len(frames)}")

    # 聚合结果
    results = [{
        'frame_index': f['frame_index'],
        'frame_url': f.get('frame_url', ''),
        'status': f['status'],
        'policy_status': f.get('policy_status', {}),
        'results': f.get('policy_results', {})
    } for f in frames]
    
    completed = sum(1 for f in frames if any(s == 'completed' for s in f.get('policy_status', {}).values()))
    failed = sum(1 for f in frames if all(s == 'failed' for s in f.get('policy_status', {}).values()) and f.get('policy_status'))
    
    # 构建 frame_stats 并计算最终状态
    frame_stats = {
        'total': len(frames),
        'completed': completed,
        'failed': failed,
        'pending': len(frames) - completed - failed
    }
    final_status = calculate_final_status(frame_stats)
    
    statistics = {
        'total_frames': len(frames),
        'completed_frames': completed,
        'failed_frames': failed,
        'success_rate': f"{(completed / len(frames) * 100):.2f}%" if frames else "0%"
    }
    
    # 保存结果到 S3
    result_key = f"results/{request_id}/result.json"
    result_data = {
        'request_id': request_id,
        'name': request['name'],
        'status': final_status,
        'statistics': statistics,
        'frames': results,
        'generated_at': datetime.utcnow().isoformat()
    }
    
    s3_client.put_object(
        Bucket=Config.RESULTS_S3_BUCKET,
        Key=result_key,
        Body=json.dumps(result_data, indent=2, cls=DecimalEncoder),
        ContentType='application/json'
    )
    
    # 生成预签名 URL
    presigned_url = s3_client.generate_presigned_url(
        'get_object',
        Params={'Bucket': Config.RESULTS_S3_BUCKET, 'Key': result_key},
        ExpiresIn=Config.RESULTS_PRESIGNED_URL_EXPIRATION
    )
    
    url_expiration = (datetime.utcnow() + timedelta(seconds=Config.RESULTS_PRESIGNED_URL_EXPIRATION)).isoformat()
    
    # 更新 Request 记录（包含最终状态）
    request_table.update_result_info(request_id, {
        'status': final_status,
        'frame_stats': frame_stats,
        'result_s3_bucket': Config.RESULTS_S3_BUCKET,
        'result_s3_key': result_key,
        'result_presigned_url': presigned_url,
        'result_url_expiration': url_expiration,
        'completed_at': datetime.utcnow().isoformat()
    })
    
    # 发送回调
    if request.get('callback_url'):
        send_callback(request['callback_url'], {
            'request_id': request_id,
            'name': request['name'],
            'status': final_status,
            'statistics': statistics,
            'result_s3_bucket': Config.RESULTS_S3_BUCKET,
            'result_s3_key': result_key,
            'result_presigned_url': presigned_url,
            'result_url_expiration': url_expiration,
            'note': '预签名 URL 将在 1 天后过期，建议使用 result_s3_bucket 和 result_s3_key 直接访问以获得长期有效性'
        })
    
    print(f"Completion Handler finished: {request_id}")


def send_callback(url, data, max_retries=5, retry_interval=30):
    """
    发送回调通知，失败时重试
    
    Args:
        url: 回调 URL
        data: 回调数据
        max_retries: 最大重试次数（默认 5 次）
        retry_interval: 重试间隔秒数（默认 30 秒）
    
    Returns:
        bool: 是否成功发送
    """
    import urllib.request
    import time
    
    for attempt in range(max_retries):
        try:
            req = urllib.request.Request(
                url,
                data=json.dumps(data).encode(),
                headers={'Content-Type': 'application/json'}
            )
            urllib.request.urlopen(req, timeout=10)
            print(f"Callback sent successfully to {url}")
            return True
        except Exception as e:
            print(f"Callback attempt {attempt + 1}/{max_retries} failed: {e}")
            if attempt < max_retries - 1:
                print(f"Retrying in {retry_interval} seconds...")
                time.sleep(retry_interval)
    
    print(f"Callback failed after {max_retries} attempts")
    return False
