"""
Layer 1: DrinkingDetectionPolicy 单元测试
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../../lambda'))

import pytest
from policies.drinking_detection_policy import DrinkingDetectionPolicy


class TestDrinkingDetectionPolicyUnit:
    """Layer 1: 单元测试"""
    
    def setup_method(self):
        self.policy = DrinkingDetectionPolicy()
    
    def test_drink_001_should_process_always_true(self):
        """DRINK-001: shouldProcess 总是返回 True"""
        assert self.policy.should_process(0, 100) == True
        assert self.policy.should_process(10, 100) == True
        assert self.policy.should_process(50, 100) == True
        assert self.policy.should_process(99, 100) == True
    
    def test_drink_002_get_name_returns_correct_name(self):
        """DRINK-002: getName 返回正确的策略名称"""
        assert self.policy.get_name() == "drinking_detection"
    
    def test_drink_003_get_context_range_returns_minus_one_to_one(self):
        """DRINK-003: 声明需要前后各 1 帧"""
        assert self.policy.get_context_range(0, 100) == (-1, 1)
        assert self.policy.get_context_range(50, 100) == (-1, 1)
        assert self.policy.get_context_range(99, 100) == (-1, 1)


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
