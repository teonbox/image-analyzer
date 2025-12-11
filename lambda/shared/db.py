"""
数据库操作模块
包含 DynamoDB 表操作和状态枚举
"""
import boto3
from datetime import datetime
from enum import Enum
from typing import Optional, List, Dict, Any


# ============ 状态枚举 ============

class RequestStatus(str, Enum):
    PENDING = 'pending'
    RUNNING = 'running'
    PARTIAL_COMPLETE = 'partial_complete'
    PARTIAL_FAILED = 'partial_failed'
    COMPLETED = 'completed'
    FAILED = 'failed'


class FrameStatus(str, Enum):
    PENDING = 'pending'
    PROCESSING = 'processing'
    COMPLETED = 'completed'
    FAILED = 'failed'


class CallbackStatus(str, Enum):
    PENDING = 'pending'
    SUCCESS = 'success'
    FAILED = 'failed'
    RETRYING = 'retrying'


class PolicyStatus(str, Enum):
    COMPLETED = 'completed'
    SKIPPED = 'skipped'
    FAILED = 'failed'


# ============ Request 表操作 ============

class RequestTable:
    def __init__(self, table_name: str):
        self.table_name = table_name
        self.dynamodb = boto3.resource('dynamodb')
        self.table = self.dynamodb.Table(table_name)
    
    def create_request(self, request: Dict[str, Any]) -> None:
        self.table.put_item(Item=request)
    
    def get_request(self, request_id: str) -> Optional[Dict[str, Any]]:
        response = self.table.get_item(Key={'request_id': request_id})
        return response.get('Item')
    
    def update_request_status(self, request_id: str, status: RequestStatus, version: Optional[int] = None) -> None:
        update_expr = 'SET #status = :status, last_activity_at = :now'
        expr_names = {'#status': 'status'}
        expr_values = {
            ':status': status.value,
            ':now': datetime.utcnow().isoformat()
        }
        
        kwargs = {
            'Key': {'request_id': request_id},
            'UpdateExpression': update_expr,
            'ExpressionAttributeNames': expr_names,
            'ExpressionAttributeValues': expr_values
        }
        
        if version is not None:
            kwargs['UpdateExpression'] += ', version = :newVersion'
            kwargs['ConditionExpression'] = 'version = :currentVersion'
            kwargs['ExpressionAttributeValues'][':newVersion'] = version + 1
            kwargs['ExpressionAttributeValues'][':currentVersion'] = version
        
        self.table.update_item(**kwargs)
    
    def update_frame_stats(self, request_id: str, stats: Dict[str, int], current_version: int = None) -> None:
        update_expr = 'SET frame_stats = :stats, last_activity_at = :now'
        expr_values = {
            ':stats': stats,
            ':now': datetime.utcnow().isoformat()
        }
        
        kwargs = {
            'Key': {'request_id': request_id},
            'UpdateExpression': update_expr,
            'ExpressionAttributeValues': expr_values
        }
        
        if current_version is not None:
            kwargs['UpdateExpression'] += ', version = :newVersion'
            kwargs['ConditionExpression'] = 'version = :currentVersion'
            kwargs['ExpressionAttributeValues'][':newVersion'] = current_version + 1
            kwargs['ExpressionAttributeValues'][':currentVersion'] = current_version
        
        self.table.update_item(**kwargs)
    
    def query_by_name(self, name: str) -> List[Dict[str, Any]]:
        response = self.table.query(
            IndexName='name-created_at-index',
            KeyConditionExpression='#name = :name',
            ExpressionAttributeNames={'#name': 'name'},
            ExpressionAttributeValues={':name': name},
            ScanIndexForward=False
        )
        return response.get('Items', [])
    
    def update_last_activity(self, request_id: str) -> None:
        self.table.update_item(
            Key={'request_id': request_id},
            UpdateExpression='SET last_activity_at = :now',
            ExpressionAttributeValues={':now': datetime.utcnow().isoformat()}
        )
    
    def update_result_info(self, request_id: str, info: Dict[str, str]) -> None:
        update_expr = 'SET result_s3_bucket = :bucket, result_s3_key = :key, result_presigned_url = :url, result_url_expiration = :exp, callback_status = :cb_status'
        expr_values = {
            ':bucket': info['result_s3_bucket'],
            ':key': info['result_s3_key'],
            ':url': info['result_presigned_url'],
            ':exp': info['result_url_expiration'],
            ':cb_status': 'pending'
        }
        
        # 如果提供了 status，也更新状态
        if 'status' in info:
            update_expr += ', #status = :status'
            expr_values[':status'] = info['status']
        
        # 如果提供了 completed_at，也更新完成时间
        if 'completed_at' in info:
            update_expr += ', completed_at = :completed_at'
            expr_values[':completed_at'] = info['completed_at']
        
        # 如果提供了 frame_stats，也更新统计
        if 'frame_stats' in info:
            update_expr += ', frame_stats = :frame_stats'
            expr_values[':frame_stats'] = info['frame_stats']
        
        kwargs = {
            'Key': {'request_id': request_id},
            'UpdateExpression': update_expr,
            'ExpressionAttributeValues': expr_values
        }
        
        if 'status' in info:
            kwargs['ExpressionAttributeNames'] = {'#status': 'status'}
        
        self.table.update_item(**kwargs)
    
    def query_by_status(self, status: RequestStatus) -> List[Dict[str, Any]]:
        response = self.table.scan(
            FilterExpression='#status = :status',
            ExpressionAttributeNames={'#status': 'status'},
            ExpressionAttributeValues={':status': status.value}
        )
        return response.get('Items', [])


