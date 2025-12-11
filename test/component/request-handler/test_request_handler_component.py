"""
Request Handler Layer 2 组件测试
测试目标：验证 Lambda 完整流程
"""
import pytest
import sys
import os
import json
from conftest import assert_timestamp_recent

# 添加 lambda 目录到路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../../lambda'))


class TestImageListFlow:
    """2.1 完整流程测试（Image List 方式）"""
    
    def test_req_comp_001_image_list_to_dynamodb_to_sqs(self, mock_aws_resources):
        """REQ-COMP-001: Image List -> DynamoDB -> SQS 完整流程
        测试目标: handler() 方法（完整流程）
        """
        # 导入 handler
        from handlers.request_handler import handler
        
        # 调用 handler
        event = {
            'body': json.dumps({
                'name': 'test-video',
                'input_config': {
                    'type': 'urls',
                    'urls': [
                        'https://example.com/video/frame-001.jpg',
                        'https://example.com/video/frame-002.jpg',
                        'https://example.com/video/frame-003.jpg',
                        'https://example.com/video/frame-004.jpg',
                        'https://example.com/video/frame-005.jpg'
                    ]
                },
                'callback_url': 'https://example.com/callback'
            })
        }
        
        response = handler(event, {})
        
        # 验证点 1: 响应状态码 200
        assert response['statusCode'] == 200
        
        # 验证点 2: 返回 request_id（UUID 格式）
        body = json.loads(response['body'])
        assert 'request_id' in body
        request_id = body['request_id']
        
        # 验证 UUID 格式
        assert len(request_id) == 36
        assert request_id.count('-') == 4
        
        # 验证点 3: DynamoDB 中创建了 Request 记录
        table = mock_aws_resources['dynamodb_table']
        db_response = table.get_item(Key={'request_id': request_id})
        assert 'Item' in db_response
        
        request_item = db_response['Item']
        
        # 验证基本字段
        assert request_item['request_id'] == request_id
        assert request_item['name'] == 'test-video'
        assert request_item['status'] == 'pending'
        assert request_item['total_frames'] == 5
        
        # 验证 input_config
        assert 'input_config' in request_item
        input_config = request_item['input_config']
        assert input_config['type'] == 'urls'
        assert len(input_config['urls']) == 5
        
        # 验证 callback
        assert request_item['callback_url'] == 'https://example.com/callback'
        assert request_item['callback_status'] == 'pending'
        assert request_item['callback_retry_count'] == 0
        
        # 验证 frame_stats
        frame_stats = request_item['frame_stats']
        assert frame_stats['total'] == 5
        assert frame_stats['completed'] == 0
        assert frame_stats['failed'] == 0
        assert frame_stats['pending'] == 5
        assert frame_stats['processing'] == 0
        
        # 验证批次信息
        assert request_item['total_batches'] == 1  # 5帧应该只有1个批次
        assert 'batch_info' in request_item
        batch_info = request_item['batch_info']
        assert isinstance(batch_info, list)
        assert len(batch_info) == 1  # 应该只有1个批次
        
        # 验证第一个批次的结构
        first_batch = batch_info[0]
        assert first_batch['batch_id'] == 'batch-0'
        assert first_batch['batch_index'] == 0
        assert first_batch['core_range'] == [0, 4]  # 5帧: 0-4
        assert first_batch['frame_range'] == [0, 4]  # 没有额外上下文
        
        # 验证时间戳格式和合理性
        created_at = request_item['created_at']
        last_activity_at = request_item['last_activity_at']
        
        # 验证 ISO 8601 格式
        assert 'T' in created_at
        assert 'T' in last_activity_at
        
        # 验证时间戳在当前时间附近（5秒内）
        assert_timestamp_recent(created_at, tolerance_seconds=5)
        assert_timestamp_recent(last_activity_at, tolerance_seconds=5)
        
        # 验证逻辑关系（刚创建，应该相同）
        assert created_at == last_activity_at
        
        # 验证版本号
        assert request_item['version'] == 0
        
        # 验证点 4: SQS 中发送了批次消息
        sqs = mock_aws_resources['sqs_client']
        queue_url = mock_aws_resources['sqs_url']
        
        messages = []
        while True:
            msg_response = sqs.receive_message(
                QueueUrl=queue_url,
                MaxNumberOfMessages=10,
                WaitTimeSeconds=1
            )
            if 'Messages' not in msg_response:
                break
            messages.extend(msg_response['Messages'])
            for msg in msg_response['Messages']:
                sqs.delete_message(
                    QueueUrl=queue_url,
                    ReceiptHandle=msg['ReceiptHandle']
                )
        
        assert len(messages) == 1  # 5帧应该只生成1个批次消息
        
        # 验证消息内容 - 所有必需字段
        msg = messages[0]
        msg_body = json.loads(msg['Body'])
        
        # 必需字段
        assert 'request_id' in msg_body
        assert 'batch_id' in msg_body
        assert 'batch_index' in msg_body
        assert 'core_range' in msg_body
        assert 'frame_range' in msg_body
        
        # 验证具体值
        assert msg_body['request_id'] == request_id
        assert msg_body['batch_id'] == 'batch-0'  # 第一个批次
        assert msg_body['batch_index'] == 0
        
        # 验证 core_range 具体值
        core_range = msg_body['core_range']
        assert core_range == [0, 4]  # 5帧: 0-4
        
        # 验证 frame_range 具体值
        frame_range = msg_body['frame_range']
        assert frame_range == [0, 4]  # 没有额外上下文
        
        # 验证范围关系
        assert frame_range[0] <= core_range[0]
        assert frame_range[1] >= core_range[1]


