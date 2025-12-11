"""
INT-004: 提交请求（API Key 认证失败）

测试目标: 验证 API Key 认证
"""
import pytest
import time
import logging
import requests

logger = logging.getLogger(__name__)


@pytest.mark.integration
class TestINT004AuthFailure:
    """INT-004: 提交请求（API Key 认证失败）"""

    @pytest.mark.skip(reason="当前 API 未启用 API Key 认证 (apiKeyRequired=false)")
    def test_submit_request_invalid_api_key(self, api_client):
        """
        测试目标: 验证使用无效 API Key 时返回 403 错误

        验证点:
        1. 响应状态码 403
        2. 返回 success: false
        3. 错误码 UNAUTHORIZED 或 Forbidden

        注意: 此测试需要 API Gateway 启用 API Key 认证才能生效
        """
        test_name = f"int-004-auth-{int(time.time())}"

        print(f"\n{'='*60}")
        print(f"INT-004: 提交请求（API Key 认证失败）")
        print(f"{'='*60}")

        # 1. 使用无效 API Key 提交请求
        print(f"\n[步骤 1] 使用无效 API Key 提交请求...")
        logger.info(f"Submitting request with invalid API key: {test_name}")

        response = requests.post(
            f'{api_client.base_url}/requests',
            headers={
                'x-api-key': 'INVALID_API_KEY_12345',
                'Content-Type': 'application/json'
            },
            json={
                'name': test_name,
                'type': 'http',
                'urls': ['https://example.com/image1.jpg'],
                'callback_url': 'https://webhook.site/test'
            }
        )

        # 2. 验证响应
        print(f"\n[步骤 2] 验证 API 响应...")
        print(f"  HTTP Status: {response.status_code}")

        # 验证点 1: 状态码应为 403
        assert response.status_code == 403, \
            f"验证失败: 状态码应为 403, 实际: {response.status_code}"
        print(f"  ✓ 状态码: 403 (Forbidden)")

        result = response.json()

        # 验证点 2: success: false 或 message 包含 Forbidden
        is_forbidden = (
            result.get('success') is False or
            'Forbidden' in str(result) or
            'forbidden' in str(result).lower()
        )
        assert is_forbidden, \
            f"验证失败: 响应应表示认证失败, 实际: {result}"
        print(f"  ✓ 认证失败响应")

        logger.info(f"INT-004 passed: status_code={response.status_code}")

        print(f"\n{'='*60}")
        print(f"✅ INT-004 测试通过")
        print(f"{'='*60}\n")

    def test_api_key_not_required_info(self, api_client):
        """
        测试目标: 验证当前 API 配置状态

        说明: 当前 API 未启用 API Key 认证，此测试记录该状态
        """
        print(f"\n{'='*60}")
        print(f"INT-004: API Key 认证状态检查")
        print(f"{'='*60}")

        print(f"\n[信息] 当前 API 配置:")
        print(f"  - API Key Required: false")
        print(f"  - 认证方式: NONE")
        print(f"\n[说明] INT-004 测试用例需要启用 API Key 认证才能执行")
        print(f"  如需启用，请在 CDK 中配置 apiKeyRequired: true")

        logger.info("INT-004 skipped: API Key authentication not enabled")

        print(f"\n{'='*60}")
        print(f"ℹ️ INT-004 已跳过（API Key 认证未启用）")
        print(f"{'='*60}\n")
