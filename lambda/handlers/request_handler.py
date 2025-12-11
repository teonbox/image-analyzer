"""
Request Handler Lambda
处理用户提交的分析请求，生成 Frame 消息发送到 SQS
"""
import json
import uuid
import boto3
import os
import re
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import List, Dict, Any, Optional
import sys
sys.path.append('/opt/python')

from shared.db import RequestTable, RequestStatus, CallbackStatus
from shared.config import Config

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 延迟初始化
request_table = None
sqs_client = None
s3_client = None


def _init_resources():
    """初始化 AWS 资源"""
    global request_table, sqs_client, s3_client
    if request_table is None:
        request_table = RequestTable(os.environ.get('REQUEST_TABLE', ''))
        sqs_client = boto3.client('sqs')
        s3_client = boto3.client('s3')
        logger.info("Resources initialized")


# ============ 图片加载（内联） ============

def list_images(storage_config: Dict[str, Any]) -> List[Optional[str]]:
    """根据存储配置列出所有图片"""
    storage_type = storage_config.get('type')
    
    if storage_type == 's3':
        return _list_from_s3(storage_config)
    elif storage_type == 'oss':
        raise NotImplementedError('OSS storage is not yet supported')
    elif storage_type == 'http':
        return _list_from_urls(storage_config.get('urls', []))
    else:
        raise ValueError(f'Unsupported storage type: {storage_type}')


def _get_s3_client_for_bucket(bucket: str, region: str = 'us-east-1'):
    """根据 bucket 名称获取对应的 S3 client（支持跨账号访问）"""
    # 检查是否是 UDEMO bucket
    udemo_bucket = os.environ.get('UDEMO_S3_BUCKET', 'udemo-us-east-1')
    if bucket == udemo_bucket:
        ak = os.environ.get('UDEMO_AWS_ACCESS_KEY_ID')
        sk = os.environ.get('UDEMO_AWS_SECRET_ACCESS_KEY')
        udemo_region = os.environ.get('UDEMO_S3_REGION', 'us-east-1')
        if ak and sk:
            logger.info(f"Using UDEMO credentials for bucket: {bucket}")
            return boto3.client(
                's3',
                region_name=udemo_region,
                aws_access_key_id=ak,
                aws_secret_access_key=sk
            )
    
    # 默认使用 Lambda 执行角色
    return boto3.client('s3', region_name=region)


def _list_from_s3(storage_config: Dict[str, Any]) -> List[Optional[str]]:
    """从 S3 加载图片列表，返回 s3://bucket/key 格式的地址"""
    bucket = storage_config.get('bucket')
    prefix = storage_config.get('prefix', '')
    region = storage_config.get('region', 'us-east-1')
    
    print(f"[PROGRESS] Listing S3 objects: bucket={bucket}, prefix={prefix}")
    t0 = time.time()
    client = _get_s3_client_for_bucket(bucket, region)
    images = []
    continuation_token = None
    page_count = 0
    
    while True:
        kwargs = {'Bucket': bucket, 'Prefix': prefix}
        if continuation_token:
            kwargs['ContinuationToken'] = continuation_token
        
        response = client.list_objects_v2(**kwargs)
        page_count += 1
        
        if 'Contents' in response:
            for obj in response['Contents']:
                key = obj['Key']
                if key != prefix and not key.endswith('/'):
                    s3_url = f"s3://{bucket}/{key}"
                    images.append(s3_url)
        
        print(f"[PROGRESS] S3 list page {page_count}: {len(images)} objects so far ({time.time()-t0:.2f}s)")
        
        if not response.get('IsTruncated'):
            break
        continuation_token = response.get('NextContinuationToken')
    
    print(f"[PROGRESS] S3 listing done: {len(images)} objects in {time.time()-t0:.2f}s")
    logger.info(f"Listed {len(images)} images from S3 bucket {bucket}")
    
    t1 = time.time()
    result = _parse_and_sort_to_keys(images)
    print(f"[PROGRESS] Parsed and sorted {len(result)} frames in {time.time()-t1:.2f}s")
    return result


def _list_from_urls(urls: List[str]) -> List[Optional[str]]:
    """从 URL 列表加载图片"""
    if not urls:
        raise ValueError('URL list is empty')
    logger.info(f"Processing {len(urls)} URLs")
    return _parse_and_sort_to_keys(urls)


def _parse_and_sort_to_keys(keys: List[str]) -> List[Optional[str]]:
    """解析并排序图片 keys，返回按索引排序的 key 列表"""
    parsed = _parse_and_sort(keys)
    if not parsed:
        return []
    
    indices = [item['index'] for item in parsed]
    min_index, max_index = min(indices), max(indices)
    
    result = [None] * (max_index - min_index + 1)
    for item in parsed:
        result[item['index'] - min_index] = item['key']
    return result


