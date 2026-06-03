from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.quick_bgm.xhs_creator_importer import preview_note_link


NOTE_ID_RE = re.compile(r"(?:/explore/|/discovery/item/)([0-9a-f]{24})", re.I)


def runtime_path(env_name: str, default: Path) -> Path:
    return Path(os.getenv(env_name, str(default))).expanduser()


def mask_xhs_url(url: str) -> str:
    """日志里不打印完整 xsec_token，只保留作品 ID 和参数名。"""
    try:
        parts = urlsplit(url)
        query = []
        for key, value in parse_qsl(parts.query, keep_blank_values=True):
            if "token" in key.lower():
                value = "****"
            query.append((key, value))
        return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))
    except Exception:
        return re.sub(r"(xsec_?token=)[^&\s]+", r"\1****", str(url or ""), flags=re.I)


def normalize_note_url(raw: str) -> str | None:
    if not raw:
        return None
    raw = raw.strip().replace("\\u002F", "/").replace("\\/", "/")
    if raw.startswith("/"):
        raw = "https://www.xiaohongshu.com" + raw
    if "xiaohongshu.com" not in raw:
        return None
    match = NOTE_ID_RE.search(raw)
    if not match:
        return None
    note_id = match.group(1)
    parts = urlsplit(raw)
    return urlunsplit(("https", "www.xiaohongshu.com", f"/discovery/item/{note_id}", parts.query or "", ""))


def note_id_from_text(value: object) -> str | None:
    text = str(value or "")
    match = re.search(r"([0-9a-fA-F]{24})", text)
    return match.group(1) if match else None


def parse_count(value: object) -> int:
    if value in (None, "", [], {}):
        return 0
    text = str(value).strip().replace(",", "").replace(" ", "")
    try:
        if text.endswith("万"):
            return int(float(text[:-1]) * 10000)
        if text.lower().endswith("k"):
            return int(float(text[:-1]) * 1000)
        return int(float(text))
    except Exception:
        match = re.search(r"\d+(?:\.\d+)?", text)
        if not match:
            return 0
        number = float(match.group(0))
        if "万" in text:
            number *= 10000
        return int(number)


def parse_publish_time(value: object) -> datetime | None:
    if value in (None, "", [], {}):
        return None

    if isinstance(value, (int, float)):
        timestamp = float(value)
        if timestamp > 10_000_000_000:
            timestamp = timestamp / 1000
        try:
            return datetime.fromtimestamp(timestamp, tz=timezone.utc)
        except Exception:
            return None

    text = str(value).strip()
    if re.fullmatch(r"\d{10,13}", text):
        return parse_publish_time(int(text))

    text = text.replace("T", " ").replace("Z", "")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d", "%Y/%m/%d %H:%M:%S", "%Y/%m/%d"):
        try:
            return datetime.strptime(text[:19], fmt).replace(tzinfo=timezone.utc)
        except Exception:
            pass
    return None


def parse_publish_time_from_note_id(value: object) -> datetime | None:
    note_id = note_id_from_text(value)
    if not note_id:
        return None
    try:
        timestamp = int(note_id[:8], 16)
        if 1_577_836_800 <= timestamp <= 2_051_222_400:
            return datetime.fromtimestamp(timestamp, tz=timezone.utc)
    except Exception:
        pass
    return None


def walk_values(obj: object):
    if isinstance(obj, dict):
        for key, value in obj.items():
            yield str(key), value
            yield from walk_values(value)
    elif isinstance(obj, list):
        for item in obj:
            yield from walk_values(item)


def first_nested_value(obj: object, key_names: set[str]):
    names = {x.lower() for x in key_names}
    for key, value in walk_values(obj):
        if key.lower() in names and value not in (None, "", [], {}):
            return value
    return None


def extract_title(item: dict, fallback: str) -> str:
    value = first_nested_value(
        item,
        {"title", "display_title", "desc", "description", "note_title", "share_title", "nickname"},
    )
    text = str(value or "").strip()
    return text[:120] if text else fallback


def extract_liked_count_info(item: dict) -> tuple[int, bool]:
    value = first_nested_value(
        item,
        {"liked_count", "like_count", "likes", "liked", "likes_count", "点赞", "点赞数", "赞", "赞数"},
    )
    if value in (None, "", [], {}):
        return 0, False
    return parse_count(value), True


def extract_publish_raw(item: dict):
    return first_nested_value(
        item,
        {"publish_time", "time", "created_time", "created_at", "publish_at", "timestamp", "发布时间", "date", "create_time"},
    )


