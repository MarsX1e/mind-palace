# -*- coding: utf-8 -*-
"""
视频描述管理工具
================
1. 扫描 00-影像资料\视频原图 里的所有视频文件
2. 维护 索引\视频描述.txt：每个视频一行，格式  文件名|你的描述
   （文件已预填好所有视频名，你只需在 | 后面写描述）
3. 运行本脚本会报告：
   - 共多少个视频、已描述多少、未描述多少
   - 未描述的视频清单（方便你逐个补写）
   - 生成 索引\视频描述汇总.md，供 影像建索引.py 并入《影像总目录》

用法：python 视频描述管理.py
"""

import os
import re

脚本目录 = os.path.dirname(os.path.abspath(__file__))
视频目录 = os.path.normpath(os.path.join(脚本目录, "..", "00-影像资料", "视频原图"))
索引目录 = os.path.normpath(os.path.join(脚本目录, "..", "00-影像资料", "索引"))
描述文件 = os.path.join(索引目录, "视频描述.txt")
汇总文件 = os.path.join(索引目录, "视频描述汇总.md")

视频扩展名 = {".mp4", ".mov", ".m4v", ".3gp", ".avi", ".mkv"}


def 扫描所有视频():
    视频列表 = []
    for 目录路径, _, 文件名列表 in os.walk(视频目录):
        for 文件名 in 文件名列表:
            if os.path.splitext(文件名)[1].lower() in 视频扩展名:
                视频列表.append(文件名)
    return sorted(视频列表)


def 读取描述():
    """解析 视频描述.txt → {文件名: 描述}；忽略空行和 # 注释行"""
    描述 = {}
    不存在的文件名 = []
    if not os.path.exists(描述文件):
        return 描述, 不存在的文件名
    with open(描述文件, encoding="utf-8") as f:
        for 行号, 行 in enumerate(f, 1):
            行 = 行.strip()
            if not 行 or 行.startswith("#"):
                continue
            if "|" not in 行:
                print(f"  ⚠ 第{行号}行格式不对（缺少 | ）：{行}")
                continue
            文件名, _, 内容 = 行.partition("|")
            文件名, 内容 = 文件名.strip(), 内容.strip()
            if 文件名:
                描述[文件名] = 内容
    return 描述, 不存在的文件名


def 主流程():
    os.makedirs(索引目录, exist_ok=True)
    所有视频 = 扫描所有视频()
    if not os.path.exists(描述文件):
        # 首次运行：生成预填好文件名的模板
        with open(描述文件, "w", encoding="utf-8") as f:
            f.write("# 视频描述文件\n")
            f.write("# 格式：文件名|你的描述（每行一个；# 开头是注释）\n")
            f.write("# 写描述小技巧：地点+景物/事件，如：新疆喀什老城，傍晚街巷\n")
            f.write("# 写完保存后，运行本脚本可查看还有哪些视频没描述\n\n")
            for 名 in 所有视频:
                f.write(f"{名}|\n")
        print(f"已创建 {描述文件}")
        print("请在每个视频名后面的 | 后面写上描述，保存后再运行本脚本。\n")

    描述, _ = 读取描述()
    未描述 = [名 for 名 in 所有视频 if not 描述.get(名)]
    已描述数 = len(所有视频) - len(未描述)
    # 检查描述文件里有没有写错名字（对不上真实文件）
    写错的 = [名 for 名 in 描述 if 名 not in 所有视频]

    print(f"视频总数：{len(所有视频)}")
    print(f"已描述：{已描述数}   未描述：{len(未描述)}")
    if 写错的:
        print(f"\n⚠ 描述文件里有 {len(写错的)} 个名字对不上实际视频（可能是文件名打错了）：")
        for 名 in 写错的:
            print(f"  - {名}")
    if 未描述:
        print(f"\n===== 未描述的视频清单（{len(未描述)} 个）=====")
        for 名 in 未描述:
            print(f"  {名}")

    # 生成汇总 md（供 AnythingLLM 检索）
    with open(汇总文件, "w", encoding="utf-8") as f:
        f.write("# 视频描述汇总（用户手工填写）\n\n")
        for 名 in 所有视频:
            内容 = 描述.get(名, "").strip()
            if 内容:
                f.write(f"- {名}：{内容}\n")
            else:
                f.write(f"- {名}：（暂无描述）\n")
    print(f"\n汇总已更新：{汇总文件}")


if __name__ == "__main__":
    主流程()
