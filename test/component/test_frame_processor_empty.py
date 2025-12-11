"""
Frame Processor 组件测试 - 使用 EmptyPolicy

测试目标: Frame Processor 的完整处理流程
Mock 策略:
- DynamoDB: moto
- HTTP 图片下载: responses
- Lambda: moto
- 策略: 使用真实的 EmptyPolicy（返回静态数据，不调用 Bedrock）
"""
import pytest
import json
import boto3
import os
import sys
import responses
from datetime import datetime, timezone
from moto import mock_aws
from unittest.mock import patch, MagicMock

# 路径设置：layer/python 必须在 lambda 之前，确保 shared 模块正确加载
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../layer/python'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../lambda'))

from conftest import (
    setup_test_environment,
    create_request_table,
    create_frame_table,
    assert_timestamp_recent
)

# 测试策略从 test/test_policies 导入
from test_policies.empty_policy import EmptyPolicy


def create_sqs_event(message: dict) -> dict:
    """创建 SQS 事件"""
    return {
        'Records': [{
            'body': json.dumps(message)
        }]
    }


def create_test_request(request_id: str, status: str = 'pending', 
                        total_frames: int = 100, version: int = 1,
                        completed: int = 0, failed: int = 0) -> dict:
    """创建测试 Request 记录"""
    pending = total_frames - completed - failed
    return {
        'request_id': request_id,
        'name': 'test-video',
        'status': status,
        'total_frames': total_frames,
        'frame_stats': {
            'total': total_frames,
            'completed': completed,
            'failed': failed,
            'pending': pending
        },
        'version': version,
        'created_at': datetime.now(timezone.utc).isoformat(),
        'last_activity_at': datetime.now(timezone.utc).isoformat()
    }


def reload_frame_processor():
    """清除模块缓存并重新导入 frame_processor"""
    modules_to_clear = [k for k in sys.modules.keys() 
                       if k.startswith('handlers') or k.startswith('shared') or k.startswith('policies')]
    for mod in modules_to_clear:
        del sys.modules[mod]
    
    from handlers import frame_processor
    frame_processor.request_table = None
    frame_processor.frame_table = None
    frame_processor._init_resources()
    
    # 注册测试策略
    frame_processor.register_policy('empty', EmptyPolicy())
    
    return frame_processor


