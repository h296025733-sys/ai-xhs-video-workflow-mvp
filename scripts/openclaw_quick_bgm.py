import argparse
import json
import random
import shutil
import re
import sys
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import requests


URL_RE = re.compile(r"https?://[^\s<>'\"，。；;、]+", re.IGNORECASE)
TRAILING_PUNCTUATION = "，。；;、,.!?！？)]）】》\"'"


@dataclass
class MessagePlan:
    raw_message: str
    note_urls: list[str]
    video_paths: list[str]
    creator_home_url: str | None
    bgm_strategy: str
    bgm_query: str | None
    bgm_start_seconds: float
    replace_audio: bool
    dry_run: bool
    force_reimport: bool
    random_music_count: int
    delivery_dir: str | None
    warnings: list[str]


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DELIVERY_DIR = Path(os.getenv("VIDEO_DELIVERY_DIR", PROJECT_ROOT / "outputs" / "小红书单条"))
DELIVERY_STATE_FILE = Path(os.getenv("VIDEO_DELIVERY_STATE_FILE", PROJECT_ROOT / ".runtime" / "last_delivery_dir.txt"))


def parse_delivery_dir(text: str) -> str | None:
    # 先移除 URL，避免保存到 D:\xxx：https://...把链接吞进目录
    cleaned = re.sub(r"https?://[^\s<>'\"，。；;]+", "", text or "", flags=re.IGNORECASE)
    patterns = [
        r"(?:保存到|输出到|放到|存到)\s*([A-Za-z]:\\[^\n\r，。；;]+)",
        r"(?:保存目录|输出目录)\s*[：:]\s*([A-Za-z]:\\[^\n\r，。；;]+)",
    ]
    for pattern in patterns:
        m = re.search(pattern, cleaned, flags=re.IGNORECASE)
        if m:
            value = m.group(1).strip().strip("\"'").rstrip(" ：:，。；;")
            if value:
                return value
    return None


def effective_delivery_dir(plan: MessagePlan) -> Path:
    if plan.delivery_dir:
        return Path(plan.delivery_dir)
    if DELIVERY_STATE_FILE.exists():
        saved = DELIVERY_STATE_FILE.read_text(encoding="utf-8").strip()
        if saved:
            return Path(saved)
    return DEFAULT_DELIVERY_DIR


def _safe_filename_stem(value: str, fallback: str = "未命名视频") -> str:
    value = (value or fallback).strip()
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "-", value)
    value = re.sub(r"\s+", " ", value).strip(" .-_")
    if not value:
        value = fallback
    return value[:80]


