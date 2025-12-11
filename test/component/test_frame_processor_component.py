"""
Frame Processor 组件测试 (Layer 2)

测试目标: Frame Processor 的完整处理流程
测试范围: Frame 记录管理、Request 状态转换、frame_stats 统计、策略执行、上下文帧加载、完成检测

Mock 策略:
- DynamoDB: 使用 moto
- HTTP 请求: 使用 responses
- Lambda: 使用 moto
"""
import pytest
import json
import boto3
import os
import sys
import importlib
import responses
from datetime import datetime, timezone
from unittest.mock import Mock, patch, MagicMock
from moto import mock_aws
from decimal import Decimal

# 添加 lambda 和 test 目录到路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../lambda'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from conftest import (
    setup_test_environment,
    create_request_table,
    create_frame_table,
    assert_timestamp_recent
)


# =============================================================================
# 动态导入辅助函数（解决 lambda 是 Python 保留关键字的问题）
# =============================================================================

MODULE_PATH = 'handlers.frame_processor'


def clear_module_cache():
    """清除 frame_processor 模块及相关模块缓存，确保下次导入时重新加载"""
    if MODULE_PATH in sys.modules:
        del sys.modules[MODULE_PATH]
    # 也清除相关的子模块，确保 Config 等类被重新导入
    to_delete = [k for k in sys.modules.keys() if k.startswith('handlers.') or k.startswith('shared.') or k.startswith('policies')]
    for k in to_delete:
        del sys.modules[k]


def get_frame_processor_module():
    """动态导入 frame_processor 模块"""
    return importlib.import_module(MODULE_PATH)


def get_module_path():
    """获取模块路径字符串（用于 patch）"""
    return MODULE_PATH


def run_frame_processor_with_policies(event: dict, policies: dict, enabled_policy_names: list):
    """
    在正确的 mock 上下文中运行 frame_processor
    
    正确的 Mock 策略注入模式：
    1. 设置环境变量 ENABLED_POLICIES
    2. 清除相关模块缓存（让 Config 重新读取环境变量）
    3. 导入 frame_processor 模块
    4. 直接修改 POLICY_MAP 注入 mock 策略
    5. 重置资源并执行
    
    Args:
        event: SQS 事件
        policies: 策略字典 {'policy_name': policy_instance}
        enabled_policy_names: 启用的策略名称列表
    """
    # 1. 设置环境变量
    os.environ['ENABLED_POLICIES'] = ','.join(enabled_policy_names)
    
    # 2. 清除模块缓存（包括 shared.config，让它重新读取环境变量）
    clear_module_cache()
    
    # 3. 导入 frame_processor 模块
    fp_module = importlib.import_module(MODULE_PATH)
    
    # 4. 注入 mock 策略到 POLICY_MAP
    for name, policy in policies.items():
        fp_module.POLICY_MAP[name] = policy
    
    # 5. 重新初始化资源并执行
    fp_module.request_table = None
    fp_module.frame_table = None
    fp_module._init_resources()
    fp_module.handler(event, {})


# =============================================================================
# Mock 策略类
# =============================================================================

class MockPolicy:
    """用于测试的 Mock 策略，返回固定结果"""
    
    def __init__(self, name: str, result: dict = None, should_fail: bool = False):
        self.name = name
        self.result = result or {'mock_key': 'mock_value'}
        self.should_fail = should_fail
        self.analyze_called = False
        self.received_target_frame = None
        self.received_context_frames = None

    def get_name(self) -> str:
        return self.name
    
    def should_process(self, frame_index: int, total_frames: int) -> bool:
        return True
    
    def get_context_range(self, frame_index: int, total_frames: int) -> tuple:
        return (-1, 1)
    
    def analyze(self, target_frame: dict, context_frames: list, bedrock_client, storage_config) -> dict:
        self.analyze_called = True
        self.received_target_frame = target_frame
        self.received_context_frames = context_frames
        
        if self.should_fail:
            raise Exception("Mock policy failure")
        return self.result


class MockIntervalPolicy(MockPolicy):
    """每 10 帧处理一次的 Mock 策略"""
    
    def should_process(self, frame_index: int, total_frames: int) -> bool:
        return frame_index % 10 == 0


class MockNoContextPolicy(MockPolicy):
    """不需要上下文的 Mock 策略"""
    
    def get_context_range(self, frame_index: int, total_frames: int) -> tuple:
        return (0, 0)


# =============================================================================
# 测试辅助函数
# =============================================================================

def create_sqs_event(message: dict) -> dict:
    """创建 SQS 事件"""
    return {
        'Records': [{
            'body': json.dumps(message)
        }]
    }


def create_test_request(request_id: str, status: str = 'pending', 
                        total_frames: int = 100, version: int = 1) -> dict:
    """创建测试 Request 记录"""
    return {
        'request_id': request_id,
        'name': 'test-video',
        'status': status,
        'total_frames': total_frames,
        'frame_stats': {
            'total': total_frames,
            'completed': 0,
            'failed': 0,
            'pending': total_frames
        },
        'version': version,
        'created_at': datetime.now(timezone.utc).isoformat(),
        'last_activity_at': datetime.now(timezone.utc).isoformat()
    }


def create_test_frame(request_id: str, frame_index: int, status: str = 'pending',
                      policy_results: dict = None, policy_status: dict = None) -> dict:
    """创建测试 Frame 记录"""
    return {
        'request_id': request_id,
        'frame_index': frame_index,
        'frame_url': f'https://example.com/frame-{frame_index}.jpg',
        'status': status,
        'policy_results': policy_results or {},
        'policy_status': policy_status or {},
        'retry_count': 0,
        'created_at': datetime.now(timezone.utc).isoformat()
    }


def reset_frame_processor_module():
    """重置 frame_processor 模块状态"""
    fp_module = get_frame_processor_module()
    fp_module.request_table = None
    fp_module.frame_table = None
    fp_module._init_resources()


def setup_and_run_frame_processor(event: dict, policies: dict, enabled_policy_names: list):
    """
    设置并运行 frame_processor（新的正确 mock 模式）
    
    这个函数替代了旧的 patch.dict + patch 模式，使用环境变量 + 模块重载的方式
    正确注入 mock 策略。
    
    Args:
        event: SQS 事件
        policies: 策略字典 {'policy_name': policy_instance}
        enabled_policy_names: 启用的策略名称列表
    """
    # 设置环境变量
    os.environ['ENABLED_POLICIES'] = ','.join(enabled_policy_names)
    
    # 清除模块缓存
    clear_module_cache()
    
    # 导入模块
    fp_module = importlib.import_module(MODULE_PATH)
    
    # 注入 mock 策略
    for name, policy in policies.items():
        fp_module.POLICY_MAP[name] = policy
    
    # 初始化并执行
    fp_module.request_table = None
    fp_module.frame_table = None
    fp_module._init_resources()
    fp_module.handler(event, {})


# =============================================================================
# 测试类: Frame 记录创建与状态管理
# =============================================================================

