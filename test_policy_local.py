#!/usr/bin/env python3
"""
本地 Policy 测试脚本

1. 修改 test_policy_config.yaml 配置文件
2. 运行: python test_policy_local.py
"""
import json
import logging
import os
import sys

import requests
import yaml

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'lambda'))

CONFIG_FILE = 'test_policy_config.yaml'

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.FileHandler('log.log'), logging.StreamHandler()]
)
logger = logging.getLogger(__name__)


def load_config() -> dict:
    """加载 YAML 配置文件"""
    if not os.path.exists(CONFIG_FILE):
        print(f"❌ 配置文件不存在: {CONFIG_FILE}")
        print("   请创建配置文件或复制 test_policy_config.yaml.example")
        sys.exit(1)
    
    with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)
    
    return {
        'policy': config.get('policy', 'drinking_detection'),
        'region': config.get('region', 'us-east-1'),
        'prev_count': config.get('prev_count', 1),
        'next_count': config.get('next_count', 1),
        'step': config.get('step', 1),
        'images': config.get('images') or [],
    }


def load_image(source: str) -> bytes:
    """加载图片，支持本地路径和 URL"""
    if source.startswith('http://') or source.startswith('https://'):
        resp = requests.get(source, timeout=30)
        resp.raise_for_status()
        return resp.content
    else:
        with open(source, 'rb') as f:
            return f.read()


def get_policy(name: str):
    """获取 policy 实例"""
    from policies.drinking_detection_policy import DrinkingDetectionPolicy
    from policies.person_appearance_policy import PersonAppearancePolicy
    from policies.streamer_behavior_policy import StreamerBehaviorPolicy
    from policies.streamer_behavior_v2_policy import StreamerBehaviorV2Policy
    from policies.stream_quality_policy import StreamQualityPolicy
    policies = {
        'drinking_detection': DrinkingDetectionPolicy,
        'person_appearance': PersonAppearancePolicy,
        'streamer_behavior': StreamerBehaviorPolicy,
        'streamer_behavior_v2': StreamerBehaviorV2Policy,
        'stream_quality': StreamQualityPolicy,
    }
    if name not in policies:
        raise ValueError(f"Unknown policy: {name}. Available: {list(policies.keys())}")
    return policies[name]()


def main():
    # 加载配置
    config = load_config()
    images = config['images']
    prev_count = config['prev_count']
    next_count = config['next_count']
    step = config['step']
    
    if not images:
        print(f"❌ 请在 {CONFIG_FILE} 的 images 列表中添加要测试的图片")
        return
    
    # 加载所有图片
    print(f"\n📷 加载 {len(images)} 张图片...")
    image_data = []
    for i, src in enumerate(images):
        data = load_image(src)
        image_data.append(data)
        print(f"   [{i}] {src} ({len(data)} bytes)")
    
    # 初始化
    from shared.bedrock_client import BedrockClient
    policy = get_policy(config['policy'])
    bedrock = BedrockClient()
    print(f"\n🔧 Policy: {policy.get_name()}")
    print(f"   prev_count: {prev_count}, next_count: {next_count}, step: {step}")
    
    # 滑动窗口处理
    results = []
    total = len(image_data)
    
    # target 从 prev_count 开始，到 total-next_count 结束，确保窗口不越界
    start_idx = prev_count
    end_idx = total - next_count if next_count > 0 else total
    
    for target_idx in range(start_idx, end_idx, step):
        print(f"\n{'='*50}")
        print(f"🎯 分析帧 [{target_idx}]: {images[target_idx]}")
        
        # 构建 target frame
        target_frame = {
            'index': target_idx,
            'url': images[target_idx],
            'data': image_data[target_idx]
        }
        
        # 构建 context frames (prev 和 next)
        context_frames = []
        
        # 添加前面的帧
        for i in range(prev_count, 0, -1):
            ctx_idx = target_idx - i
            if 0 <= ctx_idx < total:
                context_frames.append({
                    'index': ctx_idx,
                    'url': images[ctx_idx],
                    'data': image_data[ctx_idx]
                })
                print(f"   prev: [{ctx_idx}] {images[ctx_idx]}")
        
        # 添加后面的帧
        for i in range(1, next_count + 1):
            ctx_idx = target_idx + i
            if 0 <= ctx_idx < total:
                context_frames.append({
                    'index': ctx_idx,
                    'url': images[ctx_idx],
                    'data': image_data[ctx_idx]
                })
                print(f"   next: [{ctx_idx}] {images[ctx_idx]}")
        
        # 调用 policy
        print(f"   🔍 调用 Bedrock...")
        result = policy.analyze(
            target_frame=target_frame,
            context_frames=context_frames,
            bedrock_client=bedrock,
            storage_helper=None
        )
        
        results.append({'frame_index': target_idx, 'source': images[target_idx], **result})
        
        # 输出结果
        print(f"\n   📊 结果:")
        for k, v in result.items():
            print(f"      {k}: {v}")
    
    # 汇总
    print(f"\n{'='*50}")
    print(f"📋 完成，共分析 {len(results)} 帧")


if __name__ == '__main__':
    main()
