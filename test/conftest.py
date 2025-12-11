"""
pytest 配置和共享 fixtures

Moto 资源初始化规范：
- 所有 AWS mock 资源的创建应使用本文件中的公共方法
- 测试文件不应独立创建 mock 资源，应使用 fixtures 或调用公共方法
"""
import pytest


# =============================================================================
# Pytest Markers 注册
# =============================================================================

def pytest_configure(config):
    """注册自定义 markers"""
    config.addinivalue_line("markers", "integration: 集成测试")
    config.addinivalue_line("markers", "e2e: 端到端测试")
    config.addinivalue_line("markers", "bedrock: 需要 Bedrock 的测试")
import boto3
import os
from datetime import datetime, timedelta, timezone
from moto import mock_aws


# =============================================================================
# 辅助验证函数
# =============================================================================

def assert_timestamp_recent(timestamp_str: str, tolerance_seconds: int = 60):
    """
    验证时间戳是否在当前时间附近
    
    Args:
        timestamp_str: ISO 8601 格式的时间戳字符串
        tolerance_seconds: 容忍的时间差（秒），默认 60 秒
    
    Raises:
        AssertionError: 如果时间戳不在合理范围内
    """
    # 解析时间戳，处理不同格式
    if timestamp_str.endswith('Z'):
        # 移除 Z 并添加 UTC 时区
        timestamp = datetime.fromisoformat(timestamp_str[:-1]).replace(tzinfo=timezone.utc)
    elif '+' in timestamp_str or timestamp_str.count('-') > 2:
        timestamp = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
    else:
        timestamp = datetime.fromisoformat(timestamp_str).replace(tzinfo=timezone.utc)
    
    # 获取当前 UTC 时间（带时区）
    now = datetime.now(timezone.utc)
    
    # 计算时间差
    diff = abs((timestamp - now).total_seconds())
    
    # 验证在容忍范围内
    assert diff <= tolerance_seconds, (
        f"Timestamp {timestamp_str} is {diff:.1f}s away from now, "
        f"exceeds tolerance of {tolerance_seconds}s"
    )


# =============================================================================
# Moto 资源创建公共方法（供测试直接调用）
# =============================================================================

def setup_test_environment():
    """
    设置测试环境变量
    
    在 @mock_aws 装饰器内部调用此方法设置必要的环境变量
    """
    os.environ['AWS_DEFAULT_REGION'] = 'us-east-1'
    os.environ['AWS_ACCESS_KEY_ID'] = 'testing'
    os.environ['AWS_SECRET_ACCESS_KEY'] = 'testing'
    os.environ['REQUEST_TABLE'] = 'Request'
    os.environ['FRAME_TABLE'] = 'Frame'
    os.environ['CONTEXT_MAX_FRAMES'] = '60'


def create_request_table():
    """
    创建 mock DynamoDB Request 表
    
    Returns:
        boto3 Table resource
    """
    dynamodb = boto3.resource('dynamodb', region_name='us-east-1')
    table = dynamodb.create_table(
        TableName='Request',
        KeySchema=[{'AttributeName': 'request_id', 'KeyType': 'HASH'}],
        AttributeDefinitions=[
            {'AttributeName': 'request_id', 'AttributeType': 'S'},
            {'AttributeName': 'name', 'AttributeType': 'S'},
            {'AttributeName': 'created_at', 'AttributeType': 'S'}
        ],
        GlobalSecondaryIndexes=[{
            'IndexName': 'name-created_at-index',
            'KeySchema': [
                {'AttributeName': 'name', 'KeyType': 'HASH'},
                {'AttributeName': 'created_at', 'KeyType': 'RANGE'}
            ],
            'Projection': {'ProjectionType': 'ALL'}
        }],
        BillingMode='PAY_PER_REQUEST'
    )
    return table