def _unique_path(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    for i in range(2, 1000):
        candidate = path.with_name(f"{stem}_{i}{suffix}")
        if not candidate.exists():
            return candidate
    return path.with_name(f"{stem}_{id(path)}{suffix}")


def apply_delivery_to_results(plan: MessagePlan, results: list[dict[str, Any]]) -> None:
    delivery_dir = effective_delivery_dir(plan)
    delivered_any = False

    for result in results:
        for item in result.get("items") or []:
            output = item.get("output_video_path")
            if not output:
                continue
            src = Path(output)
            if not src.exists():
                continue

            title = item.get("title") or src.stem
            action_name = "换BGM" if plan.replace_audio else "保留原声"
            filename = f"{_safe_filename_stem(title)}__{action_name}.mp4"
            target = _unique_path(delivery_dir / filename)

            shutil.copy2(src, target)
            item["delivery_video_path"] = str(target)
            item["delivery_dir"] = str(delivery_dir)
            delivered_any = True

    if delivered_any:
        DELIVERY_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        DELIVERY_STATE_FILE.write_text(str(delivery_dir), encoding="utf-8")


def extract_urls(message: str) -> list[str]:
    urls: list[str] = []
    for match in URL_RE.finditer(message or ""):
        url = match.group(0).rstrip(TRAILING_PUNCTUATION)
        if "xiaohongshu.com" in url or "xhslink.com" in url:
            urls.append(url)
    return list(dict.fromkeys(urls))


def _without_urls(message: str) -> str:
    return URL_RE.sub(" ", message or "")


def parse_seconds(text: str) -> float:
    normalized = text or ""
    minute_match = re.search(r"(\d+(?:\.\d+)?)\s*分(?:钟)?\s*(\d+(?:\.\d+)?)?\s*秒?", normalized)
    if minute_match:
        minutes = float(minute_match.group(1))
        seconds = float(minute_match.group(2) or 0)
        return round(minutes * 60 + seconds, 3)

    colon_match = re.search(r"\b(\d{1,2}):(\d{1,2})(?:\.(\d+))?\b", normalized)
    if colon_match:
        minutes = float(colon_match.group(1))
        seconds = float(colon_match.group(2) + ("." + colon_match.group(3) if colon_match.group(3) else ""))
        return round(minutes * 60 + seconds, 3)

    second_match = re.search(r"(?:BGM|bgm|音乐|从|第|起始|开始)[^\d]{0,8}(\d+(?:\.\d+)?)\s*秒", normalized)
    if second_match:
        return round(float(second_match.group(1)), 3)
    return 0.0


def parse_random_music_count(text: str) -> int:
    patterns = [
        r"随机(?:换成|使用|用|配)?\s*(\d+)\s*(?:首|个|段)?\s*(?:本地|热门|随机)?\s*(?:音乐|BGM|bgm)",
        r"(\d+)\s*(?:首|个|段)\s*(?:随机)?\s*(?:本地|热门)?\s*(?:音乐|BGM|bgm)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text or "", flags=re.IGNORECASE)
        if match:
            return max(1, min(int(match.group(1)), 20))
    return 1


def _clean_bgm_query(raw: str) -> str:
    query = raw.strip()
    query = re.split(r"(?:链接|小红书|视频|处理|生成|输出|下载|去掉原声|保留原声|从\d|BGM从|bgm从|先试算|dry)", query, maxsplit=1)[0]
    query = query.strip(" ：:，。；;、")
    query = re.sub(r"\s+", " ", query)
    return query


def parse_bgm_choice(message: str) -> tuple[str, str | None]:
    original = message or ""

    # 1. BGM 后面直接给链接：必须当作 BGM 搜索/下载源，不能混进小红书作品链接
    url_match = re.search(r"(?:BGM|bgm|音乐|配乐)[^\n\r]*?(https?://[^\s，。；;]+)", original, flags=re.IGNORECASE)
    if url_match:
        bgm_url = url_match.group(1).strip().rstrip("。；;,，")
        return "search_download", bgm_url

    text = _without_urls(original)
    lowered = text.lower()
    random_words = ("随机", "随便", "自动选")

    local_bgm_intent = re.search(r"(?:本地\s*(?:音乐|BGM|bgm)|(?:音乐|BGM|bgm)\s*本地)", text)
    if local_bgm_intent and any(word in text for word in random_words):
        return "local_random", None

    query_patterns = [
        r"(?:用|换成|换为|改成|配上|音乐用|BGM用|bgm用|BGM换成|bgm换成|搜索BGM[:：]?)\s*([^，。；;\n\r]+)",
        r"(?:音乐|BGM|bgm)\s*(?:是|:|：)\s*([^，。；;\n\r]+)",
        r"在线搜索BGM[:：]\s*([^，。；;\n\r]+)",
    ]

    for pattern in query_patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue

        query = _clean_bgm_query(match.group(1))
        if not query:
            continue

        compact = re.sub(r"\s+", "", query).lower()

        # 只有随机热门/随便/自动选/热门BGM这种纯随机意图才走随机；
        # 韩国女团热门歌 / Kpop热门 / 夏日热门韩系必须走搜索下载。
        random_only_values = {
            "随机", "随便", "自动选", "热门", "热门bgm", "热门音乐",
            "随机热门", "随机热门bgm", "随机热门音乐"
        }
        if compact in random_only_values or any(word == compact for word in random_words):
            break

        if len(query) <= 120:
            return "search_download", query

    if "热门" in text and any(word in text for word in random_words):
        return "top_used_random", None
    if "local_random" in lowered:
        return "local_random", None
    if "search_download" in lowered:
        return "search_download", None
    return "top_used_random", None


def parse_message(
    message: str,
    *,
    video_paths: list[str] | None = None,
    dry_run: bool | None = None,
    force_reimport: bool = False,
) -> MessagePlan:
    urls = extract_urls(message)
    creator_urls = [url for url in urls if "/user/profile/" in url]
    note_urls = [url for url in urls if url not in creator_urls]
    strategy, bgm_query = parse_bgm_choice(message)

    if bgm_query and re.match(r"https?://", bgm_query):
        bgm_url_clean = bgm_query.strip().rstrip("。；;,，")
        note_urls = [
            url for url in note_urls
            if url.strip().rstrip("。；;,，") != bgm_url_clean
        ]
    text = message or ""
    warnings: list[str] = []

    inferred_dry_run = bool(re.search(r"(先试算|试算|预览|dry[\s_-]?run|不要生成|先看看)", text, re.IGNORECASE))
    keep_audio = bool(re.search(r"(保留原声|不要替换原声|不去原声|别去原声)", text))
    inferred_force = bool(re.search(r"(重新处理|强制重跑|重新导入|force[_ -]?reimport)", text, re.IGNORECASE))

    if creator_urls and not note_urls:
        warnings.append("检测到小红书主页链接；当前主页最近 N 条尚未稳定自动抓取，请先提供作品链接。")
    elif creator_urls:
        warnings.append("已忽略小红书主页链接，只处理消息中的作品链接。")

    return MessagePlan(
        raw_message=message,
        note_urls=note_urls,
        video_paths=video_paths or [],
        creator_home_url=creator_urls[0] if creator_urls and not note_urls else None,
        bgm_strategy=strategy,
        bgm_query=bgm_query,
        bgm_start_seconds=parse_seconds(text),
        replace_audio=not keep_audio,
        dry_run=inferred_dry_run if dry_run is None else bool(dry_run),
        force_reimport=bool(force_reimport or inferred_force),
        random_music_count=parse_random_music_count(text),
        delivery_dir=parse_delivery_dir(text),
        warnings=warnings,
    )


def request_json(method: str, url: str, payload: dict[str, Any] | None = None, timeout: int = 600) -> dict[str, Any]:
    response = requests.request(method, url, json=payload, timeout=timeout)
    try:
        data = response.json()
    except ValueError:
        data = {"raw_text": response.text}
    if response.status_code >= 400:
        message = data.get("message_zh") or data.get("detail") or response.text
        raise RuntimeError(f"HTTP {response.status_code}: {message}")
    return data


def available_bgm_ids(api_base: str, strategy: str, count: int) -> list[str]:
    if count <= 1:
        return []
    data = request_json("GET", f"{api_base}/quick-bgm/bgm", timeout=120)
    items = [item for item in data.get("items") or [] if item.get("is_available") and item.get("bgm_id")]
    if strategy == "top_used_random":
        items = items[:5]
    random.shuffle(items)
    return [item["bgm_id"] for item in items[:count]]


def _source_payload(plan: MessagePlan, note_urls: list[str], video_paths: list[str], bgm_id: str | None = None) -> dict[str, Any]:
    if note_urls:
        source_type = "xhs_note_links"
    elif video_paths:
        source_type = "local_file"
    else:
        source_type = "manual"

    strategy = "selected" if bgm_id else plan.bgm_strategy
    if plan.bgm_query and strategy == "top_used_random":
        strategy = "search_download"

    return {
        "source_type": source_type,
        "note_urls": note_urls,
        "video_paths": video_paths,
        "replace_audio": plan.replace_audio,
        "bgm_strategy": strategy,
        "bgm_id": bgm_id,
        "bgm_query": plan.bgm_query,
        "bgm_start_seconds": plan.bgm_start_seconds,
        "force_reimport": plan.force_reimport,
        "dry_run": plan.dry_run,
    }


def create_and_maybe_run(api_base: str, payload: dict[str, Any], run: bool) -> dict[str, Any]:
    created = request_json("POST", f"{api_base}/quick-bgm/automation/create", payload)
    job_id = created.get("automation_job_id")
    if run and job_id and not payload.get("dry_run"):
        request_json("POST", f"{api_base}/quick-bgm/automation/{job_id}/run")
        return request_json("GET", f"{api_base}/quick-bgm/automation/{job_id}", timeout=120)
    return created


def execute_plan(plan: MessagePlan, api_base: str, run: bool) -> list[dict[str, Any]]:
    api_base = api_base.rstrip("/")
    if plan.creator_home_url and not plan.note_urls and not plan.video_paths:
        raise RuntimeError("当前只稳定支持小红书作品链接；主页最近 N 条请先用油猴脚本提取作品链接后再发给我。")
    if not plan.note_urls and not plan.video_paths:
        raise RuntimeError("没有检测到可处理的小红书作品链接或本地视频路径。")

    source_units: list[tuple[list[str], list[str]]] = []

    # 批量处理必须强制拆分：一个小红书作品链接 = 一个 quick_bgm 任务。
    # 否则后端可能把多个 note_urls 放进同一个任务里，导致多个交付文件实际复用同一个视频内容。
    # 这在作者主页批量生成时尤其危险：文件名不同，但视频内容可能相同。
    if len(plan.note_urls) > 1:
        print(f"批量安全模式：检测到 {len(plan.note_urls)} 个小红书作品链接，将按单条链接拆分为独立任务处理。")
        source_units.extend(([url], []) for url in plan.note_urls)
    elif len(plan.video_paths) > 1:
        print(f"批量安全模式：检测到 {len(plan.video_paths)} 个本地视频，将按单个文件拆分为独立任务处理。")
        source_units.extend(([], [path]) for path in plan.video_paths)
    else:
        source_units.append((plan.note_urls, plan.video_paths))

    bgm_ids = [] if plan.bgm_strategy == "search_download" else available_bgm_ids(api_base, plan.bgm_strategy, plan.random_music_count)
    results: list[dict[str, Any]] = []
    for index, (note_urls, video_paths) in enumerate(source_units):
        bgm_id = bgm_ids[index % len(bgm_ids)] if bgm_ids else None
        payload = _source_payload(plan, note_urls, video_paths, bgm_id=bgm_id)
        results.append(create_and_maybe_run(api_base, payload, run=run))
    apply_delivery_to_results(plan, results)
    return results


def print_summary(plan: MessagePlan, results: list[dict[str, Any]]) -> None:
    print("OpenClaw quick_bgm 自动化结果")
    if plan.warnings:
        for warning in plan.warnings:
            print(f"提醒：{warning}")
    print(f"链接数量：{len(plan.note_urls)}，本地视频：{len(plan.video_paths)}")
    print(f"BGM 策略：{plan.bgm_strategy}" + (f"，搜索关键词：{plan.bgm_query}" if plan.bgm_query else ""))
    print(f"BGM 起始秒数：{plan.bgm_start_seconds}")
    print(f"声音处理：{'替换原声' if plan.replace_audio else '保留原声'}")
    print(f"执行模式：{'dry_run 预览' if plan.dry_run else '正式生成'}")
    print(f"交付目录：{effective_delivery_dir(plan)}")
    for job_index, result in enumerate(results, start=1):
        print("")
        print(f"任务 {job_index}：{result.get('automation_job_id')}")
        print(f"状态：{result.get('status_zh') or result.get('status')}")
        print(f"说明：{result.get('message_zh')}")
        selected = result.get("selected_bgm") or {}
        if selected:
            print(f"使用 BGM：{selected.get('display_name') or selected.get('song_name') or selected.get('bgm_id')}")
        for item_index, item in enumerate(result.get("items") or [], start=1):
            title = item.get("title") or item.get("source_url") or f"素材 {item_index}"
            print(f"- {item_index}. {title}：{item.get('status_zh') or item.get('status')}")
            if item.get("output_video_path"):
                print(f"  输出：{item['output_video_path']}")
            if item.get("delivery_video_path"):
                print(f"  交付：{item['delivery_video_path']}")
            if item.get("failure_reason"):
                print(f"  原因：{item['failure_reason']}")


def main() -> None:
    parser = argparse.ArgumentParser(description="从 OpenClaw/聊天原文直接触发 quick_bgm 自动化。")
    parser.add_argument("--message", help="用户原始消息。")
    parser.add_argument("--message-file", help="包含用户原始消息的 UTF-8 文本文件。")
    parser.add_argument("--video-path", action="append", default=[], help="本地视频路径，可重复传入。")
    parser.add_argument("--api-base", default="http://127.0.0.1:8004", help="FastAPI 地址。")
    parser.add_argument("--dry-run", action="store_true", help="强制只预览，不生成视频。")
    parser.add_argument("--no-run", action="store_true", help="只创建任务，不执行 run。")
    parser.add_argument("--force-reimport", action="store_true", help="强制重新导入/重新处理已处理过的作品。")
    parser.add_argument("--json", action="store_true", help="额外输出解析计划和结果 JSON。")
    args = parser.parse_args()

    if args.message_file:
        message = Path(args.message_file).read_text(encoding="utf-8")
    else:
        message = args.message or ""
    if not message.strip() and not args.video_path:
        raise SystemExit("请通过 --message 或 --message-file 传入用户消息。")

    plan = parse_message(message, video_paths=args.video_path, dry_run=True if args.dry_run else None, force_reimport=args.force_reimport)
    try:
        results = execute_plan(plan, args.api_base, run=not args.no_run)
    except Exception as exc:
        print(f"处理失败：{exc}")
        if plan.warnings:
            for warning in plan.warnings:
                print(f"提醒：{warning}")
        raise SystemExit(2) from exc

    print_summary(plan, results)
    if args.json:
        print("")
        print("完整 JSON：")
        print(json.dumps({"plan": asdict(plan), "results": results}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
