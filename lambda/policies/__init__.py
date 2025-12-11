"""
Policy 自动发现和加载模块

规则：
1. policies/ 目录下的 *_policy.py 文件会被自动扫描
2. policies/test/ 目录下的是 test policy
3. 其他目录下的是 production policy

加载逻辑：
1. 如果设置了 ENABLED_POLICIES，按指定的 policy 加载（优先级最高）
2. 如果没有设置 ENABLED_POLICIES：
   - 非 test 环境：加载所有 production policies
   - test 环境：加载所有 policies（包括 test）
"""
import importlib
import inspect
import os
from pathlib import Path

from .base import AnalysisPolicy

__all__ = [
    'AnalysisPolicy',
    'get_policy_map',
    'get_all_policies',
    'get_production_policies',
    'get_test_policies',
]

# 自动注册的 policy 映射
_POLICY_REGISTRY = {}
_PRODUCTION_POLICIES = set()
_TEST_POLICIES = set()
_INITIALIZED = False


def _scan_and_register():
    """自动扫描并注册所有 policy"""
    global _INITIALIZED
    if _INITIALIZED:
        return
    
    policies_dir = Path(__file__).parent
    
    # 扫描 production policies (policies/*.py)
    for py_file in policies_dir.glob('*_policy.py'):
        module_name = py_file.stem
        _load_policy_from_module(f'policies.{module_name}', is_test=False)
    
    # 扫描 test policies (policies/test/*.py)
    test_dir = policies_dir / 'test'
    if test_dir.exists():
        for py_file in test_dir.glob('*_policy.py'):
            module_name = py_file.stem
            _load_policy_from_module(f'policies.test.{module_name}', is_test=True)
    
    _INITIALIZED = True


def _load_policy_from_module(module_path: str, is_test: bool):
    """从模块中加载 policy 类"""
    try:
        module = importlib.import_module(module_path)
        
        # 查找继承自 AnalysisPolicy 的类
        for name, obj in inspect.getmembers(module, inspect.isclass):
            if (issubclass(obj, AnalysisPolicy) 
                and obj is not AnalysisPolicy
                and obj.__module__ == module.__name__):
                _register_policy(obj, is_test)
    except Exception as e:
        print(f"Warning: Failed to load policy from {module_path}: {e}")


def _register_policy(cls, is_test: bool = False):
    """注册一个 policy 类"""
    try:
        instance = cls()
        name = instance.get_name()
        _POLICY_REGISTRY[name] = cls
        if is_test:
            _TEST_POLICIES.add(name)
        else:
            _PRODUCTION_POLICIES.add(name)
    except Exception as e:
        print(f"Warning: Failed to register policy {cls.__name__}: {e}")


# 模块加载时自动扫描
_scan_and_register()


def get_all_policies() -> dict:
    """获取所有 policy 名称到类的映射"""
    return dict(_POLICY_REGISTRY)


def get_production_policies() -> dict:
    """获取所有 production policy 名称到类的映射"""
    return {k: v for k, v in _POLICY_REGISTRY.items() if k in _PRODUCTION_POLICIES}


def get_test_policies() -> dict:
    """获取所有 test policy 名称到类的映射"""
    return {k: v for k, v in _POLICY_REGISTRY.items() if k in _TEST_POLICIES}


def is_test_environment() -> bool:
    """判断是否为测试环境"""
    env = os.environ.get('ENVIRONMENT', '').lower()
    return env in ('test', 'testing', 'dev', 'development', 'local')


def get_policy_map(enabled_policies: list = None) -> dict:
    """
    根据配置返回要启用的 policy 实例
    
    加载逻辑：
    1. 如果 enabled_policies 非空，按指定的 policy 加载（优先级最高）
    2. 如果 enabled_policies 为空或 None：
       - 非 test 环境：加载所有 production policies
       - test 环境：加载所有 policies（包括 test）
    
    Args:
        enabled_policies: ENABLED_POLICIES 环境变量解析后的列表，可以为 None
    
    Returns:
        dict: {policy_name: policy_instance}
    """
    result = {}
    
    if enabled_policies:
        enabled_policies = [p.strip() for p in enabled_policies if p.strip()]
    
    if not enabled_policies:
        if is_test_environment():
            policies_to_load = get_all_policies()
        else:
            policies_to_load = get_production_policies()
        
        for name, cls in policies_to_load.items():
            result[name] = cls()
        return result
    
    all_policies = get_all_policies()
    for p in enabled_policies:
        if p in all_policies and p not in result:
            result[p] = all_policies[p]()
        elif p not in all_policies:
            print(f"Warning: Policy '{p}' not found, skipping")
    
    return result