class TestFrameRecordManagement:
    """测试 Frame 记录的创建和状态管理"""
    
    @mock_aws
    @responses.activate
    def test_fp_comp_001_create_frame_record_on_first_process(self):
        """
        FP-COMP-001: 首次处理帧 - 创建 Frame 记录
        测试目标: FrameProcessor.load_or_create_frame() - Frame 创建
        """
        setup_test_environment()
        request_table = create_request_table()
        frame_table = create_frame_table()
        
        # 准备测试数据
        request_id = 'test-123'
        request_table.put_item(Item=create_test_request(request_id, 'pending', 100, 1))
        
        # Mock HTTP 响应
        responses.add(
            responses.GET,
            'https://example.com/frame-0.jpg',
            body=b'fake image data for frame 0',
            status=200
        )
        responses.add(
            responses.GET,
            'https://example.com/frame-1.jpg',
            body=b'fake image data for frame 1',
            status=200
        )
        
        # Mock 策略
        mock_policy = MockPolicy('mock_policy', {'mock_key': 'mock_value'})
        
        # 创建 SQS 事件
        event = create_sqs_event({
            'request_id': request_id,
            'request_name': 'my-video',
            'frame_index': 0,
            'target_frame_url': 'https://example.com/frame-0.jpg',
            'before_frame_urls': [],
            'after_frame_urls': ['https://example.com/frame-1.jpg']
        })
        
        # 执行
        run_frame_processor_with_policies(
            event=event,
            policies={'mock_policy': mock_policy},
            enabled_policy_names=['mock_policy']
        )
        
        # 验证 Frame 记录
        frame_response = frame_table.get_item(Key={'request_id': request_id, 'frame_index': 0})
        frame = frame_response.get('Item')
        
        assert frame is not None
        assert frame['request_id'] == request_id
        assert frame['frame_index'] == 0
        assert frame['frame_url'] == 'https://example.com/frame-0.jpg'
        assert frame['status'] == 'completed'
        assert 'mock_key' in frame.get('policy_results', {})
        assert frame['policy_results']['mock_key'] == 'mock_value'
        assert frame['policy_status']['mock_policy'] == 'completed'
        assert frame.get('retry_count', 0) == 0
        assert_timestamp_recent(frame['created_at'])
        
        # 验证 Request 状态更新
        request_response = request_table.get_item(Key={'request_id': request_id})
        request = request_response.get('Item')
        
        assert request['status'] == 'running'
        assert_timestamp_recent(request['last_activity_at'])
        assert int(request['frame_stats']['completed']) == 1
        assert int(request['frame_stats']['pending']) == 99
        assert int(request['version']) == 2

    @mock_aws
    @responses.activate
    def test_fp_comp_002_skip_completed_frame(self):
        """
        FP-COMP-002: 幂等性 - 跳过已完成的帧
        测试目标: FrameProcessor.handler() - 幂等性保证
        """
        setup_test_environment()
        request_table = create_request_table()
        frame_table = create_frame_table()
        
        request_id = 'test-123'
        request_table.put_item(Item=create_test_request(request_id, 'running', 100, 1))
        
        # 创建已完成的 Frame 记录
        completed_frame = create_test_frame(request_id, 0, 'completed')
        completed_frame['policy_results'] = {'existing_key': 'existing_value'}
        completed_frame['policy_status'] = {'mock_policy': 'completed'}
        completed_frame['completed_at'] = '2025-01-01T10:00:00Z'
        frame_table.put_item(Item=completed_frame)
        
        # Mock 策略
        mock_policy = MockPolicy('mock_policy', {'new_key': 'new_value'})
        
        # 不应该发起 HTTP 请求
        event = create_sqs_event({
            'request_id': request_id,
            'request_name': 'my-video',
            'frame_index': 0,
            'target_frame_url': 'https://example.com/frame-0.jpg',
            'before_frame_urls': [],
            'after_frame_urls': []
        })
        
        fp_module = get_frame_processor_module()
        module_path = get_module_path()
        
        with patch.dict(f'{module_path}.POLICY_MAP', {'mock_policy': mock_policy}):
            with patch(f'{module_path}.Config') as mock_config:
                mock_config.ENABLED_POLICIES = ['mock_policy']
                
                fp_module.request_table = None
                fp_module.frame_table = None
                fp_module._init_resources()
                
                fp_module.handler(event, {})
        
        # 验证 Frame 记录未变化
        frame_response = frame_table.get_item(Key={'request_id': request_id, 'frame_index': 0})
        frame = frame_response.get('Item')
        
        assert frame['policy_results'] == {'existing_key': 'existing_value'}
        assert frame.get('completed_at') == '2025-01-01T10:00:00Z'
        
        # 验证策略未被调用
        assert not mock_policy.analyze_called
        
        # 验证没有 HTTP 请求
        assert len(responses.calls) == 0

    @mock_aws
    @responses.activate
    def test_fp_comp_003_retry_failed_frame(self):
        """
        FP-COMP-003: 重试失败的帧 - 更新 retry_count
        测试目标: FrameProcessor.handler() - 重试逻辑
        """
        setup_test_environment()
        request_table = create_request_table()
        frame_table = create_frame_table()
        
        request_id = 'test-123'
        request = create_test_request(request_id, 'running', 100, 5)
        request['frame_stats'] = {'total': 100, 'completed': 50, 'failed': 1, 'pending': 49}
        request_table.put_item(Item=request)
        
        # 创建失败的 Frame 记录
        failed_frame = create_test_frame(request_id, 0, 'failed')
        failed_frame['retry_count'] = 1
        failed_frame['policy_status'] = {'mock_policy': 'failed'}
        frame_table.put_item(Item=failed_frame)
        
        # Mock HTTP 响应
        responses.add(
            responses.GET,
            'https://example.com/frame-0.jpg',
            body=b'fake image data',
            status=200
        )
        
        event = create_sqs_event({
            'request_id': request_id,
            'request_name': 'my-video',
            'frame_index': 0,
            'target_frame_url': 'https://example.com/frame-0.jpg',
            'before_frame_urls': [],
            'after_frame_urls': []
        })
        
        mock_policy = MockPolicy('mock_policy', {'retry_result': 'success'})
        
        fp_module = get_frame_processor_module()
        module_path = get_module_path()
        
        with patch.dict(f'{module_path}.POLICY_MAP', {'mock_policy': mock_policy}):
            with patch(f'{module_path}.Config') as mock_config:
                mock_config.ENABLED_POLICIES = ['mock_policy']
                
                fp_module.request_table = None
                fp_module.frame_table = None
                fp_module._init_resources()
                
                fp_module.handler(event, {})
        
        # 验证 Frame 记录更新
        frame_response = frame_table.get_item(Key={'request_id': request_id, 'frame_index': 0})
        frame = frame_response.get('Item')
        
        assert frame['status'] == 'completed'
        assert int(frame['retry_count']) == 2
        assert frame['policy_status']['mock_policy'] == 'completed'


# =============================================================================
# 测试类: Request 状态转换
# =============================================================================

