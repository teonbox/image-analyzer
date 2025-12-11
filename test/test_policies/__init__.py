"""
测试策略模块

此模块包含用于 Layer 1-2 测试的策略实现。
这些策略不调用 Bedrock，返回静态数据，专门用于验证框架逻辑。

使用方式：
    from test_policies.empty_policy import EmptyPolicy
    from handlers import frame_processor
    frame_processor.register_policy('empty', EmptyPolicy())

可用策略：
- EmptyPolicy: 返回静态数据，不需要上下文帧，处理所有帧
"""

from test_policies.empty_policy import EmptyPolicy

__all__ = ['EmptyPolicy']