def _extract_filename(key: str) -> str:
    """从 URL 或 S3 路径中提取文件名"""
    # 处理 s3://bucket/path/file.jpg 或 http://xxx/path/file.jpg
    if '/' in key:
        return key.rsplit('/', 1)[-1]
    return key


def _parse_and_sort(keys: List[str]) -> List[Dict[str, Any]]:
    """解析并排序图片 keys"""
    prefix_map = {}
    
    for key in keys:
        # 提取文件名部分
        filename = _extract_filename(key)
        
        # 支持两种格式：prefix-number.ext 或 prefix_number.ext
        match = re.match(r'^(.+?)[-_](\d+)\.[^.]+$', filename)
        if not match:
            logger.warning(f"Skipping invalid image key: {key} (filename: {filename})")
            continue
        
        prefix, index_str = match.groups()
        index = int(index_str)
        
        if prefix not in prefix_map:
            prefix_map[prefix] = []
        prefix_map[prefix].append({'key': key, 'index': index})
    
    if not prefix_map:
        raise ValueError('No valid image files found with pattern: prefix-number.ext')
    
    if len(prefix_map) > 1:
        prefixes = list(prefix_map.keys())
        raise ValueError(f"Multiple prefixes detected: {', '.join(prefixes)}")
    
    images = list(prefix_map.values())[0]
    images.sort(key=lambda x: x['index'])
    return images


# ============ SQS 消息构造（内联） ============

def build_frame_message(
    request_id: str,
    request_name: str,
    frame_index: int,
    frame_keys: List[Optional[str]],
    storage_config: Dict,
    total_frames: int
) -> dict:
    """构造单个 Frame 的 SQS 消息"""
    context_max = Config.CONTEXT_MAX_FRAMES
    before_start = max(0, frame_index - context_max)
    after_end = min(total_frames - 1, frame_index + context_max)
    
    # 前序帧（倒序：最近的在前）
    before_frame_keys = []
    for i in range(frame_index - 1, before_start - 1, -1):
        before_frame_keys.append(frame_keys[i])
    
    # 后续帧（正序）
    after_frame_keys = []
    for i in range(frame_index + 1, after_end + 1):
        after_frame_keys.append(frame_keys[i])
    
    return {
        "request_id": request_id,
        "request_name": request_name,
        "frame_index": frame_index,
        "storage_config": storage_config,
        "target_frame_key": frame_keys[frame_index],
        "before_frame_keys": before_frame_keys,
        "after_frame_keys": after_frame_keys
    }


def build_all_messages(
    request_id: str,
    request_name: str,
    frame_keys: List[Optional[str]],
    storage_config: Dict
) -> List[dict]:
    """为所有 Frame 构造 SQS 消息"""
    total_frames = len(frame_keys)
    messages = []
    
    for frame_index in range(total_frames):
        if frame_keys[frame_index] is None:
            logger.warning(f"Frame {frame_index} is missing, skipping")
            continue
        
        message = build_frame_message(
            request_id=request_id,
            request_name=request_name,
            frame_index=frame_index,
            frame_keys=frame_keys,
            storage_config=storage_config,
            total_frames=total_frames
        )
        messages.append(message)
    
    logger.info(f"Built {len(messages)} SQS messages for request {request_id}")
    return messages


# ============ SQS 并行发送 ============

def _send_sqs_messages_parallel(messages: List[dict], queue_url: str, max_workers: int = 10):
    """并行发送 SQS 消息"""
    batch_size = 10  # SQS 每批最多 10 条
    batches = []
    
    for i in range(0, len(messages), batch_size):
        batch = messages[i:i + batch_size]
        entries = [{'Id': str(j), 'MessageBody': json.dumps(msg, ensure_ascii=False)} for j, msg in enumerate(batch)]
        batches.append(entries)
    
    print(f"[PROGRESS] Sending {len(batches)} batches with {max_workers} workers...")
    
    def send_batch(entries):
        try:
            response = sqs_client.send_message_batch(QueueUrl=queue_url, Entries=entries)
            failed = response.get('Failed', [])
            return len(entries) - len(failed), len(failed)
        except Exception as e:
            logger.error(f"Failed to send SQS batch: {e}")
            return 0, len(entries)
    
    success_count = 0
    fail_count = 0
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(send_batch, batch) for batch in batches]
        for i, future in enumerate(as_completed(futures)):
            s, f = future.result()
            success_count += s
            fail_count += f
            if (i + 1) % 50 == 0:
                print(f"[PROGRESS] Sent {i+1}/{len(batches)} batches, success={success_count}, failed={fail_count}")
    
    print(f"[PROGRESS] SQS send complete: success={success_count}, failed={fail_count}")
    if fail_count > 0:
        logger.error(f"Failed to send {fail_count} messages")