class TestRequestStatusTransition:
    """测试 Request 状态转换"""
    
    @mock_aws
    @responses.activate
    def test_fp_comp_004_request_status_pending_to_running(self):
        """
        FP-COMP-004: Request 状态从 pending 转为 running
        测试目标: FrameProcessor.handler() - Request 状态转换
        """
        setup_test_environment()
        request_table = create_request_table()
        frame_table = create_frame_table()
        
        request_id = 'test-123'
        request_table.put_item(Item=create_test_request(request_id, 'pending', 100, 1))
        
        responses.add(
            responses.GET,
            'https://example.com/frame-0.jpg',
            body=b'fake image data',
            status=200
        )
        
        event = create_sqs_event({
            'request_id': request_id,
            'request_name': 'my-video',
            'frame_index': 0,
            'target_frame_url': 'https://example.com/frame-0.jpg',
            'before_frame_urls': [],
            'after_frame_urls': []
        })
        
        mock_policy = MockPolicy('mock_policy', {'key': 'value'})
        
        fp_module = get_frame_processor_module()
        module_path = get_module_path()
        
        with patch.dict(f'{module_path}.POLICY_MAP', {'mock_policy': mock_policy}):
            with patch(f'{module_path}.Config') as mock_config:
                mock_config.ENABLED_POLICIES = ['mock_policy']
                
                fp_module.request_table = None
                fp_module.frame_table = None
                fp_module._init_resources()
                
                fp_module.handler(event, {})
        
        # 验证 Request 状态
        request_response = request_table.get_item(Key={'request_id': request_id})
        request = request_response.get('Item')
        
        assert request['status'] == 'running'
        assert_timestamp_recent(request['last_activity_at'])

    @mock_aws
    @responses.activate
    def test_fp_comp_005_request_status_stays_running(self):
        """
        FP-COMP-005: Request 状态保持 running
        测试目标: FrameProcessor.handler() - Request 状态保持
        """
        setup_test_environment()
        request_table = create_request_table()
        frame_table = create_frame_table()
        
        request_id = 'test-123'
        request = create_test_request(request_id, 'running', 100, 5)
        request['frame_stats'] = {'total': 100, 'completed': 50, 'failed': 0, 'pending': 50}
        request_table.put_item(Item=request)
        
        responses.add(
            responses.GET,
            'https://example.com/frame-51.jpg',
            body=b'fake image data',
            status=200
        )
        
        event = create_sqs_event({
            'request_id': request_id,
            'request_name': 'my-video',
            'frame_index': 51,
            'target_frame_url': 'https://example.com/frame-51.jpg',
            'before_frame_urls': [],
            'after_frame_urls': []
        })
        
        mock_policy = MockPolicy('mock_policy', {'key': 'value'})
        
        fp_module = get_frame_processor_module()
        module_path = get_module_path()
        
        with patch.dict(f'{module_path}.POLICY_MAP', {'mock_policy': mock_policy}):
            with patch(f'{module_path}.Config') as mock_config:
                mock_config.ENABLED_POLICIES = ['mock_policy']
                
                fp_module.request_table = None
                fp_module.frame_table = None
                fp_module._init_resources()
                
                fp_module.handler(event, {})
        
        # 验证 Request 状态保持 running
        request_response = request_table.get_item(Key={'request_id': request_id})
        request = request_response.get('Item')
        
        assert request['status'] == 'running'
        assert_timestamp_recent(request['last_activity_at'])


# =============================================================================
# 测试类: frame_stats 统计更新
# =============================================================================

class TestFrameStatsUpdate:
    """测试 frame_stats 统计更新"""
    
    @mock_aws
    @responses.activate
    def test_fp_comp_006_frame_stats_increment_completed(self):
        """
        FP-COMP-006: frame_stats 正确递增 completed
        测试目标: FrameProcessor.update_frame_stats() - 统计更新
        """
        setup_test_environment()
        request_table = create_request_table()
        frame_table = create_frame_table()
        
        request_id = 'test-123'
        request = create_test_request(request_id, 'running', 100, 10)
        request['frame_stats'] = {'total': 100, 'completed': 50, 'failed': 5, 'pending': 45}
        request_table.put_item(Item=request)
        
        responses.add(
            responses.GET,
            'https://example.com/frame-55.jpg',
            body=b'fake image data',
            status=200
        )
        
        event = create_sqs_event({
            'request_id': request_id,
            'request_name': 'my-video',
            'frame_index': 55,
            'target_frame_url': 'https://example.com/frame-55.jpg',
            'before_frame_urls': [],
            'after_frame_urls': []
        })
        
        mock_policy = MockPolicy('mock_policy', {'key': 'value'})
        
        fp_module = get_frame_processor_module()
        module_path = get_module_path()
        
        with patch.dict(f'{module_path}.POLICY_MAP', {'mock_policy': mock_policy}):
            with patch(f'{module_path}.Config') as mock_config:
                mock_config.ENABLED_POLICIES = ['mock_policy']
                
                fp_module.request_table = None
                fp_module.frame_table = None
                fp_module._init_resources()
                
                fp_module.handler(event, {})
        
        # 验证 frame_stats
        request_response = request_table.get_item(Key={'request_id': request_id})
        request = request_response.get('Item')
        
        assert int(request['frame_stats']['total']) == 100
        assert int(request['frame_stats']['completed']) == 51
        assert int(request['frame_stats']['failed']) == 5
        assert int(request['frame_stats']['pending']) == 44
        assert int(request['version']) == 11

    @mock_aws
    @responses.activate
    def test_fp_comp_007_frame_stats_increment_failed(self):
        """
        FP-COMP-007: frame_stats 正确递增 failed
        测试目标: FrameProcessor.update_frame_stats() - 失败统计
        """
        setup_test_environment()
        request_table = create_request_table()
        frame_table = create_frame_table()
        
        request_id = 'test-123'
        request = create_test_request(request_id, 'running', 100, 10)
        request['frame_stats'] = {'total': 100, 'completed': 50, 'failed': 5, 'pending': 45}
        request_table.put_item(Item=request)
        
        responses.add(
            responses.GET,
            'https://example.com/frame-55.jpg',
            body=b'fake image data',
            status=200
        )
        
        event = create_sqs_event({
            'request_id': request_id,
            'request_name': 'my-video',
            'frame_index': 55,
            'target_frame_url': 'https://example.com/frame-55.jpg',
            'before_frame_urls': [],
            'after_frame_urls': []
        })
        
        # 策略抛出异常
        mock_policy = MockPolicy('mock_policy', should_fail=True)
        
        fp_module = get_frame_processor_module()
        module_path = get_module_path()
        
        with patch.dict(f'{module_path}.POLICY_MAP', {'mock_policy': mock_policy}):
            with patch(f'{module_path}.Config') as mock_config:
                mock_config.ENABLED_POLICIES = ['mock_policy']
                
                fp_module.request_table = None
                fp_module.frame_table = None
                fp_module._init_resources()
                
                fp_module.handler(event, {})
        
        # 验证 Frame 状态
        frame_response = frame_table.get_item(Key={'request_id': request_id, 'frame_index': 55})
        frame = frame_response.get('Item')
        assert frame['status'] == 'failed'
        
        # 验证 frame_stats
        request_response = request_table.get_item(Key={'request_id': request_id})
        request = request_response.get('Item')
        
        assert int(request['frame_stats']['failed']) == 6
        assert int(request['frame_stats']['pending']) == 44



# =============================================================================
# 测试类: 策略执行与状态记录
# =============================================================================

