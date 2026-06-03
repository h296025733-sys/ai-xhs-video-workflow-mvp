from __future__ import annotations
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import requests
from pathlib import Path

# XHS_LOCAL_PROXY_BYPASS_PATCH
# 本地 FastAPI / XHS-Downloader / OpenClaw 调用必须绕过系统代理；
# 否则 requests 可能把 127.0.0.1:8004 转到 127.0.0.1:9567 导致 ProxyError。
os.environ["NO_PROXY"] = "127.0.0.1,localhost,::1"
os.environ["no_proxy"] = "127.0.0.1,localhost,::1"


PROJECT_ROOT = Path(__file__).resolve().parents[1]

# 钉钉/OpenClaw 启动脚本时，sys.path 可能只有 scripts 目录，
# 导致 import app.* 失败。这里强制加入项目根目录。
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)
PYTHON_EXE = Path(os.getenv("PYTHON_EXE", sys.executable))
REPORT_DIR = Path(os.getenv("XHS_REPORT_DIR", PROJECT_ROOT / "outputs" / "reports"))
DELIVERY_DIR = Path(os.getenv("VIDEO_DELIVERY_DIR", PROJECT_ROOT / "outputs" / "作者主页批量"))
TEMP_DIR = Path(os.getenv("XHS_TEMP_DIR", PROJECT_ROOT / ".runtime" / "xhs_direct_v2"))
DELIVERY_VIDEO_DIR = DELIVERY_DIR / "01_视频成品"
DELIVERY_COVER_DIR = DELIVERY_DIR / "02_封面"


