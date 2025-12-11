"""
Request Handler Layer 1 单元测试
测试目标：验证 validate_request_input() 参数验证逻辑
"""
import pytest
import sys
import os

# 添加 lambda 目录到路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../../lambda'))

from handlers.request_handler import validate_request_input


class TestParameterValidation:
    """1.1 参数验证测试"""
    
    def test_req_001_missing_name_field(self):
        """REQ-001: 缺少必需字段 - name
        测试目标: validate_request_input()
        """
        body = {
            "type": "s3",
            "bucket": "my-bucket",
            "region": "us-east-1",
            "callback_url": "https://example.com/callback"
        }
        
        is_valid, error_msg = validate_request_input(body)
        
        assert is_valid is False
        assert error_msg == "Missing required field: name"
    
    def test_req_002_missing_callback_url_field(self):
        """REQ-002: 缺少必需字段 - callback_url
        测试目标: validate_request_input()
        """
        body = {
            "type": "s3",
            "bucket": "my-bucket",
            "region": "us-east-1",
            "name": "test-video"
        }
        
        is_valid, error_msg = validate_request_input(body)
        
        assert is_valid is False
        assert error_msg == "Missing required field: callback_url"
    
    def test_req_003_invalid_storage_type(self):
        """REQ-003: 无效的存储类型
        测试目标: validate_request_input()
        """
        body = {
            "type": "invalid_type",
            "name": "test",
            "callback_url": "https://example.com/callback"
        }
        
        is_valid, error_msg = validate_request_input(body)
        
        assert is_valid is False
        assert "Invalid type: invalid_type" in error_msg
        assert "Must be s3, oss, or http" in error_msg
    
    def test_req_004_s3_type_missing_bucket(self):
        """REQ-004: S3 类型缺少 bucket
        测试目标: validate_request_input()
        """
        body = {
            "type": "s3",
            "region": "us-east-1",
            "name": "test-video",
            "callback_url": "https://example.com/callback"
        }
        
        is_valid, error_msg = validate_request_input(body)
        
        assert is_valid is False
        assert "bucket" in error_msg.lower()
    
    def test_req_005_s3_type_missing_region(self):
        """REQ-005: S3 类型缺少 region
        测试目标: validate_request_input()
        """
        body = {
            "type": "s3",
            "bucket": "my-bucket",
            "name": "test-video",
            "callback_url": "https://example.com/callback"
        }
        
        is_valid, error_msg = validate_request_input(body)
        
        assert is_valid is False
        assert "region" in error_msg.lower()
    
    def test_req_006_http_type_missing_urls(self):
        """REQ-006: http 类型缺少 urls
        测试目标: validate_request_input()
        """
        body = {
            "type": "http",
            "name": "test-video",
            "callback_url": "https://example.com/callback"
        }
        
        is_valid, error_msg = validate_request_input(body)
        
        assert is_valid is False
        assert "urls" in error_msg.lower()
    
    def test_req_007_http_type_empty_urls(self):
        """REQ-007: http 类型 urls 为空数组
        测试目标: validate_request_input()
        """
        body = {
            "type": "http",
            "urls": [],
            "name": "test-video",
            "callback_url": "https://example.com/callback"
        }
        
        is_valid, error_msg = validate_request_input(body)
        
        assert is_valid is False
        assert "empty" in error_msg.lower() or "urls" in error_msg.lower()
    
    def test_req_008_valid_s3_request(self):
        """REQ-008: 有效的 S3 请求参数
        测试目标: validate_request_input()
        """
        body = {
            "type": "s3",
            "bucket": "my-bucket",
            "region": "ap-northeast-2",
            "name": "test-video",
            "callback_url": "https://example.com/callback"
        }
        
        is_valid, error_msg = validate_request_input(body)
        
        assert is_valid is True
        assert error_msg is None
    
    def test_req_009_valid_http_request(self):
        """REQ-009: 有效的 http 请求参数
        测试目标: validate_request_input()
        """
        body = {
            "type": "http",
            "urls": [
                "https://example.com/frame-1.jpg",
                "https://example.com/frame-2.jpg"
            ],
            "name": "test-video",
            "callback_url": "https://example.com/callback"
        }
        
        is_valid, error_msg = validate_request_input(body)
        
        assert is_valid is True
        assert error_msg is None
    
    def test_req_010_oss_type_missing_bucket(self):
        """REQ-010: OSS 类型缺少 bucket
        测试目标: validate_request_input()
        """
        body = {
            "type": "oss",
            "endpoint": "oss-cn-hangzhou.aliyuncs.com",
            "name": "test-video",
            "callback_url": "https://example.com/callback"
        }
        
        is_valid, error_msg = validate_request_input(body)
        
        assert is_valid is False
        assert "bucket" in error_msg.lower()
    
    def test_req_011_oss_type_missing_endpoint(self):
        """REQ-011: OSS 类型缺少 endpoint
        测试目标: validate_request_input()
        """
        body = {
            "type": "oss",
            "bucket": "my-bucket",
            "name": "test-video",
            "callback_url": "https://example.com/callback"
        }
        
        is_valid, error_msg = validate_request_input(body)
        
        assert is_valid is False
        assert "endpoint" in error_msg.lower()
    
    def test_req_012_valid_oss_request(self):
        """REQ-012: 有效的 OSS 请求参数
        测试目标: validate_request_input()
        """
        body = {
            "type": "oss",
            "bucket": "my-bucket",
            "endpoint": "oss-cn-hangzhou.aliyuncs.com",
            "name": "test-video",
            "callback_url": "https://example.com/callback"
        }
        
        is_valid, error_msg = validate_request_input(body)
        
        assert is_valid is True
        assert error_msg is None


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