def create_frame_table():
    """
    创建 mock DynamoDB Frame 表
    
    Returns:
        boto3 Table resource
    """
    dynamodb = boto3.resource('dynamodb', region_name='us-east-1')
    table = dynamodb.create_table(
        TableName='Frame',
        KeySchema=[
            {'AttributeName': 'request_id', 'KeyType': 'HASH'},
            {'AttributeName': 'frame_index', 'KeyType': 'RANGE'}
        ],
        AttributeDefinitions=[
            {'AttributeName': 'request_id', 'AttributeType': 'S'},
            {'AttributeName': 'frame_index', 'AttributeType': 'N'}
        ],
        BillingMode='PAY_PER_REQUEST'
    )
    return table


def create_frame_queue():
    """
    创建 mock SQS Frame 队列
    
    Returns:
        tuple: (sqs_client, queue_url)
    """
    sqs = boto3.client('sqs', region_name='us-east-1')
    response = sqs.create_queue(QueueName='frame-queue')
    queue_url = response['QueueUrl']
    os.environ['BATCH_QUEUE_URL'] = queue_url
    return sqs, queue_url


def create_results_bucket(bucket_name: str = 'results-bucket'):
    """
    创建 mock S3 结果存储桶
    
    Args:
        bucket_name: 桶名称
    
    Returns:
        boto3 S3 client
    """
    s3 = boto3.client('s3', region_name='us-east-1')
    s3.create_bucket(Bucket=bucket_name)
    os.environ['RESULTS_S3_BUCKET'] = bucket_name
    return s3


def create_s3_bucket_with_images(bucket_name: str, prefix: str, image_count: int):
    """
    创建 mock S3 桶并上传测试图片
    
    Args:
        bucket_name: 桶名称
        prefix: 图片前缀路径
        image_count: 图片数量
    
    Returns:
        boto3 S3 client
    """
    s3 = boto3.client('s3', region_name='us-east-1')
    s3.create_bucket(Bucket=bucket_name)
    
    for i in range(1, image_count + 1):
        key = f"{prefix}frame-{i:03d}.jpg"
        s3.put_object(Bucket=bucket_name, Key=key, Body=b'fake image data')
    
    return s3


def receive_all_sqs_messages(sqs_client, queue_url: str):
    """
    接收并删除队列中的所有消息
    
    Args:
        sqs_client: boto3 SQS client
        queue_url: 队列 URL
    
    Returns:
        list: 所有消息列表
    """
    messages = []
    while True:
        resp = sqs_client.receive_message(
            QueueUrl=queue_url,
            MaxNumberOfMessages=10,
            WaitTimeSeconds=0
        )
        if 'Messages' not in resp:
            break
        messages.extend(resp['Messages'])
        for msg in resp['Messages']:
            sqs_client.delete_message(
                QueueUrl=queue_url,
                ReceiptHandle=msg['ReceiptHandle']
            )
    return messages


# =============================================================================
# Pytest Fixtures（供 fixture 注入使用）
# =============================================================================

@pytest.fixture
def mock_dynamodb_table():
    """创建 mock DynamoDB Request 表"""
    with mock_aws():
        table = create_request_table()
        yield table


@pytest.fixture
def mock_sqs_queue():
    """创建 mock SQS 队列"""
    with mock_aws():
        sqs, queue_url = create_frame_queue()
        yield {'client': sqs, 'url': queue_url}


@pytest.fixture
def mock_s3_bucket():
    """创建 mock S3 桶"""
    with mock_aws():
        s3 = create_results_bucket('test-bucket')
        yield s3


@pytest.fixture
def setup_env():
    """设置测试环境变量"""
    original_env = os.environ.copy()
    
    setup_test_environment()
    
    yield
    
    # 恢复原始环境变量
    os.environ.clear()
    os.environ.update(original_env)


@pytest.fixture
def mock_aws_resources(mock_dynamodb_table, mock_sqs_queue, setup_env):
    """组合 fixture：DynamoDB + SQS + 环境变量"""
    yield {
        'dynamodb_table': mock_dynamodb_table,
        'sqs_client': mock_sqs_queue['client'],
        'sqs_url': mock_sqs_queue['url']
    }
