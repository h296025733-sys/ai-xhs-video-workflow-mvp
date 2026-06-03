import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

import requests


def _read_links_file(path: str | None) -> list[str]:
    if not path:
        return []
    source = Path(path)
    if not source.exists():
        raise SystemExit(f"链接文件不存在：{source}")
    return [line.strip() for line in source.read_text(encoding="utf-8").splitlines() if line.strip()]


def _build_payload(args: argparse.Namespace) -> dict[str, Any]:
    note_urls = list(args.note_url or [])
    note_urls.extend(_read_links_file(args.note_urls_file))
    video_paths = list(args.video_path or [])

    if args.creator_home_url:
        source_type = "xhs_creator_profile"
    elif note_urls:
        source_type = "xhs_note_links"
    elif video_paths:
        source_type = "local_file"
    else:
        source_type = "manual"

    bgm_strategy = args.bgm_strategy
    if args.bgm_id:
        bgm_strategy = "selected"
    elif args.bgm_query and bgm_strategy == "top_used_random":
        bgm_strategy = "search_download"

    return {
        "source_type": source_type,
        "video_paths": video_paths,
        "note_urls": note_urls,
        "creator_home_url": args.creator_home_url,
        "limit": args.limit,
        "replace_audio": not args.keep_audio,
        "bgm_strategy": bgm_strategy,
        "bgm_id": args.bgm_id,
        "bgm_query": args.bgm_query,
        "bgm_start_seconds": args.start,
        "force_reimport": args.force_reimport,
        "dry_run": args.dry_run,
    }


def _post_json(url: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    response = requests.post(url, json=payload or {}, timeout=600)
    try:
        data = response.json()
    except ValueError:
        data = {"raw_text": response.text}
    if response.status_code >= 400:
        message = data.get("message_zh") or data.get("detail") or response.text
        raise SystemExit(f"请求失败：HTTP {response.status_code}\n{message}")
    return data


def _get_json(url: str) -> dict[str, Any]:
    response = requests.get(url, timeout=120)
    try:
        data = response.json()
    except ValueError:
        data = {"raw_text": response.text}
    if response.status_code >= 400:
        message = data.get("message_zh") or data.get("detail") or response.text
        raise SystemExit(f"请求失败：HTTP {response.status_code}\n{message}")
    return data


def _selected_bgm(data: dict[str, Any]) -> str:
    bgm = data.get("selected_bgm") or {}
    return bgm.get("display_name") or bgm.get("song_name") or data.get("selected_bgm_name") or "未选择"


def _print_item_summary(items: list[dict[str, Any]]) -> None:
    for index, item in enumerate(items, start=1):
        title = item.get("title") or item.get("source_url") or f"素材 {index}"
        status = item.get("status_zh") or item.get("status") or "未知"
        output = item.get("output_video_path") or item.get("download_url") or ""
        reason = item.get("failure_reason") or ""
        print(f"- {index}. {title}")
        print(f"  状态：{status}")
        if output:
            print(f"  输出：{output}")
        if reason:
            print(f"  失败原因：{reason}")


def _print_summary(title: str, data: dict[str, Any]) -> None:
    print(f"\n{title}")
    print(f"任务 ID：{data.get('automation_job_id') or '未返回'}")
    print(f"状态：{data.get('status_zh') or data.get('status') or '未知'}")
    print(f"说明：{data.get('message_zh') or '无'}")
    print(f"素材数量：{data.get('item_count', 0)}，可处理：{data.get('ready_count', 0)}，失败：{data.get('failed_count', 0)}")
    print(f"使用 BGM：{_selected_bgm(data)}")
    if data.get("next_action_zh"):
        print(f"下一步：{data['next_action_zh']}")
    items = data.get("items") or []
    if items:
        print("明细：")
        _print_item_summary(items)


def _ensure_utf8_hint() -> None:
    encoding = os.environ.get("PYTHONIOENCODING", "")
    if "utf" not in encoding.lower():
        print("提示：建议先设置 $env:PYTHONIOENCODING = \"utf-8\"，避免 Windows 终端中文乱码。", file=sys.stderr)


def main() -> None:
    _ensure_utf8_hint()

    parser = argparse.ArgumentParser(description="Quick BGM 自动化任务 CLI")
    parser.add_argument("--api-base", default="http://127.0.0.1:8004", help="FastAPI 地址")
    parser.add_argument("--note-url", action="append", help="小红书作品链接，可重复传入")
    parser.add_argument("--note-urls-file", help="包含多条小红书作品链接的文本文件")
    parser.add_argument("--creator-home-url", help="小红书博主主页链接")
    parser.add_argument("--video-path", action="append", help="本地视频路径，可重复传入")
    parser.add_argument("--limit", type=int, default=10, help="主页最多尝试处理最近 N 条，当前最大 10")
    parser.add_argument(
        "--bgm-strategy",
        default="top_used_random",
        choices=["selected", "top_used_random", "local_random", "search_download"],
        help="BGM 策略：指定、热门随机、本地随机、搜索下载",
    )
    parser.add_argument("--bgm-id", help="指定 BGM ID；传入后自动使用 selected 策略")
    parser.add_argument("--bgm-query", help="在线搜索下载 BGM 时使用的关键词")
    parser.add_argument("--start", type=float, default=0, help="BGM 开始秒数")
    parser.add_argument("--keep-audio", action="store_true", help="保留原声，不替换 BGM")
    parser.add_argument("--force-reimport", action="store_true", help="重复作品也重新导入/重新处理")
    parser.add_argument("--dry-run", action="store_true", help="只创建预览任务，不生成视频")
    parser.add_argument("--run", action="store_true", help="创建后立即执行")
    parser.add_argument("--json", action="store_true", help="额外输出完整 JSON，供调试使用")
    args = parser.parse_args()

    base = args.api_base.rstrip("/")
    payload = _build_payload(args)
    created = _post_json(f"{base}/quick-bgm/automation/create", payload)
    _print_summary("已创建 quick_bgm 自动化任务", created)

    automation_job_id = created.get("automation_job_id")
    final_data = created
    if args.run and automation_job_id and not args.dry_run:
        ran = _post_json(f"{base}/quick-bgm/automation/{automation_job_id}/run")
        _print_summary("已执行 quick_bgm 自动化任务", ran)
        final_data = _get_json(f"{base}/quick-bgm/automation/{automation_job_id}")
        _print_summary("任务最终状态", final_data)
    elif args.run and args.dry_run:
        print("\n这是 dry_run 任务，只做预览，不会执行生成。确认后请去掉 --dry-run 再使用 --run。")

    if args.json:
        print("\n完整 JSON：")
        print(json.dumps(final_data, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
