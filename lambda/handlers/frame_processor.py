"""
Frame Processor Lambda
处理单个 Frame 的分析任务
"""
import json
import logging
import boto3
import os
import requests
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional
import sys
sys.path.append('/opt/python')

from shared.db import RequestTable, FrameTable, RequestStatus, FrameStatus
from shared.bedrock_client import BedrockClient
from shared.config import Config
from policies import get_policy_map

# 配置日志
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


# ============ SQS 消息解析（内联） ============

class MessageParseError(Exception):
    """消息解析错误"""
    pass


@dataclass
class FrameMessage:
    """Frame 消息数据类"""
    request_id: str
    request_name: str
    frame_index: int
    target_frame_url: str
    before_frame_urls: List[Optional[str]]
    after_frame_urls: List[Optional[str]]
    storage_config: Optional[dict] = None


def parse_sqs_record(record: dict) -> FrameMessage:
    """解析单个 SQS 记录"""
    try:
        body = record.get('body', '')
        data = json.loads(body)
    except json.JSONDecodeError as e:
        raise MessageParseError(f"Invalid JSON format: {e}")
    
    # 验证必需字段
    required = ['request_id', 'frame_index']
    missing = [f for f in required if f not in data]
    
    # 检查 target_frame_url 或 target_frame_key
    has_target = 'target_frame_url' in data or 'target_frame_key' in data
    if not has_target:
        missing.append('target_frame_url')
    
    if missing:
        raise MessageParseError(f"Missing required fields: {', '.join(missing)}")
    
    frame_index = data['frame_index']
    if not isinstance(frame_index, int):
        raise MessageParseError(f"frame_index must be integer, got {type(frame_index).__name__}")
    
    # 支持两种 URL 字段名（兼容性）
    target_url = data.get('target_frame_url') or data.get('target_frame_key', '')
    before_urls = data.get('before_frame_urls', data.get('before_frame_keys', []))
    after_urls = data.get('after_frame_urls', data.get('after_frame_keys', []))
    
    if not isinstance(before_urls, list):
        raise MessageParseError(f"before_frame_urls must be list, got {type(before_urls).__name__}")
    if not isinstance(after_urls, list):
        raise MessageParseError(f"after_frame_urls must be list, got {type(after_urls).__name__}")
    
    return FrameMessage(
        request_id=data['request_id'],
        request_name=data.get('request_name', ''),
        frame_index=frame_index,
        target_frame_url=target_url,
        before_frame_urls=before_urls,
        after_frame_urls=after_urls,
        storage_config=data.get('storage_config')
    )


# ============ 全局资源 ============

request_table = None
frame_table = None
bedrock_client = None
lambda_client = None

# 业务策略映射 (延迟初始化)
POLICY_MAP = None


def _init_policy_map():
    """初始化策略映射"""
    global POLICY_MAP
    if POLICY_MAP is None:
        # 如果设置了 ENABLED_POLICIES，使用指定的；否则使用默认逻辑
        enabled = [p.strip() for p in Config.ENABLED_POLICIES if p.strip()]
        POLICY_MAP = get_policy_map(enabled if enabled else None)
        print(f"Initialized policy map: {list(POLICY_MAP.keys())}")


def register_policy(name: str, policy):
    """注册策略（用于测试）"""
    global POLICY_MAP
    if POLICY_MAP is None:
        POLICY_MAP = {}
    POLICY_MAP[name] = policy


def _init_resources():
    """初始化 AWS 资源"""
    global request_table, frame_table, bedrock_client, lambda_client
    if request_table is None:
        request_table = RequestTable(os.environ['REQUEST_TABLE'])
        frame_table = FrameTable(os.environ['FRAME_TABLE'])
        bedrock_client = BedrockClient()
        lambda_client = boto3.client('lambda')
    _init_policy_map()


def handler(event, context):
    """Frame Processor 主入口"""
    _init_resources()
    print(f"Frame Processor started, records: {len(event['Records'])}")
    logger.info(f"Frame Processor started, records: {len(event['Records'])}")
    
    for record in event['Records']:
        try:
            process_frame_message(record)
        except MessageParseError as e:
            logger.error(f"Message parse error, skipping: {e}")
            print(f"Message parse error, skipping: {e}")
        except Exception as e:
            logger.error(f"Failed to process frame: {e}")
            print(f"Failed to process frame: {e}")
            raise