class TestS3Flow:
    """2.2 完整流程测试（S3 方式）"""
    
    def test_req_comp_002_s3_to_dynamodb_to_sqs(self, mock_aws_resources, mock_s3_bucket):
        """REQ-COMP-002: S3 -> DynamoDB -> SQS 完整流程
        测试目标: handler() 方法（完整流程）
        """
        # 上传 5 张测试图片到 S3
        for i in range(1, 6):
            mock_s3_bucket.put_object(
                Bucket='test-bucket',
                Key=f'video1/frame-{i:03d}.jpg',
                Body=b'fake image data'
            )
        
        # 导入 handler
        from handlers.request_handler import handler
        
        # 调用 handler
        event = {
            'body': json.dumps({
                'name': 'test-video',
                'input_config': {
                    'type': 'storage',
                    'storage': {
                        'type': 's3',
                        'bucket': 'test-bucket',
                        'prefix': 'video1/',
                        'region': 'us-east-1'
                    }
                },
                'callback_url': 'https://example.com/callback'
            })
        }
        
        response = handler(event, {})
        
        # 验证点 1: 调用了 S3 ListObjects（隐式验证）
        # 验证点 2: 响应状态码 200
        assert response['statusCode'] == 200
        
        # 验证点 3: DynamoDB 中创建了 Request 记录
        body = json.loads(response['body'])
        request_id = body['request_id']
        
        table = mock_aws_resources['dynamodb_table']
        db_response = table.get_item(Key={'request_id': request_id})
        assert 'Item' in db_response
        
        request_item = db_response['Item']
        
        # 验证基本字段
        assert request_item['request_id'] == request_id
        assert request_item['name'] == 'test-video'
        assert request_item['status'] == 'pending'
        assert request_item['total_frames'] == 5
        
        # 验证 input_config
        assert 'input_config' in request_item
        input_config = request_item['input_config']
        assert input_config['type'] == 'storage'
        assert input_config['storage']['type'] == 's3'
        assert input_config['storage']['bucket'] == 'test-bucket'
        assert input_config['storage']['prefix'] == 'video1/'
        
        # 验证 callback
        assert request_item['callback_url'] == 'https://example.com/callback'
        assert request_item['callback_status'] == 'pending'
        
        # 验证 frame_stats
        frame_stats = request_item['frame_stats']
        assert frame_stats['total'] == 5
        assert frame_stats['completed'] == 0
        assert frame_stats['failed'] == 0
        assert frame_stats['pending'] == 5
        assert frame_stats['processing'] == 0
        
        # 验证批次信息
        assert request_item['total_batches'] == 1
        batch_info = request_item['batch_info']
        assert len(batch_info) == 1
        assert batch_info[0]['batch_id'] == 'batch-0'
        assert batch_info[0]['batch_index'] == 0
        
        # 验证时间戳格式和合理性
        created_at = request_item['created_at']
        last_activity_at = request_item['last_activity_at']
        
        # 验证 ISO 8601 格式
        assert 'T' in created_at
        assert 'T' in last_activity_at
        
        # 验证时间戳在当前时间附近（5秒内）
        assert_timestamp_recent(created_at, tolerance_seconds=5)
        assert_timestamp_recent(last_activity_at, tolerance_seconds=5)
        
        # 验证逻辑关系
        assert created_at == last_activity_at
        
        # 验证版本号
        assert request_item['version'] == 0
        
        # 验证点 4: SQS 中发送了批次消息
        sqs = mock_aws_resources['sqs_client']
        queue_url = mock_aws_resources['sqs_url']
        
        messages = []
        while True:
            msg_response = sqs.receive_message(
                QueueUrl=queue_url,
                MaxNumberOfMessages=10,
                WaitTimeSeconds=1
            )
            if 'Messages' not in msg_response:
                break
            messages.extend(msg_response['Messages'])
            for msg in msg_response['Messages']:
                sqs.delete_message(
                    QueueUrl=queue_url,
                    ReceiptHandle=msg['ReceiptHandle']
                )
        
        assert len(messages) == 1  # 5帧应该只生成1个批次消息
        
        # 验证消息中包含所有必需字段和具体值
        msg = messages[0]
        msg_body = json.loads(msg['Body'])
        
        # 必需字段
        assert 'request_id' in msg_body
        assert 'batch_id' in msg_body
        assert 'batch_index' in msg_body
        assert 'core_range' in msg_body
        assert 'frame_range' in msg_body
        
        # 验证具体值
        assert msg_body['request_id'] == request_id
        assert msg_body['batch_id'] == 'batch-0'
        assert msg_body['batch_index'] == 0
        assert msg_body['core_range'] == [0, 4]
        assert msg_body['frame_range'] == [0, 4]


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