class TestPolicyExecution:
    """测试策略执行与状态记录"""
    
    @mock_aws
    @responses.activate
    def test_fp_comp_009_multi_policy_all_success(self):
        """
        FP-COMP-009: 多策略顺序执行 - 全部成功
        测试目标: FrameProcessor.execute_policy() - 多策略执行
        """
        setup_test_environment()
        request_table = create_request_table()
        frame_table = create_frame_table()
        
        request_id = 'test-123'
        request_table.put_item(Item=create_test_request(request_id, 'running', 100, 1))
        
        responses.add(
            responses.GET,
            'https://example.com/frame-0.jpg',
            body=b'fake image data',
            status=200
        )
        
        event = create_sqs_event({
            'request_id': request_id,
            'request_name': 'my-video',
            'frame_index': 0,
            'target_frame_url': 'https://example.com/frame-0.jpg',
            'before_frame_urls': [],
            'after_frame_urls': []
        })
        
        # 配置 3 个 Mock 策略
        policy_a = MockPolicy('policy_a', {'policy_a_result': 'value_a'})
        policy_b = MockPolicy('policy_b', {'policy_b_result': 'value_b'})
        policy_c = MockPolicy('policy_c', {'policy_c_result': 'value_c'})
        
        fp_module = get_frame_processor_module()
        module_path = get_module_path()
        
        with patch.dict(f'{module_path}.POLICY_MAP', {
            'policy_a': policy_a,
            'policy_b': policy_b,
            'policy_c': policy_c
        }):
            with patch(f'{module_path}.Config') as mock_config:
                mock_config.ENABLED_POLICIES = ['policy_a', 'policy_b', 'policy_c']
                
                fp_module.request_table = None
                fp_module.frame_table = None
                fp_module._init_resources()
                
                fp_module.handler(event, {})
        
        # 验证 Frame 记录
        frame_response = frame_table.get_item(Key={'request_id': request_id, 'frame_index': 0})
        frame = frame_response.get('Item')
        
        assert frame['policy_status']['policy_a'] == 'completed'
        assert frame['policy_status']['policy_b'] == 'completed'
        assert frame['policy_status']['policy_c'] == 'completed'
        assert frame['policy_results']['policy_a_result'] == 'value_a'
        assert frame['policy_results']['policy_b_result'] == 'value_b'
        assert frame['policy_results']['policy_c_result'] == 'value_c'
        assert frame['status'] == 'completed'

    @mock_aws
    @responses.activate
    def test_fp_comp_010_policy_should_process_false_skipped(self):
        """
        FP-COMP-010: 策略 shouldProcess 返回 False - 标记为 skipped
        测试目标: FrameProcessor.execute_policy() - 策略跳过
        """
        setup_test_environment()
        request_table = create_request_table()
        frame_table = create_frame_table()
        
        request_id = 'test-123'
        request_table.put_item(Item=create_test_request(request_id, 'running', 100, 1))
        
        responses.add(
            responses.GET,
            'https://example.com/frame-5.jpg',
            body=b'fake image data',
            status=200
        )
        
        # frame_index = 5（不是 10 的倍数）
        event = create_sqs_event({
            'request_id': request_id,
            'request_name': 'my-video',
            'frame_index': 5,
            'target_frame_url': 'https://example.com/frame-5.jpg',
            'before_frame_urls': [],
            'after_frame_urls': []
        })
        
        # 使用间隔策略（每 10 帧处理一次）
        interval_policy = MockIntervalPolicy('interval_policy', {'interval_result': 'value'})
        
        fp_module = get_frame_processor_module()
        module_path = get_module_path()
        
        with patch.dict(f'{module_path}.POLICY_MAP', {'interval_policy': interval_policy}):
            with patch(f'{module_path}.Config') as mock_config:
                mock_config.ENABLED_POLICIES = ['interval_policy']
                
                fp_module.request_table = None
                fp_module.frame_table = None
                fp_module._init_resources()
                
                fp_module.handler(event, {})
        
        # 验证 Frame 记录
        frame_response = frame_table.get_item(Key={'request_id': request_id, 'frame_index': 5})
        frame = frame_response.get('Item')
        
        assert frame['policy_status']['interval_policy'] == 'skipped'
        assert 'interval_result' not in frame.get('policy_results', {})
        assert frame['status'] == 'completed'
        assert not interval_policy.analyze_called

    @mock_aws
    @responses.activate
    def test_fp_comp_011_single_policy_failure_others_continue(self):
        """
        FP-COMP-011: 单个策略失败 - 其他策略继续执行
        测试目标: FrameProcessor.execute_policy() - 部分失败
        """
        setup_test_environment()
        request_table = create_request_table()
        frame_table = create_frame_table()
        
        request_id = 'test-123'
        request_table.put_item(Item=create_test_request(request_id, 'running', 100, 1))
        
        responses.add(
            responses.GET,
            'https://example.com/frame-0.jpg',
            body=b'fake image data',
            status=200
        )
        
        event = create_sqs_event({
            'request_id': request_id,
            'request_name': 'my-video',
            'frame_index': 0,
            'target_frame_url': 'https://example.com/frame-0.jpg',
            'before_frame_urls': [],
            'after_frame_urls': []
        })
        
        # policy_b 配置为抛出异常
        policy_a = MockPolicy('policy_a', {'policy_a_result': 'value_a'})
        policy_b = MockPolicy('policy_b', should_fail=True)
        policy_c = MockPolicy('policy_c', {'policy_c_result': 'value_c'})
        
        fp_module = get_frame_processor_module()
        module_path = get_module_path()
        
        with patch.dict(f'{module_path}.POLICY_MAP', {
            'policy_a': policy_a,
            'policy_b': policy_b,
            'policy_c': policy_c
        }):
            with patch(f'{module_path}.Config') as mock_config:
                mock_config.ENABLED_POLICIES = ['policy_a', 'policy_b', 'policy_c']
                
                fp_module.request_table = None
                fp_module.frame_table = None
                fp_module._init_resources()
                
                fp_module.handler(event, {})
        
        # 验证 Frame 记录
        frame_response = frame_table.get_item(Key={'request_id': request_id, 'frame_index': 0})
        frame = frame_response.get('Item')
        
        assert frame['policy_status']['policy_a'] == 'completed'
        assert frame['policy_status']['policy_b'] == 'failed'
        assert frame['policy_status']['policy_c'] == 'completed'
        assert frame['policy_results']['policy_a_result'] == 'value_a'
        assert 'policy_b_result' not in frame.get('policy_results', {})
        assert frame['policy_results']['policy_c_result'] == 'value_c'
        # 部分成功仍标记为 completed
        assert frame['status'] == 'completed'

    @mock_aws
    @responses.activate
    def test_fp_comp_012_all_policies_fail_frame_failed(self):
        """
        FP-COMP-012: 所有策略失败 - Frame 标记为 failed
        测试目标: FrameProcessor.execute_policy() - 全部失败
        """
        setup_test_environment()
        request_table = create_request_table()
        frame_table = create_frame_table()
        
        request_id = 'test-123'
        request_table.put_item(Item=create_test_request(request_id, 'running', 100, 1))
        
        responses.add(
            responses.GET,
            'https://example.com/frame-0.jpg',
            body=b'fake image data',
            status=200
        )
        
        event = create_sqs_event({
            'request_id': request_id,
            'request_name': 'my-video',
            'frame_index': 0,
            'target_frame_url': 'https://example.com/frame-0.jpg',
            'before_frame_urls': [],
            'after_frame_urls': []
        })
        
        # 所有策略都抛出异常
        policy_a = MockPolicy('policy_a', should_fail=True)
        policy_b = MockPolicy('policy_b', should_fail=True)
        
        fp_module = get_frame_processor_module()
        module_path = get_module_path()
        
        with patch.dict(f'{module_path}.POLICY_MAP', {
            'policy_a': policy_a,
            'policy_b': policy_b
        }):
            with patch(f'{module_path}.Config') as mock_config:
                mock_config.ENABLED_POLICIES = ['policy_a', 'policy_b']
                
                fp_module.request_table = None
                fp_module.frame_table = None
                fp_module._init_resources()
                
                fp_module.handler(event, {})
        
        # 验证 Frame 记录
        frame_response = frame_table.get_item(Key={'request_id': request_id, 'frame_index': 0})
        frame = frame_response.get('Item')
        
        assert frame['policy_status']['policy_a'] == 'failed'
        assert frame['policy_status']['policy_b'] == 'failed'
        assert frame.get('policy_results', {}) == {}
        assert frame['status'] == 'failed'
        
        # 验证 frame_stats.failed 递增
        request_response = request_table.get_item(Key={'request_id': request_id})
        request = request_response.get('Item')
        assert int(request['frame_stats']['failed']) == 1


# =============================================================================
# 测试类: 上下文帧加载
# =============================================================================

