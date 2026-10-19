# -*- coding: utf-8 -*-
"""
知识检索（RAG）
==============
把书籍、笔记、素材、影像描述切成片段，用阿里云百炼 text-embedding-v3
（支持 50+ 语言）计算向量，提问时只把**最相关的片段**交给 AI。

好处：
- 不再受"上下文 12 万字符"限制，资料再多也能检索
- 中文提问可以直接命中英文/日文等外文原文（向量空间跨语言对齐）
- 每次提问只送几段原文，token 消耗大幅下降

索引文件（都在 00-影像资料\\索引\\ 下）：
- 检索索引_块.json    片段文本与出处（文件、页码、类型）
- 检索索引_向量.npy   每段的向量（float32 矩阵）
- 检索索引_状态.json  各源文件的大小/时间，用于增量更新

用法：
    python 知识检索.py             # 增量重建索引
    python 知识检索.py --全量       # 强制重建
"""

import json
import os
import re
import sys

脚本目录 = os.path.dirname(os.path.abspath(__file__))
根目录 = os.path.normpath(os.path.join(脚本目录, ".."))

照片目录 = os.path.join(根目录, "00-影像资料", "照片原图")
视频目录 = os.path.join(根目录, "00-影像资料", "视频原图")
索引目录 = os.path.join(根目录, "00-影像资料", "索引")
笔记目录 = os.path.join(根目录, "02-笔记")
素材目录 = os.path.join(根目录, "03-素材卡片")
书籍目录 = os.path.join(根目录, "01-书籍扫描", "已OCR")

块文件 = os.path.join(索引目录, "检索索引_块.json")
向量文件 = os.path.join(索引目录, "检索索引_向量.npy")
状态文件 = os.path.join(索引目录, "检索索引_状态.json")

识图缓存 = os.path.join(索引目录, "识图缓存.json")
照片文字 = os.path.join(索引目录, "照片文字.json")
视频描述文件 = os.path.join(索引目录, "视频描述.txt")
影像总目录 = os.path.join(索引目录, "影像总目录.md")
PDF缓存目录 = os.path.join(索引目录, "pdf文本缓存")

嵌入地址 = "https://dashscope.aliyuncs.com/compatible-mode/v1/embeddings"
嵌入模型 = "text-embedding-v3"
向量维度 = 1024
分批大小 = 8          # 每次请求送 8 段
片段上限 = 900        # 每段字符数


def 读密钥():
    """优先 config.json，其次从识图脚本里取"""
    try:
        with open(os.path.join(根目录, "config.json"), encoding="utf-8") as f:
            key = str(json.load(f).get("阿里云Key", "")).strip()
        if key:
            return key
    except Exception:
        pass
    try:
        with open(os.path.join(脚本目录, "照片视频识图.py"), encoding="utf-8-sig") as f:
            m = re.search(r'阿里云API密钥\s*=[^\n]*?"(sk-[^"\n]+)"', f.read())
        return m.group(1) if m else ""
    except Exception:
        return ""


