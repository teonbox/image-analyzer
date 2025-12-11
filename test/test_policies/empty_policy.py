"""
EmptyPolicy - 用于测试的空策略

返回静态数据，不调用 Bedrock，不需要上下文帧。
专门用于 Layer 1-2 测试，验证框架逻辑而非策略分析结果。

使用方式：
    from test_policies.empty_policy import EmptyPolicy
    from handlers import frame_processor
    frame_processor.register_policy('empty', EmptyPolicy())
"""
from typing import Dict, Any, List, Tuple

try:
    from policies.base import AnalysisPolicy
except ImportError:
    # 如果直接导入失败，尝试添加路径
    import sys
    import os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'lambda'))
    from policies.base import AnalysisPolicy


class EmptyPolicy(AnalysisPolicy):
    """
    测试用空策略，返回静态数据。
    
    特点：
    - 不调用 Bedrock，返回静态数据
    - 不需要上下文帧（get_context_range 返回 (0, 0)）
    - 处理所有帧（should_process 总是返回 True）
    
    返回结果：
    {
        'empty_result': 'static_value',
        'empty_frame_index': <frame_index>
    }
    
    使用场景：
    - 验证 Frame Processor 的框架逻辑
    - 验证 DynamoDB 读写
    - 验证状态转换
    - 验证 frame_stats 统计
    """
    
    def get_name(self) -> str:
        return 'empty'
    
    def should_process(self, frame_index: int, total_frames: int) -> bool:
        return True
    
    def get_context_range(self, frame_index: int, total_frames: int) -> Tuple[int, int]:
        return (0, 0)  # 不需要上下文
    
    def analyze(
        self,
        target_frame: Dict[str, Any],
        context_frames: List[Dict[str, Any]],
        bedrock_client: Any,
        storage_config: Any = None
    ) -> Dict[str, Any]:
        """返回静态数据，不调用任何外部服务"""
        return {
            'empty_result': 'static_value',
            'empty_frame_index': target_frame['index']
        }
