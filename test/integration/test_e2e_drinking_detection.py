"""
端到端测试：喝东西检测

测试目标: 验证从提交到完成的完整端到端流程，并验证检测结果准确性
"""
import pytest
import time
import logging

logger = logging.getLogger(__name__)


@pytest.mark.e2e
@pytest.mark.bedrock
class TestE2EDrinkingDetection:
    """端到端测试：喝东西检测"""

    def test_drinking_positive(
        self,
        test_case_loader,
        api_client,
        request_waiter,
        verifier
    ):
        """
        测试目标: 端到端流程 - 喝东西检测正向场景

        验证:
        1. API 提交请求成功
        2. 系统自动处理完成
        3. 检测结果准确（所有帧都识别为正在喝水）
        """
        # 1. 加载测试配置
        test_config = test_case_loader('drinking-positive')
        print(f"\n{'='*60}")
        print(f"测试: {test_config['name']}")
        print(f"描述: {test_config['description']}")
        print(f"帧数: {len(test_config['frames'])}")
        print(f"{'='*60}")

        # 2. 提交请求
        print(f"\n[步骤 1] 提交请求...")
        urls = [frame['url'] for frame in test_config['frames']]
        test_name = f"e2e-{test_config['name']}-{int(time.time())}"

        response = api_client.submit_request(
            name=test_name,
            urls=urls,
            callback_url='https://webhook.site/test'
        )

        assert response['success'] is True, f"提交失败: {response}"
        request_id = response['data']['request_id']
        total_frames = response['data']['total_frames']

        print(f"  ✓ Request ID: {request_id}")
        print(f"  ✓ Total frames: {total_frames}")
        logger.info(f"Request submitted: {request_id}, frames: {total_frames}")

        assert total_frames == len(test_config['frames']), \
            f"帧数不匹配: 预期 {len(test_config['frames'])}, 实际 {total_frames}"

        # 3. 等待处理完成
        print(f"\n[步骤 2] 等待处理完成...")
        final_status = request_waiter.wait_for_completion(request_id)
        print(f"  ✓ 最终状态: {final_status}")
        logger.info(f"Request {request_id} completed with status: {final_status}")

        assert final_status in ['completed', 'partial_complete'], \
            f"处理失败，状态: {final_status}"

        # 4. 获取结果
        print(f"\n[步骤 3] 获取分析结果...")
        results = api_client.get_request_results(request_id)

        assert results['success'] is True, f"获取结果失败: {results}"
        results_data = results['data']

        # 打印完整结果
        import json
        print(f"\n  完整结果:")
        print(json.dumps(results_data, indent=2, ensure_ascii=False))

        frame_stats = results_data.get('frame_stats', results_data.get('statistics', {}))
        print(f"\n  ✓ 成功帧数: {frame_stats.get('completed', frame_stats.get('completed_frames', 0))}")
        print(f"  ✓ 失败帧数: {frame_stats.get('failed', frame_stats.get('failed_frames', 0))}")
        logger.info(f"Results retrieved: {frame_stats}")

        # 5. 验证检测结果
        print(f"\n[步骤 4] 验证检测结果准确性...")
        actual_frames = results_data.get('frames', [])

        # 按 frame_index 排序
        actual_frames_sorted = sorted(actual_frames, key=lambda x: x['frame_index'])

        verifier.verify_frame_results(
            test_config['frames'],
            actual_frames_sorted
        )

        print(f"\n{'='*60}")
        print(f"✅ 测试通过: {test_config['name']}")
        print(f"{'='*60}\n")
        logger.info(f"Test passed: {test_config['name']}")
