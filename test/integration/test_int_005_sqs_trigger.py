"""
INT-005: SQS 触发 Lambda

测试目标: 验证 SQS 消息触发 Frame Processor Lambda
"""
import boto3
import json
import pytest
import time
import uuid
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

# AWS 资源配置
REQUEST_TABLE = 'InfrastructureStack-RequestTableC81DB378-FU6UID33GSK6'
FRAME_TABLE = 'InfrastructureStack-FrameTableA9FEF785-1DW4R9CW8GOGK'
QUEUE_URL = 'https://sqs.us-east-1.amazonaws.com/257712309840/InfrastructureStack-BatchQueue28C25975-wvIxenGslUhn'
REGION = 'us-east-1'

# 测试图片 URL
TEST_IMAGE_URL = 'https://d1ailgqvsvzgh0.cloudfront.net/images/nocache/drinking-detection/drinking/image1.jpg'


@pytest.mark.integration
class TestINT005SQSTrigger:
    """INT-005: SQS 触发 Lambda"""

    @pytest.fixture
    def dynamodb(self):
        """DynamoDB 客户端"""
        return boto3.resource('dynamodb', region_name=REGION)

    @pytest.fixture
    def sqs(self):
        """SQS 客户端"""
        return boto3.client('sqs', region_name=REGION)

    def test_sqs_trigger_frame_processor(self, dynamodb, sqs):
        """
        测试目标: 验证 SQS 消息触发 Frame Processor Lambda 处理

        验证点:
        1. SQS 消息成功发送
        2. Frame 记录被创建
        3. Frame 状态变为 completed
        4. Frame 包含 policy_results
        5. Request 的 frame_stats 被更新
        """
        request_id = f"int-005-{uuid.uuid4()}"
        now = datetime.utcnow().isoformat() + 'Z'

        print(f"\n{'='*60}")
        print(f"INT-005: SQS 触发 Lambda")
        print(f"{'='*60}")

        # 1. 创建 Request 记录
        print(f"\n[步骤 1] 创建 Request 记录...")
        print(f"  Request ID: {request_id}")
        logger.info(f"Creating request record: {request_id}")

        request_table = dynamodb.Table(REQUEST_TABLE)
        request_item = {
            'request_id': request_id,
            'name': 'int-005-sqs-trigger',
            'status': 'running',
            'input_config': {
                'type': 'http',
                'urls': [TEST_IMAGE_URL]
            },
            'callback_url': 'https://webhook.site/test',
            'callback_status': 'pending',
            'total_frames': 1,
            'frame_stats': {
                'total': 1,
                'completed': 0,
                'failed': 0,
                'pending': 1
            },
            'created_at': now,
            'last_activity_at': now,
            'version': 1
        }
        request_table.put_item(Item=request_item)
        print(f"  ✓ Request 记录已创建")

        # 2. 发送 SQS 消息
        print(f"\n[步骤 2] 发送 SQS 消息...")
        message = {
            'request_id': request_id,
            'request_name': 'int-005-sqs-trigger',
            'frame_index': 0,
            'storage_config': {
                'type': 'http',
                'urls': [TEST_IMAGE_URL]
            },
            'target_frame_key': TEST_IMAGE_URL,
            'before_frame_keys': [],
            'after_frame_keys': []
        }

        response = sqs.send_message(
            QueueUrl=QUEUE_URL,
            MessageBody=json.dumps(message, ensure_ascii=False)
        )
        message_id = response['MessageId']
        print(f"  ✓ SQS 消息已发送: {message_id}")
        logger.info(f"SQS message sent: {message_id}")

        # 3. 等待处理完成
        print(f"\n[步骤 3] 等待 Lambda 处理...")
        frame_table = dynamodb.Table(FRAME_TABLE)
        max_wait = 60
        wait_interval = 3
        elapsed = 0

        frame_item = None
        while elapsed < max_wait:
            time.sleep(wait_interval)
            elapsed += wait_interval

            try:
                response = frame_table.get_item(
                    Key={'request_id': request_id, 'frame_index': 0}
                )
                if 'Item' in response:
                    frame_item = response['Item']
                    status = frame_item.get('status')
                    print(f"  [{elapsed}s] Frame 状态: {status}")

                    if status in ['completed', 'failed']:
                        break
                else:
                    print(f"  [{elapsed}s] Frame 记录尚未创建...")
            except Exception as e:
                print(f"  [{elapsed}s] 查询失败: {e}")

        # 4. 验证 Frame 记录
        print(f"\n[步骤 4] 验证 Frame 记录...")

        assert frame_item is not None, "验证失败: Frame 记录未创建"
        print(f"  ✓ Frame 记录已创建")

        frame_status = frame_item.get('status')
        assert frame_status == 'completed', \
            f"验证失败: Frame 状态应为 completed, 实际: {frame_status}"
        print(f"  ✓ Frame 状态: completed")

        policy_results = frame_item.get('policy_results', {})
        assert policy_results, "验证失败: Frame 缺少 policy_results"
        print(f"  ✓ policy_results 存在: {list(policy_results.keys())}")

        # 5. 验证 Request 更新
        print(f"\n[步骤 5] 验证 Request 更新...")
        response = request_table.get_item(Key={'request_id': request_id})
        updated_request = response.get('Item', {})

        frame_stats = updated_request.get('frame_stats', {})
        completed = int(frame_stats.get('completed', 0))
        assert completed >= 1, \
            f"验证失败: frame_stats.completed 应 >= 1, 实际: {completed}"
        print(f"  ✓ frame_stats.completed: {completed}")

        logger.info(
            f"INT-005 passed: request_id={request_id}, "
            f"frame_status={frame_status}, completed={completed}"
        )

        # 6. 清理测试数据
        print(f"\n[步骤 6] 清理测试数据...")
        try:
            frame_table.delete_item(
                Key={'request_id': request_id, 'frame_index': 0}
            )
            request_table.delete_item(Key={'request_id': request_id})
            print(f"  ✓ 测试数据已清理")
        except Exception as e:
            print(f"  ⚠ 清理失败: {e}")

        print(f"\n{'='*60}")
        print(f"✅ INT-005 测试通过")
        print(f"{'='*60}\n")
