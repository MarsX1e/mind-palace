# -*- coding: utf-8 -*-
r"""
照片AI识图工具（阿里云百炼 Qwen-VL）
====================================
批量调用视觉大模型，给 00-影像资料\照片原图 里的每张照片生成一句中文描述，
结果写入 00-影像资料\索引\AI识图描述.md，随后运行 影像建索引.py
会自动把它并进《影像总目录.md》，供 AnythingLLM 检索。

依赖：Pillow（已安装）

使用前：
1. 把下面的 阿里云API密钥 填上（https://bailian.console.aliyun.com → API-KEY）
2. 模型名保持默认 qwen-vl-max 即可；如果你的控制台里模型 ID 不同，改一下
3. 运行：python 照片视频识图.py
   已识别过的照片有缓存，不会重复扣费。
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


def 读根配置():
    """优先读知识库根目录的 config.json（推荐），没有则返回空"""
    try:
        with open(os.path.normpath(os.path.join(脚本目录, "..", "config.json")), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


_配置 = 读根配置()

# ================== 配置区 ==================
# 优先读知识库根目录的 config.json；没有该文件时用下面的保底值。
# 开源版本会把下面的保底值清空，你只需在 config.json 里填自己的 Key。
阿里云API密钥 = str(_配置.get("阿里云Key", "")).strip() or ""
模型名 = str(_配置.get("识图模型", "")).strip() or "qwen3-vl-plus"
BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
# ==========================================

照片目录 = os.path.normpath(os.path.join(脚本目录, "..", "00-影像资料", "照片原图"))
输出目录 = os.path.normpath(os.path.join(脚本目录, "..", "00-影像资料", "索引"))
缓存文件 = os.path.join(输出目录, "识图缓存.json")
输出文件 = os.path.join(输出目录, "AI识图描述.md")

支持的扩展名 = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
提示词 = ("用一句话简要描述这张照片：拍摄的地点特征、主要景物、人物活动（50字以内，中文）。"
          "如果能判断大致地区（省/城市/景点）也写上。")


def 压缩图片(路径, 最长边=1280):
    """太大的照片压缩后再传，省流量也避免超出API限制"""
    from PIL import Image
    with Image.open(路径) as img:
        img = img.convert("RGB")
        if max(img.size) > 最长边:
            比例 = 最长边 / max(img.size)
            img = img.resize((int(img.width * 比例), int(img.height * 比例)))
        缓冲 = io.BytesIO()
        img.save(缓冲, "JPEG", quality=82)
        return 缓冲.getvalue()


支持的重试次数 = 3


class 致命错误(Exception):
    """Key 无效、欠费、无权限：继续跑也没用，应立即停止"""


class 可重试错误(Exception):
    """频率限制、网络抖动：等一下再试"""


def 调用视觉模型(jpg字节):
    data_url = "data:image/jpeg;base64," + base64.b64encode(jpg字节).decode()
    请求体 = json.dumps({
        "model": 模型名,
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": 提示词},
            {"type": "image_url", "image_url": {"url": data_url}},
        ]}],
    }).encode("utf-8")
    请求 = urllib.request.Request(
        BASE_URL, data=请求体,
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {阿里云API密钥}"})
    try:
        with urllib.request.urlopen(请求, timeout=60) as 响应:
            数据 = json.loads(响应.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        正文 = e.read().decode("utf-8", "ignore")
        致命关键词 = ["Arrearage", "insufficient", "Insufficient", "InvalidApiKey",
                      "invalid_api_key", "AccessDenied", "Unauthorized", "欠费", "余额不足", "not activated"]
        if e.code in (401, 402, 403) or any(词 in 正文 for 词 in 致命关键词):
            raise 致命错误(f"HTTP {e.code} {正文[:200]}")
        raise 可重试错误(f"HTTP {e.code} {正文[:200]}")
    except Exception as e:
        raise 可重试错误(str(e))
    return 数据["choices"][0]["message"]["content"].strip()


def 主流程():
    if not 阿里云API密钥:
        print("错误：请先在脚本开头填写 阿里云API密钥。")
        sys.exit(1)
    os.makedirs(输出目录, exist_ok=True)

    缓存 = {}
    if os.path.exists(缓存文件):
        with open(缓存文件, encoding="utf-8") as f:
            缓存 = json.load(f)

    照片列表 = []
    for 目录路径, _, 文件名列表 in os.walk(照片目录):
        for 文件名 in 文件名列表:
            if os.path.splitext(文件名)[1].lower() in 支持的扩展名:
                照片列表.append(os.path.join(目录路径, 文件名))
    照片列表.sort()
    print(f"共发现 {len(照片列表)} 张照片")

    结果 = dict(缓存)          # {路径: 描述}
    失败 = []
    致命中断 = ""
    for i, 路径 in enumerate(照片列表, 1):
        if 路径 in 结果:
            continue  # 缓存命中，不重复扣费
        描述 = None
        for 尝试 in range(1, 支持的重试次数 + 1):
            try:
                描述 = 调用视觉模型(压缩图片(路径))
                break
            except 致命错误 as e:
                致命中断 = str(e)
                break
            except 可重试错误 as e:
                if 尝试 >= 支持的重试次数:
                    失败.append(路径)
                    print(f"[{i}/{len(照片列表)}] {os.path.basename(路径)}: 失败 {e}")
                else:
                    print(f"  重试 {尝试}/{支持的重试次数 - 1}（{e}）…")
                    time.sleep(5)
        if 致命中断:
            print(f"\n⚠ 识别被中断：{致命中断}")
            break
        if 描述 is not None:
            结果[路径] = 描述
            print(f"[{i}/{len(照片列表)}] {os.path.basename(路径)}: {描述}")
            time.sleep(0.3)  # 控制频率
        # 每10张存一次缓存，中断也不丢进度
        if i % 10 == 0:
            with open(缓存文件, "w", encoding="utf-8") as f:
                json.dump(结果, f, ensure_ascii=False, indent=1)

    with open(缓存文件, "w", encoding="utf-8") as f:
        json.dump(结果, f, ensure_ascii=False, indent=1)

    with open(输出文件, "w", encoding="utf-8") as f:
        f.write("# AI识图描述（由视觉模型自动生成）\n\n")
        for 路径, 描述 in sorted(结果.items()):
            f.write(f"- {os.path.basename(路径)}：{描述}\n")

    # 未完成的照片写成清单，充值/恢复后一眼看到还剩多少
    未完成 = [p for p in 照片列表 if p not in 结果]
    清单文件 = os.path.join(输出目录, "待重试识图清单.txt")
    if 未完成:
        with open(清单文件, "w", encoding="utf-8") as f:
            f.write(f"# 尚未识别成功的照片（{len(未完成)} 张）\n")
            f.write("# 充值/恢复后直接重新运行 照片视频识图.py 即可，已识别的不会重复扣费\n\n")
            for p in 未完成:
                f.write(os.path.basename(p) + "\n")
    elif os.path.exists(清单文件):
        os.remove(清单文件)

    print(f"\n完成！已识别 {len(结果)} 张，未完成 {len(未完成)} 张。")
    if 致命中断:
        print(f"中断原因：{致命中断}")
        print("→ 给阿里云百炼账号充值/检查 Key 后，重新运行本脚本即可；")
        print("  已识别的照片有缓存，不会重复扣费，只会接着识别剩下的。")
    if 未完成:
        print(f"未完成清单：{清单文件}")
    print(f"描述已写入：{输出文件}")


if __name__ == "__main__":
    主流程()
