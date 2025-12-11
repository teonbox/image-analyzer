"""
Message Dispatcher Lambda
异步发送 SQS 消息，由 Request Handler 异步调用
"""
import json
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Optional
import boto3
import sys
sys.path.append('/opt/python')

from shared.config import Config

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

sqs_client = None


def _init_resources():
    """初始化 AWS 资源"""
    global sqs_client
    if sqs_client is None:
        sqs_client = boto3.client('sqs')


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
    
    before_frame_keys = []
    for i in range(frame_index - 1, before_start - 1, -1):
        before_frame_keys.append(frame_keys[i])
    
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
    
    return messages


def send_sqs_messages_parallel(messages: List[dict], queue_url: str, max_workers: int = 20):
    """并行发送 SQS 消息"""
    batch_size = 10
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
    return success_count, fail_count


def handler(event, context):
    """Lambda 入口函数 - 异步调用"""
    _init_resources()
    
    request_id = event['request_id']
    request_name = event['request_name']
    frame_keys = event['frame_keys']
    storage_config = event['storage_config']
    
    total_frames = len(frame_keys)
    print(f"[PROGRESS] Message Dispatcher started: request_id={request_id}, frames={total_frames}")
    
    t0 = time.time()
    messages = build_all_messages(request_id, request_name, frame_keys, storage_config)
    print(f"[PROGRESS] Built {len(messages)} messages in {time.time()-t0:.2f}s")
    
    queue_url = os.environ.get('BATCH_QUEUE_URL')
    t1 = time.time()
    success, failed = send_sqs_messages_parallel(messages, queue_url, max_workers=20)
    print(f"[PROGRESS] Sent {len(messages)} messages in {time.time()-t1:.2f}s")
    
    logger.info(f"Message Dispatcher completed: request_id={request_id}, success={success}, failed={failed}")
    
    return {'success': success, 'failed': failed}