# ============ 请求验证 ============

def validate_request_input(body):
    """验证请求输入参数"""
    if not body.get('name'):
        return False, 'Missing required field: name'
    
    if not body.get('callback_url'):
        return False, 'Missing required field: callback_url'
    
    storage_type = body.get('type')
    if storage_type not in ['s3', 'oss', 'http']:
        return False, f'Invalid type: {storage_type}. Must be s3, oss, or http'
    
    if storage_type == 's3':
        if not body.get('bucket'):
            return False, 'Missing required field: bucket (for S3)'
        if not body.get('region'):
            return False, 'Missing required field: region (for S3)'
    elif storage_type == 'oss':
        if not body.get('bucket'):
            return False, 'Missing required field: bucket (for OSS)'
        if not body.get('endpoint'):
            return False, 'Missing required field: endpoint (for OSS)'
    elif storage_type == 'http':
        urls = body.get('urls', [])
        if not urls or not isinstance(urls, list):
            return False, 'Invalid or empty urls list'
    
    return True, None


# ============ Lambda 入口 ============

def handler(event, context):
    """Lambda 入口函数"""
    _init_resources()
    
    try:
        body = json.loads(event.get('body', '{}'))
        logger.info(f"Received request: {json.dumps(body, ensure_ascii=False)}")
        
        is_valid, error_message = validate_request_input(body)
        if not is_valid:
            logger.error(f"Validation failed: {error_message}")
            return {
                'statusCode': 400,
                'body': json.dumps({
                    'success': False,
                    'error': {'code': 'INVALID_REQUEST', 'message': error_message}
                }, ensure_ascii=False)
            }
        
        storage_config = {
            'type': body['type'],
            'bucket': body.get('bucket'),
            'prefix': body.get('prefix', ''),
            'region': body.get('region'),
            'endpoint': body.get('endpoint'),
            'urls': body.get('urls')
        }
        
        # 列出所有图片
        logger.info("Listing images...")
        try:
            frame_keys = list_images(storage_config)
        except Exception as e:
            logger.error(f"Failed to list images: {e}")
            return {
                'statusCode': 500,
                'body': json.dumps({
                    'success': False,
                    'error': {'code': 'LIST_IMAGES_FAILED', 'message': str(e)}
                }, ensure_ascii=False)
            }
        
        total_frames = len(frame_keys)
        logger.info(f"Listed {total_frames} images")
        
        if total_frames == 0:
            return {
                'statusCode': 400,
                'body': json.dumps({
                    'success': False,
                    'error': {'code': 'EMPTY_IMAGE_LIST', 'message': 'No images found'}
                }, ensure_ascii=False)
            }
        
        # 创建 Request 记录
        request_id = str(uuid.uuid4())
        now = datetime.utcnow().isoformat() + 'Z'
        
        request_item = {
            'request_id': request_id,
            'name': body['name'],
            'status': RequestStatus.PENDING.value,
            'input_config': storage_config,
            'callback_url': body['callback_url'],
            'callback_status': CallbackStatus.PENDING.value,
            'total_frames': total_frames,
            'frame_stats': {'total': total_frames, 'completed': 0, 'failed': 0, 'pending': total_frames},
            'created_at': now,
            'last_activity_at': now,
            'version': 1
        }
        
        request_table.create_request(request_item)
        logger.info(f"Created request: {request_id}")
        print(f"[PROGRESS] Created request: {request_id}")
        
        # 异步调用 Message Dispatcher 发送 SQS 消息
        dispatcher_name = os.environ.get('MESSAGE_DISPATCHER_NAME')
        if dispatcher_name:
            lambda_client = boto3.client('lambda')
            payload = {
                'request_id': request_id,
                'request_name': body['name'],
                'frame_keys': frame_keys,
                'storage_config': storage_config
            }
            lambda_client.invoke(
                FunctionName=dispatcher_name,
                InvocationType='Event',  # 异步调用
                Payload=json.dumps(payload, ensure_ascii=False)
            )
            print(f"[PROGRESS] Triggered Message Dispatcher asynchronously")
            logger.info(f"Triggered Message Dispatcher for request {request_id}")
        else:
            # 回退到同步发送（用于测试或未配置 dispatcher 的情况）
            print(f"[PROGRESS] No dispatcher configured, sending synchronously...")
            messages = build_all_messages(request_id, body['name'], frame_keys, storage_config)
            queue_url = os.environ.get('BATCH_QUEUE_URL')
            _send_sqs_messages_parallel(messages, queue_url, max_workers=20)
        
        return {
            'statusCode': 200,
            'body': json.dumps({
                'success': True,
                'data': {'request_id': request_id, 'status': RequestStatus.PENDING.value, 'total_frames': total_frames, 'created_at': now}
            }, ensure_ascii=False)
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
