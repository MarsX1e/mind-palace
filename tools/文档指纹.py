# -*- coding: utf-8 -*-
"""
文档指纹（PDF / md / txt 去重）
==============================
不看文件名，只看内容。三层判断，越来越宽松：

1. 字节完全相同       → MD5 相同（同一份文件）
2. 文字完全相同       → 把文字去掉空白/标点/大小写后再算 MD5
                        （同一篇文章从不同来源下载、另存、压缩，字节变了但文字一样）
3. 文字高度相似       → 字数接近 + 文本相似度 ≥ 98%（同一篇但小改了标题/页眉）

扫描版 PDF 提取不出文字，只参与第 1 层判断。

指纹存在 00-影像资料\\索引\\文档指纹.json，避免每次重新提取。

用法：
    python 文档指纹.py             # 只扫描并列出重复
    python 文档指纹.py --执行       # 把重复的移入 00-影像资料\\已删除重复\\文档
"""

import hashlib
import json
import os
import re
import shutil
import sys

脚本目录 = os.path.dirname(os.path.abspath(__file__))
根目录 = os.path.normpath(os.path.join(脚本目录, ".."))
书籍目录 = os.path.join(根目录, "01-书籍扫描", "已OCR")
待OCR目录 = os.path.join(根目录, "01-书籍扫描", "待OCR")
笔记目录 = os.path.join(根目录, "02-笔记")
素材目录 = os.path.join(根目录, "03-素材卡片")
索引目录 = os.path.join(根目录, "00-影像资料", "索引")
回收目录 = os.path.join(根目录, "00-影像资料", "已删除重复", "文档")
指纹文件 = os.path.join(索引目录, "文档指纹.json")

文档扩展名 = {".pdf", ".md", ".txt", ".markdown"}
相似阈值 = 0.98      # 文字相似度达到这个值就认为重复
字数容差 = 0.05      # 字数差异超过 5% 就不做相似比对
相似比对上限 = 20000  # 只比对前 2 万字，保证速度


# ---------------- 文本提取与规范化 ----------------
def 提取文本(路径) -> str:
    扩展 = os.path.splitext(路径)[1].lower()
    if 扩展 == ".pdf":
        try:
            from pypdf import PdfReader
            读 = PdfReader(路径)
            页们 = []
            for i, 页 in enumerate(读.pages):
                if i >= 500:
                    break
                文 = (页.extract_text() or "").strip()
                if 文:
                    页们.append(文)
            return "\n".join(页们)
        except Exception:
            return ""
    try:
        with open(路径, encoding="utf-8", errors="ignore") as f:
            return f.read()
    except Exception:
        return ""


def 规范化(文本: str) -> str:
    """去掉空白、标点、统一小写 —— 这样"排版不同但文字一样"也能识别"""
    if not 文本:
        return ""
    文本 = 文本.lower()
    文本 = re.sub(r"[\s\u3000]+", "", 文本)
    文本 = re.sub(r"[，。；：！？、,.;:!?\"'“”‘’（）()《》〈〉【】\[\]{}…—\-~·|/\\*#+=<>@&%$^`]+", "", 文本)
    return 文本


def 算指纹(路径) -> dict:
    条目 = {"大小": os.path.getsize(路径), "md5": 算文件md5(路径)}
    文本 = 提取文本(路径)
    规范 = 规范化(文本)
    条目["字数"] = len(规范)
    条目["文本md5"] = hashlib.md5(规范.encode()).hexdigest() if 规范 else ""
    条目["预览"] = re.sub(r"\s+", " ", 文本.strip())[:80]
    return 条目


def 算文件md5(路径) -> str:
    哈希 = hashlib.md5()
    with open(路径, "rb") as f:
        while True:
            块 = f.read(1024 * 1024)
            if not 块:
                break
            哈希.update(块)
    return 哈希.hexdigest()