def has_video_signal(obj: object) -> bool:
    if obj is None:
        return False
    if isinstance(obj, dict):
        for key, value in obj.items():
            key_lower = str(key).lower()
            if "video" in key_lower and value:
                return True
            if has_video_signal(value):
                return True
    elif isinstance(obj, list):
        return any(has_video_signal(item) for item in obj)
    elif isinstance(obj, str):
        low = obj.lower()
        return any(sig in low for sig in [".mp4", "sns-video", "xhs-video", "xhscdn", "video"])
    return False


def find_urls_in_obj(obj: object, out: set[str]) -> None:
    if obj is None:
        return
    if isinstance(obj, str):
        for match in re.finditer(
            r"(?:https?:)?//www\.xiaohongshu\.com/(?:explore|discovery/item)/[0-9a-f]{24}[^\"'<>\\\s]*",
            obj,
        ):
            raw = match.group(0)
            if raw.startswith("//"):
                raw = "https:" + raw
            normalized = normalize_note_url(raw)
            if normalized:
                out.add(normalized)
        for match in NOTE_ID_RE.finditer(obj):
            normalized = normalize_note_url(f"https://www.xiaohongshu.com/discovery/item/{match.group(1)}")
            if normalized:
                out.add(normalized)
        return
    if isinstance(obj, dict):
        for key, value in obj.items():
            if key.lower() in {"noteid", "note_id", "id", "itemid", "item_id"} and isinstance(value, str):
                if re.fullmatch(r"[0-9a-f]{24}", value):
                    out.add(f"https://www.xiaohongshu.com/discovery/item/{value}")
            find_urls_in_obj(value, out)
    elif isinstance(obj, list):
        for item in obj:
            find_urls_in_obj(item, out)


def collect_dom_urls(page) -> set[str]:
    js = r"""
    () => {
      const out = new Set();

      function addNote(id, token) {
        if (!id || !/^[0-9a-f]{24}$/i.test(String(id))) return;
        if (token) {
          out.add(`https://www.xiaohongshu.com/discovery/item/${id}?source=webshare&xhsshare=pc_web&xsec_token=${encodeURIComponent(token)}&xsec_source=pc_share`);
        } else {
          out.add(`https://www.xiaohongshu.com/discovery/item/${id}`);
        }
      }

      function walk(value) {
        if (!value) return;
        if (Array.isArray(value)) {
          for (const item of value) walk(item);
          return;
        }
        if (typeof value === "object") {
          const id = value.id || value.noteId || value.note_id || value.itemId || value.item_id;
          const token = value.xsecToken || value.xsec_token || value.xsecTokenRaw || value.xsec_token_raw;
          if (id) addNote(id, token);
          for (const key of Object.keys(value)) walk(value[key]);
        }
      }

      try {
        const state = window.__INITIAL_STATE__;
        walk(state);
      } catch(e) {}

      for (const a of document.querySelectorAll('a[href]')) {
        try {
          const url = new URL(a.getAttribute('href'), location.href).href;
          if (url.includes('/explore/') || url.includes('/discovery/item/')) out.add(url);
        } catch(e) {}
      }

      const html = document.documentElement.innerHTML || '';
      const re = /(?:https?:\/\/www\.xiaohongshu\.com)?\/(?:explore|discovery\/item)\/[0-9a-f]{24}[^"'<>\\s]*/g;
      for (const match of html.matchAll(re)) out.add(match[0]);
      return Array.from(out);
    }
    """
    out: set[str] = set()
    try:
        for raw in page.evaluate(js):
            normalized = normalize_note_url(raw)
            if normalized:
                out.add(normalized)
    except Exception:
        pass
    return out


def collect_author_notes(creator_url: str, max_scrolls: int, stable_rounds: int, cdp_url: str) -> list[str]:
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        raise RuntimeError("Playwright 未安装。请执行：pip install playwright && python -m playwright install chromium") from exc

    found: set[str] = set()
    network_found: set[str] = set()

    with sync_playwright() as playwright:
        browser = playwright.chromium.connect_over_cdp(cdp_url)
        context = browser.contexts[0] if browser.contexts else browser.new_context()
        page = context.new_page()

        def on_response(resp):
            try:
                if "xiaohongshu.com" not in resp.url:
                    return
                content_type = (resp.headers.get("content-type") or "").lower()
                if "json" not in content_type and "api" not in resp.url:
                    return
                text = resp.text()
                local: set[str] = set()
                try:
                    find_urls_in_obj(json.loads(text), local)
                except Exception:
                    find_urls_in_obj(text, local)
                network_found.update(local)
            except Exception:
                pass

        page.on("response", on_response)
        print("打开作者主页：", creator_url)
        page.goto(creator_url, wait_until="domcontentloaded", timeout=60_000)
        time.sleep(4)

        found.update(collect_dom_urls(page))
        found.update(network_found)

        stable = 0
        last_count = len(found)
        for index in range(max_scrolls):
            print(f"滚动 {index + 1}/{max_scrolls}，当前作品链接：{len(found)}")
            page.mouse.wheel(0, 2600)
            time.sleep(1.4)
            found.update(collect_dom_urls(page))
            found.update(network_found)
            if len(found) == last_count:
                stable += 1
            else:
                stable = 0
                last_count = len(found)
            if stable >= stable_rounds and found:
                print("链接数量多轮未变化，停止滚动。")
                break

        try:
            page.close()
        except Exception:
            pass

    def sort_key(url: str) -> str:
        note_id = note_id_from_text(url)
        return note_id or url

    return sorted(dict.fromkeys(found), key=sort_key, reverse=True)


