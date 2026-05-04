#!/usr/bin/env python3
"""测试 Playwright Gemini 封面生成"""

import asyncio
import sys
from pathlib import Path

# 添加 backend 到路径
sys.path.insert(0, '/home/zzgzczq/12-video/01-auto-video-studio/web/backend')

from services.social_ai_cover_playwright import generate_ai_cover_playwright


def test_gemini_cover():
    """测试 Gemini 封面生成"""
    print("="*60)
    print("测试 Playwright Gemini 封面生成")
    print("="*60)
    print()

    job_id = "test_job_001"
    title = "美丽的日落风景"
    description = "展示壮观的日落场景"

    print(f"任务 ID: {job_id}")
    print(f"标题: {title}")
    print(f"描述: {description}")
    print()
    print("开始生成...")
    print("-"*60)

    try:
        result = generate_ai_cover_playwright(
            job_id=job_id,
            title=title,
            description=description,
            platforms=["gemini"],
        )

        print()
        print("="*60)
        print("测试结果:")
        print("="*60)
        print(f"状态: {result.get('status')}")
        print(f"提示词: {result.get('prompt')}")
        print(f"生成图片数量: {len(result.get('images', []))}")

        if result.get('images'):
            for img in result['images']:
                print(f"  - {img.get('filename')} ({img.get('platform')})")
            print("\n✓ 测试成功!")
        else:
            print("\n✗ 测试失败 - 没有生成图片")

        return result

    except Exception as e:
        print(f"\n✗ 测试出错: {e}")
        import traceback
        traceback.print_exc()
        return None


if __name__ == "__main__":
    # 清理旧文件
    test_dirs = [
        Path("/tmp/test_output"),
        Path("/tmp/test_downloads"),
    ]
    for d in test_dirs:
        d.mkdir(exist_ok=True)

    # 运行测试
    result = test_gemini_cover()

    # 检查结果
    if result and result.get('images'):
        print("\n" + "="*60)
        print("所有测试通过!")
        print("="*60)
        sys.exit(0)
    else:
        print("\n" + "="*60)
        print("测试失败，请检查日志")
        print("="*60)
        sys.exit(1)
