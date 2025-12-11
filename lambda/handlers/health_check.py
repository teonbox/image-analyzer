"""
Health Check Lambda
检查超时 Request，强制完成
"""
import json
import boto3
import os
from datetime import datetime, timedelta
import sys
sys.path.append('/opt/python')

from shared.db import RequestTable, FrameTable, RequestStatus, FrameStatus
from shared.config import Config

request_table = None
frame_table = None
lambda_client = None


def _init_resources():
    """初始化 AWS 资源"""
    global request_table, frame_table, lambda_client
    if request_table is None:
        request_table = RequestTable(os.environ['REQUEST_TABLE'])
        frame_table = FrameTable(os.environ['FRAME_TABLE'])
        lambda_client = boto3.client('lambda')


def handler(event, context):
    """Health Check 主入口"""
    _init_resources()
    print("Health Check started")
    
    running_requests = request_table.query_by_status(RequestStatus.RUNNING)
    print(f"Found {len(running_requests)} running requests")
    
    timeout_limit = datetime.utcnow() - timedelta(seconds=Config.REQUEST_TIMEOUT)
    
    for request in running_requests:
        last_activity = datetime.fromisoformat(request['last_activity_at'].replace('Z', '+00:00'))
        
        if last_activity.replace(tzinfo=None) < timeout_limit:
            print(f"Request timeout: {request['request_id']}")
            
            request_table.update_request_status(request['request_id'], RequestStatus.COMPLETED)
            
            frames = frame_table.query_frames_by_request(request['request_id'])
            for frame in frames:
                if frame['status'] == FrameStatus.PENDING.value:
                    frame_table.update_frame_status(request['request_id'], frame['frame_index'], FrameStatus.FAILED)
            
            if os.environ.get('COMPLETION_HANDLER_NAME'):
                lambda_client.invoke(
                    FunctionName=os.environ['COMPLETION_HANDLER_NAME'],
                    InvocationType='Event',
                    Payload=json.dumps({'request_id': request['request_id']})
                )
    
    print("Health Check finished")