def process_frame_message(record):
    """处理单个 Frame 消息"""
    message = parse_sqs_record(record)
    request_id = message.request_id
    frame_index = message.frame_index
    
    print(f"Processing frame: request_id={request_id}, frame_index={frame_index}")
    logger.info(f"Processing frame: request_id={request_id}, frame_index={frame_index}")
    
    # 加载 Request 信息
    request = request_table.get_request(request_id)
    if not request:
        logger.error(f"Request not found: {request_id}")
        print(f"Request not found: {request_id}, skipping frame")
        return
    
    # 更新 last_activity_at
    request_table.update_last_activity(request_id)
    
    # 如果是第一个 Frame，更新状态为 running
    if request['status'] == RequestStatus.PENDING.value:
        request_table.update_request_status(request_id, RequestStatus.RUNNING)
    
    # 创建或加载 Frame 记录
    frame = load_or_create_frame(message, request)
    
    # 如果 Frame 已完成，跳过
    if frame['status'] == FrameStatus.COMPLETED.value:
        print(f"Frame {frame_index} already completed, skipping")
        return
    
    # 加载启用的策略 (POLICY_MAP 已在 _init_resources 中初始化)
    policies = list(POLICY_MAP.values())
    print(f"Loaded policies: {[p.get_name() for p in policies]}")
    
    # 记录帧的原始状态
    previous_frame_status = frame['status']
    
    # 遍历所有策略顺序执行
    all_failed = True
    for policy in policies:
        try:
            execute_policy(message, request, frame, policy)
            all_failed = False
        except Exception as e:
            logger.error(f"Policy {policy.get_name()} failed: {e}")
            print(f"Policy {policy.get_name()} failed: {e}")
    
    # 更新 Frame 状态
    if all_failed and len(policies) > 0:
        frame_table.update_frame_status(request_id, frame_index, FrameStatus.FAILED)
        update_frame_stats(request_id, 'failed', previous_frame_status)
    else:
        frame_table.update_frame_status(request_id, frame_index, FrameStatus.COMPLETED)
        update_frame_stats(request_id, 'completed', previous_frame_status)
    
    # 检查是否所有 Frame 完成
    if check_all_frames_completed(request_id, request):
        trigger_completion_handler(request_id)


def load_or_create_frame(message: FrameMessage, request):
    """创建或加载 Frame 记录"""
    frame = frame_table.get_frame(message.request_id, message.frame_index)
    
    if not frame:
        frame = {
            'request_id': message.request_id,
            'frame_index': message.frame_index,
            'frame_url': message.target_frame_url,
            'policy_results': {},
            'policy_status': {},
            'status': FrameStatus.PENDING.value,
            'retry_count': 0,
            'created_at': datetime.now(timezone.utc).isoformat()
        }
        frame_table.create_frame(frame)
        print(f"Created frame record: {message.frame_index}")
    else:
        if frame['status'] == FrameStatus.FAILED.value:
            frame['retry_count'] = frame.get('retry_count', 0) + 1
            frame_table.update_retry_count(message.request_id, message.frame_index, frame['retry_count'])
    
    return frame


def update_frame_stats(request_id: str, result_type: str, previous_frame_status: str):
    """更新 Request 的 frame_stats 统计（使用乐观锁）"""
    max_retries = 3
    for attempt in range(max_retries):
        try:
            request = request_table.get_request(request_id)
            if not request:
                return
            
            current_version = request.get('version', 1)
            stats = request.get('frame_stats', {'total': 0, 'completed': 0, 'failed': 0, 'pending': 0})
            
            if previous_frame_status == FrameStatus.FAILED.value:
                stats['failed'] = max(0, stats.get('failed', 0) - 1)
            else:
                stats['pending'] = max(0, stats.get('pending', 0) - 1)
            
            if result_type == 'completed':
                stats['completed'] = stats.get('completed', 0) + 1
            elif result_type == 'failed':
                stats['failed'] = stats.get('failed', 0) + 1
            
            request_table.update_frame_stats(request_id, stats, current_version)
            return
            
        except Exception as e:
            if attempt < max_retries - 1:
                logger.warning(f"Optimistic lock conflict, retrying: {e}")
            else:
                raise


