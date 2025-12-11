"""
INT-002: 提交请求（S3）

测试目标: 验证通过 S3 存储桶提交请求的完整流程
"""
import pytest
import re
import time
import logging

logger = logging.getLogger(__name__)

# UUID 格式正则
UUID_PATTERN = re.compile(
    r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$',
    re.IGNORECASE
)

# 测试用 S3 配置（使用已有的测试图片）
TEST_S3_BUCKET = 'image-analyzer-test-1763980954'
TEST_S3_PREFIX = 'test-video/'
TEST_S3_REGION = 'us-east-1'
EXPECTED_FRAME_COUNT = 10


@pytest.mark.integration
class TestINT002SubmitS3:
    """INT-002: 提交请求（S3）"""

    def test_submit_request_s3(self, api_client):
        """
        测试目标: 验证通过 S3 存储桶提交请求

        验证点:
        1. API 响应状态码 200
        2. 响应包含 success: true
        3. 返回有效的 request_id（UUID 格式）
        4. 返回 status: 'pending'
        5. 返回正确的 total_frames
        """
        test_name = f"int-002-s3-{int(time.time())}"

        print(f"\n{'='*60}")
        print(f"INT-002: 提交请求（S3）")
        print(f"{'='*60}")

        # 1. 提交请求
        print(f"\n[步骤 1] 提交 S3 请求...")
        print(f"  Name: {test_name}")
        print(f"  Bucket: {TEST_S3_BUCKET}")
        print(f"  Prefix: {TEST_S3_PREFIX}")
        print(f"  Region: {TEST_S3_REGION}")
        logger.info(
            f"Submitting S3 request: {test_name}, "
            f"bucket={TEST_S3_BUCKET}, prefix={TEST_S3_PREFIX}"
        )

        response = api_client.submit_request_s3(
            name=test_name,
            bucket=TEST_S3_BUCKET,
            prefix=TEST_S3_PREFIX,
            region=TEST_S3_REGION,
            callback_url='https://webhook.site/test'
        )

        # 2. 验证响应
        print(f"\n[步骤 2] 验证 API 响应...")

        # 验证点 1 & 2: success: true
        assert response.get('success') is True, \
            f"验证失败: success 应为 true, 实际: {response.get('success')}"
        print(f"  ✓ success: true")

        data = response.get('data', {})

        # 验证点 3: request_id 是有效的 UUID
        request_id = data.get('request_id')
        assert request_id is not None, "验证失败: 缺少 request_id"
        assert UUID_PATTERN.match(request_id), \
            f"验证失败: request_id 不是有效的 UUID 格式, 实际: {request_id}"
        print(f"  ✓ request_id: {request_id} (UUID 格式)")

        # 验证点 4: status: 'pending'
        status = data.get('status')
        assert status == 'pending', \
            f"验证失败: status 应为 'pending', 实际: {status}"
        print(f"  ✓ status: pending")

        # 验证点 5: total_frames
        total_frames = data.get('total_frames')
        assert total_frames == EXPECTED_FRAME_COUNT, \
            f"验证失败: total_frames 应为 {EXPECTED_FRAME_COUNT}, 实际: {total_frames}"
        print(f"  ✓ total_frames: {total_frames}")

        logger.info(
            f"INT-002 passed: request_id={request_id}, "
            f"status={status}, total_frames={total_frames}"
        )

        print(f"\n{'='*60}")
        print(f"✅ INT-002 测试通过")
        print(f"{'='*60}\n")
