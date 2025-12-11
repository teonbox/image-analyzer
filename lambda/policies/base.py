"""
分析策略基类
"""
from abc import ABC, abstractmethod
from typing import Dict, Any, List, Tuple


# Model ID 映射表
MODEL_REGISTRY = {
    # Nova 2 系列 (最新)
    'nova-2-lite': 'amazon.nova-2-lite-v1:0',
    'nova-2-lite-256k': 'amazon.nova-2-lite-v1:0:256k',
    'nova-2-sonic': 'amazon.nova-2-sonic-v1:0',
    'nova-2-embeddings': 'amazon.nova-2-multimodal-embeddings-v1:0',
    # Nova 1 系列
    'nova-premier': 'amazon.nova-premier-v1:0',
    'nova-premier-8k': 'amazon.nova-premier-v1:0:8k',
    'nova-premier-20k': 'amazon.nova-premier-v1:0:20k',
    'nova-premier-1000k': 'amazon.nova-premier-v1:0:1000k',
    'nova-premier-mm': 'amazon.nova-premier-v1:0:mm',
    'nova-pro': 'amazon.nova-pro-v1:0',
    'nova-pro-24k': 'amazon.nova-pro-v1:0:24k',
    'nova-pro-300k': 'amazon.nova-pro-v1:0:300k',
    'nova-lite': 'amazon.nova-lite-v1:0',
    'nova-lite-24k': 'amazon.nova-lite-v1:0:24k',
    'nova-lite-300k': 'amazon.nova-lite-v1:0:300k',
    'nova-micro': 'amazon.nova-micro-v1:0',
    'nova-micro-24k': 'amazon.nova-micro-v1:0:24k',
    'nova-micro-128k': 'amazon.nova-micro-v1:0:128k',
    'nova-sonic': 'amazon.nova-sonic-v1:0',
    'nova-canvas': 'amazon.nova-canvas-v1:0',
    'nova-reel': 'amazon.nova-reel-v1:0',
    'nova-reel-v1.1': 'amazon.nova-reel-v1:1',
    # Claude 3.x 系列
    'claude-3-haiku': 'anthropic.claude-3-haiku-20240307-v1:0',
    'claude-3-sonnet': 'anthropic.claude-3-sonnet-20240229-v1:0',
    'claude-3-opus': 'anthropic.claude-3-opus-20240229-v1:0',
    'claude-3.5-haiku': 'anthropic.claude-3-5-haiku-20241022-v1:0',
    'claude-3.5-sonnet': 'anthropic.claude-3-5-sonnet-20241022-v2:0',
    'claude-3.7-sonnet': 'anthropic.claude-3-7-sonnet-20250219-v1:0',
    # Claude 4.x 系列 (使用 cross-region inference profile)
    'claude-4-sonnet': 'us.anthropic.claude-sonnet-4-20250514-v1:0',
    'claude-4.5-sonnet': 'us.anthropic.claude-sonnet-4-5-20250929-v1:0',
    'claude-4.5-haiku': 'us.anthropic.claude-haiku-4-5-20251001-v1:0',
    'claude-4-opus': 'us.anthropic.claude-opus-4-20250514-v1:0',
    'claude-4.1-opus': 'us.anthropic.claude-opus-4-1-20250805-v1:0',
    'claude-4.5-opus': 'us.anthropic.claude-opus-4-5-20251101-v1:0',
}

# 别名映射
MODEL_ALIASES = {
    'lite': 'nova-2-lite',
    'pro': 'nova-pro',
    'premier': 'nova-premier',
    'micro': 'nova-micro',
    'haiku': 'claude-4.5-haiku',
    'sonnet': 'claude-4.5-sonnet',
    'opus': 'claude-4.5-opus',
}


def get_model_id(name: str) -> str:
    """
    根据别名获取 Bedrock Model ID
    
    Args:
        name: 模型别名，如 'nova-lite', 'claude-3.7-sonnet', 'sonnet' 等
        
    Returns:
        Bedrock Model ID
        
    Raises:
        ValueError: 未知的模型名称
        
    Examples:
        >>> get_model_id('nova-lite')
        'us.amazon.nova-lite-v1:0'
        >>> get_model_id('sonnet')  # 别名
        'anthropic.claude-3-7-sonnet-20250219-v1:0'
    """
    name = name.lower().strip()
    
    # 先检查别名
    if name in MODEL_ALIASES:
        name = MODEL_ALIASES[name]
    
    if name in MODEL_REGISTRY:
        return MODEL_REGISTRY[name]
    
    raise ValueError(
        f"Unknown model: '{name}'. "
        f"Available: {list(MODEL_REGISTRY.keys())} "
        f"Aliases: {list(MODEL_ALIASES.keys())}"
    )


def list_models() -> Dict[str, str]:
    """返回所有可用模型及其 ID"""
    return dict(MODEL_REGISTRY)


class AnalysisPolicy(ABC):
    """
    分析策略抽象接口
    
    策略需要实现以下方法：
    - get_name: 返回策略标识符
    - should_process: 判断是否处理某一帧
    - get_context_range: 声明需要的上下文帧范围
    - analyze: 执行图片分析
    """
    
    @abstractmethod
    def get_name(self) -> str:
        """返回策略标识符"""
        pass
    
    @abstractmethod
    def should_process(self, frame_index: int, total_frames: int) -> bool:
        """
        判断是否处理此帧
        
        Args:
            frame_index: 当前帧索引
            total_frames: 总帧数
            
        Returns:
            True 表示处理此帧，False 表示跳过
        """
        pass
    
    @abstractmethod
    def get_context_range(self, frame_index: int, total_frames: int) -> Tuple[int, int]:
        """
        声明需要的上下文帧范围
        
        Args:
            frame_index: 当前帧索引
            total_frames: 总帧数
            
        Returns:
            (start_offset, end_offset) 相对于当前帧的偏移量
            例如：(-1, 1) 表示需要前1帧和后1帧
        """
        pass
    
    @abstractmethod
    def analyze(
        self,
        target_frame: Dict[str, Any],
        context_frames: List[Dict[str, Any]],
        bedrock_client: Any,
        storage_helper: Any = None
    ) -> Dict[str, Any]:
        """
        分析图片
        
        Args:
            target_frame: 当前要分析的帧 {'index': int, 'url': str, 'data': bytes}
            context_frames: 上下文帧列表 [{'index': int, 'url': str, 'data': bytes}, ...]
            bedrock_client: Bedrock 客户端实例
            storage_helper: 存储辅助类实例（可选使用）
            
        Returns:
            key-value 格式的分析结果，将合并到 Frame.policy_results 中
        """
        pass
