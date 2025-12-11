"""
INT-001: 提交请求（Image List）

测试目标: 验证通过 URL 列表提交请求的完整流程
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


@pytest.mark.integration
class TestINT001SubmitUrlList:
    """INT-001: 提交请求（Image List）"""

    def test_submit_request_urllist(self, test_case_loader, api_client):
        """
        测试目标: 验证通过 URL 列表提交请求

        验证点:
        1. API 响应状态码 200
        2. 响应包含 success: true
        3. 返回有效的 request_id（UUID 格式）
        4. 返回 status: 'pending'
        5. 返回 total_frames: 3
        """
        # 加载测试配置（复用 drinking-positive 的 URL）
        test_config = test_case_loader('drinking-positive')
        urls = [frame['url'] for frame in test_config['frames']]
        test_name = f"int-001-urllist-{int(time.time())}"

        print(f"\n{'='*60}")
        print(f"INT-001: 提交请求（Image List）")
        print(f"{'='*60}")

        # 1. 提交请求
        print(f"\n[步骤 1] 提交请求...")
        print(f"  Name: {test_name}")
        print(f"  URLs: {len(urls)} 个")
        logger.info(f"Submitting request: {test_name} with {len(urls)} URLs")

        response = api_client.submit_request(
            name=test_name,
            urls=urls,
            callback_url='https://webhook.site/test'
        )

        # 2. 验证响应
        print(f"\n[步骤 2] 验证 API 响应...")

        # 验证点 2: success: true
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

        # 验证点 5: total_frames: 3
        total_frames = data.get('total_frames')
        assert total_frames == len(urls), \
            f"验证失败: total_frames 应为 {len(urls)}, 实际: {total_frames}"
        print(f"  ✓ total_frames: {total_frames}")

        logger.info(
            f"INT-001 passed: request_id={request_id}, "
            f"status={status}, total_frames={total_frames}"
        )

        print(f"\n{'='*60}")
        print(f"✅ INT-001 测试通过")
        print(f"{'='*60}\n")
