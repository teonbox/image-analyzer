"""
Empty Policy - 空策略（测试用）
不做任何处理，直接返回空结果
"""
from ..base import AnalysisPolicy


class EmptyPolicy(AnalysisPolicy):
    """空策略 - 测试用"""
    
    def get_name(self) -> str:
        return "empty"
    
    def should_process(self, frame_index: int, total_frames: int) -> bool:
        return True
    
    def get_context_range(self, frame_index: int, total_frames: int) -> tuple:
        return (0, 0)
    
    def analyze(self, target_frame: dict, context_frames: list, bedrock_client, config: dict = None) -> dict:
        """返回空结果"""
        return {
            "policy": self.get_name(),
            "frame_index": target_frame.get("index"),
            "status": "completed",
            "result": {}
        }