def execute_policy(message: FrameMessage, request, frame, policy):
    """执行单个策略"""
    policy_name = policy.get_name()
    
    # 检查策略是否已完成或跳过
    if frame.get('policy_status', {}).get(policy_name) in ['completed', 'skipped']:
        return
    
    # 检查策略是否需要处理此帧
    if not policy.should_process(message.frame_index, request['total_frames']):
        frame_table.update_policy_status(message.request_id, message.frame_index, policy_name, 'skipped')
        return
    
    try:
        # 加载目标图片
        target_frame = load_image_from_url(message.target_frame_url, message.frame_index)
        
        # 加载上下文图片
        context_frames = load_context_frames(message, request, policy)
        
        # 调用策略分析
        result = policy.analyze(target_frame, context_frames, bedrock_client, None)
        
        # 合并结果
        frame_table.update_frame_result(message.request_id, message.frame_index, result, policy_name, 'completed')
        
    except Exception as e:
        frame_table.update_policy_status(message.request_id, message.frame_index, policy_name, 'failed')
        raise


def load_context_frames(message: FrameMessage, request, policy):
    """加载上下文帧"""
    context_range = policy.get_context_range(message.frame_index, request['total_frames'])
    before_needed = abs(min(0, context_range[0]))
    after_needed = max(0, context_range[1])
    
    context_frames = []
    
    for i, url in enumerate(message.before_frame_urls[:before_needed]):
        if url is None:
            continue
        frame_index = message.frame_index - (i + 1)
        try:
            context_frames.append(load_image_from_url(url, frame_index))
        except Exception as e:
            logger.warning(f"Failed to load before context frame {frame_index}: {e}")
    
    for i, url in enumerate(message.after_frame_urls[:after_needed]):
        if url is None:
            continue
        frame_index = message.frame_index + (i + 1)
        try:
            context_frames.append(load_image_from_url(url, frame_index))
        except Exception as e:
            logger.warning(f"Failed to load after context frame {frame_index}: {e}")
    
    context_frames.sort(key=lambda f: f['index'])
    return context_frames


def _get_s3_client_for_bucket(bucket: str):
    """根据 bucket 名称获取对应的 S3 client（支持跨账号访问）"""
    from shared.config import Config
    
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
    return boto3.client('s3')


def load_image_from_url(url: str, frame_index: int, timeout: int = 30) -> dict:
    """下载图片，支持 HTTP URL 和 S3 地址"""
    if url.startswith('s3://'):
        return _load_image_from_s3(url, frame_index)
    else:
        response = requests.get(url, timeout=timeout)
        response.raise_for_status()
        return {'index': frame_index, 'url': url, 'data': response.content}


def _load_image_from_s3(s3_url: str, frame_index: int) -> dict:
    """从 S3 下载图片，s3_url 格式: s3://bucket/key"""
    # 解析 s3://bucket/key
    if not s3_url.startswith('s3://'):
        raise ValueError(f"Invalid S3 URL: {s3_url}")
    
    path = s3_url[5:]  # 去掉 s3://
    parts = path.split('/', 1)
    if len(parts) != 2:
        raise ValueError(f"Invalid S3 URL format: {s3_url}")
    
    bucket, key = parts
    client = _get_s3_client_for_bucket(bucket)
    
    response = client.get_object(Bucket=bucket, Key=key)
    data = response['Body'].read()
    
    logger.info(f"Downloaded from S3: {s3_url}, size: {len(data)} bytes")
    return {'index': frame_index, 'url': s3_url, 'data': data}


def check_all_frames_completed(request_id, request):
    """检查是否所有 Frame 完成"""
    current_request = request_table.get_request(request_id)
    if not current_request:
        return False
    
    stats = current_request.get('frame_stats', {})
    total = stats.get('total', 0)
    completed = stats.get('completed', 0)
    failed = stats.get('failed', 0)
    
    return (completed + failed) >= total


def trigger_completion_handler(request_id):
    """触发 Completion Handler"""
    print(f"All frames completed for request {request_id}, triggering completion handler")
    
    if os.environ.get('COMPLETION_HANDLER_NAME'):
        lambda_client.invoke(
            FunctionName=os.environ['COMPLETION_HANDLER_NAME'],
            InvocationType='Event',
            Payload=json.dumps({'request_id': request_id})
        )