def prefer_xsec_urls(urls: list[str]) -> list[str]:
    by_id: dict[str, str] = {}
    order: list[str] = []
    for url in urls:
        note_id = note_id_from_text(url) or url
        if note_id not in by_id:
            by_id[note_id] = url
            order.append(note_id)
            continue
        old = by_id[note_id]
        if "xsec_token=" in url and "xsec_token=" not in old:
            by_id[note_id] = url
    return [by_id[note_id] for note_id in order]


def preview_note_link_safe(url: str) -> dict:
    data: dict = {}
    try:
        data = preview_note_link(url) or {}
    except Exception as exc:
        print(f"  提示：预览失败，按候选保留基础信息：{exc}")
    if not isinstance(data, dict):
        data = {}
    data.setdefault("url", url)
    data.setdefault("note_url", url)
    note_id = note_id_from_text(url)
    if note_id:
        data.setdefault("note_id", note_id)
    data["url_masked"] = mask_xhs_url(url)
    return data


def build_author_quick_bgm_message(args: argparse.Namespace, urls: list[str]) -> str:
    delivery_dir = str(args.delivery_dir)
    if args.original_only:
        head = f"下载这些作者主页筛选出来的原视频，不替换BGM，保留原声，保存到 {delivery_dir} ："
    elif args.bgm_query:
        head = (
            f"处理这些作者主页筛选出来的视频，BGM用{args.bgm_query}，"
            f"从第{args.bgm_start_seconds}秒开始，替换原声，保存到 {delivery_dir} ："
        )
    else:
        head = f"处理这些作者主页筛选出来的视频，随机热门 BGM，从第{args.bgm_start_seconds}秒开始，替换原声，保存到 {delivery_dir} ："
    return head + "\n\n" + "\n".join(urls)


def run_quick_bgm(args: argparse.Namespace, message_file: Path) -> int:
    cmd = [
        sys.executable,
        str(PROJECT_ROOT / "scripts" / "openclaw_quick_bgm.py"),
        "--api-base",
        args.api_base,
        "--message-file",
        str(message_file),
        "--json",
    ]
    if args.dry_run:
        cmd.append("--dry-run")
    if args.force_reimport:
        cmd.append("--force-reimport")

    print("\n开始调用 quick_bgm 批量处理。")
    completed = subprocess.run(
        cmd,
        cwd=str(PROJECT_ROOT),
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
    )
    if completed.stdout:
        print(completed.stdout, end="" if completed.stdout.endswith("\n") else "\n")
    if completed.stderr:
        print(completed.stderr, end="" if completed.stderr.endswith("\n") else "\n", file=sys.stderr)
    return completed.returncode


