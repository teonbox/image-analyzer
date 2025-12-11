"""
INT-003: 提交请求（多个前缀错误）

测试目标: 验证检测到多个前缀时返回错误
"""
import pytest
import time
import logging
import requests

logger = logging.getLogger(__name__)


@pytest.mark.integration
class TestINT003MultiplePrefix:
    """INT-003: 提交请求（多个前缀错误）"""

    def test_submit_request_multiple_prefix_error(self, api_client):
        """
        测试目标: 验证提交包含多个前缀的 URL 时返回错误

        验证点:
        1. 响应状态码 400 或 500（取决于实现）
        2. 返回 success: false
        3. 错误码包含 MULTIPLE_PREFIXES 或相关信息
        4. 错误详情包含检测到的前缀信息
        """
        test_name = f"int-003-multi-prefix-{int(time.time())}"

        # 使用不同前缀的 URL
        urls_with_different_prefixes = [
            "https://d1ailgqvsvzgh0.cloudfront.net/images/nocache/drinking-detection/drinking/image1.jpg",
            "https://d1ailgqvsvzgh0.cloudfront.net/images/nocache/drinking-detection/holding/image1.jpg",
        ]

        print(f"\n{'='*60}")
        print(f"INT-003: 提交请求（多个前缀错误）")
        print(f"{'='*60}")

        # 1. 提交请求
        print(f"\n[步骤 1] 提交包含多个前缀的请求...")
        print(f"  Name: {test_name}")
        print(f"  URLs:")
        for url in urls_with_different_prefixes:
            print(f"    - {url}")
        logger.info(f"Submitting request with multiple prefixes: {test_name}")

        # 使用 requests 直接调用，因为 api_client 会 raise_for_status
        response = requests.post(
            f'{api_client.base_url}/requests',
            headers={
                'x-api-key': api_client.api_key,
                'Content-Type': 'application/json'
            },
            json={
                'name': test_name,
                'type': 'http',
                'urls': urls_with_different_prefixes,
                'callback_url': 'https://webhook.site/test'
            }
        )

        # 2. 验证响应
        print(f"\n[步骤 2] 验证 API 响应...")
        print(f"  HTTP Status: {response.status_code}")

        # 验证点 1: 状态码应为 400 或 500
        assert response.status_code in [400, 500], \
            f"验证失败: 状态码应为 400 或 500, 实际: {response.status_code}"
        print(f"  ✓ 状态码: {response.status_code} (错误响应)")

        result = response.json()
        print(f"  响应内容: {result}")

        # 验证点 2: success: false
        assert result.get('success') is False, \
            f"验证失败: success 应为 false, 实际: {result.get('success')}"
        print(f"  ✓ success: false")

        # 验证点 3 & 4: 错误信息包含前缀相关内容
        error = result.get('error', {})
        error_code = error.get('code', '')
        error_message = error.get('message', '')

        # 检查错误码或消息中包含 prefix 相关信息
        has_prefix_error = (
            'prefix' in error_code.lower() or
            'prefix' in error_message.lower() or
            'Multiple' in error_message
        )
        assert has_prefix_error, \
            f"验证失败: 错误信息应包含前缀相关内容, 实际: code={error_code}, message={error_message}"
        print(f"  ✓ 错误码: {error_code}")
        print(f"  ✓ 错误信息: {error_message}")

        logger.info(
            f"INT-003 passed: status_code={response.status_code}, "
            f"error_code={error_code}"
        )

        print(f"\n{'='*60}")
        print(f"✅ INT-003 测试通过")
        print(f"{'='*60}\n")
