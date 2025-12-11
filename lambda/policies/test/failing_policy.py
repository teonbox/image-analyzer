"""
FailingPolicy - 用于测试的失败策略

总是抛出异常，用于测试策略失败场景。
"""
from typing import Dict, Any, List, Tuple

from ..base import AnalysisPolicy


class FailingPolicy(AnalysisPolicy):
    """测试用失败策略，总是抛出异常"""
    
    def get_name(self) -> str:
        return 'failing'
    
    def should_process(self, frame_index: int, total_frames: int) -> bool:
        return True
    
    def get_context_range(self, frame_index: int, total_frames: int) -> Tuple[int, int]:
        return (0, 0)
    
    def analyze(
        self,
        target_frame: Dict[str, Any],
        context_frames: List[Dict[str, Any]],
        bedrock_client: Any,
        storage_config: Any = None
    ) -> Dict[str, Any]:
        """总是抛出异常，用于测试失败场景"""
        raise RuntimeError(f"FailingPolicy intentionally failed for frame {target_frame['index']}")
