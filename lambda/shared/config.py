import os

class Config:
    # DynamoDB Tables
    REQUEST_TABLE = os.getenv('REQUEST_TABLE', '')
    FRAME_TABLE = os.getenv('FRAME_TABLE', '')
    
    # SQS
    BATCH_QUEUE_URL = os.getenv('BATCH_QUEUE_URL', '')
    
    # S3
    RESULTS_S3_BUCKET = os.getenv('RESULTS_S3_BUCKET', os.getenv('RESULTS_BUCKET', ''))
    RESULTS_PRESIGNED_URL_EXPIRATION = int(os.getenv('RESULTS_PRESIGNED_URL_EXPIRATION', '86400'))
    
    # Bedrock
    BEDROCK_MODEL_ID = os.getenv('BEDROCK_MODEL_ID', 'us.amazon.nova-lite-v1:0')
    BEDROCK_REGION = os.getenv('BEDROCK_REGION', 'us-east-1')
    BEDROCK_MAX_RETRIES = int(os.getenv('BEDROCK_MAX_RETRIES', '3'))
    BEDROCK_RETRY_DELAYS = [int(d) for d in os.getenv('BEDROCK_RETRY_DELAYS', '2,4,8').split(',')]
    
    # Batch
    BATCH_SIZE_COEFFICIENT = float(os.getenv('BATCH_SIZE_COEFFICIENT', '1.0'))
    CONTEXT_MAX_FRAMES = int(os.getenv('CONTEXT_MAX_FRAMES', '60'))
    
    # Worker
    WORKER_CONCURRENCY = int(os.getenv('WORKER_CONCURRENCY', '10'))
    
    # Callback
    CALLBACK_MAX_RETRIES = int(os.getenv('CALLBACK_MAX_RETRIES', '5'))
    CALLBACK_RETRY_DELAYS = [int(d) for d in os.getenv('CALLBACK_RETRY_DELAYS', '0,60,300,1800,3600').split(',')]
    
    # Frame
    FRAME_MAX_RETRIES = int(os.getenv('FRAME_MAX_RETRIES', '3'))
    FRAME_RETRY_DELAYS = [int(d) for d in os.getenv('FRAME_RETRY_DELAYS', '5,10,20').split(',')]
    
    # Policy
    ENABLED_POLICIES = os.getenv('ENABLED_POLICIES', '').split(',')
    
    # Health Check
    HEALTH_CHECK_INTERVAL = int(os.getenv('HEALTH_CHECK_INTERVAL', '300'))
    REQUEST_TIMEOUT = int(os.getenv('REQUEST_TIMEOUT', '7200'))
