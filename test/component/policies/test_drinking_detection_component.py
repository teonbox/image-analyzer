"""
Layer 2: DrinkingDetectionPolicy 组件测试
使用真实 Bedrock 服务
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../../lambda'))

import pytest
import boto3
from policies.drinking_detection_policy import DrinkingDetectionPolicy
from shared.bedrock_client import BedrockClient


@pytest.mark.bedrock
class TestDrinkingDetectionPolicyComponent:
    """Layer 2: 组件测试 - 使用真实 Bedrock"""
    
    def setup_method(self):
        self.policy = DrinkingDetectionPolicy()
        self.bedrock_client = BedrockClient()
        self.fixtures_dir = os.path.join(os.path.dirname(__file__), '../../fixtures/drinking-detection')
    
    def load_image(self, path):
        """加载图片数据"""
        with open(path, 'rb') as f:
            return f.read()
    
    # ========== 正在喝东西场景 ==========
    
    def test_drink_comp_001_drinking_with_context(self):
        """DRINK-COMP-001: 正在喝东西 + 有前后帧"""
        target_frame = {
            'index': 1,
            'key': 'drinking/image2.jpg',
            'data': self.load_image(f'{self.fixtures_dir}/drinking/image2.jpg')
        }
        context_frames = [
            {'index': 0, 'key': 'drinking/image1.jpg', 'data': self.load_image(f'{self.fixtures_dir}/drinking/image1.jpg')},
            target_frame,
            {'index': 2, 'key': 'drinking/image3.jpg', 'data': self.load_image(f'{self.fixtures_dir}/drinking/image3.jpg')}
        ]
        
        result = self.policy.analyze(target_frame, context_frames, self.bedrock_client, None)
        
        # 验证业务逻辑
        assert result['drinking_is_drinking'] == True, f"应该检测到正在喝东西，但结果是 {result['drinking_is_drinking']}"
        assert result['drinking_confidence'] > 0.8, f"置信度应该 > 0.8，但实际是 {result['drinking_confidence']}"
        assert len(result['drinking_details']) > 0
        print(f"\n结果: {result}")
    
    def test_drink_comp_002_drinking_only_prev_frame(self):
        """DRINK-COMP-002: 正在喝东西 + 只有前帧无后帧"""
        target_frame = {'index': 2, 'key': 'drinking/image3.jpg', 'data': self.load_image(f'{self.fixtures_dir}/drinking/image3.jpg')}
        context_frames = [
            {'index': 1, 'key': 'drinking/image2.jpg', 'data': self.load_image(f'{self.fixtures_dir}/drinking/image2.jpg')},
            target_frame
        ]
        
        result = self.policy.analyze(target_frame, context_frames, self.bedrock_client, None)
        assert result['drinking_is_drinking'] == True
        assert result['drinking_confidence'] > 0.7
        print(f"\n结果: {result}")
    
    def test_drink_comp_003_drinking_only_next_frame(self):
        """DRINK-COMP-003: 正在喝东西 + 只有后帧无前帧"""
        target_frame = {'index': 0, 'key': 'drinking/image1.jpg', 'data': self.load_image(f'{self.fixtures_dir}/drinking/image1.jpg')}
        context_frames = [
            target_frame,
            {'index': 1, 'key': 'drinking/image2.jpg', 'data': self.load_image(f'{self.fixtures_dir}/drinking/image2.jpg')}
        ]
        
        result = self.policy.analyze(target_frame, context_frames, self.bedrock_client, None)
        assert result['drinking_is_drinking'] == True
        assert result['drinking_confidence'] > 0.7
        print(f"\n结果: {result}")
    
    def test_drink_comp_004_drinking_missing_adjacent_frame(self):
        """DRINK-COMP-004: 正在喝东西 + 相邻帧丢失"""
        target_frame = {'index': 1, 'key': 'drinking/image2.jpg', 'data': self.load_image(f'{self.fixtures_dir}/drinking/image2.jpg')}
        context_frames = [
            target_frame,
            {'index': 2, 'key': 'drinking/image3.jpg', 'data': self.load_image(f'{self.fixtures_dir}/drinking/image3.jpg')}
        ]
        
        result = self.policy.analyze(target_frame, context_frames, self.bedrock_client, None)
        assert result['drinking_is_drinking'] == True
        assert result['drinking_confidence'] > 0.6
        print(f"\n结果: {result}")
    
    def test_drink_comp_005_drinking_isolated_frame(self):
        """DRINK-COMP-005: 正在喝东西 + 孤立帧"""
        target_frame = {'index': 0, 'key': 'drinking/image2.jpg', 'data': self.load_image(f'{self.fixtures_dir}/drinking/image2.jpg')}
        context_frames = [target_frame]
        
        result = self.policy.analyze(target_frame, context_frames, self.bedrock_client, None)
        # 孤立帧可能无法准确判断
        assert isinstance(result['drinking_is_drinking'], bool)
        assert 0 <= result['drinking_confidence'] <= 1
        print(f"\n结果: {result}")
    
    # ========== 拿着饮品但不在喝场景 ==========
    
    def test_drink_comp_006_holding_with_context(self):
        """DRINK-COMP-006: 拿着饮品不在喝 + 有前后帧"""
        target_frame = {'index': 1, 'key': 'holding/image2.jpg', 'data': self.load_image(f'{self.fixtures_dir}/holding/image2.jpg')}
        context_frames = [
            {'index': 0, 'key': 'holding/image1.jpg', 'data': self.load_image(f'{self.fixtures_dir}/holding/image1.jpg')},
            target_frame,
            {'index': 2, 'key': 'holding/image3.jpg', 'data': self.load_image(f'{self.fixtures_dir}/holding/image3.jpg')}
        ]
        
        result = self.policy.analyze(target_frame, context_frames, self.bedrock_client, None)
        assert result['drinking_is_drinking'] == False, f"不应该检测到喝东西，但结果是 {result['drinking_is_drinking']}"
        assert result['drinking_confidence'] > 0.8
        print(f"\n结果: {result}")
    
    def test_drink_comp_007_holding_only_prev_frame(self):
        """DRINK-COMP-007: 拿着饮品不在喝 + 只有前帧无后帧"""
        target_frame = {'index': 2, 'key': 'holding/image3.jpg', 'data': self.load_image(f'{self.fixtures_dir}/holding/image3.jpg')}
        context_frames = [
            {'index': 1, 'key': 'holding/image2.jpg', 'data': self.load_image(f'{self.fixtures_dir}/holding/image2.jpg')},
            target_frame
        ]
        
        result = self.policy.analyze(target_frame, context_frames, self.bedrock_client, None)
        assert result['drinking_is_drinking'] == False
        print(f"\n结果: {result}")
    
    def test_drink_comp_008_holding_only_next_frame(self):
        """DRINK-COMP-008: 拿着饮品不在喝 + 只有后帧无前帧"""
        target_frame = {'index': 0, 'key': 'holding/image1.jpg', 'data': self.load_image(f'{self.fixtures_dir}/holding/image1.jpg')}
        context_frames = [
            target_frame,
            {'index': 1, 'key': 'holding/image2.jpg', 'data': self.load_image(f'{self.fixtures_dir}/holding/image2.jpg')}
        ]
        
        result = self.policy.analyze(target_frame, context_frames, self.bedrock_client, None)
        assert result['drinking_is_drinking'] == False
        print(f"\n结果: {result}")
    
    def test_drink_comp_009_holding_missing_adjacent_frame(self):
        """DRINK-COMP-009: 拿着饮品不在喝 + 相邻帧丢失"""
        target_frame = {'index': 1, 'key': 'holding/image2.jpg', 'data': self.load_image(f'{self.fixtures_dir}/holding/image2.jpg')}
        context_frames = [
            target_frame,
            {'index': 2, 'key': 'holding/image3.jpg', 'data': self.load_image(f'{self.fixtures_dir}/holding/image3.jpg')}
        ]
        
        result = self.policy.analyze(target_frame, context_frames, self.bedrock_client, None)
        assert result['drinking_is_drinking'] == False
        print(f"\n结果: {result}")
    
    def test_drink_comp_010_holding_isolated_frame(self):
        """DRINK-COMP-010: 拿着饮品不在喝 + 孤立帧"""
        target_frame = {'index': 0, 'key': 'holding/image2.jpg', 'data': self.load_image(f'{self.fixtures_dir}/holding/image2.jpg')}
        context_frames = [target_frame]
        
        result = self.policy.analyze(target_frame, context_frames, self.bedrock_client, None)
        assert isinstance(result['drinking_is_drinking'], bool)
        print(f"\n结果: {result}")
    
    # ========== 完全没在喝东西场景 ==========
    
    def test_drink_comp_011_no_drinking_with_context(self):
        """DRINK-COMP-011: 完全没在喝东西 + 有前后帧"""
        target_frame = {'index': 1, 'key': 'no-drinking/image2.jpg', 'data': self.load_image(f'{self.fixtures_dir}/no-drinking/image2.jpg')}
        context_frames = [
            {'index': 0, 'key': 'no-drinking/image1.jpg', 'data': self.load_image(f'{self.fixtures_dir}/no-drinking/image1.jpg')},
            target_frame,
            {'index': 2, 'key': 'no-drinking/image3.jpg', 'data': self.load_image(f'{self.fixtures_dir}/no-drinking/image3.jpg')}
        ]
        
        result = self.policy.analyze(target_frame, context_frames, self.bedrock_client, None)
        assert result['drinking_is_drinking'] == False
        assert result['drinking_confidence'] >= 0.9
        print(f"\n结果: {result}")
    
    def test_drink_comp_012_no_drinking_only_prev_frame(self):
        """DRINK-COMP-012: 完全没在喝东西 + 只有前帧无后帧"""
        target_frame = {'index': 2, 'key': 'no-drinking/image3.jpg', 'data': self.load_image(f'{self.fixtures_dir}/no-drinking/image3.jpg')}
        context_frames = [
            {'index': 1, 'key': 'no-drinking/image2.jpg', 'data': self.load_image(f'{self.fixtures_dir}/no-drinking/image2.jpg')},
            target_frame
        ]
        
        result = self.policy.analyze(target_frame, context_frames, self.bedrock_client, None)
        assert result['drinking_is_drinking'] == False
        print(f"\n结果: {result}")
    
    def test_drink_comp_013_no_drinking_only_next_frame(self):
        """DRINK-COMP-013: 完全没在喝东西 + 只有后帧无前帧"""
        target_frame = {'index': 0, 'key': 'no-drinking/image1.jpg', 'data': self.load_image(f'{self.fixtures_dir}/no-drinking/image1.jpg')}
        context_frames = [
            target_frame,
            {'index': 1, 'key': 'no-drinking/image2.jpg', 'data': self.load_image(f'{self.fixtures_dir}/no-drinking/image2.jpg')}
        ]
        
        result = self.policy.analyze(target_frame, context_frames, self.bedrock_client, None)
        assert result['drinking_is_drinking'] == False
        print(f"\n结果: {result}")
    
    def test_drink_comp_014_no_drinking_missing_adjacent_frame(self):
        """DRINK-COMP-014: 完全没在喝东西 + 相邻帧丢失"""
        target_frame = {'index': 1, 'key': 'no-drinking/image2.jpg', 'data': self.load_image(f'{self.fixtures_dir}/no-drinking/image2.jpg')}
        context_frames = [
            target_frame,
            {'index': 2, 'key': 'no-drinking/image3.jpg', 'data': self.load_image(f'{self.fixtures_dir}/no-drinking/image3.jpg')}
        ]
        
        result = self.policy.analyze(target_frame, context_frames, self.bedrock_client, None)
        assert result['drinking_is_drinking'] == False
        print(f"\n结果: {result}")
    
    def test_drink_comp_015_no_drinking_isolated_frame(self):
        """DRINK-COMP-015: 完全没在喝东西 + 孤立帧"""
        target_frame = {'index': 0, 'key': 'no-drinking/image2.jpg', 'data': self.load_image(f'{self.fixtures_dir}/no-drinking/image2.jpg')}
        context_frames = [target_frame]
        
        result = self.policy.analyze(target_frame, context_frames, self.bedrock_client, None)
        assert isinstance(result['drinking_is_drinking'], bool)
        print(f"\n结果: {result}")


if __name__ == '__main__':
    pytest.main([__file__, '-v', '-s', '-m', 'bedrock'])