# ---------------- 指纹库 ----------------
def 读指纹() -> dict:
    try:
        with open(指纹文件, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def 存指纹(表: dict):
    os.makedirs(索引目录, exist_ok=True)
    with open(指纹文件, "w", encoding="utf-8") as f:
        json.dump(表, f, ensure_ascii=False, indent=1)


def 扫描文档() -> list:
    结果 = []
    for 目录 in (书籍目录, 待OCR目录, 笔记目录, 素材目录):
        if not os.path.isdir(目录):
            continue
        for 根, _, 文件们 in os.walk(目录):
            if os.path.basename(根) in ("pdf文本缓存", "thumbs"):
                continue
            for 名 in sorted(文件们):
                if os.path.splitext(名)[1].lower() in 文档扩展名:
                    结果.append(os.path.join(根, 名))
    return 结果


def 更新指纹(打印=print) -> dict:
    文件们 = 扫描文档()
    旧表 = 读指纹()
    新表 = {}
    新增 = 0
    for 路径 in 文件们:
        键 = os.path.basename(路径)
        大小 = os.path.getsize(路径)
        旧 = 旧表.get(键)
        if 旧 and 旧.get("大小") == 大小 and 旧.get("路径") == 路径:
            新表[键] = 旧
            continue
        条目 = 算指纹(路径)
        条目["路径"] = 路径
        新表[键] = 条目
        新增 += 1
        打印(f"  已处理 {键}（{条目['字数']} 字）" if 条目["字数"] else f"  已处理 {键}（提取不出文字）")

    存指纹(新表)
    打印(f"文档指纹已更新：共 {len(新表)} 个文档，本次新算 {新增} 个")
    return 新表


# ---------------- 找重复 ----------------
def _相似度(文本甲: str, 文本乙: str) -> float:
    import difflib
    甲, 乙 = 文本甲[:相似比对上限], 文本乙[:相似比对上限]
    return difflib.SequenceMatcher(None, 甲, 乙).ratio()


def 找重复(表=None, 打印=print) -> list:
    """返回 [(保留文件名, [重复文件名...], 依据, 说明)]"""
    if 表 is None:
        表 = 读指纹()
    结果 = []
    已报重复 = set()      # 已被判定为"重复"的文件

    # 第 1 层：字节完全相同
    按md5 = {}
    for 名, 条目 in 表.items():
        按md5.setdefault(条目.get("md5"), []).append(名)
    for 哈希, 名们 in 按md5.items():
        if len(名们) > 1:
            名们 = sorted(名们)
            结果.append((名们[0], 名们[1:], "完全相同", "文件字节完全一致"))
            已报重复.update(名们[1:])

    # 第 2 层：文字完全相同（跨字节组 —— 重新下载/另存/换排版都能抓到）
    按文本 = {}
    for 名, 条目 in 表.items():
        if 条目.get("文本md5"):
            按文本.setdefault(条目["文本md5"], []).append(名)
    for 哈希, 名们 in 按文本.items():
        未报 = [n for n in 名们 if n not in 已报重复]
        if len(名们) > 1 and len(未报) > 1:
            未报 = sorted(未报)
            结果.append((未报[0], 未报[1:], "文字相同", "文字内容完全一致（排版或来源不同）"))
            已报重复.update(未报[1:])

    # 第 3 层：文字高度相似（同一篇但小改过标题/页眉）
    剩余 = [(名, 条目) for 名, 条目 in 表.items()
            if 名 not in 已报重复 and 条目.get("字数", 0) > 200]
    for i, (名甲, 甲) in enumerate(剩余):
        if 名甲 in 已报重复:
            continue
        文本甲 = 规范化(提取文本(甲.get("路径") or os.path.join(文件所在目录(名甲), 名甲)))
        if not 文本甲:
            continue
        for 名乙, 乙 in 剩余[i + 1:]:
            if 名乙 in 已报重复:
                continue
            字数甲, 字数乙 = 甲["字数"], 乙["字数"]
            if abs(字数甲 - 字数乙) / max(字数甲, 字数乙) > 字数容差:
                continue
            文本乙 = 规范化(提取文本(乙.get("路径") or os.path.join(文件所在目录(名乙), 名乙)))
            if not 文本乙:
                continue
            比值 = _相似度(文本甲, 文本乙)
            if 比值 >= 相似阈值:
                结果.append((名甲, [名乙], "高度相似", f"文字相似度 {比值:.1%}"))
                已报重复.add(名乙)
    return 结果


def 文件所在目录(名: str) -> str:
    for 目录 in (书籍目录, 待OCR目录, 笔记目录, 素材目录):
        if os.path.exists(os.path.join(目录, 名)):
            return 目录
    return 书籍目录


def 移到回收站(名: str) -> bool:
    源 = os.path.join(文件所在目录(名), 名)
    if not os.path.isfile(源):
        return False
    os.makedirs(回收目录, exist_ok=True)
    目标 = os.path.join(回收目录, 名)
    序号 = 1
    while os.path.exists(目标):
        主干, 扩展 = os.path.splitext(名)
        目标 = os.path.join(回收目录, f"{主干}_重复{序号}{扩展}")
        序号 += 1
    shutil.move(源, 目标)
    return True


def 主流程():
    执行 = "--执行" in sys.argv
    print("=" * 66)
    print("  文档去重（按内容比对，不看文件名）")
    print("=" * 66)
    print("\n[1/2] 更新文档指纹（首次需要提取所有文档的文字）…")
    表 = 更新指纹(打印=print)

    print("\n[2/2] 查找重复…")
    组 = 找重复(表)
    if not 组:
        print("\n没有发现重复文档")
        return

    总重复 = sum(len(重) for _, 重, _, _ in 组)
    print(f"\n发现 {len(组)} 组重复，共 {总重复} 个多余文档：\n")
    for 保留, 重复们, 依据, 说明 in 组:
        print(f"  保留：{保留}")
        print(f"    （依据：{依据} —— {说明}）")
        for 名 in 重复们:
            print(f"      重复 → {名}")

    if not 执行:
        print(f"\n确认无误后执行清理：python 文档指纹.py --执行")
        print(f"（重复文档会被移到 {回收目录}，可随时恢复）")
        return

    print("\n开始移动…")
    移动 = 0
    for 保留, 重复们, _, _ in 组:
        for 名 in 重复们:
            if 移到回收站(名):
                移动 += 1
    print(f"已移动 {移动} 个文档到 {回收目录}")
    print("正在刷新指纹库…")
    更新指纹(打印=print)


if __name__ == "__main__":
    主流程()