def main() -> int:
    parser = argparse.ArgumentParser(description="小红书作者主页自动采集 + 条件筛选 + quick-bgm 批量处理")
    parser.add_argument("--creator-url", required=True, help="小红书作者主页链接")
    parser.add_argument("--api-base", default=os.getenv("API_BASE_URL", "http://127.0.0.1:8004"))
    parser.add_argument("--cdp-url", default=os.getenv("XHS_CDP_URL", "http://127.0.0.1:9222"))
    parser.add_argument("--max-scrolls", type=int, default=30)
    parser.add_argument("--max-links", type=int, default=80)
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--min-likes", type=int, default=0)
    parser.add_argument("--bgm-query", default="")
    parser.add_argument("--bgm-start-seconds", type=float, default=0.0)
    parser.add_argument("--original-only", action="store_true")
    parser.add_argument("--within-days", type=int, default=0)
    parser.add_argument("--min-days-ago", type=int, default=0)
    parser.add_argument("--max-days-ago", type=int, default=0)
    parser.add_argument("--delivery-dir", default=str(runtime_path("VIDEO_DELIVERY_DIR", PROJECT_ROOT / "outputs" / "作者主页批量")))
    parser.add_argument("--report-dir", default=str(runtime_path("XHS_REPORT_DIR", PROJECT_ROOT / "outputs" / "reports")))
    parser.add_argument("--link-dir", default=str(runtime_path("XHS_LINK_DIR", PROJECT_ROOT / ".runtime" / "xhs_author_links")))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force-reimport", action="store_true")
    args = parser.parse_args()

    report_dir = Path(args.report_dir)
    link_dir = Path(args.link_dir)
    report_dir.mkdir(parents=True, exist_ok=True)
    link_dir.mkdir(parents=True, exist_ok=True)

    urls = collect_author_notes(args.creator_url, args.max_scrolls, stable_rounds=5, cdp_url=args.cdp_url)
    before = len(urls)
    urls = prefer_xsec_urls(urls)[: args.max_links]
    if len(urls) != before:
        print(f"作品链接去重：{before} -> {len(urls)}（同作品优先保留带 xsec_token 的链接）")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    links_file = link_dir / f"author_auto_links_{timestamp}.txt"
    links_file.write_text("\n".join(urls), encoding="utf-8")

    print(f"\n采集完成，作品链接数量：{len(urls)}")
    print(f"链接文件：{links_file}")
    if not urls:
        print("没有抓到作品链接。请确认 Chrome 已用 CDP 启动、已登录小红书，并且作者主页能看到作品卡片。")
        return 2

    min_days_ago = max(0, int(args.min_days_ago or 0))
    max_days_ago = max(0, int(args.max_days_ago or args.within_days or 0))
    if min_days_ago and max_days_ago and min_days_ago > max_days_ago:
        min_days_ago, max_days_ago = max_days_ago, min_days_ago
    date_range_label = "不限制"
    if max_days_ago:
        date_range_label = f"{min_days_ago}-{max_days_ago}天前" if min_days_ago else f"最近{max_days_ago}天内"
    print(f"日期筛选范围：{date_range_label}")

    now = datetime.now(timezone.utc)
    selected: list[dict] = []
    all_items: list[dict] = []

    for index, url in enumerate(urls, start=1):
        print(f"\n预览 {index}/{len(urls)}：{mask_xhs_url(url)}")
        item = preview_note_link_safe(url)
        all_items.append(item)

        title = extract_title(item, item.get("note_id") or f"作品{index}")
        liked, liked_known = extract_liked_count_info(item)
        if liked_known:
            item["liked_count"] = liked
        else:
            item["_liked_count_unknown"] = True

        publish_raw = extract_publish_raw(item)
        publish_dt = parse_publish_time(publish_raw) or parse_publish_time_from_note_id(item.get("note_id") or url)
        if publish_dt and not publish_raw:
            publish_raw = publish_dt.strftime("%Y-%m-%d %H:%M:%S")

        note_type = str(item.get("type") or item.get("note_type") or "").lower()
        video_signal = has_video_signal(item)
        if note_type in {"image", "images", "photo", "photos", "图文"} and not video_signal:
            print(f"  跳过：明确是图文作品 | {title}")
            continue

        if liked_known and liked < args.min_likes:
            print(f"  跳过：点赞 {liked} < {args.min_likes} | {title}")
            continue
        if not liked_known and args.min_likes > 0:
            print(f"  提示：未取到点赞数，先不误杀，后续下载/预览再复核 | {title}")

        if max_days_ago:
            if not publish_dt:
                print(f"  跳过：无法确认发布时间 | {title}")
                continue
            if publish_dt.tzinfo is None:
                publish_dt = publish_dt.replace(tzinfo=timezone.utc)
            if min_days_ago and publish_dt > now - timedelta(days=min_days_ago):
                print(f"  跳过：发布时间太新，不在 {date_range_label} | {title}")
                continue
            if publish_dt < now - timedelta(days=max_days_ago):
                print(f"  跳过：发布时间早于 {max_days_ago} 天前 | {title}")
                continue

        item["title"] = title
        item["publish_time"] = str(publish_raw or "")
        print(f"  选中：{title} | 点赞 {liked if liked_known else '未知'} | 发布时间 {publish_raw or '未知'}")
        selected.append(item)
        if len(selected) >= args.limit:
            break

    report_file = report_dir / f"author_auto_filter_{timestamp}.json"
    report_payload = {
        "filters": {
            "creator_url": args.creator_url,
            "date_range_label": date_range_label,
            "min_days_ago": min_days_ago,
            "max_days_ago": max_days_ago,
            "min_likes": args.min_likes,
            "limit": args.limit,
        },
        "all": all_items,
        "selected": selected,
    }
    report_file.write_text(json.dumps(report_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n筛选报告：{report_file}")

    if not selected:
        print("没有筛选出可处理视频。")
        return 1

    message_file = report_dir / f"author_auto_selected_{timestamp}.txt"
    selected_urls = [item["url"] for item in selected]
    message_file.write_text(build_author_quick_bgm_message(args, selected_urls), encoding="utf-8")
    return run_quick_bgm(args, message_file)


if __name__ == "__main__":
    raise SystemExit(main())
