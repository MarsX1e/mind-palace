# -*- coding: utf-8 -*-
"""
照片文字识别（OCR）
==================
用阿里云百炼 qwen-vl-ocr 把照片里的文字提取出来（单据、白板、屏幕、路牌、菜单…），
存到 00-影像资料\\索引\\照片文字.json，检索索引会把文字一起纳入，
这样就能"用文字搜照片"。

特性：
- 增量：已处理过的照片跳过，不重复花钱
- 无文字的照片也会记成空值，避免下次再调用
- 欠费/Key 无效会立即停止并提示
- 每 10 张存一次进度，可随时中断

用法：
    python 照片OCR.py            # 处理所有还没 OCR 的照片
    python 照片OCR.py --重做      # 全部重做（会重新调用）
"""

import base64
import io
import json
import os
import sys
import time
import urllib.error
import urllib.request

脚本目录 = os.path.dirname(os.path.abspath(__file__))
根目录 = os.path.normpath(os.path.join(脚本目录, ".."))
照片目录 = os.path.join(根目录, "00-影像资料", "照片原图")
索引目录 = os.path.join(根目录, "00-影像资料", "索引")
输出文件 = os.path.join(索引目录, "照片文字.json")

模型 = "qwen-vl-ocr"
地址 = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
支持扩展名 = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
提示词 = "提取图片中的所有文字，按原样输出，保留换行；如果图中没有文字，只输出一个减号 -"


class 致命错误(Exception):
    pass


class 可重试错误(Exception):
    pass


def 读密钥():
    import re
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


def 压缩图片(路径, 最长边=1600):
    from PIL import Image
    with Image.open(路径) as 图:
        图 = 图.convert("RGB")
        if max(图.size) > 最长边:
            比例 = 最长边 / max(图.size)
            图 = 图.resize((int(图.width * 比例), int(图.height * 比例)))
        缓冲 = io.BytesIO()
        图.save(缓冲, "JPEG", quality=88)
        return 缓冲.getvalue()


def 识别(路径, 密钥):
    data_url = "data:image/jpeg;base64," + base64.b64encode(压缩图片(路径)).decode()
    请求体 = json.dumps({
        "model": 模型,
        "messages": [{"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": data_url}},
            {"type": "text", "text": 提示词},
        ]}],
    }).encode()
    请求 = urllib.request.Request(
        地址, data=请求体,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {密钥}"})
    try:
        with urllib.request.urlopen(请求, timeout=90) as r:
            数据 = json.loads(r.read().decode())
        文本 = (数据["choices"][0]["message"]["content"] or "").strip()
        文本 = 清理文字(文本)
        return "" if 文本 in ("-", "—", "", "无") else 文本
    except urllib.error.HTTPError as e:
        正文 = e.read().decode("utf-8", "ignore")
        if e.code in (401, 402, 403) or any(k in 正文 for k in ("Arrearage", "InvalidApiKey", "余额")):
            raise 致命错误(f"HTTP {e.code} {正文[:150]}")
        raise 可重试错误(f"HTTP {e.code} {正文[:150]}")
    except Exception as e:
        raise 可重试错误(str(e))


def 清理文字(文本):
    """去掉 qwen-vl-ocr 附带输出的坐标数字，只留真正的文字"""
    import re
    if not 文本:
        return ""
    # 去掉 4 元组坐标（如 704,746,219,31）
    文本 = re.sub(r"\b\d{1,5}(?:\s*,\s*\d{1,5}){3}\b", " ", 文本)
    # 去掉只剩数字和逗号的行
    行们 = []
    for 行 in 文本.splitlines():
        干净 = 行.strip()
        if not 干净:
            continue
        if re.fullmatch(r"[\d\s.,:;\-_/\\|]+", 干净):
            continue
        行们.append(干净)
    结果 = "\n".join(行们)
    结果 = re.sub(r"[ \t]{2,}", " ", 结果)
    return 结果.strip()


def 主流程():
    重做 = "--重做" in sys.argv
    仅清理 = "--清理" in sys.argv

    if 仅清理:
        if not os.path.exists(输出文件):
            print("还没有 OCR 结果文件，无需清理")
            return
        with open(输出文件, encoding="utf-8") as f:
            数据 = json.load(f)
        清理后 = {k: 清理文字(v) for k, v in 数据.items()}
        with open(输出文件, "w", encoding="utf-8") as f:
            json.dump(清理后, f, ensure_ascii=False, indent=1)
        含字 = sum(1 for v in 清理后.values() if v)
        print(f"已清理 {len(清理后)} 条 OCR 结果，其中 {含字} 条含有效文字（未调用任何 API，未产生费用）")
        return

    密钥 = 读密钥()
    if not 密钥:
        print("错误：没有读到阿里云 Key（config.json 的 阿里云Key，或 tools/照片视频识图.py）")
        sys.exit(1)
    os.makedirs(索引目录, exist_ok=True)

    已有 = {}
    if os.path.exists(输出文件) and not 重做:
        try:
            with open(输出文件, encoding="utf-8") as f:
                已有 = json.load(f)
        except Exception:
            已有 = {}

    照片们 = []
    for 根, _, 文件们 in os.walk(照片目录):
        for 名 in 文件们:
            if os.path.splitext(名)[1].lower() in 支持扩展名:
                照片们.append(os.path.join(根, 名))
    照片们.sort()
    待做 = [p for p in 照片们 if os.path.basename(p) not in 已有]
    print(f"共 {len(照片们)} 张照片，已 OCR {len(照片们) - len(待做)} 张，本次处理 {len(待做)} 张")

    有字 = 0
    中断 = ""
    for i, 路径 in enumerate(待做, 1):
        名 = os.path.basename(路径)
        文本 = None
        for 尝试 in range(1, 4):
            try:
                文本 = 识别(路径, 密钥)
                break
            except 致命错误 as e:
                中断 = str(e)
                break
            except 可重试错误 as e:
                if 尝试 >= 3:
                    print(f"[{i}/{len(待做)}] {名}: 失败 {e}")
                else:
                    time.sleep(5)
        if 中断:
            print(f"\n⚠ OCR 被中断：{中断}\n  → 充值/检查 Key 后重新运行即可，已完成的不会重复处理")
            break
        if 文本 is None:
            continue
        已有[名] = 文本
        if 文本:
            有字 += 1
            print(f"[{i}/{len(待做)}] {名}: 有文字 {len(文本)} 字 → {文本[:40].replace(chr(10), ' ')}")
        else:
            print(f"[{i}/{len(待做)}] {名}: 无文字")
        if i % 10 == 0:
            with open(输出文件, "w", encoding="utf-8") as f:
                json.dump(已有, f, ensure_ascii=False, indent=1)

    with open(输出文件, "w", encoding="utf-8") as f:
        json.dump(已有, f, ensure_ascii=False, indent=1)

    含字 = sum(1 for v in 已有.values() if v)
    print(f"\n完成！本次识别出文字的 {有字} 张；累计 {len(已有)} 张已处理，其中 {含字} 张含文字。")
    print(f"结果文件：{输出文件}")
    print("下一步：运行 知识检索.py 或点网页上的『建立/更新检索索引』，文字就会被纳入检索。")


if __name__ == "__main__":
    主流程()