# ---------------- 向量计算 ----------------
def 算向量(文本们, 密钥):
    """批量调用 embedding 接口，返回向量列表"""
    import urllib.request
    结果 = []
    for i in range(0, len(文本们), 分批大小):
        批 = 文本们[i:i + 分批大小]
        请求体 = json.dumps({"model": 嵌入模型, "input": 批, "dimensions": 向量维度}).encode()
        请求 = urllib.request.Request(
            嵌入地址, data=请求体,
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {密钥}"})
        with urllib.request.urlopen(请求, timeout=120) as r:
            数据 = json.loads(r.read().decode())
        结果.extend(x["embedding"] for x in 数据["data"])
    return 结果


# ---------------- 切块 ----------------
def 切文本(文本, 上限=片段上限):
    """按空行/段落切，超长的再硬切"""
    段们 = [s.strip() for s in re.split(r"\n\s*\n", 文本) if s.strip()]
    块们, 当前 = [], ""
    for 段 in 段们:
        if len(当前) + len(段) + 1 <= 上限:
            当前 = (当前 + "\n" + 段).strip()
        else:
            if 当前:
                块们.append(当前)
            while len(段) > 上限:
                块们.append(段[:上限])
                段 = 段[上限:]
            当前 = 段
    if 当前:
        块们.append(当前)
    return 块们


def 切书籍PDF(路径):
    """按页切，保留页码"""
    import hashlib
    指纹 = hashlib.md5(("v2" + 路径 + str(os.path.getmtime(路径))).encode()).hexdigest()
    缓存 = os.path.join(PDF缓存目录, 指纹 + ".txt")
    块们 = []
    if os.path.exists(缓存):
        with open(缓存, encoding="utf-8") as f:
            全文 = f.read()
    else:
        return 块们      # 还没提取过文字（可能是扫描版），跳过
    页码 = None
    当前 = ""
    for 行 in 全文.splitlines():
        m = re.match(r"【第(\d+)页】", 行.strip())
        if m:
            if 当前.strip():
                for 片段 in 切文本(当前):
                    块们.append({"文件": os.path.basename(路径), "页码": 页码, "类型": "书籍", "文本": 片段})
            页码 = int(m.group(1))
            当前 = ""
            continue
        当前 += 行 + "\n"
    if 当前.strip():
        for 片段 in 切文本(当前):
            块们.append({"文件": os.path.basename(路径), "页码": 页码, "类型": "书籍", "文本": 片段})
    return 块们


def 切普通文本(路径, 类型):
    块们 = []
    try:
        with open(路径, encoding="utf-8", errors="ignore") as f:
            全文 = f.read()
    except Exception:
        return 块们
    for 片段 in 切文本(全文):
        块们.append({"文件": os.path.basename(路径), "页码": None, "类型": 类型, "文本": 片段})
    return 块们


def 解析拍摄地点():
    """从影像总目录.md 里提取 文件名 → 地名"""
    地点 = {}
    if not os.path.exists(影像总目录):
        return 地点
    try:
        内容 = open(影像总目录, encoding="utf-8").read()
    except Exception:
        return 地点
    当前名 = None
    for 行 in 内容.splitlines():
        m = re.match(r"-\s*【照片】(.+?)\s*$", 行)
        if m:
            当前名 = os.path.basename(m.group(1).strip())
            continue
        m = re.match(r"\s*-\s*拍摄地点：(.+)$", 行)
        if m and 当前名:
            地点[当前名] = m.group(1).strip("，, ")
            当前名 = None
    return 地点


def 影像块们():
    """把每 4 条影像描述打包成一个片段，带类型与文件名"""
    条目 = []
    地点表 = 解析拍摄地点()

    # 照片（画面描述 + OCR 出的文字）
    try:
        with open(识图缓存, encoding="utf-8") as f:
            照片描述 = json.load(f)
    except Exception:
        照片描述 = {}
    try:
        with open(照片文字, encoding="utf-8") as f:
            OCR文字 = json.load(f)
    except Exception:
        OCR文字 = {}
    for 路径, 描述 in 照片描述.items():
        名 = os.path.basename(路径)
        地点 = 地点表.get(名, "")
        前缀 = f"【照片】{名}"
        if 地点:
            前缀 += f"（拍摄地点：{地点}）"
        文本 = OCR文字.get(名, "")
        条目文本 = f"{前缀}：{描述}"
        if 文本:
            条目文本 += f"\n    图中文字：{文本[:400]}"
        条目.append(条目文本)

    # 视频
    try:
        with open(视频描述文件, encoding="utf-8") as f:
            for 行 in f:
                行 = 行.strip()
                if not 行 or 行.startswith("#") or "|" not in 行:
                    continue
                名, _, 描述 = 行.partition("|")
                if 描述.strip():
                    条目.append(f"【视频】{名.strip()}：{描述.strip()}")
    except Exception:
        pass

    块们 = []
    for 条目文本 in 条目:
        块们.append({"文件": "影像资料", "页码": None, "类型": "影像", "文本": 条目文本})
    return 块们


# ---------------- 索引读写 ----------------
def 读状态():
    try:
        with open(状态文件, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def 存状态(状态):
    with open(状态文件, "w", encoding="utf-8") as f:
        json.dump(状态, f, ensure_ascii=False, indent=1)


def 读索引():
    import numpy as np
    try:
        with open(块文件, encoding="utf-8") as f:
            块们 = json.load(f)
        向量 = np.load(向量文件)
        if len(块们) != 向量.shape[0]:
            return [], None
        return 块们, 向量
    except Exception:
        return [], None


def 收集源文件():
    """返回 [(路径, 类型, 切块函数)]"""
    源 = []
    for 目录, 类型, 后缀 in [
        (书籍目录, "书籍", {".pdf", ".md", ".txt"}),
        (笔记目录, "笔记", {".md", ".txt"}),
        (素材目录, "素材", {".md", ".txt"}),
    ]:
        if not os.path.isdir(目录):
            continue
        for 根, _, 文件们 in os.walk(目录):
            if os.path.basename(根) in ("pdf文本缓存", "thumbs"):
                continue
            for 名 in sorted(文件们):
                if os.path.splitext(名)[1].lower() in 后缀:
                    源.append((os.path.join(根, 名), 类型))
    return 源


def 建索引(全量=False, 打印=print):
    import numpy as np

    密钥 = 读密钥()
    if not 密钥:
        打印("× 没有读到阿里云 Key，无法建立检索索引（请在 config.json 的 阿里云Key 里填写）")
        return False

    旧块们, 旧矩阵 = ([], None) if 全量 else 读索引()
    旧状态 = {} if 全量 else 读状态()

    # 旧索引按"来源文件"分组：{文件名: (块列表, 向量列表)}
    旧分组 = {}
    if 旧块们 and 旧矩阵 is not None:
        for i, 块 in enumerate(旧块们):
            旧分组.setdefault(块["文件"], ([], []))
            旧分组[块["文件"]][0].append(块)
            旧分组[块["文件"]][1].append(旧矩阵[i])

    # 收集所有来源：(键, 标识, 生成块函数)
    源们 = []
    for 路径, 类型 in 收集源文件():
        标识 = f"{os.path.getsize(路径)}:{int(os.path.getmtime(路径))}"
        if 路径.lower().endswith(".pdf"):
            生成 = (lambda p=路径: 切书籍PDF(p))
        else:
            生成 = (lambda p=路径, t=类型: 切普通文本(p, t))
        源们.append((os.path.basename(路径), 标识, 生成))

    新块们, 行们 = [], []      # 行们: 已有向量 或 None（待计算）
    状态 = {}
    复用段数 = 0

    for 键, 标识, 生成 in 源们:
        状态[键] = 标识
        可复用 = (not 全量) and 旧状态.get(键) == 标识 and 键 in 旧分组
        if 可复用:
            块组, 向量组 = 旧分组[键]
            新块们.extend(块组)
            行们.extend(list(向量组))
            复用段数 += len(块组)
        else:
            块组 = 生成()
            新块们.extend(块组)
            行们.extend([None] * len(块组))

    # 影像描述作为一类特殊来源（签名要包含内容摘要，否则 OCR/描述更新后不会重建）
    影像块 = 影像块们()
    if 影像块:
        import hashlib as _h
        键 = "影像资料"
        标识 = _h.md5("\n".join(b["文本"] for b in 影像块).encode()).hexdigest()[:16]
        状态[键] = 标识
        可复用 = (not 全量) and 旧状态.get(键) == 标识 and 键 in 旧分组
        if 可复用:
            块组, 向量组 = 旧分组[键]
            新块们.extend(块组)
            行们.extend(list(向量组))
            复用段数 += len(块组)
        else:
            新块们.extend(影像块)
            行们.extend([None] * len(影像块))

    # 只计算新增片段的向量
    待算 = [i for i, v in enumerate(行们) if v is None]
    打印(f"片段总数 {len(新块们)}，复用 {复用段数} 段，需要新计算 {len(待算)} 段")

    矩阵 = np.zeros((len(新块们), 向量维度), dtype=np.float32)
    for i, v in enumerate(行们):
        if v is not None:
            矩阵[i] = v

    for 起 in range(0, len(待算), 40):
        序号们 = 待算[起:起 + 40]
        向量们 = 算向量([新块们[i]["文本"] for i in 序号们], 密钥)
        for i, 向量 in zip(序号们, 向量们):
            矩阵[i] = np.array(向量, dtype=np.float32)
        打印(f"  向量已计算 {min(起 + 40, len(待算))}/{len(待算)}")

    # 影像块的"文件"字段统一成"影像资料"，保证下次复用时键能对上
    for 块 in 新块们:
        if 块["类型"] == "影像":
            块["文件"] = "影像资料"

    os.makedirs(索引目录, exist_ok=True)
    with open(块文件, "w", encoding="utf-8") as f:
        json.dump(新块们, f, ensure_ascii=False, indent=1)
    np.save(向量文件, 矩阵)
    存状态(状态)

    分类 = {}
    for 块 in 新块们:
        分类[块["类型"]] = 分类.get(块["类型"], 0) + 1
    打印(f"索引已建立：{len(新块们)} 段（" + "、".join(f"{k} {v}" for k, v in 分类.items()) + "）")
    return True


# ---------------- 检索 ----------------
def 检索(问题, 条数=16, 打印=print):
    """返回 [(相似度, 块), ...]"""
    import numpy as np

    块们, 矩阵 = 读索引()
    if not 块们:
        return []
    密钥 = 读密钥()
    if not 密钥:
        return []
    查询向量 = np.array(算向量([问题], 密钥)[0], dtype=np.float32)
    范数 = np.linalg.norm(矩阵, axis=1) * np.linalg.norm(查询向量)
    范数[范数 == 0] = 1e-9
    相似度们 = (矩阵 @ 查询向量) / 范数
    前几 = np.argsort(-相似度们)[:条数]
    return [(float(相似度们[i]), 块们[i]) for i in 前几]


def 检索上下文(问题, 条数=16):
    """把检索结果拼成给 AI 的上下文文本；索引为空时返回空字符串"""
    结果 = 检索(问题, 条数=条数)
    if not 结果:
        return ""
    片段 = []
    for 相似度, 块 in 结果:
        出处 = 块["文件"]
        if 块.get("页码"):
            出处 += f" 第{块['页码']}页"
        片段.append(f"===== 资料片段：{出处}（相关度 {相似度:.2f}）=====\n{块['文本']}")
    return "\n\n".join(片段)


if __name__ == "__main__":
    全量 = "--全量" in sys.argv
    建索引(全量=全量)