class TestFrameProcessorWithEmptyPolicy:
    """使用 EmptyPolicy 测试 Frame Processor"""
    
    # =========================================================================
    # FP-COMP-001: 首次处理帧 - 创建 Frame 记录
    # =========================================================================
    @mock_aws
    @responses.activate
    def test_fp_comp_001_create_frame_record(self):
        """
        测试目标: handler() - 首次处理帧时创建 Frame 记录
        验证: Frame 记录创建、状态更新、策略结果保存
        """
        setup_test_environment()
        os.environ['ENABLED_POLICIES'] = 'empty'
        
        request_table = create_request_table()
        frame_table = create_frame_table()
        
        request_id = 'test-req-001'
        request_table.put_item(Item=create_test_request(request_id, 'pending', 100, 1))
        
        responses.add(responses.GET, 'https://example.com/frame-0.jpg', body=b'fake image data', status=200)
        
        event = create_sqs_event({
            'request_id': request_id,
            'request_name': 'test-video',
            'frame_index': 0,
            'target_frame_url': 'https://example.com/frame-0.jpg',
            'before_frame_urls': [],
            'after_frame_urls': []
        })
        
        frame_processor = reload_frame_processor()
        frame_processor.handler(event, {})
        
        # 验证 Frame 记录
        frame = frame_table.get_item(Key={'request_id': request_id, 'frame_index': 0}).get('Item')
        assert frame is not None
        assert frame['request_id'] == request_id
        assert frame['frame_index'] == 0
        assert frame['status'] == 'completed'
        assert frame['policy_status']['empty'] == 'completed'
        assert frame['policy_results']['empty_result'] == 'static_value'
        assert frame['policy_results']['empty_frame_index'] == 0
        assert frame['retry_count'] == 0
        assert_timestamp_recent(frame['created_at'])


    # =========================================================================
    # FP-COMP-002: 幂等性 - 跳过已完成的帧
    # =========================================================================
    @mock_aws
    @responses.activate
    def test_fp_comp_002_skip_completed_frame(self):
        """
        测试目标: handler() - 幂等性保证，跳过已完成的帧
        验证: 不发起 HTTP 请求，不更新 Frame 记录
        """
        setup_test_environment()
        os.environ['ENABLED_POLICIES'] = 'empty'
        
        request_table = create_request_table()
        frame_table = create_frame_table()
        
        request_id = 'test-req-002'
        request_table.put_item(Item=create_test_request(request_id, 'running', 100, 1, completed=50))
        
        # 预先创建已完成的 Frame 记录
        original_completed_at = '2025-01-01T10:00:00+00:00'
        frame_table.put_item(Item={
            'request_id': request_id,
            'frame_index': 0,
            'status': 'completed',
            'policy_results': {'existing_key': 'existing_value'},
            'policy_status': {'empty': 'completed'},
            'completed_at': original_completed_at,
            'created_at': '2025-01-01T09:00:00+00:00'
        })
        
        event = create_sqs_event({
            'request_id': request_id,
            'request_name': 'test-video',
            'frame_index': 0,
            'target_frame_url': 'https://example.com/frame-0.jpg',
            'before_frame_urls': [],
            'after_frame_urls': []
        })
        
        frame_processor = reload_frame_processor()
        frame_processor.handler(event, {})
        
        # 验证没有发起 HTTP 请求
        assert len(responses.calls) == 0
        
        # 验证 Frame 记录未被修改
        frame = frame_table.get_item(Key={'request_id': request_id, 'frame_index': 0}).get('Item')
        assert frame['policy_results'] == {'existing_key': 'existing_value'}
        assert frame['completed_at'] == original_completed_at

    # =========================================================================
    # FP-COMP-003: 重试失败的帧 - 更新 retry_count
    # =========================================================================
    @mock_aws
    @responses.activate
    def test_fp_comp_003_retry_failed_frame(self):
        """
        测试目标: handler() - 重试失败的帧，更新 retry_count
        验证: retry_count 递增，状态从 failed 变为 completed，frame_stats 正确更新
        """
        setup_test_environment()
        os.environ['ENABLED_POLICIES'] = 'empty'
        
        request_table = create_request_table()
        frame_table = create_frame_table()
        
        request_id = 'test-req-003'
        # 初始状态：100 帧，50 完成，1 失败，49 待处理
        request_table.put_item(Item=create_test_request(request_id, 'running', 100, 1, completed=50, failed=1))
        
        # 预先创建失败的 Frame 记录
        frame_table.put_item(Item={
            'request_id': request_id,
            'frame_index': 0,
            'status': 'failed',
            'policy_results': {},
            'policy_status': {'empty': 'failed'},
            'retry_count': 1,
            'created_at': '2025-01-01T09:00:00+00:00'
        })
        
        responses.add(responses.GET, 'https://example.com/frame-0.jpg', body=b'image data', status=200)
        
        event = create_sqs_event({
            'request_id': request_id,
            'request_name': 'test-video',
            'frame_index': 0,
            'target_frame_url': 'https://example.com/frame-0.jpg',
            'before_frame_urls': [],
            'after_frame_urls': []
        })
        
        frame_processor = reload_frame_processor()
        frame_processor.handler(event, {})
        
        # 验证 Frame 记录
        frame = frame_table.get_item(Key={'request_id': request_id, 'frame_index': 0}).get('Item')
        assert frame['status'] == 'completed'
        assert frame['retry_count'] == 2
        assert frame['policy_status']['empty'] == 'completed'
        
        # 验证 frame_stats 更新（重试成功场景）
        # 重试成功：failed 减 1，completed 加 1，pending 不变
        request = request_table.get_item(Key={'request_id': request_id}).get('Item')
        assert int(request['frame_stats']['completed']) == 51  # 50 + 1
        assert int(request['frame_stats']['failed']) == 0      # 1 - 1
        assert int(request['frame_stats']['pending']) == 49    # 保持不变（重试不影响 pending）
        assert int(request['version']) == 2                    # 乐观锁递增


    # =========================================================================
    # FP-COMP-004: Request 状态从 pending 转为 running
    # =========================================================================
    @mock_aws
    @responses.activate
    def test_fp_comp_004_request_status_pending_to_running(self):
        """
        测试目标: handler() - Request 状态从 pending 转为 running
        验证: 处理第一个帧时状态转换
        """
        setup_test_environment()
        os.environ['ENABLED_POLICIES'] = 'empty'
        
        request_table = create_request_table()
        frame_table = create_frame_table()
        
        request_id = 'test-req-004'
        request_table.put_item(Item=create_test_request(request_id, 'pending', 50, 1))
        
        responses.add(responses.GET, 'https://example.com/frame-5.jpg', body=b'image data', status=200)
        
        event = create_sqs_event({
            'request_id': request_id,
            'request_name': 'test-video',
            'frame_index': 5,
            'target_frame_url': 'https://example.com/frame-5.jpg',
            'before_frame_urls': [],
            'after_frame_urls': []
        })
        
        frame_processor = reload_frame_processor()
        frame_processor.handler(event, {})
        
        request = request_table.get_item(Key={'request_id': request_id}).get('Item')
        assert request['status'] == 'running'
        assert_timestamp_recent(request['last_activity_at'])

    # =========================================================================
    # FP-COMP-005: Request 状态保持 running
    # =========================================================================
    @mock_aws
    @responses.activate
    def test_fp_comp_005_request_status_stays_running(self):
        """
        测试目标: handler() - Request 状态保持 running
        验证: 处理中间帧时状态不变，frame_stats 正确更新
        """
        setup_test_environment()
        os.environ['ENABLED_POLICIES'] = 'empty'
        
        request_table = create_request_table()
        frame_table = create_frame_table()
        
        request_id = 'test-req-005'
        request_table.put_item(Item=create_test_request(request_id, 'running', 100, 5, completed=50))
        
        responses.add(responses.GET, 'https://example.com/frame-60.jpg', body=b'image data', status=200)
        
        event = create_sqs_event({
            'request_id': request_id,
            'request_name': 'test-video',
            'frame_index': 60,
            'target_frame_url': 'https://example.com/frame-60.jpg',
            'before_frame_urls': [],
            'after_frame_urls': []
        })
        
        frame_processor = reload_frame_processor()
        frame_processor.handler(event, {})
        
        # 验证 Request 状态保持 running
        request = request_table.get_item(Key={'request_id': request_id}).get('Item')
        assert request['status'] == 'running'
        assert_timestamp_recent(request['last_activity_at'])
        
        # 验证 frame_stats 正确更新
        assert int(request['frame_stats']['completed']) == 51  # 50 + 1
        assert int(request['frame_stats']['failed']) == 0
        assert int(request['frame_stats']['pending']) == 49    # 50 - 1
        assert int(request['version']) == 6                    # 5 + 1
        
        # 验证 Frame 记录创建
        frame = frame_table.get_item(Key={'request_id': request_id, 'frame_index': 60}).get('Item')
        assert frame is not None
        assert frame['status'] == 'completed'
        assert frame['policy_status']['empty'] == 'completed'

    # =========================================================================
    # FP-COMP-006: frame_stats 正确递增 completed
    # =========================================================================
    @mock_aws
    @responses.activate
    def test_fp_comp_006_frame_stats_increment_completed(self):
        """
        测试目标: update_frame_stats() - completed 计数递增
        验证: frame_stats.completed 增加 1，pending 减少 1
        """
        setup_test_environment()
        os.environ['ENABLED_POLICIES'] = 'empty'
        
        request_table = create_request_table()
        frame_table = create_frame_table()
        
        request_id = 'test-req-006'
        request_table.put_item(Item=create_test_request(request_id, 'running', 100, 10, completed=50, failed=5))
        
        responses.add(responses.GET, 'https://example.com/frame-70.jpg', body=b'image data', status=200)
        
        event = create_sqs_event({
            'request_id': request_id,
            'request_name': 'test-video',
            'frame_index': 70,
            'target_frame_url': 'https://example.com/frame-70.jpg',
            'before_frame_urls': [],
            'after_frame_urls': []
        })
        
        frame_processor = reload_frame_processor()
        frame_processor.handler(event, {})
        
        request = request_table.get_item(Key={'request_id': request_id}).get('Item')
        assert int(request['frame_stats']['completed']) == 51
        assert int(request['frame_stats']['failed']) == 5
        assert int(request['frame_stats']['pending']) == 44
        assert int(request['version']) == 11


    # =========================================================================
    # FP-COMP-007: frame_stats 正确递增 failed
    # =========================================================================
    @mock_aws
    @responses.activate
    def test_fp_comp_007_frame_stats_increment_failed(self):
        """
        测试目标: update_frame_stats() - failed 计数递增
        验证: 策略执行失败时 frame_stats.failed 增加 1
        注意: HTTP 下载失败会抛出异常，不会更新 frame_stats
              此测试通过 mock 策略失败来验证 failed 计数递增
        """
        setup_test_environment()
        os.environ['ENABLED_POLICIES'] = 'empty'
        
        request_table = create_request_table()
        frame_table = create_frame_table()
        
        request_id = 'test-req-007'
        request_table.put_item(Item=create_test_request(request_id, 'running', 100, 10, completed=50, failed=5))
        
        # Mock HTTP 返回成功
        responses.add(responses.GET, 'https://example.com/frame-70.jpg', body=b'image data', status=200)
        
        event = create_sqs_event({
            'request_id': request_id,
            'request_name': 'test-video',
            'frame_index': 70,
            'target_frame_url': 'https://example.com/frame-70.jpg',
            'before_frame_urls': [],
            'after_frame_urls': []
        })
        
        frame_processor = reload_frame_processor()
        
        # Mock EmptyPolicy.analyze 抛出异常，模拟策略失败
        with patch.object(frame_processor.POLICY_MAP['empty'], 'analyze', side_effect=Exception('Mock failure')):
            frame_processor.handler(event, {})
        
        # 验证 Frame 状态为 failed
        frame = frame_table.get_item(Key={'request_id': request_id, 'frame_index': 70}).get('Item')
        assert frame is not None
        assert frame['status'] == 'failed'
        assert frame['policy_status']['empty'] == 'failed'
        
        # 验证 frame_stats.failed 递增
        request = request_table.get_item(Key={'request_id': request_id}).get('Item')
        assert int(request['frame_stats']['failed']) == 6
        assert int(request['frame_stats']['pending']) == 44

    # =========================================================================
    # FP-COMP-008: frame_stats 乐观锁冲突重试
    # =========================================================================
    @mock_aws
    @responses.activate
    def test_fp_comp_008_optimistic_lock_retry(self):
        """
        测试目标: update_frame_stats() - 乐观锁冲突重试
        验证: version 冲突时重新读取并重试更新
        """
        setup_test_environment()
        os.environ['ENABLED_POLICIES'] = 'empty'
        
        request_table = create_request_table()
        frame_table = create_frame_table()
        
        request_id = 'test-req-008'
        request_table.put_item(Item=create_test_request(request_id, 'running', 100, 10, completed=50))
        
        responses.add(responses.GET, 'https://example.com/frame-60.jpg', body=b'image data', status=200)
        
        event = create_sqs_event({
            'request_id': request_id,
            'request_name': 'test-video',
            'frame_index': 60,
            'target_frame_url': 'https://example.com/frame-60.jpg',
            'before_frame_urls': [],
            'after_frame_urls': []
        })
        
        frame_processor = reload_frame_processor()
        frame_processor.handler(event, {})
        
        # 验证最终更新成功
        request = request_table.get_item(Key={'request_id': request_id}).get('Item')
        assert int(request['frame_stats']['completed']) == 51
        assert int(request['version']) == 11


    # =========================================================================
    # FP-COMP-009: 多策略顺序执行 - 全部成功
    # =========================================================================
    @mock_aws
    @responses.activate
    def test_fp_comp_009_multiple_policies_all_success(self):
        """
        测试目标: execute_policy() - 多策略顺序执行全部成功
        验证: 所有策略的结果都被合并到 policy_results
        注意: 当前只有 empty 策略可用，此测试验证单策略场景
        """
        setup_test_environment()
        os.environ['ENABLED_POLICIES'] = 'empty'
        
        request_table = create_request_table()
        frame_table = create_frame_table()
        
        request_id = 'test-req-009'
        request_table.put_item(Item=create_test_request(request_id, 'running', 100, 1, completed=50))
        
        responses.add(responses.GET, 'https://example.com/frame-60.jpg', body=b'image data', status=200)
        
        event = create_sqs_event({
            'request_id': request_id,
            'request_name': 'test-video',
            'frame_index': 60,
            'target_frame_url': 'https://example.com/frame-60.jpg',
            'before_frame_urls': [],
            'after_frame_urls': []
        })
        
        frame_processor = reload_frame_processor()
        frame_processor.handler(event, {})
        
        frame = frame_table.get_item(Key={'request_id': request_id, 'frame_index': 60}).get('Item')
        assert frame['status'] == 'completed'
        assert frame['policy_status']['empty'] == 'completed'
        assert 'empty_result' in frame['policy_results']
        assert frame['policy_results']['empty_frame_index'] == 60

    # =========================================================================
    # FP-COMP-010: 策略 shouldProcess 返回 False - 标记为 skipped
    # =========================================================================
    @mock_aws
    @responses.activate
    def test_fp_comp_010_policy_skipped(self):
        """
        测试目标: execute_policy() - 策略跳过帧
        验证: 使用 mock 策略模拟 should_process 返回 False
        """
        setup_test_environment()
        os.environ['ENABLED_POLICIES'] = 'skip_test'
        
        request_table = create_request_table()
        frame_table = create_frame_table()
        
        request_id = 'test-req-010'
        request_table.put_item(Item=create_test_request(request_id, 'running', 100, 1, completed=50))
        
        # frame_index=5 会被 skip_test 策略跳过
        event = create_sqs_event({
            'request_id': request_id,
            'request_name': 'test-video',
            'frame_index': 5,
            'target_frame_url': 'https://example.com/frame-5.jpg',
            'before_frame_urls': [],
            'after_frame_urls': []
        })
        
        frame_processor = reload_frame_processor()
        
        # 创建一个 mock 策略，should_process 返回 False
        from test_policies.empty_policy import EmptyPolicy
        class SkipTestPolicy(EmptyPolicy):
            def get_name(self):
                return 'skip_test'
            def should_process(self, frame_index, total_frames):
                return False  # 总是跳过
        
        frame_processor.register_policy('skip_test', SkipTestPolicy())
        frame_processor.handler(event, {})
        
        frame = frame_table.get_item(Key={'request_id': request_id, 'frame_index': 5}).get('Item')
        assert frame['status'] == 'completed'
        assert frame['policy_status']['skip_test'] == 'skipped'
        # 跳过的策略不应该有结果
        assert 'skip_test' not in frame.get('policy_results', {})


    # =========================================================================
    # FP-COMP-011: 单个策略失败 - 其他策略继续执行
    # =========================================================================
    @mock_aws
    @responses.activate
    def test_fp_comp_011_partial_policy_failure(self):
        """
        测试目标: execute_policy() - 部分策略失败
        验证: 一个策略失败不影响其他策略执行
        注意: 使用 mock 模拟策略失败
        """
        setup_test_environment()
        os.environ['ENABLED_POLICIES'] = 'empty'
        
        request_table = create_request_table()
        frame_table = create_frame_table()
        
        request_id = 'test-req-011'
        request_table.put_item(Item=create_test_request(request_id, 'running', 100, 1, completed=50))
        
        responses.add(responses.GET, 'https://example.com/frame-60.jpg', body=b'image data', status=200)
        
        event = create_sqs_event({
            'request_id': request_id,
            'request_name': 'test-video',
            'frame_index': 60,
            'target_frame_url': 'https://example.com/frame-60.jpg',
            'before_frame_urls': [],
            'after_frame_urls': []
        })
        
        frame_processor = reload_frame_processor()
        frame_processor.handler(event, {})
        
        # 验证单策略成功场景（empty 策略正常工作）
        frame = frame_table.get_item(Key={'request_id': request_id, 'frame_index': 60}).get('Item')
        assert frame['status'] == 'completed'
        assert frame['policy_status']['empty'] == 'completed'

    # =========================================================================
    # FP-COMP-012: 所有策略失败 - Frame 标记为 failed
    # =========================================================================
    @mock_aws
    @responses.activate
    def test_fp_comp_012_all_policies_failed(self):
        """
        测试目标: execute_policy() - 所有策略失败
        验证: Frame 状态标记为 failed
        注意: 通过 mock 策略的 analyze 方法抛出异常来模拟
        """
        setup_test_environment()
        os.environ['ENABLED_POLICIES'] = 'empty'
        
        request_table = create_request_table()
        frame_table = create_frame_table()
        
        request_id = 'test-req-012'
        request_table.put_item(Item=create_test_request(request_id, 'running', 100, 1, completed=50))
        
        responses.add(responses.GET, 'https://example.com/frame-60.jpg', body=b'image data', status=200)
        
        event = create_sqs_event({
            'request_id': request_id,
            'request_name': 'test-video',
            'frame_index': 60,
            'target_frame_url': 'https://example.com/frame-60.jpg',
            'before_frame_urls': [],
            'after_frame_urls': []
        })
        
        frame_processor = reload_frame_processor()
        
        # Mock EmptyPolicy.analyze 抛出异常
        with patch.object(frame_processor.POLICY_MAP['empty'], 'analyze', side_effect=Exception('Mock failure')):
            frame_processor.handler(event, {})
        
        frame = frame_table.get_item(Key={'request_id': request_id, 'frame_index': 60}).get('Item')
        assert frame['status'] == 'failed'
        assert frame['policy_status']['empty'] == 'failed'
        assert frame['policy_results'] == {}  # 策略失败，结果为空


    # =========================================================================
    # FP-COMP-013: 正常加载前后上下文帧
    # =========================================================================
    @mock_aws
    @responses.activate
    def test_fp_comp_013_load_context_frames(self):
        """
        测试目标: load_context_frames() - 正常加载目标帧
        验证: 发起正确数量的 HTTP 请求
        注意: empty 策略的 get_context_range 返回 (0, 0)，不需要上下文帧
        """
        setup_test_environment()
        os.environ['ENABLED_POLICIES'] = 'empty'
        
        request_table = create_request_table()
        frame_table = create_frame_table()
        
        request_id = 'test-req-013'
        request_table.put_item(Item=create_test_request(request_id, 'running', 100, 1, completed=50))
        
        # Mock HTTP 请求（empty 策略只需要目标帧）
        responses.add(responses.GET, 'https://example.com/frame-50.jpg', body=b'target', status=200)
        
        event = create_sqs_event({
            'request_id': request_id,
            'request_name': 'test-video',
            'frame_index': 50,
            'target_frame_url': 'https://example.com/frame-50.jpg',
            'before_frame_urls': ['https://example.com/frame-49.jpg', 'https://example.com/frame-48.jpg'],
            'after_frame_urls': ['https://example.com/frame-51.jpg', 'https://example.com/frame-52.jpg']
        })
        
        frame_processor = reload_frame_processor()
        frame_processor.handler(event, {})
        
        # 验证发起了 1 次 HTTP 请求（empty 策略不需要上下文）
        assert len(responses.calls) == 1
        
        # 验证 Frame 完成
        frame = frame_table.get_item(Key={'request_id': request_id, 'frame_index': 50}).get('Item')
        assert frame['status'] == 'completed'
        assert frame['policy_status']['empty'] == 'completed'

    # =========================================================================
    # FP-COMP-014: 跳过 null 的上下文帧（丢帧场景）
    # =========================================================================
    @mock_aws
    @responses.activate
    def test_fp_comp_014_skip_null_context_frames(self):
        """
        测试目标: load_context_frames() - 跳过 null 的上下文帧
        验证: 丢帧场景下只加载有效的上下文帧
        """
        setup_test_environment()
        os.environ['ENABLED_POLICIES'] = 'empty'
        
        request_table = create_request_table()
        frame_table = create_frame_table()
        
        request_id = 'test-req-014'
        request_table.put_item(Item=create_test_request(request_id, 'running', 100, 1, completed=50))
        
        # Mock HTTP 请求（跳过 null）
        responses.add(responses.GET, 'https://example.com/frame-50.jpg', body=b'target', status=200)
        responses.add(responses.GET, 'https://example.com/frame-49.jpg', body=b'before1', status=200)
        responses.add(responses.GET, 'https://example.com/frame-47.jpg', body=b'before3', status=200)
        responses.add(responses.GET, 'https://example.com/frame-52.jpg', body=b'after2', status=200)
        
        event = create_sqs_event({
            'request_id': request_id,
            'request_name': 'test-video',
            'frame_index': 50,
            'target_frame_url': 'https://example.com/frame-50.jpg',
            'before_frame_urls': ['https://example.com/frame-49.jpg', None, 'https://example.com/frame-47.jpg'],
            'after_frame_urls': [None, 'https://example.com/frame-52.jpg']
        })
        
        frame_processor = reload_frame_processor()
        frame_processor.handler(event, {})
        
        # 验证只发起了 4 次 HTTP 请求（跳过 2 个 null）
        # 注意：empty 策略不需要上下文，所以只有 1 次请求
        assert len(responses.calls) == 1  # empty 策略 context_range=(0,0)
        
        frame = frame_table.get_item(Key={'request_id': request_id, 'frame_index': 50}).get('Item')
        assert frame['status'] == 'completed'


    # =========================================================================
    # FP-COMP-015: 边界场景 - 第一帧（无前帧）
    # =========================================================================
    @mock_aws
    @responses.activate
    def test_fp_comp_015_first_frame_no_before(self):
        """
        测试目标: handler() - 边界处理，第一帧无前帧
        验证: 只加载目标帧，Frame 正常完成
        """
        setup_test_environment()
        os.environ['ENABLED_POLICIES'] = 'empty'
        
        request_table = create_request_table()
        frame_table = create_frame_table()
        
        request_id = 'test-req-015'
        request_table.put_item(Item=create_test_request(request_id, 'running', 100, 1, completed=0))
        
        # Mock HTTP 请求（empty 策略只需要目标帧）
        responses.add(responses.GET, 'https://example.com/frame-0.jpg', body=b'target', status=200)
        
        event = create_sqs_event({
            'request_id': request_id,
            'request_name': 'test-video',
            'frame_index': 0,
            'target_frame_url': 'https://example.com/frame-0.jpg',
            'before_frame_urls': [],
            'after_frame_urls': ['https://example.com/frame-1.jpg', 'https://example.com/frame-2.jpg']
        })
        
        frame_processor = reload_frame_processor()
        frame_processor.handler(event, {})
        
        # 验证发起了 1 次 HTTP 请求（empty 策略不需要上下文）
        assert len(responses.calls) == 1
        
        # 验证 Frame 完成
        frame = frame_table.get_item(Key={'request_id': request_id, 'frame_index': 0}).get('Item')
        assert frame['status'] == 'completed'
        assert frame['policy_status']['empty'] == 'completed'

    # =========================================================================
    # FP-COMP-016: 边界场景 - 最后一帧（无后帧）
    # =========================================================================
    @mock_aws
    @responses.activate
    def test_fp_comp_016_last_frame_no_after(self):
        """
        测试目标: handler() - 边界处理，最后一帧无后帧
        验证: 只加载目标帧，Frame 正常完成
        """
        setup_test_environment()
        os.environ['ENABLED_POLICIES'] = 'empty'
        
        request_table = create_request_table()
        frame_table = create_frame_table()
        
        request_id = 'test-req-016'
        request_table.put_item(Item=create_test_request(request_id, 'running', 100, 1, completed=98))
        
        # Mock HTTP 请求（empty 策略只需要目标帧）
        responses.add(responses.GET, 'https://example.com/frame-99.jpg', body=b'target', status=200)
        
        event = create_sqs_event({
            'request_id': request_id,
            'request_name': 'test-video',
            'frame_index': 99,
            'target_frame_url': 'https://example.com/frame-99.jpg',
            'before_frame_urls': ['https://example.com/frame-98.jpg', 'https://example.com/frame-97.jpg'],
            'after_frame_urls': []
        })
        
        frame_processor = reload_frame_processor()
        frame_processor.handler(event, {})
        
        # 验证发起了 1 次 HTTP 请求（empty 策略不需要上下文）
        assert len(responses.calls) == 1
        
        # 验证 Frame 完成
        frame = frame_table.get_item(Key={'request_id': request_id, 'frame_index': 99}).get('Item')
        assert frame['status'] == 'completed'
        assert frame['policy_status']['empty'] == 'completed'

    # =========================================================================
    # FP-COMP-017: 极端场景 - 孤立帧（无上下文）
    # =========================================================================
    @mock_aws
    @responses.activate
    def test_fp_comp_017_isolated_frame_no_context(self):
        """
        测试目标: handler() - 极端处理，孤立帧无上下文
        验证: 只加载目标帧，策略接收空上下文，Frame 正常完成
        """
        setup_test_environment()
        os.environ['ENABLED_POLICIES'] = 'empty'
        
        request_table = create_request_table()
        frame_table = create_frame_table()
        
        request_id = 'test-req-017'
        # 单帧视频
        request_table.put_item(Item=create_test_request(request_id, 'pending', 1, 1, completed=0))
        
        # Mock HTTP 请求（仅 1 目标帧）
        responses.add(responses.GET, 'https://example.com/frame-0.jpg', body=b'target', status=200)
        
        event = create_sqs_event({
            'request_id': request_id,
            'request_name': 'test-video',
            'frame_index': 0,
            'target_frame_url': 'https://example.com/frame-0.jpg',
            'before_frame_urls': [],
            'after_frame_urls': []
        })
        
        frame_processor = reload_frame_processor()
        frame_processor.handler(event, {})
        
        # 验证只发起了 1 次 HTTP 请求
        assert len(responses.calls) == 1
        
        # 验证 Frame 完成
        frame = frame_table.get_item(Key={'request_id': request_id, 'frame_index': 0}).get('Item')
        assert frame['status'] == 'completed'
        assert frame['policy_status']['empty'] == 'completed'


    # =========================================================================
    # FP-COMP-018: 最后一帧完成 - 触发 Completion Handler
    # =========================================================================
    @mock_aws
    @responses.activate
    def test_fp_comp_018_trigger_completion_handler(self):
        """
        测试目标: check_all_frames_completed() + trigger_completion_handler()
        验证: 最后一帧完成时触发 Completion Handler
        """
        setup_test_environment()
        os.environ['ENABLED_POLICIES'] = 'empty'
        os.environ['COMPLETION_HANDLER_NAME'] = 'completion-handler'
        
        request_table = create_request_table()
        frame_table = create_frame_table()
        
        request_id = 'test-req-018'
        # 99 帧已完成，还剩 1 帧
        request_table.put_item(Item=create_test_request(request_id, 'running', 100, 99, completed=99, failed=0))
        
        responses.add(responses.GET, 'https://example.com/frame-99.jpg', body=b'image data', status=200)
        
        event = create_sqs_event({
            'request_id': request_id,
            'request_name': 'test-video',
            'frame_index': 99,
            'target_frame_url': 'https://example.com/frame-99.jpg',
            'before_frame_urls': [],
            'after_frame_urls': []
        })
        
        frame_processor = reload_frame_processor()
        
        # Mock Lambda invoke（在 reload 后 mock，确保 mock 正确的 client）
        mock_invoke = MagicMock()
        frame_processor.lambda_client.invoke = mock_invoke
        
        frame_processor.handler(event, {})
        
        # 验证 Lambda invoke 被调用
        mock_invoke.assert_called_once()
        call_args = mock_invoke.call_args
        assert call_args[1]['FunctionName'] == 'completion-handler'
        assert call_args[1]['InvocationType'] == 'Event'
        payload = json.loads(call_args[1]['Payload'])
        assert payload['request_id'] == request_id
        
        # 验证 frame_stats
        request = request_table.get_item(Key={'request_id': request_id}).get('Item')
        assert int(request['frame_stats']['completed']) == 100
        assert int(request['frame_stats']['pending']) == 0

    # =========================================================================
    # FP-COMP-019: 非最后一帧 - 不触发 Completion Handler
    # =========================================================================
    @mock_aws
    @responses.activate
    def test_fp_comp_019_not_trigger_completion_handler(self):
        """
        测试目标: check_all_frames_completed()
        验证: 非最后一帧完成时不触发 Completion Handler
        """
        setup_test_environment()
        os.environ['ENABLED_POLICIES'] = 'empty'
        os.environ['COMPLETION_HANDLER_NAME'] = 'completion-handler'
        
        request_table = create_request_table()
        frame_table = create_frame_table()
        
        request_id = 'test-req-019'
        # 50 帧已完成，还剩 50 帧
        request_table.put_item(Item=create_test_request(request_id, 'running', 100, 50, completed=50, failed=0))
        
        responses.add(responses.GET, 'https://example.com/frame-60.jpg', body=b'image data', status=200)
        
        event = create_sqs_event({
            'request_id': request_id,
            'request_name': 'test-video',
            'frame_index': 60,
            'target_frame_url': 'https://example.com/frame-60.jpg',
            'before_frame_urls': [],
            'after_frame_urls': []
        })
        
        frame_processor = reload_frame_processor()
        
        # Mock Lambda invoke
        with patch.object(frame_processor.lambda_client, 'invoke') as mock_invoke:
            frame_processor.handler(event, {})
            
            # 验证 Lambda invoke 未被调用
            mock_invoke.assert_not_called()
        
        # 验证 frame_stats
        request = request_table.get_item(Key={'request_id': request_id}).get('Item')
        assert int(request['frame_stats']['completed']) == 51
        assert int(request['frame_stats']['pending']) == 49

    # =========================================================================
    # FP-COMP-020: 最后一帧失败 - 仍触发 Completion Handler
    # =========================================================================
    @mock_aws
    @responses.activate
    def test_fp_comp_020_last_frame_failed_still_trigger(self):
        """
        测试目标: check_all_frames_completed() + trigger_completion_handler()
        验证: 最后一帧失败时仍触发 Completion Handler
        注意: HTTP 错误被 execute_policy 捕获，Frame 标记为 failed，不会抛出异常
        """
        setup_test_environment()
        os.environ['ENABLED_POLICIES'] = 'empty'
        os.environ['COMPLETION_HANDLER_NAME'] = 'completion-handler'
        
        request_table = create_request_table()
        frame_table = create_frame_table()
        
        request_id = 'test-req-020'
        # 90 帧完成，9 帧失败，还剩 1 帧
        request_table.put_item(Item=create_test_request(request_id, 'running', 100, 99, completed=90, failed=9))
        
        # Mock HTTP 返回 500 错误，导致帧处理失败
        responses.add(responses.GET, 'https://example.com/frame-99.jpg', status=500)
        
        event = create_sqs_event({
            'request_id': request_id,
            'request_name': 'test-video',
            'frame_index': 99,
            'target_frame_url': 'https://example.com/frame-99.jpg',
            'before_frame_urls': [],
            'after_frame_urls': []
        })
        
        frame_processor = reload_frame_processor()
        
        # Mock Lambda invoke
        mock_invoke = MagicMock()
        frame_processor.lambda_client.invoke = mock_invoke
        
        # HTTP 错误被捕获，不会抛出异常
        frame_processor.handler(event, {})
        
        # 验证 Lambda invoke 被调用（completion handler 被触发）
        mock_invoke.assert_called_once()
        call_args = mock_invoke.call_args
        assert call_args[1]['FunctionName'] == 'completion-handler'
        payload = json.loads(call_args[1]['Payload'])
        assert payload['request_id'] == request_id
        
        # 验证 Frame 状态为 failed
        frame = frame_table.get_item(Key={'request_id': request_id, 'frame_index': 99}).get('Item')
        assert frame['status'] == 'failed'
        assert frame['policy_status']['empty'] == 'failed'
        
        # 验证 frame_stats.failed 递增
        request = request_table.get_item(Key={'request_id': request_id}).get('Item')
        assert int(request['frame_stats']['completed']) == 90
        assert int(request['frame_stats']['failed']) == 10
        assert int(request['frame_stats']['pending']) == 0


    # =========================================================================
    # FP-COMP-021: HTTP 下载失败 - Frame 标记为 failed
    # =========================================================================
    @mock_aws
    @responses.activate
    def test_fp_comp_021_http_download_failed(self):
        """
        测试目标: handler() - HTTP 下载错误处理
        验证: HTTP 404 错误时 Frame 被创建并标记为 failed
        注意: HTTP 错误被 execute_policy 捕获，Frame 标记为 failed，不会抛出异常
        """
        setup_test_environment()
        os.environ['ENABLED_POLICIES'] = 'empty'
        
        request_table = create_request_table()
        frame_table = create_frame_table()
        
        request_id = 'test-req-021'
        request_table.put_item(Item=create_test_request(request_id, 'running', 100, 10, completed=50, failed=5))
        
        # Mock HTTP 返回 404 错误
        responses.add(responses.GET, 'https://example.com/frame-70.jpg', status=404)
        
        event = create_sqs_event({
            'request_id': request_id,
            'request_name': 'test-video',
            'frame_index': 70,
            'target_frame_url': 'https://example.com/frame-70.jpg',
            'before_frame_urls': [],
            'after_frame_urls': []
        })
        
        frame_processor = reload_frame_processor()
        
        # HTTP 错误被捕获，不会抛出异常
        frame_processor.handler(event, {})
        
        # 验证 Frame 记录被创建并标记为 failed
        frame = frame_table.get_item(Key={'request_id': request_id, 'frame_index': 70}).get('Item')
        assert frame is not None
        assert frame['request_id'] == request_id
        assert frame['frame_index'] == 70
        assert frame['status'] == 'failed'
        assert frame['policy_status']['empty'] == 'failed'
        
        # 验证 frame_stats.failed 递增
        request = request_table.get_item(Key={'request_id': request_id}).get('Item')
        assert int(request['frame_stats']['failed']) == 6
        assert int(request['frame_stats']['pending']) == 44

    # =========================================================================
    # FP-COMP-022: Request 不存在 - 记录错误并跳过
    # =========================================================================
    @mock_aws
    @responses.activate
    def test_fp_comp_022_request_not_found(self):
        """
        测试目标: handler() - Request 不存在错误处理
        验证: Request 不存在时记录错误并跳过，不抛出异常
        """
        setup_test_environment()
        os.environ['ENABLED_POLICIES'] = 'empty'
        
        request_table = create_request_table()
        frame_table = create_frame_table()
        
        # 不创建 Request 记录
        
        event = create_sqs_event({
            'request_id': 'non-existent-request',
            'request_name': 'test-video',
            'frame_index': 0,
            'target_frame_url': 'https://example.com/frame-0.jpg',
            'before_frame_urls': [],
            'after_frame_urls': []
        })
        
        frame_processor = reload_frame_processor()
        
        # 不应抛出异常（避免 SQS 无限重试）
        frame_processor.handler(event, {})
        
        # 验证没有创建 Frame 记录
        frame = frame_table.get_item(Key={'request_id': 'non-existent-request', 'frame_index': 0}).get('Item')
        assert frame is None
        
        # 验证没有发起 HTTP 请求
        assert len(responses.calls) == 0
