# -*- coding: utf-8 -*-
import argparse
import re
import shutil
import subprocess
import sys
import time
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PYTHON_EXE = Path(os.getenv("PYTHON_EXE", sys.executable))
DIRECT = PROJECT_ROOT / "scripts" / "openclaw_xhs_author_direct_v2.py"
TEMP_DIR = PROJECT_ROOT / ".tmp" / "xhs_variants_wrapper"
DELIVERY_DIR = Path(os.getenv("VIDEO_DELIVERY_DIR", PROJECT_ROOT / "outputs" / "作者主页批量"))

def parse_bgm_variant_count(text: str) -> int:
    t = text or ""
    zh_num = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5}
    patterns = [
        r"每条(?:视频|作品)?[^\n\r]{0,16}(\d+)\s*(?:个|款|版|种|首)?\s*(?:不同)?\s*(?:BGM|bgm|音乐|配乐|版本)",
        r"每条(?:视频|作品)?[^\n\r]{0,16}([一二两三四五])\s*(?:个|款|版|种|首)?\s*(?:不同)?\s*(?:BGM|bgm|音乐|配乐|版本)",
        r"(\d+)\s*(?:个|款|版|种|首)\s*(?:不同)?\s*(?:BGM|bgm|音乐|配乐)",
        r"([一二两三四五])\s*(?:个|款|版|种|首)\s*(?:不同)?\s*(?:BGM|bgm|音乐|配乐)",
    ]
    for p in patterns:
        m = re.search(p, t, flags=re.I)
        if not m:
            continue
        raw = m.group(1)
        n = zh_num.get(raw, None) if not raw.isdigit() else int(raw)
        if n:
            return max(1, min(5, n))
    return 1

def variant_message(base: str, index: int, total: int) -> str:
    # 不要求用户说一堆英文，wrapper 内部负责补充搜索方向
    pools = [
        "BGM 找最近日本 TikTok 穿搭 OOTD 热门歌，偏女装展示和日系时尚感，不要本地歌，不要中文歌，不要印度 Reels 合集。",
        "BGM 找最近韩国 TikTok 穿搭 OOTD 热门歌，偏 K-pop / 女装展示 / 时尚感，不要本地歌，不要中文歌，不要印度 Reels 合集。",
        "BGM 找最近日韩 TikTok 穿搭 lookbook 热门歌，适合服装展示，不要本地歌，不要中文歌，不要印度 Reels 合集。",
        "BGM 找最近日本韩国 TikTok fashion outfit 热门歌，节奏轻快，适合穿搭博主，不要本地歌，不要中文歌。",
        "BGM 找最近日韩 TikTok OOTD viral song，适合女装展示，不要印度、中文、本地库存。",
    ]
    extra = pools[(index - 1) % len(pools)]
    # 避免 direct_v2 或旧链路误认为 dry-run
    cleaned = re.sub(r"(只做\s*)?dry[-\s_]?run|预览|先看看|不要生成|不生成", "", base, flags=re.I)
    return cleaned.strip() + f"""

这是第 {index}/{total} 个 BGM 版本。
{extra}
音乐从第 20 秒开始截取。
正式生成。
"""

def snapshot_mp4s() -> dict[str, float]:
    DELIVERY_DIR.mkdir(parents=True, exist_ok=True)
    return {str(p): p.stat().st_mtime for p in DELIVERY_DIR.glob("*.mp4")}

def rename_new_outputs(before: dict[str, float], variant_index: int) -> list[str]:
    outputs = []
    for p in DELIVERY_DIR.glob("*.mp4"):
        old_mtime = before.get(str(p))
        if old_mtime is not None and p.stat().st_mtime <= old_mtime:
            continue
        if f"__BGM{variant_index:02d}" in p.stem:
            outputs.append(str(p))
            continue

        if "__换BGM" in p.stem:
            target = p.with_name(p.stem.replace("__换BGM", f"__BGM{variant_index:02d}") + p.suffix)
        else:
            target = p.with_name(p.stem + f"__BGM{variant_index:02d}" + p.suffix)

        if target.exists():
            target = target.with_name(target.stem + "_" + str(int(time.time())) + target.suffix)

        shutil.copy2(p, target)
        outputs.append(str(target))
        print(f"已保存版本文件：{target}")
    return outputs

def run_variant(message: str, api_base: str, index: int, total: int) -> tuple[int, list[str]]:
    TEMP_DIR.mkdir(parents=True, exist_ok=True)
    msg = TEMP_DIR / f"variant_{index:02d}_{int(time.time())}.txt"
    msg.write_text(variant_message(message, index, total), encoding="utf-8")

    before = snapshot_mp4s()
    cmd = [
        str(PYTHON_EXE),
        str(DIRECT),
        "--message-file",
        str(msg),
        "--api-base",
        api_base,
    ]
    print("")
    print(f"==== 开始第 {index}/{total} 个 BGM 版本 ====")
    print(" ".join(cmd))

    proc = subprocess.run(cmd, cwd=str(PROJECT_ROOT), text=True, encoding="utf-8", errors="replace")
    outputs = rename_new_outputs(before, index)
    return proc.returncode, outputs

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--message", default="")
    parser.add_argument("--message-file", default="")
    parser.add_argument("--api-base", default="http://127.0.0.1:8004")
    args = parser.parse_args()

    text = args.message or ""
    if args.message_file:
        text += "\n" + Path(args.message_file).read_text(encoding="utf-8")
    text = text.strip()

    if not text:
        print("错误：消息为空。")
        return 2

    count = parse_bgm_variant_count(text)
    print(f"XHS_VARIANTS_WRAPPER：检测到每条视频 BGM 版本数 = {count}")

    all_outputs = []
    failed = 0

    for i in range(1, count + 1):
        code, outputs = run_variant(text, args.api_base, i, count)
        all_outputs.extend(outputs)
        if code != 0:
            failed += 1
            print(f"第 {i} 个版本执行失败，退出码：{code}")

    print("")
    print("==== XHS_VARIANTS_WRAPPER 汇总 ====")
    print(f"BGM版本数：{count}")
    print(f"生成文件数：{len(all_outputs)}")
    print(f"失败版本数：{failed}")
    print(f"交付目录：{DELIVERY_DIR}")
    for p in all_outputs:
        print(f"- {p}")

    return 1 if failed else 0

if __name__ == "__main__":
    raise SystemExit(main())