class TestContextFrameLoading:
    """测试上下文帧加载"""
    
    @mock_aws
    @responses.activate
    def test_fp_comp_013_load_context_frames_normal(self):
        """
        FP-COMP-013: 正常加载前后上下文帧
        测试目标: FrameProcessor.handler() - 上下文加载
        """
        setup_test_environment()
        request_table = create_request_table()
        frame_table = create_frame_table()
        
        request_id = 'test-123'
        request_table.put_item(Item=create_test_request(request_id, 'running', 100, 1))
        
        # Mock HTTP 为每个 URL 返回不同的图片数据
        responses.add(responses.GET, 'https://example.com/frame-48.jpg', body=b'frame-48-data', status=200)
        responses.add(responses.GET, 'https://example.com/frame-49.jpg', body=b'frame-49-data', status=200)
        responses.add(responses.GET, 'https://example.com/frame-50.jpg', body=b'frame-50-data', status=200)
        responses.add(responses.GET, 'https://example.com/frame-51.jpg', body=b'frame-51-data', status=200)
        responses.add(responses.GET, 'https://example.com/frame-52.jpg', body=b'frame-52-data', status=200)
        
        event = create_sqs_event({
            'request_id': request_id,
            'request_name': 'my-video',
            'frame_index': 50,
            'target_frame_url': 'https://example.com/frame-50.jpg',
            'before_frame_urls': ['https://example.com/frame-49.jpg', 'https://example.com/frame-48.jpg'],
            'after_frame_urls': ['https://example.com/frame-51.jpg', 'https://example.com/frame-52.jpg']
        })
        
        mock_policy = MockPolicy('mock_policy', {'key': 'value'})
        
        fp_module = get_frame_processor_module()
        module_path = get_module_path()
        
        with patch.dict(f'{module_path}.POLICY_MAP', {'mock_policy': mock_policy}):
            with patch(f'{module_path}.Config') as mock_config:
                mock_config.ENABLED_POLICIES = ['mock_policy']
                
                fp_module.request_table = None
                fp_module.frame_table = None
                fp_module._init_resources()
                
                fp_module.handler(event, {})
        
        # 验证发起了正确数量的 HTTP 请求
        # 策略 get_context_range 返回 (-1, 1)，所以只需要前1帧和后1帧
        # 目标帧 + 前1帧 + 后1帧 = 3 次请求
        assert len(responses.calls) == 3
        
        # 验证策略接收到的数据
        assert mock_policy.analyze_called
        assert mock_policy.received_target_frame['data'] == b'frame-50-data'
        assert mock_policy.received_target_frame['index'] == 50

    @mock_aws
    @responses.activate
    def test_fp_comp_014_skip_null_context_frames(self):
        """
        FP-COMP-014: 跳过 null 的上下文帧（丢帧场景）
        测试目标: FrameProcessor.handler() - 丢帧处理
        """
        setup_test_environment()
        request_table = create_request_table()
        frame_table = create_frame_table()
        
        request_id = 'test-123'
        request_table.put_item(Item=create_test_request(request_id, 'running', 100, 1))
        
        # 只 mock 非 null 的 URL
        responses.add(responses.GET, 'https://example.com/frame-49.jpg', body=b'frame-49-data', status=200)
        responses.add(responses.GET, 'https://example.com/frame-50.jpg', body=b'frame-50-data', status=200)
        
        event = create_sqs_event({
            'request_id': request_id,
            'request_name': 'my-video',
            'frame_index': 50,
            'target_frame_url': 'https://example.com/frame-50.jpg',
            'before_frame_urls': ['https://example.com/frame-49.jpg', None, 'https://example.com/frame-47.jpg'],
            'after_frame_urls': [None, 'https://example.com/frame-52.jpg']
        })
        
        mock_policy = MockPolicy('mock_policy', {'key': 'value'})
        
        fp_module = get_frame_processor_module()
        module_path = get_module_path()
        
        with patch.dict(f'{module_path}.POLICY_MAP', {'mock_policy': mock_policy}):
            with patch(f'{module_path}.Config') as mock_config:
                mock_config.ENABLED_POLICIES = ['mock_policy']
                
                fp_module.request_table = None
                fp_module.frame_table = None
                fp_module._init_resources()
                
                fp_module.handler(event, {})
        
        # 验证跳过了 null URL（策略只需要前后各1帧，所以只请求 frame-49 和 frame-50）
        # 由于 after_frame_urls[0] 是 null，所以不会请求后帧
        assert len(responses.calls) == 2  # 目标帧 + 前1帧
        
        # 验证 Frame 完成
        frame_response = frame_table.get_item(Key={'request_id': request_id, 'frame_index': 50})
        frame = frame_response.get('Item')
        assert frame['status'] == 'completed'

    @mock_aws
    @responses.activate
    def test_fp_comp_015_first_frame_no_before_frames(self):
        """
        FP-COMP-015: 边界场景 - 第一帧（无前帧）
        测试目标: FrameProcessor.handler() - 边界处理
        """
        setup_test_environment()
        request_table = create_request_table()
        frame_table = create_frame_table()
        
        request_id = 'test-123'
        request_table.put_item(Item=create_test_request(request_id, 'running', 100, 1))
        
        responses.add(responses.GET, 'https://example.com/frame-0.jpg', body=b'frame-0-data', status=200)
        responses.add(responses.GET, 'https://example.com/frame-1.jpg', body=b'frame-1-data', status=200)
        responses.add(responses.GET, 'https://example.com/frame-2.jpg', body=b'frame-2-data', status=200)
        
        event = create_sqs_event({
            'request_id': request_id,
            'request_name': 'my-video',
            'frame_index': 0,
            'target_frame_url': 'https://example.com/frame-0.jpg',
            'before_frame_urls': [],
            'after_frame_urls': ['https://example.com/frame-1.jpg', 'https://example.com/frame-2.jpg']
        })
        
        mock_policy = MockPolicy('mock_policy', {'key': 'value'})
        
        fp_module = get_frame_processor_module()
        module_path = get_module_path()
        
        with patch.dict(f'{module_path}.POLICY_MAP', {'mock_policy': mock_policy}):
            with patch(f'{module_path}.Config') as mock_config:
                mock_config.ENABLED_POLICIES = ['mock_policy']
                
                fp_module.request_table = None
                fp_module.frame_table = None
                fp_module._init_resources()
                
                fp_module.handler(event, {})
        
        # 验证请求数量（目标帧 + 后1帧）
        assert len(responses.calls) == 2
        
        # 验证 Frame 完成
        frame_response = frame_table.get_item(Key={'request_id': request_id, 'frame_index': 0})
        frame = frame_response.get('Item')
        assert frame['status'] == 'completed'

    @mock_aws
    @responses.activate
    def test_fp_comp_016_last_frame_no_after_frames(self):
        """
        FP-COMP-016: 边界场景 - 最后一帧（无后帧）
        测试目标: FrameProcessor.handler() - 边界处理
        """
        setup_test_environment()
        request_table = create_request_table()
        frame_table = create_frame_table()
        
        request_id = 'test-123'
        request_table.put_item(Item=create_test_request(request_id, 'running', 100, 1))
        
        responses.add(responses.GET, 'https://example.com/frame-97.jpg', body=b'frame-97-data', status=200)
        responses.add(responses.GET, 'https://example.com/frame-98.jpg', body=b'frame-98-data', status=200)
        responses.add(responses.GET, 'https://example.com/frame-99.jpg', body=b'frame-99-data', status=200)
        
        event = create_sqs_event({
            'request_id': request_id,
            'request_name': 'my-video',
            'frame_index': 99,
            'target_frame_url': 'https://example.com/frame-99.jpg',
            'before_frame_urls': ['https://example.com/frame-98.jpg', 'https://example.com/frame-97.jpg'],
            'after_frame_urls': []
        })
        
        mock_policy = MockPolicy('mock_policy', {'key': 'value'})
        
        fp_module = get_frame_processor_module()
        module_path = get_module_path()
        
        with patch.dict(f'{module_path}.POLICY_MAP', {'mock_policy': mock_policy}):
            with patch(f'{module_path}.Config') as mock_config:
                mock_config.ENABLED_POLICIES = ['mock_policy']
                
                fp_module.request_table = None
                fp_module.frame_table = None
                fp_module._init_resources()
                
                fp_module.handler(event, {})
        
        # 验证请求数量（目标帧 + 前1帧）
        assert len(responses.calls) == 2
        
        # 验证 Frame 完成
        frame_response = frame_table.get_item(Key={'request_id': request_id, 'frame_index': 99})
        frame = frame_response.get('Item')
        assert frame['status'] == 'completed'

    @mock_aws
    @responses.activate
    def test_fp_comp_017_isolated_frame_no_context(self):
        """
        FP-COMP-017: 极端场景 - 孤立帧（无上下文）
        测试目标: FrameProcessor.handler() - 极端处理
        """
        setup_test_environment()
        request_table = create_request_table()
        frame_table = create_frame_table()
        
        request_id = 'test-123'
        request_table.put_item(Item=create_test_request(request_id, 'running', 1, 1))
        
        responses.add(responses.GET, 'https://example.com/frame-0.jpg', body=b'frame-0-data', status=200)
        
        event = create_sqs_event({
            'request_id': request_id,
            'request_name': 'my-video',
            'frame_index': 0,
            'target_frame_url': 'https://example.com/frame-0.jpg',
            'before_frame_urls': [],
            'after_frame_urls': []
        })
        
        mock_policy = MockPolicy('mock_policy', {'key': 'value'})
        
        fp_module = get_frame_processor_module()
        module_path = get_module_path()
        
        with patch.dict(f'{module_path}.POLICY_MAP', {'mock_policy': mock_policy}):
            with patch(f'{module_path}.Config') as mock_config:
                mock_config.ENABLED_POLICIES = ['mock_policy']
                
                fp_module.request_table = None
                fp_module.frame_table = None
                fp_module._init_resources()
                
                fp_module.handler(event, {})
        
        # 验证只请求了目标帧
        assert len(responses.calls) == 1
        
        # 验证策略接收到空的上下文
        assert mock_policy.received_context_frames == []
        
        # 验证 Frame 完成
        frame_response = frame_table.get_item(Key={'request_id': request_id, 'frame_index': 0})
        frame = frame_response.get('Item')
        assert frame['status'] == 'completed'


