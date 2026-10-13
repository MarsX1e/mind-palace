# -*- coding: utf-8 -*-
"""
影像指纹模块（去重核心）
========================
给照片/视频算指纹，用于找出重复文件：
- md5   ：文件字节指纹 → 找出"完全相同的文件"（可靠）
- dhash ：图片感知指纹 → 找出"同一张图但被压缩/改过尺寸"的近似重复

为避免误判，近似重复还要求：
- 两张图都不是"低细节图"（纯色、大片留白、夜景等，dhash 位太少不可信）
- 两张图长宽比接近（差 ≤ 8%）

指纹存在 00-影像资料\\索引\\影像指纹.json（含版本号，规则升级后自动重算）。
"""

import hashlib
import json
import os

脚本目录 = os.path.dirname(os.path.abspath(__file__))
根目录 = os.path.normpath(os.path.join(脚本目录, ".."))
照片目录 = os.path.join(根目录, "00-影像资料", "照片原图")
视频目录 = os.path.join(根目录, "00-影像资料", "视频原图")
索引目录 = os.path.join(根目录, "00-影像资料", "索引")
回收目录 = os.path.join(根目录, "00-影像资料", "已删除重复")
指纹文件 = os.path.join(索引目录, "影像指纹.json")

图片扩展名 = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
视频扩展名 = {".mp4", ".mov", ".m4v", ".3gp", ".avi", ".mkv"}

当前版本 = 2
近似阈值 = 5        # dhash 汉明距离 ≤ 该值才算"同一张图"（0-64）
最少细节位 = 8      # dhash 至少要有这么多位为 1，否则图片太"平"，不参与近似比对
长宽比容差 = 0.08   # 长宽比差异超过 8% 就不算同一张图


# ---------------- 基础指纹 ----------------
def 算md5(路径):
    哈希 = hashlib.md5()
    with open(路径, "rb") as f:
        while True:
            块 = f.read(1024 * 1024)
            if not 块:
                break
            哈希.update(块)
    return 哈希.hexdigest()


def 算md5字节(数据):
    return hashlib.md5(数据).hexdigest()


def _dhash图(图, 尺寸=9):
    图 = 图.convert("L").resize((尺寸, 尺寸))
    像素 = list(图.getdata())
    位 = 0
    for 行 in range(尺寸 - 1):
        for 列 in range(尺寸 - 1):
            左 = 像素[行 * 尺寸 + 列]
            右 = 像素[行 * 尺寸 + 列 + 1]
            位 = (位 << 1) | (1 if 左 > 右 else 0)
    return f"{位:016x}"


def 细节位数(dhash):
    try:
        return bin(int(dhash, 16)).count("1")
    except Exception:
        return 0


def 距离(指纹一, 指纹二):
    try:
        return bin(int(指纹一, 16) ^ int(指纹二, 16)).count("1")
    except Exception:
        return 64


# ---------------- 单个文件/字节的指纹 ----------------
def 图片指纹(路径):
    条目 = {"版本": 当前版本, "大小": os.path.getsize(路径), "md5": 算md5(路径)}
    try:
        from PIL import Image
        with Image.open(路径) as 图:
            宽, 高 = 图.size
            条目["dhash"] = _dhash图(图)
            条目["宽"], 条目["高"] = 宽, 高
    except Exception:
        pass
    return 条目


def 图片指纹字节(数据):
    条目 = {"版本": 当前版本, "大小": len(数据), "md5": 算md5字节(数据)}
    try:
        import io
        from PIL import Image
        with Image.open(io.BytesIO(数据)) as 图:
            宽, 高 = 图.size
            条目["dhash"] = _dhash图(图)
            条目["宽"], 条目["高"] = 宽, 高
    except Exception:
        pass
    return 条目


def 视频指纹(路径):
    return {"版本": 当前版本, "大小": os.path.getsize(路径), "md5": 算md5(路径)}


def 视频指纹字节(数据):
    return {"版本": 当前版本, "大小": len(数据), "md5": 算md5字节(数据)}


# ---------------- 近似重复判定 ----------------
def 可能近似重复(甲, 乙):
    """两个照片指纹条目是否可能是同一张图（保守判定，宁缺勿滥）"""
    d甲, d乙 = 甲.get("dhash"), 乙.get("dhash")
    if not d甲 or not d乙:
        return False
    if 细节位数(d甲) < 最少细节位 or 细节位数(d乙) < 最少细节位:
        return False          # 纯色/低细节图，指纹不可靠，不参与近似比对
    宽甲, 高甲, 宽乙, 高乙 = 甲.get("宽"), 甲.get("高"), 乙.get("宽"), 乙.get("高")
    if 宽甲 and 宽乙 and 高甲 and 高乙:
        比甲, 比乙 = 宽甲 / 高甲, 宽乙 / 高乙
        if abs(比甲 - 比乙) / max(比甲, 比乙) > 长宽比容差:
            return False
    return 距离(d甲, d乙) <= 近似阈值


