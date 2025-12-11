"""结果验证器"""
import logging
from typing import Dict, Any, List

logger = logging.getLogger(__name__)


class ResultVerifier:
    """结果验证器"""

    def verify_frame_results(
        self,
        expected_frames: List[Dict[str, Any]],
        actual_frames: List[Dict[str, Any]]
    ):
        """验证帧结果"""
        assert len(actual_frames) == len(expected_frames), \
            f"帧数不匹配: 预期 {len(expected_frames)}, 实际 {len(actual_frames)}"

        for i, (expected, actual) in enumerate(zip(expected_frames, actual_frames)):
            self._verify_single_frame(i, expected, actual)

    def _verify_single_frame(
        self,
        frame_index: int,
        expected: Dict[str, Any],
        actual: Dict[str, Any]
    ):
        """验证单个帧"""
        frame_desc = expected.get('description', f'Frame {frame_index}')
        print(f"\n  验证 {frame_desc}:")

        # 如果预期状态是 failed
        if expected.get('expected_status') == 'failed':
            assert actual['status'] == 'failed', \
                f"  ✗ 预期失败但实际状态为 {actual['status']}"
            print(f"    ✓ 状态: failed (符合预期)")
            return

        # 验证状态
        assert actual['status'] == 'completed', \
            f"  ✗ 帧状态为 {actual['status']}, 预期 completed"

        # 验证结果字段
        expected_results = expected.get('expected_results', {})
        actual_results = actual.get('results', {})

        # 收集所有 _min 和 _max 的 base_key，避免重复验证
        processed_range_keys = set()

        for key, expected_value in expected_results.items():
            if key.endswith('_max'):
                # _max 在 _min 中一起处理
                continue
            self._verify_field(
                key, expected_value, actual_results,
                expected_results, processed_range_keys
            )

        # 验证不应该存在的字段
        not_expected = expected.get('not_expected', [])
        for key in not_expected:
            assert key not in actual_results, \
                f"  ✗ 字段 '{key}' 不应该存在"
            print(f"    ✓ 字段 '{key}' 不存在 (符合预期)")

    def _verify_field(
        self,
        key: str,
        expected_value: Any,
        actual_results: Dict[str, Any],
        all_expected: Dict[str, Any],
        processed_range_keys: set
    ):
        """验证单个字段（简化版）"""
        if key.endswith('_min'):
            # 范围匹配
            base_key = key[:-4]
            if base_key in processed_range_keys:
                return
            processed_range_keys.add(base_key)

            assert base_key in actual_results, \
                f"  ✗ 缺少字段 '{base_key}'"

            actual_value = actual_results[base_key]
            min_val = expected_value
            max_key = f"{base_key}_max"
            max_val = all_expected.get(max_key, float('inf'))

            assert min_val <= actual_value <= max_val, \
                f"  ✗ {base_key} = {actual_value} 不在范围 [{min_val}, {max_val}]"
            print(f"    ✓ {base_key} = {actual_value} (在范围 [{min_val}, {max_val}] 内)")

        elif key.endswith('_contains'):
            # 包含匹配
            base_key = key[:-9]

            assert base_key in actual_results, \
                f"  ✗ 缺少字段 '{base_key}'"

            actual_value = actual_results[base_key]
            substring = expected_value

            assert substring in str(actual_value), \
                f"  ✗ {base_key} = '{actual_value}' 不包含 '{substring}'"
            print(f"    ✓ {base_key} 包含 '{substring}'")

        else:
            # 精确匹配
            assert key in actual_results, \
                f"  ✗ 缺少字段 '{key}'"

            actual_value = actual_results[key]
            assert actual_value == expected_value, \
                f"  ✗ {key} = {actual_value}, 预期 {expected_value}"
            print(f"    ✓ {key} = {actual_value}")