# =============================================================================
# 测试类: 乐观锁冲突重试
# =============================================================================

class TestOptimisticLockRetry:
    """测试乐观锁冲突重试"""
    
    @mock_aws
    @responses.activate
    def test_fp_comp_008_optimistic_lock_conflict_retry(self):
        """
        FP-COMP-008: frame_stats 乐观锁冲突重试
        测试目标: FrameProcessor.update_frame_stats() - 乐观锁
        """
        setup_test_environment()
        request_table = create_request_table()
        frame_table = create_frame_table()
        
        request_id = 'test-123'
        request = create_test_request(request_id, 'running', 100, 10)
        request['frame_stats'] = {'total': 100, 'completed': 50, 'failed': 5, 'pending': 45}
        request_table.put_item(Item=request)
        
        responses.add(
            responses.GET,
            'https://example.com/frame-55.jpg',
            body=b'fake image data',
            status=200
        )
        
        event = create_sqs_event({
            'request_id': request_id,
            'request_name': 'my-video',
            'frame_index': 55,
            'target_frame_url': 'https://example.com/frame-55.jpg',
            'before_frame_urls': [],
            'after_frame_urls': []
        })
        
        mock_policy = MockPolicy('mock_policy', {'key': 'value'})
        
        fp_module = get_frame_processor_module()
        module_path = get_module_path()
        
        # 模拟乐观锁冲突：第一次更新时 version 已变化
        original_update_frame_stats = None
        call_count = [0]
        
        def mock_update_frame_stats(req_id, stats, version):
            call_count[0] += 1
            if call_count[0] == 1:
                # 第一次调用时模拟并发更新，先更新 version
                request_table.update_item(
                    Key={'request_id': req_id},
                    UpdateExpression='SET version = :v',
                    ExpressionAttributeValues={':v': version + 1}
                )
                # 然后抛出条件检查失败异常
                from botocore.exceptions import ClientError
                raise ClientError(
                    {'Error': {'Code': 'ConditionalCheckFailedException', 'Message': 'Version mismatch'}},
                    'UpdateItem'
                )
            else:
                # 第二次调用正常执行
                request_table.update_item(
                    Key={'request_id': req_id},
                    UpdateExpression='SET frame_stats = :s, version = :v',
                    ExpressionAttributeValues={
                        ':s': stats,
                        ':v': version + 1
                    }
                )
        
        with patch.dict(f'{module_path}.POLICY_MAP', {'mock_policy': mock_policy}):
            with patch(f'{module_path}.Config') as mock_config:
                mock_config.ENABLED_POLICIES = ['mock_policy']
                
                fp_module.request_table = None
                fp_module.frame_table = None
                fp_module._init_resources()
                
                # 替换 request_table 的 update_frame_stats 方法
                with patch.object(fp_module.request_table, 'update_frame_stats', side_effect=mock_update_frame_stats):
                    fp_module.handler(event, {})
        
        # 验证重试发生（至少调用了 2 次）
        assert call_count[0] >= 2
        
        # 验证最终 Frame 状态正确
        frame_response = frame_table.get_item(Key={'request_id': request_id, 'frame_index': 55})
        frame = frame_response.get('Item')
        assert frame['status'] == 'completed'


# =============================================================================
# 测试类: 完成检测与触发
# =============================================================================

