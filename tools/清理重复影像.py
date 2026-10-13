# -*- coding: utf-8 -*-
"""
清理重复影像
============
扫描照片和视频，找出重复的（内容完全相同，或同一张图被压缩/改尺寸过），
把它们移到 00-影像资料\\已删除重复\\ 文件夹（不会真的删除，随时能恢复）。

用法：
    python 清理重复影像.py           只扫描并列出结果，不动任何文件
    python 清理重复影像.py --执行     确认无误后执行，把重复项移入回收文件夹
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import 影像指纹 as 指纹            # noqa: E402


def 主流程():
    执行 = "--执行" in sys.argv

    print("=" * 60)
    print("  影像去重扫描")
    print("=" * 60)
    print("\n[1/2] 更新指纹库（首次运行需要读完所有文件，请稍候）…")
    表 = 指纹.更新指纹()

    print("\n[2/2] 查找重复…")
    组 = 指纹.找重复(表)
    if not 组:
        print("\n✅ 没有发现重复的影像")
        return

    总重复数 = sum(len(重复) for _, 重复 in 组)
    print(f"\n发现 {len(组)} 组重复，共 {总重复数} 个多余文件：\n")
    for 保留, 重复们 in 组:
        print(f"  保留：{保留}")
        for 名 in 重复们:
            print(f"    重复 → {名}")
    print(f"\n要清理的话，运行：python 清理重复影像.py --执行")
    print(f"（重复文件会被移到：{指纹.回收目录}）")

    if not 执行:
        return

    print("\n开始移动重复文件…")
    成功 = 0
    for 保留, 重复们 in 组:
        for 名 in 重复们:
            类别 = "照片" if os.path.splitext(名)[1].lower() in 指纹.图片扩展名 else "视频"
            if 指纹.移到回收站(名, 类别):
                成功 += 1
    print(f"√ 已移动 {成功} 个文件到 {指纹.回收目录}")
    print("  确认没问题后可以手动清空该文件夹；发现误判就把它移回来。")
    print("\n正在刷新指纹库…")
    指纹.更新指纹()


if __name__ == "__main__":
    主流程()