# ---------------- 指纹库读写 ----------------
def 读指纹():
    if os.path.exists(指纹文件):
        try:
            with open(指纹文件, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"照片": {}, "视频": {}}


def 存指纹(指纹):
    os.makedirs(索引目录, exist_ok=True)
    with open(指纹文件, "w", encoding="utf-8") as f:
        json.dump(指纹, f, ensure_ascii=False, indent=1)


def 扫描文件(目录, 扩展名们):
    结果 = []
    if os.path.isdir(目录):
        for 根, _, 文件们 in os.walk(目录):
            for 名 in 文件们:
                if os.path.splitext(名)[1].lower() in 扩展名们:
                    结果.append(os.path.join(根, 名))
    return sorted(结果)


def 更新指纹(打印=print):
    """增量更新指纹库：新文件补算，改动过的重算，已删除的移除"""
    指纹 = 读指纹()
    统计 = {"新增": 0, "删除": 0, "重算": 0}

    for 类别, 目录 in [("照片", 照片目录), ("视频", 视频目录)]:
        扩展名们 = 图片扩展名 if 类别 == "照片" else 视频扩展名
        现有 = {os.path.basename(p): p for p in 扫描文件(目录, 扩展名们)}
        旧有 = 指纹.get(类别, {})
        新表 = {}
        for 名, 路径 in 现有.items():
            旧 = 旧有.get(名)
            大小 = os.path.getsize(路径)
            if 旧 and 旧.get("版本") == 当前版本 and 旧.get("大小") == 大小:
                新表[名] = 旧          # 没变，沿用
                continue
            新表[名] = 图片指纹(路径) if 类别 == "照片" else 视频指纹(路径)
            if 旧:
                统计["重算"] += 1
            else:
                统计["新增"] += 1
            计数 = 统计["新增"] + 统计["重算"]
            if 计数 % 50 == 0:
                打印(f"  已处理 {计数} 个文件…")
        统计["删除"] += len(set(旧有) - set(新表))
        指纹[类别] = 新表

    存指纹(指纹)
    打印(f"指纹库已更新：新增 {统计['新增']}，重算 {统计['重算']}，移除 {统计['删除']}；"
         f"现有照片 {len(指纹['照片'])} 张、视频 {len(指纹['视频'])} 个")
    return 指纹


def 找重复(指纹=None):
    """返回 [(保留的文件名, [重复的文件名, ...]), ...]，先比 md5 再比感知指纹"""
    if 指纹 is None:
        指纹 = 读指纹()
    重复组 = []
    已归组 = set()

    # 1) 完全相同的文件（照片+视频一起比，md5 相同就是同一份内容）
    按md5 = {}
    for 类别 in ("照片", "视频"):
        for 名, 条目 in 指纹.get(类别, {}).items():
            if 条目.get("md5"):
                按md5.setdefault(条目["md5"], []).append(名)
    for 哈希, 名们 in 按md5.items():
        if len(名们) > 1:
            名们 = sorted(名们)
            重复组.append((名们[0], 名们[1:]))
            已归组.update(名们)

    # 2) 照片的近似重复
    照片表 = 指纹.get("照片", {})
    剩余 = sorted(名 for 名 in 照片表 if 名 not in 已归组)
    for i, 名一 in enumerate(剩余):
        if 名一 in 已归组:
            continue
        同类 = []
        for 名二 in 剩余[i + 1:]:
            if 名二 in 已归组:
                continue
            if 可能近似重复(照片表[名一], 照片表[名二]):
                同类.append(名二)
                已归组.add(名二)
        if 同类:
            已归组.add(名一)
            重复组.append((名一, 同类))
    return 重复组


def 移到回收站(文件名, 类别):
    目录 = 照片目录 if 类别 == "照片" else 视频目录
    源 = os.path.join(目录, 文件名)
    if not os.path.isfile(源):
        return False
    os.makedirs(回收目录, exist_ok=True)
    目标 = os.path.join(回收目录, 文件名)
    序号 = 1
    while os.path.exists(目标):
        主干, 扩展 = os.path.splitext(文件名)
        目标 = os.path.join(回收目录, f"{主干}_重复{序号}{扩展}")
        序号 += 1
    os.replace(源, 目标)
    return True