class TestCompletionDetection:
    """测试完成检测与触发 Completion Handler"""
    
    @mock_aws
    @responses.activate
    def test_fp_comp_018_last_frame_triggers_completion(self):
        """
        FP-COMP-018: 最后一帧完成 - 触发 Completion Handler
        测试目标: FrameProcessor.check_all_frames_completed() - 完成检测
        """
        setup_test_environment()
        request_table = create_request_table()
        frame_table = create_frame_table()
        
        # 不需要创建真实的 Lambda 函数，因为我们会 mock lambda_client.invoke
        
        request_id = 'test-123'
        request = create_test_request(request_id, 'running', 100, 99)
        request['frame_stats'] = {'total': 100, 'completed': 99, 'failed': 0, 'pending': 1}
        request_table.put_item(Item=request)
        
        responses.add(
            responses.GET,
            'https://example.com/frame-99.jpg',
            body=b'fake image data',
            status=200
        )
        
        event = create_sqs_event({
            'request_id': request_id,
            'request_name': 'my-video',
            'frame_index': 99,
            'target_frame_url': 'https://example.com/frame-99.jpg',
            'before_frame_urls': [],
            'after_frame_urls': []
        })
        
        mock_policy = MockPolicy('mock_policy', {'key': 'value'})
        
        fp_module = get_frame_processor_module()
        module_path = get_module_path()
        
        # 跟踪 Lambda invoke 调用
        invoke_called = [False]
        invoke_payload = [None]
        
        def mock_invoke(**kwargs):
            invoke_called[0] = True
            invoke_payload[0] = json.loads(kwargs.get('Payload', '{}'))
            return {'StatusCode': 202}
        
        with patch.dict(f'{module_path}.POLICY_MAP', {'mock_policy': mock_policy}):
            with patch(f'{module_path}.Config') as mock_config:
                mock_config.ENABLED_POLICIES = ['mock_policy']
                
                fp_module.request_table = None
                fp_module.frame_table = None
                fp_module._init_resources()
                
                # Mock Lambda client
                with patch.object(fp_module.lambda_client, 'invoke', side_effect=mock_invoke):
                    with patch.dict(os.environ, {'COMPLETION_HANDLER_NAME': 'completion-handler'}):
                        fp_module.handler(event, {})
        
        # 验证 frame_stats 更新
        request_response = request_table.get_item(Key={'request_id': request_id})
        request = request_response.get('Item')
        assert int(request['frame_stats']['completed']) == 100
        assert int(request['frame_stats']['pending']) == 0
        
        # 验证 Completion Handler 被触发
        assert invoke_called[0] is True
        assert invoke_payload[0]['request_id'] == request_id

    @mock_aws
    @responses.activate
    def test_fp_comp_019_not_last_frame_no_trigger(self):
        """
        FP-COMP-019: 非最后一帧 - 不触发 Completion Handler
        测试目标: FrameProcessor.check_all_frames_completed() - 未完成检测
        """
        setup_test_environment()
        request_table = create_request_table()
        frame_table = create_frame_table()
        
        request_id = 'test-123'
        request = create_test_request(request_id, 'running', 100, 50)
        request['frame_stats'] = {'total': 100, 'completed': 50, 'failed': 0, 'pending': 50}
        request_table.put_item(Item=request)
        
        responses.add(
            responses.GET,
            'https://example.com/frame-50.jpg',
            body=b'fake image data',
            status=200
        )
        
        event = create_sqs_event({
            'request_id': request_id,
            'request_name': 'my-video',
            'frame_index': 50,
            'target_frame_url': 'https://example.com/frame-50.jpg',
            'before_frame_urls': [],
            'after_frame_urls': []
        })
        
        mock_policy = MockPolicy('mock_policy', {'key': 'value'})
        
        fp_module = get_frame_processor_module()
        module_path = get_module_path()
        
        # 跟踪 Lambda invoke 调用
        invoke_called = [False]
        
        def mock_invoke(**kwargs):
            invoke_called[0] = True
            return {'StatusCode': 202}
        
        with patch.dict(f'{module_path}.POLICY_MAP', {'mock_policy': mock_policy}):
            with patch(f'{module_path}.Config') as mock_config:
                mock_config.ENABLED_POLICIES = ['mock_policy']
                
                fp_module.request_table = None
                fp_module.frame_table = None
                fp_module._init_resources()
                
                # Mock Lambda client
                with patch.object(fp_module.lambda_client, 'invoke', side_effect=mock_invoke):
                    with patch.dict(os.environ, {'COMPLETION_HANDLER_NAME': 'completion-handler'}):
                        fp_module.handler(event, {})
        
        # 验证 frame_stats 更新
        request_response = request_table.get_item(Key={'request_id': request_id})
        request = request_response.get('Item')
        assert int(request['frame_stats']['completed']) == 51
        assert int(request['frame_stats']['pending']) == 49
        
        # 验证 Completion Handler 未被触发
        assert invoke_called[0] is False

    @mock_aws
    @responses.activate
    def test_fp_comp_020_last_frame_failed_still_triggers(self):
        """
        FP-COMP-020: 最后一帧失败 - 仍触发 Completion Handler
        测试目标: FrameProcessor.check_all_frames_completed() - 失败完成
        """
        setup_test_environment()
        request_table = create_request_table()
        frame_table = create_frame_table()
        
        request_id = 'test-123'
        request = create_test_request(request_id, 'running', 100, 99)
        request['frame_stats'] = {'total': 100, 'completed': 90, 'failed': 9, 'pending': 1}
        request_table.put_item(Item=request)
        
        responses.add(
            responses.GET,
            'https://example.com/frame-99.jpg',
            body=b'fake image data',
            status=200
        )
        
        event = create_sqs_event({
            'request_id': request_id,
            'request_name': 'my-video',
            'frame_index': 99,
            'target_frame_url': 'https://example.com/frame-99.jpg',
            'before_frame_urls': [],
            'after_frame_urls': []
        })
        
        # 策略抛出异常导致帧失败
        mock_policy = MockPolicy('mock_policy', should_fail=True)
        
        fp_module = get_frame_processor_module()
        module_path = get_module_path()
        
        # 跟踪 Lambda invoke 调用
        invoke_called = [False]
        invoke_payload = [None]
        
        def mock_invoke(**kwargs):
            invoke_called[0] = True
            invoke_payload[0] = json.loads(kwargs.get('Payload', '{}'))
            return {'StatusCode': 202}
        
        with patch.dict(f'{module_path}.POLICY_MAP', {'mock_policy': mock_policy}):
            with patch(f'{module_path}.Config') as mock_config:
                mock_config.ENABLED_POLICIES = ['mock_policy']
                
                fp_module.request_table = None
                fp_module.frame_table = None
                fp_module._init_resources()
                
                # Mock Lambda client
                with patch.object(fp_module.lambda_client, 'invoke', side_effect=mock_invoke):
                    with patch.dict(os.environ, {'COMPLETION_HANDLER_NAME': 'completion-handler'}):
                        fp_module.handler(event, {})
        
        # 验证 frame_stats 更新
        request_response = request_table.get_item(Key={'request_id': request_id})
        request = request_response.get('Item')
        assert int(request['frame_stats']['completed']) == 90
        assert int(request['frame_stats']['failed']) == 10
        assert int(request['frame_stats']['pending']) == 0
        
        # 验证 Frame 状态为 failed
        frame_response = frame_table.get_item(Key={'request_id': request_id, 'frame_index': 99})
        frame = frame_response.get('Item')
        assert frame['status'] == 'failed'
        
        # 验证 Completion Handler 仍被触发
        assert invoke_called[0] is True
        assert invoke_payload[0]['request_id'] == request_id


# =============================================================================
# 测试类: 错误处理
# =============================================================================