# ============ Frame 表操作 ============

class FrameTable:
    def __init__(self, table_name: str):
        self.table_name = table_name
        self.dynamodb = boto3.resource('dynamodb')
        self.table = self.dynamodb.Table(table_name)
    
    def create_frame(self, frame: Dict[str, Any]) -> Dict[str, Any]:
        self.table.put_item(Item=frame)
        return frame
    
    def get_frame(self, request_id: str, frame_index: int) -> Optional[Dict[str, Any]]:
        response = self.table.get_item(
            Key={'request_id': request_id, 'frame_index': frame_index}
        )
        return response.get('Item')
    
    def update_frame_result(
        self,
        request_id: str,
        frame_index: int,
        policy_results: Dict[str, Any],
        policy_name: str,
        policy_status: str
    ) -> None:
        frame = self.get_frame(request_id, frame_index)
        if not frame:
            raise ValueError(f"Frame not found: {request_id}/{frame_index}")
        
        merged_results = {**(frame.get('policy_results', {})), **policy_results}
        merged_status = {**(frame.get('policy_status', {})), policy_name: policy_status}
        
        self.table.update_item(
            Key={'request_id': request_id, 'frame_index': frame_index},
            UpdateExpression='SET policy_results = :results, policy_status = :status_map, updated_at = :now',
            ExpressionAttributeValues={
                ':results': merged_results,
                ':status_map': merged_status,
                ':now': datetime.utcnow().isoformat()
            }
        )
    
    def update_policy_status(
        self,
        request_id: str,
        frame_index: int,
        policy_name: str,
        status: str
    ) -> None:
        frame = self.get_frame(request_id, frame_index)
        if not frame:
            raise ValueError(f"Frame not found: {request_id}/{frame_index}")
        
        merged_status = {**(frame.get('policy_status', {})), policy_name: status}
        
        self.table.update_item(
            Key={'request_id': request_id, 'frame_index': frame_index},
            UpdateExpression='SET policy_status = :status_map, updated_at = :now',
            ExpressionAttributeValues={
                ':status_map': merged_status,
                ':now': datetime.utcnow().isoformat()
            }
        )
    
    def update_retry_count(self, request_id: str, frame_index: int, retry_count: int) -> None:
        self.table.update_item(
            Key={'request_id': request_id, 'frame_index': frame_index},
            UpdateExpression='SET retry_count = :count, updated_at = :now',
            ExpressionAttributeValues={
                ':count': retry_count,
                ':now': datetime.utcnow().isoformat()
            }
        )
    
    def batch_get_frames(self, request_id: str, frame_indices: List[int]) -> List[Dict[str, Any]]:
        keys = [{'request_id': request_id, 'frame_index': idx} for idx in frame_indices]
        response = self.dynamodb.batch_get_item(
            RequestItems={self.table_name: {'Keys': keys}}
        )
        return response.get('Responses', {}).get(self.table_name, [])
    
    def query_frames_by_request(self, request_id: str) -> List[Dict[str, Any]]:
        response = self.table.query(
            KeyConditionExpression='request_id = :requestId',
            ExpressionAttributeValues={':requestId': request_id}
        )
        return response.get('Items', [])
    
    def update_frame_status(self, request_id: str, frame_index: int, status: FrameStatus) -> None:
        self.table.update_item(
            Key={'request_id': request_id, 'frame_index': frame_index},
            UpdateExpression='SET #status = :status, updated_at = :now',
            ExpressionAttributeNames={'#status': 'status'},
            ExpressionAttributeValues={
                ':status': status.value,
                ':now': datetime.utcnow().isoformat()
            }
        )