def sha16(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()[:16]


def safe_name(text: str, fallback: str = "video") -> str:
    text = str(text or "").strip() or fallback
    text = re.sub(r'[<>:"/\\\\|?*\r\n\t]+', "_", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:90] or fallback


def extract_note_id_for_output(item: dict, url: str = "") -> str:
    """从 item 或作品 URL 提取 note_id，用于避免同标题作品覆盖输出文件。"""
    candidates = []

    if isinstance(item, dict):
        # 优先使用明确的作品 note_id 字段
        for key in ["note_id", "noteId", "note_id_str", "noteIdStr"]:
            candidates.append(item.get(key))

        # 其次从作品 URL 中提取 /discovery/item/<note_id>
        for key in ["url", "note_url", "share_url", "xhs_url"]:
            candidates.append(item.get(key))

        # 最后才尝试通用 id，避免误把作者 id 当作品 id
        candidates.append(item.get("id"))

    candidates.append(url)

    for value in candidates:
        text = str(value or "").strip()
        if not text:
            continue

        if re.fullmatch(r"[0-9a-fA-F]{12,32}", text):
            return text

        m = re.search(r"/(?:discovery/item|explore)/([0-9a-fA-F]{12,32})", text)
        if m:
            return m.group(1)

    return ""


def output_stem_for_item(title: str, item: dict, idx: int, url: str = "") -> str:
    base = safe_name(title, f"作品{idx}")
    note_id = extract_note_id_for_output(item, url)

    if note_id:
        return f"{base}__{note_id[-4:].lower()}"

    # 理论兜底：如果极端情况下没有 note_id，至少用批次序号避免覆盖
    return f"{base}__{idx:02d}"


def xhs_v3_is_note_id_like(text: str) -> bool:
    return bool(re.fullmatch(r"[0-9a-fA-F]{16,32}", str(text or "").strip()))


def xhs_v3_note_id_for_delivery(item: dict, url: str = "") -> str:
    candidates = []
    if isinstance(item, dict):
        for key in ["note_id", "noteId", "note_id_str", "noteIdStr", "id"]:
            candidates.append(item.get(key))
        for key in ["url", "note_url", "share_url", "xhs_url"]:
            candidates.append(item.get(key))
    candidates.append(url)

    for value in candidates:
        text = str(value or "").strip()
        if not text:
            continue
        if re.fullmatch(r"[0-9a-fA-F]{12,32}", text):
            return text
        m = re.search(r"/(?:discovery/item|explore)/([0-9a-fA-F]{12,32})", text)
        if m:
            return m.group(1)
    return ""


def xhs_v3_cached_title_for_delivery(item: dict, url: str = "") -> str:
    finder = globals().get("_find_cached_source_video_for_note_id")
    title_from_path = globals().get("_title_from_cached_source_path")
    if not callable(finder) or not callable(title_from_path):
        return ""

    note_id = xhs_v3_note_id_for_delivery(item, url)
    if not note_id:
        return ""

    cached = finder(note_id)
    if not cached:
        return ""

    title = title_from_path(cached)
    if title and not xhs_v3_is_note_id_like(title):
        return title.strip()
    return ""


def xhs_v3_detail_title_for_delivery(item: dict, url: str = "") -> str:
    if not url:
        return ""

    try:
        detail = _refresh_item_detail_for_video_url(url) or {}
    except Exception as exc:
        print(f"重新获取标题/封面详情失败：{exc}")
        return ""

    if detail:
        item.update(detail)

    for key in ["title", "display_title", "note_title", "desc", "description", "name"]:
        value = detail.get(key)
        if isinstance(value, str):
            value = value.strip()
            if value and not xhs_v3_is_note_id_like(value):
                return value
    return ""


def xhs_v3_title_for_delivery(item: dict, idx: int, url: str = "") -> str:
    title = str((item or {}).get("title") or "").strip()
    note_id = xhs_v3_note_id_for_delivery(item, url)

    if (not title) or xhs_v3_is_note_id_like(title) or (note_id and title == note_id):
        title = xhs_v3_detail_title_for_delivery(item, url) or xhs_v3_cached_title_for_delivery(item, url) or title

    if (not title) or xhs_v3_is_note_id_like(title):
        title = f"作品{idx}"

    item["title"] = title
    return title


def xhs_v3_count_delivery_titles(items: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for i, item in enumerate(items or [], start=1):
        url = item.get("url") or item.get("note_url") or ""
        title = xhs_v3_title_for_delivery(item, i, url)
        base = safe_name(title, f"作品{i}")
        counts[base] = counts.get(base, 0) + 1

    print("交付标题重复检测：")
    for base, count in counts.items():
        print(f"- {base}：{count}")
    return counts


def xhs_v3_output_stem(title: str, item: dict, idx: int, url: str, title_counts: dict[str, int]) -> str:
    base = safe_name(title, f"作品{idx}")
    note_id = xhs_v3_note_id_for_delivery(item, url)
    duplicate = title_counts.get(base, 0) > 1

    # 标题唯一：标题__BGM01.mp4
    if not duplicate:
        return base

    # 标题重复：标题__note短ID__BGM01.mp4
    if note_id:
        return f"{base}__{note_id[-4:].lower()}"

    return f"{base}__{idx:02d}"


def xhs_v3_save_cover_or_frame(item: dict, title: str, output_stem: str, source: Path, note_url: str = "") -> str | None:
    DELIVERY_COVER_DIR.mkdir(parents=True, exist_ok=True)

    cover_url = xhs_v3_extract_cover_url(item)

    if not cover_url and note_url:
        print("当前筛选数据没有封面URL，尝试重新获取作品详情。")
        try:
            detail = _refresh_item_detail_for_video_url(note_url) or {}
            if detail:
                item.update(detail)
                cover_url = xhs_v3_extract_cover_url(item)
        except Exception as exc:
            print(f"重新获取封面详情失败：{exc}")

    if cover_url:
        suffix = ".jpg"
        low = cover_url.lower()
        if ".png" in low:
            suffix = ".png"
        elif ".webp" in low:
            suffix = ".webp"

        out = DELIVERY_COVER_DIR / (output_stem + "__cover" + suffix)

        headers = {
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://www.xiaohongshu.com/",
            "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
        }

        try:
            r = requests.get(cover_url, headers=headers, timeout=60)
            r.raise_for_status()
            out.write_bytes(r.content)

            if out.exists() and out.stat().st_size > 1024:
                print(f"已保存原封面：{out}")
                return str(out)

            print(f"原封面文件过小，改用视频抽帧：{out}")
        except Exception as exc:
            print(f"原封面下载失败，改用视频抽帧：{exc}")

    # 兜底：拿不到平台原封面时，从视频 0.8 秒抽一帧，保证后续发布至少有封面文件。
    try:
        source = Path(source)
        frame_out = DELIVERY_COVER_DIR / (output_stem + "__cover_frame.jpg")
        cmd = [
            ffmpeg_bin(),
            "-y",
            "-ss", "0.8",
            "-i", str(source),
            "-frames:v", "1",
            "-q:v", "2",
            str(frame_out),
        ]
        proc = subprocess.run(cmd, cwd=str(PROJECT_ROOT), text=True, capture_output=True, timeout=90)
        if frame_out.exists() and frame_out.stat().st_size > 1024:
            print(f"未找到原封面URL，已从视频抽帧生成候选封面：{frame_out}")
            return str(frame_out)

        print(f"视频抽帧封面失败：returncode={proc.returncode} stderr={proc.stderr[-500:] if proc.stderr else ''}")
    except Exception as exc:
        print(f"视频抽帧封面异常：{exc}")

    return None


# XHS_NO_SLOW_DETAIL_TITLE_COVER_PATCH
# 覆盖前面可能存在的慢详情刷新函数：
# 1）标题优先用筛选报告，其次本地 source 缓存文件名；
# 2）不再为了标题/封面调用慢接口；
# 3）没有原封面 URL 时直接从视频抽帧，确保后续发布有封面文件。

def xhs_v3_title_for_delivery(item: dict, idx: int, url: str = "") -> str:
    title = str((item or {}).get("title") or "").strip()
    note_id = xhs_v3_note_id_for_delivery(item, url)

    if (not title) or xhs_v3_is_note_id_like(title) or (note_id and title == note_id):
        cached = xhs_v3_cached_title_for_delivery(item, url)
        if cached:
            title = cached

    if (not title) or xhs_v3_is_note_id_like(title):
        title = f"作品{idx}"

    item["title"] = title
    return title


def xhs_v3_count_delivery_titles(items: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for i, item in enumerate(items or [], start=1):
        url = item.get("url") or item.get("note_url") or ""
        title = xhs_v3_title_for_delivery(item, i, url)
        base = safe_name(title, f"作品{i}")
        counts[base] = counts.get(base, 0) + 1

    print("交付标题重复检测：")
    for base, count in counts.items():
        print(f"- {base}：{count}")
    return counts


def xhs_v3_save_cover_or_frame(item: dict, title: str, output_stem: str, source: Path, note_url: str = "") -> str | None:
    DELIVERY_COVER_DIR.mkdir(parents=True, exist_ok=True)

    cover_url = ""
    try:
        cover_url = xhs_v3_extract_cover_url(item)
    except Exception:
        cover_url = ""

    if cover_url:
        suffix = ".jpg"
        low = cover_url.lower()
        if ".png" in low:
            suffix = ".png"
        elif ".webp" in low:
            suffix = ".webp"

        out = DELIVERY_COVER_DIR / (output_stem + "__cover" + suffix)
        headers = {
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://www.xiaohongshu.com/",
            "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
        }

        try:
            r = requests.get(cover_url, headers=headers, timeout=15)
            r.raise_for_status()
            out.write_bytes(r.content)
            if out.exists() and out.stat().st_size > 1024:
                print(f"已保存原封面：{out}")
                return str(out)
        except Exception as exc:
            print(f"原封面下载失败，改用视频抽帧：{exc}")

    try:
        source = Path(source)
        frame_out = DELIVERY_COVER_DIR / (output_stem + "__cover_frame.jpg")
        cmd = [
            ffmpeg_bin(),
            "-y",
            "-ss", "0.8",
            "-i", str(source),
            "-frames:v", "1",
            "-q:v", "2",
            str(frame_out),
        ]

        proc = subprocess.run(
            cmd,
            cwd=str(PROJECT_ROOT),
            text=True,
            capture_output=True,
            timeout=45,
        )

        if frame_out.exists() and frame_out.stat().st_size > 1024:
            print(f"未找到原封面URL，已从视频抽帧生成候选封面：{frame_out}")
            return str(frame_out)

        print(f"视频抽帧封面失败：returncode={proc.returncode}")
    except Exception as exc:
        print(f"视频抽帧封面异常：{exc}")

    return None


def parse_bgm_instruction(text: str) -> str | None:
    m = re.search(r"(?:BGM|bgm|音乐|配乐)[^\n\r]*(https?://[^\s，。；;]+)", text, flags=re.I)
    if m:
        return m.group(1).strip().rstrip("。；;,，")

    patterns = [
        r"(?:BGM|bgm)\s*(?:用|使用|换成|选择|找|搜索)\s*(.+)",
        r"(?:音乐|配乐)\s*(?:用|使用|换成|选择|找|搜索)\s*(.+)",
    ]

    for pattern in patterns:
        m = re.search(pattern, text, flags=re.I | re.S)
        if not m:
            continue

        value = m.group(1).strip()

        # 保留欧美音乐，要今年4月后的新歌这种约束；
        # 只截断真正属于后续执行控制的话。
        stop_patterns = [
            r"从第?\s*\d+(?:\.\d+)?\s*秒开始",
            r"从\s*\d+(?:\.\d+)?\s*s\s*开始",
            r"起始(?:秒数|位置)?\s*\d+(?:\.\d+)?",
            r"正式生成",
            r"强制重新处理",
            r"强制重做",
            r"只下载原视频",
            r"只要原视频",
            r"不要换BGM",
            r"不换BGM",
            r"保留原声",
        ]

        cut = len(value)
        for sp in stop_patterns:
            sm = re.search(sp, value, flags=re.I)
            if sm:
                cut = min(cut, sm.start())

        value = value[:cut].strip()
        value = value.strip(" ，。；;、")
        return value or None

    return None

def parse_bgm_start_seconds(text: str) -> float:
    patterns = [
        r"(?:BGM|bgm|音乐|配乐)?\s*从第?\s*(\d+(?:\.\d+)?)\s*秒开始",
        r"(?:BGM|bgm|音乐|配乐)?\s*从\s*(\d+(?:\.\d+)?)\s*s\s*开始",
    ]
    for pattern in patterns:
        m = re.search(pattern, text, flags=re.I)
        if m:
            return float(m.group(1))
    return 0.0


def is_dry_run(text: str) -> bool:
    t = text.lower()
    return any(x in t for x in ["dry-run", "dry run", "先看看", "先筛选", "预览", "不要生成", "不生成"])


def is_original_only(text: str) -> bool:
    return any(x in text for x in ["只要原视频", "只下载原视频", "不换BGM", "不要换BGM", "保留原声"])


def ffmpeg_bin() -> str:
    found = shutil.which("ffmpeg")
    if found:
        return found
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception as e:
        raise RuntimeError(f"找不到 ffmpeg：{e}")


def resolve_bgm_query(intent: str) -> tuple[str, str]:
    intent = (intent or "").strip()
    if not intent:
        raise RuntimeError("正式生成换 BGM 时必须提供 BGM 描述、歌名、搜索词或链接。")

    if re.match(r"https?://", intent, flags=re.I):
        return intent, f"用户直接提供 BGM 链接：{intent}"

    resolver = PROJECT_ROOT / "scripts" / "bgm_smart_resolver.py"
    if resolver.exists():
        proc = subprocess.run(
            [str(PYTHON_EXE), str(resolver), "--intent", intent, "--json", "--max-per-query", "5"],
            cwd=str(PROJECT_ROOT),
            text=True,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=240,
        )
        if proc.returncode == 0:
            data = json.loads(proc.stdout)
            selected = data.get("selected_url") or intent
            title = data.get("selected_title") or selected
            score = data.get("score")
            return selected, f"智能BGM解析：{title}"
        else:
            print("智能BGM解析失败，回退原始词：")
            print((proc.stderr or proc.stdout or "")[-800:])

    return intent, f"回退为原始 BGM 搜索词：{intent}"


def download_bgm(query: str, work_dir: Path) -> Path:
    bgm_dir = work_dir / "bgm"
    bgm_dir.mkdir(parents=True, exist_ok=True)

    safe_q = safe_name(query, "bgm")[:60]
    out_tpl = str(bgm_dir / f"{safe_q}.%(ext)s")
    target = query if re.match(r"https?://", query, flags=re.I) else f"ytsearch1:{query}"

    cmd = [
        sys.executable,
        "-m",
        "yt_dlp",
        "--no-playlist",
        "-x",
        "--audio-format",
        "mp3",
        "-o",
        out_tpl,
        target,
    ]

    ffmpeg = ffmpeg_bin()
    cmd[3:3] = ["--ffmpeg-location", str(Path(ffmpeg).parent)]

    print("下载 BGM：")
    print(" ".join(cmd))

    proc = subprocess.run(
        cmd,
        cwd=str(PROJECT_ROOT),
        text=True,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        timeout=300,
    )
    if proc.returncode != 0:
        raise RuntimeError("BGM 下载失败：" + ((proc.stderr or proc.stdout or "")[-1200:]))

    mp3s = sorted(bgm_dir.glob("*.mp3"), key=lambda x: x.stat().st_mtime, reverse=True)
    if not mp3s:
        raise RuntimeError("BGM 下载完成但没有生成 mp3 文件。")
    return mp3s[0]


def replace_bgm(source: Path, bgm: Path, out: Path, start: float) -> None:
    ffmpeg = ffmpeg_bin()
    out.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        ffmpeg,
        "-y",
        "-i",
        str(source),
        "-stream_loop",
        "-1",
    ]

    if start > 0:
        cmd += ["-ss", str(start)]

    cmd += [
        "-i",
        str(bgm),
        "-map",
        "0:v:0",
        "-map",
        "1:a:0",
        "-c:v",
        "copy",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-shortest",
        str(out),
    ]

    proc = subprocess.run(cmd, text=True, capture_output=True, encoding="utf-8", errors="replace", timeout=360)

    if proc.returncode != 0:
        # 降级重编码
        cmd2 = [
            ffmpeg,
            "-y",
            "-i",
            str(source),
            "-stream_loop",
            "-1",
        ]
        if start > 0:
            cmd2 += ["-ss", str(start)]
        cmd2 += [
            "-i",
            str(bgm),
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "20",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-shortest",
            str(out),
        ]
        proc = subprocess.run(cmd2, text=True, capture_output=True, encoding="utf-8", errors="replace", timeout=720)

    if proc.returncode != 0:
        raise RuntimeError("ffmpeg 失败：" + ((proc.stderr or proc.stdout or "")[-1200:]))

    if not out.exists() or out.stat().st_size <= 0:
        raise RuntimeError("ffmpeg 返回成功但输出文件不存在或为空。")



def normalize_text_for_execution(text: str) -> tuple[str, dict]:
    """
    主链路入口：先把钉钉自然语言归一化为标准任务。
    失败时不阻断旧链路，但会打印提示。
    """
    try:
        from scripts.xhs_intent_normalizer import normalize_and_build_message
        intent, canonical = normalize_and_build_message(text)
        print("XHS_INTENT_NORMALIZED：")
        print(canonical)
        return canonical, intent
    except Exception as exc:
        print(f"XHS_INTENT_NORMALIZE_FAILED：{exc}")
        return text, {}


def run_author_filter(message: str, api_base: str) -> Path:
    """
    EMERGENCY_FAST_REPORT_PATCH:
    当前调试阶段不再重复浏览主页、不再等 quick_bgm dry-run。
    优先复用环境变量 XHS_DIRECT_V2_FILTER_REPORT 指向的筛选报告。
    """
    forced = os.environ.get("XHS_DIRECT_V2_FILTER_REPORT", "").strip().strip('"')
    if forced:
        forced_path = Path(forced)
        if forced_path.exists():
            print(f"XHS_DIRECT_V2：复用指定筛选报告，跳过作者主页筛选：{forced_path}")
            return forced_path
        print(f"指定筛选报告不存在，继续尝试最新报告：{forced_path}")

    candidates = list(REPORT_DIR.glob("author_auto_filter_*.json"))
    if not candidates:
        raise RuntimeError("没有找到 author_auto_filter_*.json，不能复用筛选报告。")

    latest = sorted(candidates, key=lambda x: x.stat().st_mtime, reverse=True)[0]
    print(f"XHS_DIRECT_V2：复用最新筛选报告，跳过作者主页筛选：{latest}")
    return latest

def _norm_video_url(url: str) -> str:
    url = str(url or "").strip().strip("'\"")
    url = url.replace("\\u002F", "/").replace("\\/", "/")
    if url.startswith("//"):
        url = "https:" + url
    return url


def _looks_like_direct_video_url(url: str) -> bool:
    u = _norm_video_url(url)
    low = u.lower()

    if not u.startswith("http"):
        return False

    # 排除小红书作品页/主页链接，它们不是视频文件直链
    if "xiaohongshu.com/discovery/item" in low:
        return False
    if "xiaohongshu.com/explore/" in low:
        return False
    if "xiaohongshu.com/user/profile" in low:
        return False

    # 小红书视频 CDN 常见特征
    video_signals = [
        "sns-video",
        "sns-bak",
        "xhscdn.com",
        "xhs-video",
        ".mp4",
        "video",
    ]

    return any(x in low for x in video_signals)


def _walk_strings(obj):
    if isinstance(obj, dict):
        for v in obj.values():
            yield from _walk_strings(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk_strings(v)
    elif isinstance(obj, str):
        yield obj


def _candidate_video_urls_from_item(item: dict) -> list[str]:
    candidates: list[str] = []

    # 优先从明确字段拿
    priority_keys = [
        "video_download_url",
        "preview_video_url",
        "video_url",
        "download_url",
        "play_url",
        "master_url",
        "url_default",
        "local_video_url",
    ]

    for key in priority_keys:
        value = item.get(key)
        if isinstance(value, str) and _looks_like_direct_video_url(value):
            candidates.append(_norm_video_url(value))
        elif isinstance(value, list):
            for x in value:
                if isinstance(x, str) and _looks_like_direct_video_url(x):
                    candidates.append(_norm_video_url(x))

    # 再从整个 item 递归扫描 sns-video / xhscdn 字符串
    for value in _walk_strings(item):
        if _looks_like_direct_video_url(value):
            candidates.append(_norm_video_url(value))

    # 去重，保序
    out: list[str] = []
    seen = set()
    for u in candidates:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


def _refresh_item_detail_for_video_url(note_url: str) -> dict:
    """
    如果筛选报告里没带视频直链，就重新调用本项目已有 preview_note_link。
    注意：只拿 detail 元数据，不使用 download_note_video。
    """
    try:
        from scripts.xhs_author_auto_pipeline import preview_note_link
        data = preview_note_link(note_url)
        return data or {}
    except Exception as exc:
        print(f"重新 preview_note_link 失败：{exc}")
        return {}


def _download_url_to_file(url: str, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36",
        "Referer": "https://www.xiaohongshu.com/",
        "Accept": "*/*",
        "Connection": "keep-alive",
    }

    print(f"直链下载视频：{url}")
    with requests.get(url, headers=headers, stream=True, timeout=90) as r:
        r.raise_for_status()
        total = 0
        with open(output_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=1024 * 1024):
                if not chunk:
                    continue
                f.write(chunk)
                total += len(chunk)

    if not output_path.exists() or output_path.stat().st_size < 100 * 1024:
        raise RuntimeError(f"直链下载结果异常，文件过小：{output_path} size={output_path.stat().st_size if output_path.exists() else 0}")

    return output_path



def _extract_note_id_from_any_text(text: str) -> str:
    text = str(text or "").strip()
    if not text:
        return ""
    m = re.search(r"/(?:discovery/item|explore)/([0-9a-fA-F]{12,32})", text)
    if m:
        return m.group(1)
    m = re.search(r"([0-9a-fA-F]{20,32})", text)
    if m:
        return m.group(1)
    return ""


def _note_id_for_cache_lookup(item: dict, note_url: str = "") -> str:
    if isinstance(item, dict):
        for key in ["note_id", "noteId", "note_id_str", "noteIdStr", "id"]:
            value = str(item.get(key) or "").strip()
            if re.fullmatch(r"[0-9a-fA-F]{12,32}", value):
                return value

        for key in ["url", "note_url", "share_url", "xhs_url"]:
            value = str(item.get(key) or "").strip()
            nid = _extract_note_id_from_any_text(value)
            if nid:
                return nid

    return _extract_note_id_from_any_text(note_url)


def _find_cached_source_video_for_note_id(note_id: str) -> Path | None:
    note_id = str(note_id or "").strip()
    if not note_id:
        return None

    try:
        candidates = []
        for p in TEMP_DIR.glob("direct_generate_real_v3_*/**/*__source_*.mp4"):
            try:
                if note_id in str(p) and p.is_file() and p.stat().st_size > 100 * 1024:
                    candidates.append(p)
            except Exception:
                continue

        if not candidates:
            return None

        candidates.sort(key=lambda x: x.stat().st_mtime, reverse=True)
        return candidates[0]
    except Exception as exc:
        print(f"查找本地原视频缓存失败：{exc}")
        return None


def _title_from_cached_source_path(path: Path) -> str:
    try:
        name = path.name
        title = name.split("__source_", 1)[0].strip()
        if title and not re.fullmatch(r"[0-9a-fA-F]{16,32}", title):
            return title
    except Exception:
        pass
    return ""

def _download_selected_video_direct(item: dict, item_dir: Path) -> dict:
    """
    关键修复：
    不再调用 app.quick_bgm.xhs_creator_importer.download_note_video，
    因为它在当前链路下会反复返回同一个本地文件。
    这里直接使用每条作品自己的视频 CDN 直链下载。
    """
    title = item.get("title") or item.get("note_id") or "video"
    note_url = item.get("url") or item.get("note_url") or ""
    note_id = str(item.get("note_id") or "").strip()

    # 标题保护：quick_bgm dry-run 失败反写时，可能把真实标题覆盖成 note_id。
    # 如果 title 看起来就是 note_id，则尝试重新取作品详情里的真实标题/封面。
    raw_title = str(title or "").strip()
    looks_like_note_id = bool(re.fullmatch(r"[0-9a-fA-F]{16,32}", raw_title)) or (note_id and raw_title == note_id)
    if looks_like_note_id and note_url:
        print(f"标题疑似被 note_id 覆盖，尝试重新获取作品标题：{raw_title}")
        try:
            detail_for_title = _refresh_item_detail_for_video_url(note_url) or {}
        except Exception as exc:
            print(f"重新获取标题失败：{exc}")
            detail_for_title = {}

        title_keys = ["title", "display_title", "note_title", "desc", "description", "name"]
        for k in title_keys:
            v = detail_for_title.get(k)
            if isinstance(v, str) and v.strip() and not re.fullmatch(r"[0-9a-fA-F]{16,32}", v.strip()):
                title = v.strip()
                item["title"] = title
                print(f"已恢复作品标题：{title}")
                break

        cover_keys = ["cover_url", "cover", "image", "image_url", "thumbnail", "thumbnail_url"]
        if not item.get("cover_url"):
            for k in cover_keys:
                v = detail_for_title.get(k)
                if isinstance(v, str) and v.startswith("http"):
                    item["cover_url"] = v
                    print(f"已补充封面URL：{v}")
                    break

    candidates = _candidate_video_urls_from_item(item)

    if not candidates and note_url:
        print("筛选报告里没有视频直链，重新获取作品详情。")
        detail = _refresh_item_detail_for_video_url(note_url)
        if detail:
            candidates = _candidate_video_urls_from_item(detail)
            item.update(detail)

    print("视频直链候选：")
    for i, u in enumerate(candidates, start=1):
        print(f"- {i}. {u[:220]}")

    if not candidates:
        cache_note_id = _note_id_for_cache_lookup(item, note_url)
        cached_source = _find_cached_source_video_for_note_id(cache_note_id)

        if cached_source:
            cached_title = _title_from_cached_source_path(cached_source)
            if cached_title:
                title = cached_title
                item["title"] = cached_title
                print(f"未拿到视频直链，但已从本地缓存恢复标题：{cached_title}")

            print(f"未拿到视频直链，复用本地原视频缓存：{cached_source}")
            return {
                "ok": True,
                "local_video_path": str(cached_source),
                "video_url": f"local-cache:{cached_source}",
            }

        raise RuntimeError(f"没有找到视频直链，且没有可复用的本地原视频缓存。note_url={note_url}")

    last_error = None
    for i, video_url in enumerate(candidates, start=1):
        try:
            out_name = f"{safe_name(title, 'video')}__source_{i}.mp4"
            out_path = item_dir / out_name
            _download_url_to_file(video_url, out_path)

            return {
                "ok": True,
                "local_video_path": str(out_path),
                "video_url": video_url,
            }
        except Exception as exc:
            last_error = exc
            print(f"候选直链下载失败：{exc}")

    raise RuntimeError(f"所有视频直链下载失败：{last_error}")




# ===== PATCH_FAST: 原封面单独保存，不嵌入视频 =====
def patch_fast_walk_obj(obj):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield k, v
            yield from patch_fast_walk_obj(v)
    elif isinstance(obj, list):
        for v in obj:
            yield "", v
            yield from patch_fast_walk_obj(v)

def patch_fast_extract_cover_url(item: dict) -> str | None:
    keys = ("cover", "cover_url", "image", "image_url", "thumbnail", "thumb", "poster")
    for key, value in patch_fast_walk_obj(item or {}):
        if not isinstance(value, str):
            continue
        u = value.strip().replace("\\u002F", "/").replace("\\/", "/")
        low = u.lower()
        key_low = (key or "").lower()
        if not low.startswith("http"):
            continue
        if any(x in low for x in [".mp4", ".m3u8", "video"]):
            continue
        if any(k in key_low for k in keys) or any(x in low for x in [".jpg", ".jpeg", ".png", ".webp"]):
            return u
    return None

def patch_fast_save_original_cover(item: dict, title: str) -> str | None:
    try:
        url = patch_fast_extract_cover_url(item)
        if not url:
            print("未找到原封面URL，跳过封面保存。")
            return None

        suffix = ".jpg"
        low = url.lower()
        if ".png" in low:
            suffix = ".png"
        elif ".webp" in low:
            suffix = ".webp"

        DELIVERY_DIR.mkdir(parents=True, exist_ok=True)
        out = DELIVERY_DIR / (safe_name(title, "cover") + "__原封面" + suffix)

        headers = {
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://www.xiaohongshu.com/",
            "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
        }
        r = requests.get(url, headers=headers, timeout=60)
        r.raise_for_status()
        out.write_bytes(r.content)

        if out.exists() and out.stat().st_size > 1024:
            print(f"已保存原封面：{out}")
            return str(out)

        print(f"原封面文件过小，跳过：{out}")
        return None
    except Exception as exc:
        print(f"原封面保存失败：{exc}")
        return None




# ===== PATCH_REAL_V3: 真多BGM版本 + 原封面保存 =====
def xhs_v3_parse_bgm_variant_count(text: str) -> int:
    t = text or ""
    zh_num = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5}
    patterns = [
        r"每条(?:视频|作品)?[^\n\r]{0,18}(\d+)\s*(?:个|款|版|种|首)?\s*(?:不同)?\s*(?:BGM|bgm|音乐|配乐|版本)",
        r"每条(?:视频|作品)?[^\n\r]{0,18}([一二两三四五])\s*(?:个|款|版|种|首)?\s*(?:不同)?\s*(?:BGM|bgm|音乐|配乐|版本)",
        r"(\d+)\s*(?:个|款|版|种|首)\s*(?:不同)?\s*(?:BGM|bgm|音乐|配乐)",
        r"([一二两三四五])\s*(?:个|款|版|种|首)\s*(?:不同)?\s*(?:BGM|bgm|音乐|配乐)",
    ]
    for p in patterns:
        m = re.search(p, t, flags=re.I)
        if not m:
            continue
        raw = m.group(1)
        n = int(raw) if raw.isdigit() else zh_num.get(raw, 1)
        return max(1, min(5, n))
    return 1

def xhs_v3_bad_bgm_text(text: str) -> bool:
    blob = re.sub(r"\s+", " ", str(text or "").lower())
    bad_words = [
        "india", "indian", "hindi", "bollywood", "punjabi", "tamil", "bhojpuri",
        "indonesia", "indonesian", "indo ", "印尼",
        "instagram reels india", "reels india", "indian reels",
        "sing-off", "sing off", "montagem", "montage",
        "playlist", "nonstop", "top 100", "top100", "mashup", "合集", "串烧", "歌单",
        "周杰伦", "告白气球", "jay chou", "中文", "华语", "抖音神曲"
    ]
    return any(w in blob for w in bad_words)


def xhs_v3_load_seed_bgm_queries() -> list[str]:
    seed_file = PROJECT_ROOT / "config" / "bgm_jk_outfit_seed_queries.txt"
    if not seed_file.exists():
        return []
    lines = []
    for line in seed_file.read_text(encoding="utf-8").splitlines():
        s = line.strip().lstrip("\ufeff")
        if not s or s.startswith("#"):
            continue
        lines.append(s)
    return list(dict.fromkeys(lines))

def xhs_v3_seed_queries_for_variant(variant_index: int) -> list[str]:
    """
    短期稳定策略：
    不再广泛搜索 TikTok 2026 trending songs，避免命中印度/印尼/Reels 合集。
    先从日韩穿搭安全候选池里轮换选歌。
    """
    seeds = xhs_v3_load_seed_bgm_queries()
    if not seeds:
        return []
    start = (variant_index - 1) % len(seeds)
    ordered = seeds[start:] + seeds[:start]
    return ordered[:8]

def xhs_v3_variant_intents(base: str, variant_index: int) -> list[str]:
    seed_queries = xhs_v3_seed_queries_for_variant(variant_index)
    if seed_queries:
        print(f"使用日韩穿搭 BGM 种子池，第 {variant_index} 版候选：")
        for q in seed_queries[:3]:
            print(f"- {q}")
        return seed_queries

    base = (base or "日韩 TikTok 穿搭 OOTD 热门 BGM").strip()
    return [
        f"{base} 日本 TikTok 穿搭 OOTD J-pop official audio",
        f"{base} 韩国 TikTok 穿搭 OOTD K-pop official audio",
        f"{base} 日韩 TikTok lookbook fashion outfit official audio",
    ]

def xhs_v3_prepare_bgm_variants(base_intent: str, count: int, work_dir: Path) -> list[dict]:
    variants = []
    used = set()

    for v in range(1, count + 1):
        chosen = None
        errors = []

        for intent in xhs_v3_variant_intents(base_intent, v):
            try:
                print(f"尝试解析 BGM{v:02d}：{intent}")
                resolved, info = resolve_bgm_query(intent)
                check_text = f"{resolved} {info}"

                if xhs_v3_bad_bgm_text(check_text):
                    errors.append(f"拒绝无关BGM：{info}")
                    print(f"拒绝无关BGM：{info}")
                    continue

                if resolved in used:
                    errors.append(f"拒绝重复BGM：{info}")
                    print(f"拒绝重复BGM：{info}")
                    continue

                bgm_path = download_bgm(resolved, work_dir / f"bgm_{v:02d}")
                bgm_hash = sha16(bgm_path)

                if bgm_hash in used:
                    errors.append(f"拒绝重复BGM文件：{bgm_path}")
                    print(f"拒绝重复BGM文件：{bgm_path}")
                    continue

                used.add(resolved)
                used.add(bgm_hash)

                chosen = {
                    "index": v,
                    "intent": intent,
                    "resolved": resolved,
                    "info": info,
                    "path": bgm_path,
                    "hash": bgm_hash,
                }
                print(f"已准备 BGM{v:02d}：{info}")
                print(f"BGM{v:02d} 文件：{bgm_path}")
                print(f"BGM{v:02d} Hash：{bgm_hash}")
                break

            except Exception as exc:
                errors.append(str(exc))
                print(f"BGM{v:02d} 候选失败：{exc}")

        if not chosen:
            raise RuntimeError(
                f"BGM{v:02d} 没找到合格候选，已拒绝生成错误视频。最近错误："
                + " | ".join(errors[-5:])
            )

        variants.append(chosen)

    return variants

def xhs_v3_walk_obj(obj):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield k, v
            yield from xhs_v3_walk_obj(v)
    elif isinstance(obj, list):
        for v in obj:
            yield "", v
            yield from xhs_v3_walk_obj(v)

def xhs_v3_extract_cover_url(item: dict) -> str | None:
    cover_keys = ("cover", "cover_url", "image", "image_url", "thumbnail", "thumb", "poster")
    for key, value in xhs_v3_walk_obj(item or {}):
        if not isinstance(value, str):
            continue

        u = value.strip().replace("\\u002F", "/").replace("\\/", "/")
        low = u.lower()
        key_low = (key or "").lower()

        if not low.startswith("http"):
            continue
        if any(x in low for x in [".mp4", ".m3u8", "video"]):
            continue

        if any(k in key_low for k in cover_keys):
            return u

        if any(x in low for x in [".jpg", ".jpeg", ".png", ".webp"]) and any(x in low for x in ["image", "cover", "sns"]):
            return u

    return None

def xhs_v3_save_original_cover(item: dict, title: str, note_url: str = "") -> str | None:
    try:
        cover_url = xhs_v3_extract_cover_url(item)

        if not cover_url and note_url:
            print("当前筛选数据没有封面URL，尝试重新获取作品详情。")
            detail = _refresh_item_detail_for_video_url(note_url)
            if detail:
                item.update(detail)
                cover_url = xhs_v3_extract_cover_url(item)

        if not cover_url:
            print("未找到原封面URL，跳过封面保存。")
            return None

        suffix = ".jpg"
        low = cover_url.lower()
        if ".png" in low:
            suffix = ".png"
        elif ".webp" in low:
            suffix = ".webp"

        DELIVERY_DIR.mkdir(parents=True, exist_ok=True)
        out = DELIVERY_DIR / (safe_name(title, "cover") + "__原封面" + suffix)

        headers = {
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://www.xiaohongshu.com/",
            "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
        }

        r = requests.get(cover_url, headers=headers, timeout=60)
        r.raise_for_status()
        out.write_bytes(r.content)

        if out.exists() and out.stat().st_size > 1024:
            print(f"已保存原封面：{out}")
            return str(out)

        print(f"原封面文件过小，跳过：{out}")
        return None

    except Exception as exc:
        print(f"原封面保存失败：{exc}")
        return None


def main() -> int:
    # XHS_DIRECT_V2_LOCK_FILE: avoid duplicate concurrent Dingtalk executions
    lock_file = PROJECT_ROOT / ".runtime" / "xhs_direct_v2" / "direct_v2_running.lock"
    lock_file.parent.mkdir(parents=True, exist_ok=True)
    if lock_file.exists():
        try:
            age = time.time() - lock_file.stat().st_mtime
        except Exception:
            age = 0
        if age < 1800:
            print("XHS_DIRECT_V2_LOCKED: ???? direct_v2 ???????????????")
            print(f"lock_file={lock_file}")
            print(f"lock_age_seconds={age:.1f}")
            return 2
        else:
            print("XHS_DIRECT_V2_LOCK_STALE: ???????????")
            try:
                lock_file.unlink()
            except Exception:
                pass
    lock_file.write_text(str(os.getpid()), encoding="utf-8")
    try:
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

        print("XHS_DIRECT_V2：启动。当前为 REAL_V3，多BGM版本会在单次筛选后生成，避免重复浏览主页。")

        exec_text, intent_json = normalize_text_for_execution(text)
        parse_only_markers = [
            "\u53ea\u505a\u8bca\u65ad",
            "\u8bca\u65ad\u6a21\u5f0f",
            "\u53ea\u505a\u53c2\u6570\u89e3\u6790",
            "\u53ea\u89e3\u6790\u53c2\u6570",
            "\u53ea\u8fd4\u56de\u89e3\u6790\u7ed3\u679c",
            "\u4e0d\u751f\u6210\u4e0d\u4e0b\u8f7d",
            "\u4e0d\u4e0b\u8f7d\u4e0d\u751f\u6210",
        ]
        parse_only = any(k in text for k in parse_only_markers) or any(k in exec_text for k in parse_only_markers)
        if parse_only:
            raw_bgm_variant_count = xhs_v3_parse_bgm_variant_count(text)
            exec_bgm_variant_count = xhs_v3_parse_bgm_variant_count(exec_text)
            original_only_tmp = is_original_only(exec_text)
            final_bgm_variant_count = 1 if original_only_tmp else max(raw_bgm_variant_count, exec_bgm_variant_count)
            _loc = locals()
            print("XHS_PARSE_ONLY_MODE: YES")
            print("XHS_PARSE_ONLY: no homepage open, no download, no generate")
            print("creator =", _loc.get("creator_url") or _loc.get("xhs_id") or _loc.get("raw_query"))
            print("limit =", _loc.get("limit"))
            print("min_likes =", _loc.get("min_likes"))
            print("bgm_variant_count_raw =", raw_bgm_variant_count)
            print("bgm_variant_count_normalized =", exec_bgm_variant_count)
            print("bgm_variant_count_final =", final_bgm_variant_count)
            print("bgm_query =", parse_bgm_instruction(exec_text))
            print("bgm_start_seconds =", parse_bgm_start_seconds(exec_text))
            print("dry_run =", is_dry_run(exec_text))
            print("XHS_PARSE_ONLY_DONE")
            return 0
        report_path = run_author_filter(exec_text, args.api_base)
        report = json.loads(report_path.read_text(encoding="utf-8"))
        selected = report.get("selected") or []

        if not selected:
            print("没有筛选出可处理视频。")
            return 1

        print(f"筛选到 {len(selected)} 条：")
        for i, item in enumerate(selected, start=1):
            print(f"- {i}. {item.get('title')} | {item.get('url')}")

        if is_dry_run(exec_text):
            print("当前是 dry-run：只筛选，不生成。")
            return 0

        original_only = is_original_only(exec_text)
        bgm_intent = parse_bgm_instruction(exec_text)
        bgm_start = parse_bgm_start_seconds(exec_text)
        raw_bgm_variant_count = xhs_v3_parse_bgm_variant_count(text)
        exec_bgm_variant_count = xhs_v3_parse_bgm_variant_count(exec_text)
        bgm_variant_count = 1 if original_only else max(raw_bgm_variant_count, exec_bgm_variant_count)
        print(f"XHS_VARIANT_COUNT_DEBUG: raw={raw_bgm_variant_count}, normalized={exec_bgm_variant_count}, final={bgm_variant_count}")

        work_dir = TEMP_DIR / f"direct_generate_real_v3_{int(time.time())}"
        work_dir.mkdir(parents=True, exist_ok=True)
        DELIVERY_DIR.mkdir(parents=True, exist_ok=True)
        REPORT_DIR.mkdir(parents=True, exist_ok=True)

        bgm_variants = []
        if not original_only:
            if not bgm_intent:
                bgm_intent = "日韩 TikTok 穿搭 OOTD 热门 BGM"
            print(f"本次 BGM 版本数：{bgm_variant_count}")
            bgm_variants = xhs_v3_prepare_bgm_variants(bgm_intent, bgm_variant_count, work_dir)

        DELIVERY_VIDEO_DIR.mkdir(parents=True, exist_ok=True)
        DELIVERY_COVER_DIR.mkdir(parents=True, exist_ok=True)
        delivery_title_counts = xhs_v3_count_delivery_titles(selected)

        rows = []
        output_hash_groups: dict[str, list[str]] = {}
        input_hash_groups: dict[str, list[str]] = {}

        for idx, item in enumerate(selected, start=1):
            title = item.get("title") or f"作品{idx}"
            url = item.get("url") or item.get("note_url") or ""
            item_dir = work_dir / f"{idx:02d}_{safe_name(title)}"
            item_dir.mkdir(parents=True, exist_ok=True)

            print(f"\n==== XHS_DIRECT_V2 REAL_V3 第 {idx}/{len(selected)} 条 ====")
            print(f"标题：{title}")
            print(f"链接：{url}")

            try:
                dl = _download_selected_video_direct(item, item_dir)
            except Exception as exc:
                reason = str(exc)
                print(f"直链下载失败：{reason}")
                rows.append({"index": idx, "title": title, "url": url, "status": "failed", "reason": reason})
                continue

            source = Path(dl["local_video_path"])
            print(f"使用视频直链：{dl.get('video_url')}")
            source_hash = sha16(source)
            input_hash_groups.setdefault(source_hash, []).append(title)

            print(f"原视频路径：{source}")
            print(f"原视频大小：{source.stat().st_size}")
            print(f"原视频Hash：{source_hash}")

            title = xhs_v3_title_for_delivery(item, idx, url)
            item["title"] = title
            output_stem = xhs_v3_output_stem(title, item, idx, url, delivery_title_counts)
            cover_path = xhs_v3_save_cover_or_frame(item, title, output_stem, source, url)

            # 输出命名必须包含作品短 ID，避免同标题作品互相覆盖。
            title = item.get("title") or title or item.get("note_id") or f"作品{idx}"
            output_stem = xhs_v3_output_stem(title, item, idx, url, delivery_title_counts)

            if original_only:
                out = DELIVERY_VIDEO_DIR / (output_stem + "__原视频.mp4")
                shutil.copy2(source, out)
                out_hash = sha16(out)
                output_hash_groups.setdefault(out_hash, []).append(title)

                print(f"交付路径：{out}")
                print(f"交付大小：{out.stat().st_size}")
                print(f"交付Hash：{out_hash}")

                rows.append({
                    "index": idx,
                    "title": title,
                    "url": url,
                    "status": "done",
                    "variant": 0,
                    "source_path": str(source),
                    "source_size": source.stat().st_size,
                    "source_hash": source_hash,
                    "output_path": str(out),
                    "output_size": out.stat().st_size,
                    "output_hash": out_hash,
                    "cover_path": cover_path,
                })
                continue

            for bgm in bgm_variants:
                v = int(bgm["index"])
                out = DELIVERY_VIDEO_DIR / (output_stem + f"__BGM{v:02d}.mp4")

                replace_bgm(source, Path(bgm["path"]), out, bgm_start)

                out_hash = sha16(out)
                output_key = f"{output_stem}__BGM{v:02d}"
                output_hash_groups.setdefault(out_hash, []).append(output_key)

                print(f"交付路径：{out}")
                print(f"交付大小：{out.stat().st_size}")
                print(f"交付Hash：{out_hash}")

                rows.append({
                    "index": idx,
                    "title": title,
                    "url": url,
                    "status": "done",
                    "variant": v,
                    "bgm_info": bgm.get("info"),
                    "bgm_resolved": bgm.get("resolved"),
                    "bgm_path": str(bgm.get("path")),
                    "bgm_hash": bgm.get("hash"),
                    "source_path": str(source),
                    "source_size": source.stat().st_size,
                    "source_hash": source_hash,
                    "output_path": str(out),
                    "output_size": out.stat().st_size,
                    "output_hash": out_hash,
                    "cover_path": cover_path,
                })

        final_report = {
            "mode": "XHS_DIRECT_V2_REAL_V3",
            "message": text,
            "delivery_dir": str(DELIVERY_DIR),
            "bgm_intent": bgm_intent,
            "bgm_start_seconds": bgm_start,
            "bgm_variant_count": bgm_variant_count,
            "bgm_variants": [
                {
                    "index": x.get("index"),
                    "intent": x.get("intent"),
                    "resolved": x.get("resolved"),
                    "info": x.get("info"),
                    "path": str(x.get("path")),
                    "hash": x.get("hash"),
                }
                for x in bgm_variants
            ],
            "rows": rows,
            "input_hash_groups": input_hash_groups,
            "output_hash_groups": output_hash_groups,
        }

        final_report_path = REPORT_DIR / f"xhs_direct_v2_real_v3_report_{int(time.time())}.json"
        final_report_path.write_text(json.dumps(final_report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nXHS_DIRECT_V2 REAL_V3 报告：{final_report_path}")

        dup = {h: names for h, names in output_hash_groups.items() if len(names) > 1}
        if dup:
            print("严重错误：检测到重复输出 Hash，本次不视为成功：")
            for h, names in dup.items():
                print(f"- {h}: {names}")
            return 4

        done = sum(1 for r in rows if r.get("status") == "done")
        fail = len(rows) - done

        print(f"\nXHS_DIRECT_V2 REAL_V3 完成：成功 {done} 个成品，失败 {fail} 个。")
        print(f"交付目录：{DELIVERY_DIR}")
        return 0 if done else 1

    finally:
        try:
            lock_file.unlink()
        except Exception:
            pass

if __name__ == "__main__":
    raise SystemExit(main())