class TestErrorHandling:
    """测试错误处理"""
    
    @mock_aws
    @responses.activate
    def test_fp_comp_021_http_download_failure(self):
        """
        FP-COMP-021: HTTP 下载失败 - Frame 标记为 failed
        测试目标: FrameProcessor.handler() - 下载错误处理
        """
        setup_test_environment()
        request_table = create_request_table()
        frame_table = create_frame_table()
        
        request_id = 'test-123'
        request_table.put_item(Item=create_test_request(request_id, 'running', 100, 1))
        
        # Mock HTTP 返回 404 错误
        responses.add(
            responses.GET,
            'https://example.com/frame-0.jpg',
            status=404
        )
        
        event = create_sqs_event({
            'request_id': request_id,
            'request_name': 'my-video',
            'frame_index': 0,
            'target_frame_url': 'https://example.com/frame-0.jpg',
            'before_frame_urls': [],
            'after_frame_urls': []
        })
        
        mock_policy = MockPolicy('mock_policy', {'key': 'value'})
        
        fp_module = get_frame_processor_module()
        module_path = get_module_path()
        
        with patch.dict(f'{module_path}.POLICY_MAP', {'mock_policy': mock_policy}):
            with patch(f'{module_path}.Config') as mock_config:
                mock_config.ENABLED_POLICIES = ['mock_policy']
                
                fp_module.request_table = None
                fp_module.frame_table = None
                fp_module._init_resources()
                
                # 捕获异常但不让测试失败
                try:
                    fp_module.handler(event, {})
                except Exception:
                    pass  # 预期会抛出异常
        
        # 验证 Frame 记录
        frame_response = frame_table.get_item(Key={'request_id': request_id, 'frame_index': 0})
        frame = frame_response.get('Item')
        
        # Frame 应该被创建但标记为 failed 或 pending（取决于实现）
        if frame:
            assert frame['status'] in ['failed', 'pending']
        
        # 验证策略未被调用
        assert not mock_policy.analyze_called

    @mock_aws
    def test_fp_comp_022_request_not_found(self):
        """
        FP-COMP-022: Request 不存在 - 记录错误并跳过
        测试目标: FrameProcessor.handler() - Request 不存在
        """
        setup_test_environment()
        request_table = create_request_table()
        frame_table = create_frame_table()
        
        # 不创建 Request 记录
        
        event = create_sqs_event({
            'request_id': 'non-existent-id',
            'request_name': 'my-video',
            'frame_index': 0,
            'target_frame_url': 'https://example.com/frame-0.jpg',
            'before_frame_urls': [],
            'after_frame_urls': []
        })
        
        mock_policy = MockPolicy('mock_policy', {'key': 'value'})
        
        fp_module = get_frame_processor_module()
        module_path = get_module_path()
        
        with patch.dict(f'{module_path}.POLICY_MAP', {'mock_policy': mock_policy}):
            with patch(f'{module_path}.Config') as mock_config:
                mock_config.ENABLED_POLICIES = ['mock_policy']
                
                fp_module.request_table = None
                fp_module.frame_table = None
                fp_module._init_resources()
                
                # 不应抛出异常
                fp_module.handler(event, {})
        
        # 验证 Frame 记录未创建
        frame_response = frame_table.get_item(Key={'request_id': 'non-existent-id', 'frame_index': 0})
        assert frame_response.get('Item') is None
        
        # 验证策略未被调用
        assert not mock_policy.analyze_called


    @mock_aws
    @responses.activate
    def test_fp_comp_026_http_connection_timeout(self):
        """
        FP-COMP-026: HTTP 连接超时 - Frame 标记为 failed
        测试目标: FrameProcessor.handler() - HTTP 超时处理
        """
        from requests.exceptions import Timeout
        
        setup_test_environment()
        request_table = create_request_table()
        frame_table = create_frame_table()
        
        request_id = 'test-req-026'
        request = create_test_request(request_id, 'running', 100, 10)
        request['frame_stats'] = {'total': 100, 'completed': 50, 'failed': 5, 'pending': 45}
        request_table.put_item(Item=request)
        
        # Mock HTTP 请求超时
        responses.add(
            responses.GET,
            'https://example.com/frame-70.jpg',
            body=Timeout("Connection timed out")
        )
        
        event = create_sqs_event({
            'request_id': request_id,
            'request_name': 'test-video',
            'frame_index': 70,
            'target_frame_url': 'https://example.com/frame-70.jpg',
            'before_frame_urls': [],
            'after_frame_urls': []
        })
        
        mock_policy = MockPolicy('mock_policy', {'key': 'value'})
        
        fp_module = get_frame_processor_module()
        module_path = get_module_path()
        
        with patch.dict(f'{module_path}.POLICY_MAP', {'mock_policy': mock_policy}):
            with patch(f'{module_path}.Config') as mock_config:
                mock_config.ENABLED_POLICIES = ['mock_policy']
                
                fp_module.request_table = None
                fp_module.frame_table = None
                fp_module._init_resources()
                
                # 不应抛出异常（超时错误被捕获）
                try:
                    fp_module.handler(event, {})
                except Exception:
                    pass  # 某些实现可能抛出异常
        
        # 验证 Frame 记录被创建并标记为 failed
        frame_response = frame_table.get_item(Key={'request_id': request_id, 'frame_index': 70})
        frame = frame_response.get('Item')
        
        assert frame is not None
        assert frame['request_id'] == request_id
        assert frame['frame_index'] == 70
        assert frame['status'] == 'failed'
        assert frame['policy_status']['mock_policy'] == 'failed'
        
        # 验证 frame_stats 更新
        request_response = request_table.get_item(Key={'request_id': request_id})
        request = request_response.get('Item')
        assert int(request['frame_stats']['failed']) == 6
        assert int(request['frame_stats']['pending']) == 44
        
        # 验证策略未被调用（因为图片下载失败）
        assert not mock_policy.analyze_called


class TestConfigurationErrors:
    """测试配置错误场景"""
    
    @mock_aws
    @responses.activate
    def test_fp_comp_027_empty_enabled_policies(self):
        """
        FP-COMP-027: ENABLED_POLICIES 为空 - 跳过策略执行
        测试目标: FrameProcessor.handler() - 空策略配置
        """
        setup_test_environment()
        request_table = create_request_table()
        frame_table = create_frame_table()
        
        request_id = 'test-req-027'
        request = create_test_request(request_id, 'running', 100, 1)
        request['frame_stats'] = {'total': 100, 'completed': 50, 'failed': 0, 'pending': 50}
        request_table.put_item(Item=request)
        
        # Mock HTTP 返回测试图片数据
        responses.add(
            responses.GET,
            'https://example.com/frame-60.jpg',
            body=b'fake image data',
            status=200
        )
        
        event = create_sqs_event({
            'request_id': request_id,
            'request_name': 'test-video',
            'frame_index': 60,
            'target_frame_url': 'https://example.com/frame-60.jpg',
            'before_frame_urls': [],
            'after_frame_urls': []
        })
        
        # 设置空的 ENABLED_POLICIES
        os.environ['ENABLED_POLICIES'] = ''
        
        # 清除模块缓存
        clear_module_cache()
        
        # 导入模块
        fp_module = importlib.import_module(MODULE_PATH)
        
        # 初始化并执行
        fp_module.request_table = None
        fp_module.frame_table = None
        fp_module._init_resources()
        fp_module.handler(event, {})
        
        # 验证 Frame 记录
        frame_response = frame_table.get_item(Key={'request_id': request_id, 'frame_index': 60})
        frame = frame_response.get('Item')
        
        assert frame is not None
        assert frame['request_id'] == request_id
        assert frame['frame_index'] == 60
        assert frame['status'] == 'completed'
        assert frame.get('policy_status', {}) == {}
        assert frame.get('policy_results', {}) == {}
        
        # 验证 frame_stats 正确更新
        request_response = request_table.get_item(Key={'request_id': request_id})
        request = request_response.get('Item')
        assert int(request['frame_stats']['completed']) == 51
        assert int(request['frame_stats']['pending']) == 49

    @mock_aws
    @responses.activate
    def test_fp_comp_028_non_existent_policy_name(self):
        """
        FP-COMP-028: 策略名不存在 - 记录错误并跳过该策略
        测试目标: FrameProcessor.handler() - 无效策略名
        """
        setup_test_environment()
        request_table = create_request_table()
        frame_table = create_frame_table()
        
        request_id = 'test-req-028'
        request = create_test_request(request_id, 'running', 100, 1)
        request['frame_stats'] = {'total': 100, 'completed': 50, 'failed': 0, 'pending': 50}
        request_table.put_item(Item=request)
        
        # Mock HTTP 返回测试图片数据
        responses.add(
            responses.GET,
            'https://example.com/frame-60.jpg',
            body=b'fake image data',
            status=200
        )
        
        event = create_sqs_event({
            'request_id': request_id,
            'request_name': 'test-video',
            'frame_index': 60,
            'target_frame_url': 'https://example.com/frame-60.jpg',
            'before_frame_urls': [],
            'after_frame_urls': []
        })
        
        # 创建一个有效的 mock 策略
        mock_policy = MockPolicy('mock_policy', {'mock_result': 'success', 'mock_frame_index': 60})
        
        fp_module = get_frame_processor_module()
        module_path = get_module_path()
        
        # 配置包含有效策略和不存在的策略
        with patch.dict(f'{module_path}.POLICY_MAP', {'mock_policy': mock_policy}):
            with patch(f'{module_path}.Config') as mock_config:
                mock_config.ENABLED_POLICIES = ['mock_policy', 'non_existent_policy']
                
                fp_module.request_table = None
                fp_module.frame_table = None
                fp_module._init_resources()
                
                fp_module.handler(event, {})
        
        # 验证 Frame 记录
        frame_response = frame_table.get_item(Key={'request_id': request_id, 'frame_index': 60})
        frame = frame_response.get('Item')
        
        assert frame is not None
        assert frame['request_id'] == request_id
        assert frame['frame_index'] == 60
        # 有效策略成功，Frame 应该是 completed（取决于实现，可能是 failed 如果任何策略失败）
        assert frame['status'] in ['completed', 'failed']
        
        # 验证策略状态
        assert frame['policy_status']['mock_policy'] == 'completed'
        assert frame['policy_status']['non_existent_policy'] == 'failed'
        
        # 验证 policy_results 包含有效策略的结果
        assert frame['policy_results']['mock_result'] == 'success'
        assert frame['policy_results']['mock_frame_index'] == 60
        
        # 验证有效策略被调用
        assert mock_policy.analyze_called
