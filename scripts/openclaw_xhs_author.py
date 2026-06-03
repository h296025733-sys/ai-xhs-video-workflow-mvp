from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import quote

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

PYTHON_EXE = Path(os.getenv("PYTHON_EXE", sys.executable))
AUTHOR_PIPELINE = PROJECT_ROOT / "scripts" / "xhs_author_auto_pipeline.py"
AUTHOR_CACHE = Path(os.getenv("XHS_AUTHOR_CACHE_PATH", PROJECT_ROOT / ".runtime" / "xhs_author_profile_cache.json"))


def norm(text: str) -> str:
    return re.sub(r"\s+", "", str(text or "")).lower()


def load_cache() -> dict:
    try:
        if AUTHOR_CACHE.exists():
            return json.loads(AUTHOR_CACHE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def save_cache(cache: dict) -> None:
    AUTHOR_CACHE.parent.mkdir(parents=True, exist_ok=True)
    AUTHOR_CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")


def extract_creator_url(text: str) -> str | None:
    match = re.search(r"https?://www\.xiaohongshu\.com/user/profile/[^\s，。；;]+", text or "")
    if match:
        return match.group(0).strip().rstrip("。；;,，")
    return None


def parse_creator_query(text: str) -> str | None:
    if extract_creator_url(text):
        return None
    patterns = [
        r"小红书号[:：]?\s*([A-Za-z0-9_\-.一-龥]+)",
        r"小红书ID[:：]?\s*([A-Za-z0-9_\-.一-龥]+)",
        r"xhs\s*(?:id|号)?[:：]?\s*([A-Za-z0-9_\-.一-龥]+)",
        r"博主[:：]?\s*([A-Za-z0-9_\-.一-龥]+)",
        r"作者[:：]?\s*([A-Za-z0-9_\-.一-龥]+)",
        r"用户[:：]?\s*([A-Za-z0-9_\-.一-龥]+)",
        r"(?:搜索|找|查找)\s*([A-Za-z0-9_\-.一-龥]+)\s*(?:的小红书|主页|博主|作者)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.I)
        if match:
            return match.group(1).strip()
    return None


def parse_limit(text: str) -> int:
    patterns = [
        r"(?:取|抓|采集|处理|生成|最近|前)\s*(\d+)\s*(?:条|个)",
        r"(\d+)\s*(?:条|个)\s*(?:视频|作品|笔记)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return max(1, min(int(match.group(1)), 50))
    return 5


def parse_day_range(text: str) -> dict | None:
    t = str(text or "")
    match = re.search(
        r"(?:最近|近|最新|第)?\s*(\d{1,3})\s*(?:-|~|－|到|至)\s*(?:第)?\s*(\d{1,3})\s*天(?:内|前|以内|之间)?",
        t,
    )
    if match:
        a, b = int(match.group(1)), int(match.group(2))
        lo, hi = sorted([max(0, min(a, 365)), max(1, min(b, 365))])
        return {"min_days_ago": lo, "max_days_ago": hi, "label": f"{lo}-{hi}天前"}
    if re.search(r"最近一周|近一周|最近\s*7\s*天|近\s*7\s*天", t):
        return {"min_days_ago": 0, "max_days_ago": 7, "label": "最近7天内"}
    if re.search(r"最近一个月|近一个月|最近\s*30\s*天|近\s*30\s*天", t):
        return {"min_days_ago": 0, "max_days_ago": 30, "label": "最近30天内"}
    if re.search(r"最近三天|近三天|最近\s*3\s*天|近\s*3\s*天", t):
        return {"min_days_ago": 0, "max_days_ago": 3, "label": "最近3天内"}
    match = re.search(r"(?:最近|近|最新)\s*(\d{1,3})\s*天(?:内|以内)?", t)
    if match:
        days = max(1, min(int(match.group(1)), 365))
        return {"min_days_ago": 0, "max_days_ago": days, "label": f"最近{days}天内"}
    return None


def parse_min_likes(text: str) -> int:
    patterns = [
        r"(?:点赞|赞)\s*(?:大于|超过|>=|不少于|至少)\s*(\d+)",
        r"(\d+)\s*(?:赞|点赞)以上",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return int(match.group(1))
    return 0


def is_dry_run(text: str) -> bool:
    t = text.lower()
    return any(key in t for key in ["dry-run", "dry run", "预览", "先看看", "先筛选", "不要生成", "不生成", "测试一下"])


def is_force_reimport(text: str) -> bool:
    return any(key in text for key in ["强制重新处理", "强制重做", "重新处理", "force_reimport", "force-reimport"])


def is_original_only(text: str) -> bool:
    return any(key in text for key in ["只要原视频", "只下载原视频", "不要换BGM", "不换BGM", "保留原声", "不要替换BGM"])


def parse_bgm_instruction(text: str) -> str | None:
    match = re.search(r"(?:BGM|bgm|音乐|配乐)[^\n\r]*(https?://[^\s，。；;]+)", text, flags=re.I)
    if match:
        return match.group(1).strip().rstrip("。；;,，")
    patterns = [
        r"(?:BGM|bgm)\s*(?:用|使用|换成|选择|找|搜索)\s*(.+)",
        r"(?:音乐|配乐)\s*(?:用|使用|换成|选择|找|搜索)\s*(.+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.I | re.S)
        if not match:
            continue
        value = match.group(1).strip()
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
        for stop in stop_patterns:
            stop_match = re.search(stop, value, flags=re.I)
            if stop_match:
                cut = min(cut, stop_match.start())
        value = value[:cut].strip(" ，。；;、")
        return value or None
    return None


def parse_bgm_start_seconds(text: str) -> float:
    patterns = [
        r"(?:BGM|bgm|音乐|配乐)?\s*从第?\s*(\d+(?:\.\d+)?)\s*秒开始",
        r"(?:BGM|bgm|音乐|配乐)?\s*从\s*(\d+(?:\.\d+)?)\s*s\s*开始",
        r"(?:BGM|bgm|音乐|配乐)?\s*起始(?:秒数|位置)?\s*(\d+(?:\.\d+)?)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.I)
        if match:
            return float(match.group(1))
    return 0.0


def verify_profile_page(page, query: str) -> bool:
    try:
        body = page.evaluate("() => document.body.innerText || ''")
    except Exception:
        return False
    q = norm(query)
    b = norm(body)
    if q not in b:
        return False
    bad_signals = ["你还没有发布任何内容哦", "编辑资料", "我的收藏", "我的点赞"]
    return not any(norm(signal) in b for signal in bad_signals) or q in b


def resolve_creator_url_by_browser(query: str, cdp_url: str) -> str | None:
    cache = load_cache()
    cache_key = norm(query)
    cached = cache.get(cache_key)
    if cached and "/user/profile/" in cached:
        print(f"命中作者主页缓存：{query} -> {cached}")
        return cached

    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        print(f"错误：Playwright 不可用：{exc}")
        return None

    with sync_playwright() as playwright:
        browser = playwright.chromium.connect_over_cdp(cdp_url)
        context = browser.contexts[0] if browser.contexts else browser.new_context()
        page = context.new_page()

        search_url = f"https://www.xiaohongshu.com/search_result?keyword={quote(query)}"
        print(f"打开小红书搜索页：{search_url}")
        page.goto(search_url, wait_until="domcontentloaded", timeout=30_000)
        page.wait_for_timeout(3500)

        try:
            box = page.locator('input[placeholder*="搜索"], input[type="search"], input').first
            box.click(timeout=3000)
            box.fill(query, timeout=3000)
            box.press("Enter", timeout=3000)
            page.wait_for_timeout(4500)
        except Exception as exc:
            print(f"提示：搜索框输入失败，继续解析当前页：{exc}")

        for label in ["用户", "博主"]:
            try:
                page.get_by_text(label, exact=True).first.click(timeout=2000)
                page.wait_for_timeout(3000)
                print(f"已尝试切换到：{label}")
                break
            except Exception:
                pass

        candidates = page.evaluate(
            """(query) => {
                const q = String(query || '').replace(/\\s+/g, '').toLowerCase();
                const rows = [];
                const abs = (u) => !u ? '' : (u.startsWith('/') ? location.origin + u : u);
                const txt = (el) => (el && el.innerText ? el.innerText : '').replace(/\\s+/g, ' ').trim();
                const norm = (s) => String(s || '').replace(/\\s+/g, '').toLowerCase();
                function visible(el) {
                    const r = el.getBoundingClientRect();
                    const st = window.getComputedStyle(el);
                    return r.width > 20 && r.height > 10 && st.visibility !== 'hidden' && st.display !== 'none';
                }
                function nearestCard(el) {
                    let cur = el;
                    for (let i = 0; i < 8 && cur; i++, cur = cur.parentElement) {
                        const t = txt(cur);
                        const nt = norm(t);
                        if (nt.includes(q) && (nt.includes('小红书号') || nt.includes('粉丝') || nt.includes('获赞') || nt.includes('关注'))) {
                            return cur;
                        }
                    }
                    return el;
                }
                const all = Array.from(document.querySelectorAll('a, div, span, section'));
                for (const el of all) {
                    if (!visible(el)) continue;
                    const t = txt(el);
                    if (!t || !norm(t).includes(q)) continue;
                    const card = nearestCard(el);
                    const cardText = txt(card);
                    const cardNorm = norm(cardText);
                    if (!cardNorm.includes(q)) continue;
                    const a = (card.matches && card.matches('a[href*="/user/profile/"]')) ? card : card.querySelector('a[href*="/user/profile/"]');
                    const r = card.getBoundingClientRect();
                    rows.push({
                        href: a ? abs(a.getAttribute('href')) : '',
                        text: cardText.slice(0, 400),
                        x: r.left + r.width / 2,
                        y: r.top + Math.min(r.height / 2, 80),
                        score: (cardNorm.includes('小红书号') ? 80 : 0) + (cardNorm.includes('粉丝') ? 20 : 0) + (a ? 50 : 0) + 100
                    });
                }
                const seen = new Set();
                return rows.sort((a, b) => b.score - a.score).filter((row) => {
                    const key = (row.href || '') + '|' + Math.round(row.x) + '|' + Math.round(row.y);
                    if (seen.has(key)) return false;
                    seen.add(key);
                    return true;
                }).slice(0, 10);
            }""",
            query,
        )

        print("用户卡候选：")
        for index, candidate in enumerate(candidates, start=1):
            print(f"- {index}. score={candidate.get('score')} href={candidate.get('href')} text={candidate.get('text')}")

        if not candidates:
            page.close()
            return None

        best = candidates[0]
        href = best.get("href") or ""
        if href and "/user/profile/" in href:
            page.goto(href, wait_until="domcontentloaded", timeout=30_000)
            page.wait_for_timeout(3500)
        else:
            page.mouse.click(float(best.get("x")), float(best.get("y")))
            page.wait_for_timeout(4500)
            try:
                page = context.pages[-1]
            except Exception:
                pass

        current_url = page.url
        print(f"进入后的页面：{current_url}")
        if "/user/profile/" not in current_url or not verify_profile_page(page, query):
            print("错误：未能确认可信作者主页。")
            page.close()
            return None

        cache[cache_key] = current_url
        save_cache(cache)
        page.close()
        return current_url


def read_message(args: argparse.Namespace) -> str:
    text = args.message or ""
    if args.message_file:
        text += "\n" + Path(args.message_file).read_text(encoding="utf-8")
    return text.strip()


def main() -> int:
    parser = argparse.ArgumentParser(description="OpenClaw / 企业 IM 小红书作者主页自动处理入口")
    parser.add_argument("--message", default="")
    parser.add_argument("--message-file", default="")
    parser.add_argument("--api-base", default=os.getenv("API_BASE_URL", "http://127.0.0.1:8004"))
    parser.add_argument("--cdp-url", default=os.getenv("XHS_CDP_URL", "http://127.0.0.1:9222"))
    parser.add_argument("--max-scrolls", type=int, default=30)
    parser.add_argument("--max-links", type=int, default=80)
    parser.add_argument("--parse-only", action="store_true", help="只解析消息，不打开浏览器、不生成视频")
    args = parser.parse_args()

    text = read_message(args)
    if not text:
        print("错误：消息为空。")
        return 2

    creator_url = extract_creator_url(text)
    creator_query = parse_creator_query(text)
    day_range = parse_day_range(text)
    limit = parse_limit(text)
    min_likes = parse_min_likes(text)
    bgm_query = parse_bgm_instruction(text) or ""
    bgm_start = parse_bgm_start_seconds(text)
    dry_run = is_dry_run(text)
    original_only = is_original_only(text)
    force_reimport = is_force_reimport(text)

    print("XHS_AUTHOR_INTENT：")
    print(json.dumps(
        {
            "creator_url": creator_url,
            "creator_query": creator_query,
            "day_range": day_range,
            "limit": limit,
            "min_likes": min_likes,
            "bgm_query": bgm_query,
            "bgm_start_seconds": bgm_start,
            "dry_run": dry_run,
            "original_only": original_only,
            "force_reimport": force_reimport,
        },
        ensure_ascii=False,
        indent=2,
    ))

    if args.parse_only:
        return 0

    if not creator_url and creator_query:
        creator_url = resolve_creator_url_by_browser(creator_query, args.cdp_url)

    if not creator_url:
        print("错误：没有识别到作者主页链接，也没有通过小红书号/昵称解析出主页。")
        return 2

    cmd = [
        str(PYTHON_EXE),
        str(AUTHOR_PIPELINE),
        "--creator-url",
        creator_url,
        "--api-base",
        args.api_base,
        "--cdp-url",
        args.cdp_url,
        "--limit",
        str(limit),
        "--min-likes",
        str(min_likes),
        "--max-scrolls",
        str(args.max_scrolls),
        "--max-links",
        str(args.max_links),
        "--bgm-start-seconds",
        str(bgm_start),
    ]
    if day_range:
        cmd += ["--min-days-ago", str(day_range["min_days_ago"]), "--max-days-ago", str(day_range["max_days_ago"])]
    if bgm_query:
        cmd += ["--bgm-query", bgm_query]
    if dry_run:
        cmd.append("--dry-run")
    if original_only:
        cmd.append("--original-only")
    if force_reimport:
        cmd.append("--force-reimport")

    print("\n开始执行作者主页自动化流水线。")
    proc = subprocess.run(cmd, cwd=str(PROJECT_ROOT), text=True, encoding="utf-8", errors="replace")
    return proc.returncode


if __name__ == "__main__":
    raise SystemExit(main())
