"""
端到端集成测试 pytest 配置
"""
import pytest
import json
import os
import logging
from pathlib import Path
from .helpers import APIClient, Waiter, WaitConfig, RequestWaiter, ResultVerifier

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('log.log'),
        logging.StreamHandler()
    ]
)


@pytest.fixture(scope='session')
def api_url():
    """API URL"""
    url = os.environ.get('API_URL')
    if not url:
        pytest.skip("API_URL 环境变量未设置")
    return url


@pytest.fixture(scope='session')
def api_key():
    """API Key"""
    key = os.environ.get('API_KEY')
    if not key:
        pytest.skip("API_KEY 环境变量未设置")
    return key


@pytest.fixture(scope='session')
def api_client(api_url, api_key):
    """API 客户端"""
    return APIClient(api_url, api_key)


@pytest.fixture(scope='session')
def waiter():
    """等待器 - 配置较短的超时时间（图片不多，处理应该很快）"""
    config = WaitConfig(
        initial_wait=2.0,    # 初始等待 2 秒
        max_wait=5.0,        # 最大等待 5 秒
        backoff_factor=1.5,  # 退避因子
        timeout=60           # 总超时 60 秒（3张图片应该很快）
    )
    return Waiter(config)


@pytest.fixture(scope='session')
def request_waiter(api_client, waiter):
    """请求等待器"""
    return RequestWaiter(api_client, waiter)


@pytest.fixture(scope='session')
def verifier():
    """结果验证器"""
    return ResultVerifier()


@pytest.fixture
def test_case_loader():
    """测试用例加载器"""
    def load(name: str) -> dict:
        path = (
            Path(__file__).parent.parent /
            'fixtures' / 'integration' / 'test-cases' / f'{name}.json'
        )
        with open(path) as f:
            return json.load(f)
    return load
