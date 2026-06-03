from __future__ import annotations
import argparse
import json
import math
import re
import subprocess
import sys

# XHS_STDIO_UTF8_FIX
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
import os


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CACHE_PATH = Path(os.getenv("BGM_SMART_CACHE_PATH", PROJECT_ROOT / ".runtime" / "bgm_smart_cache.json"))
CACHE_VERSION = "v5_jk_tiktok_strict"

# ===== PATCH: 日韩 TikTok / OOTD BGM 强约束 =====
JK_NEGATIVE_WORDS = [
    "india", "indian", "hindi", "bollywood", "punjabi", "tamil", "bhojpuri",
    "instagram reels india", "reels india", "indian reels", "viral songs india",
    "part 1", "part-1", "part 2", "part-2",
    "playlist", "nonstop", "top 100", "top100", "mix 2026", "mashup",
    "合集", "串烧", "歌单", "中文", "华语", "抖音神曲",
    "周杰伦", "告白气球", "jay chou"
]

JK_POSITIVE_WORDS = [
    "tiktok", "tik tok",
    "japan", "japanese", "jp", "日本", "日本語",
    "korea", "korean", "kr", "韩国", "韓国", "한국",
    "ootd", "outfit", "fashion", "lookbook", "穿搭", "女装",
    "kpop", "k-pop", "jpop", "j-pop"
]

def jk_norm(s: str) -> str:
    return re.sub(r"\s+", " ", str(s or "").lower()).strip()

def jk_required(intent: str) -> bool:
    blob = jk_norm(intent)
    return any(w in blob for w in [
        "日韩", "日本", "韩国", "japan", "korea", "japanese", "korean",
        "tiktok", "tik tok", "ootd", "outfit", "fashion", "穿搭", "女装"
    ])

def jk_reinforce_intent(intent: str) -> str:
    intent = (intent or "").strip()
    blob = jk_norm(intent)
    add = []
    if "tiktok" not in blob and "tik tok" not in blob:
        add.append("TikTok")
    if not any(x in blob for x in ["japan", "japanese", "日本"]):
        add.append("Japan")
    if not any(x in blob for x in ["korea", "korean", "韩国", "kpop", "k-pop"]):
        add.append("Korea")
    if not any(x in blob for x in ["ootd", "outfit", "fashion", "穿搭"]):
        add.append("OOTD fashion outfit")
    if "2026" not in blob:
        add.append("2026")
    if add:
        intent = intent + " " + " ".join(add)
    return intent

def jk_is_bad_candidate(title: str, query: str = "", uploader: str = "") -> bool:
    blob = jk_norm(f"{title} {query} {uploader}")
    return any(w in blob for w in JK_NEGATIVE_WORDS)

def jk_bonus(title: str, query: str = "", uploader: str = "") -> float:
    blob = jk_norm(f"{title} {query} {uploader}")
    score = 0.0

    if jk_required(intent):
        title_for_check = item.get("title") or ""
        uploader_for_check = item.get("uploader") or item.get("channel") or ""
        if jk_is_bad_candidate(title_for_check, query, uploader_for_check):
            return -9999.0, "rejected: not JK/TikTok/OOTD target"
        score += jk_bonus(title_for_check, query, uploader_for_check)
    if "tiktok" in blob or "tik tok" in blob:
        score += 14
    if any(w in blob for w in ["ootd", "outfit", "fashion", "lookbook", "穿搭"]):
        score += 12
    if any(w in blob for w in ["japan", "japanese", "日本", "j-pop", "jpop"]):
        score += 10
    if any(w in blob for w in ["korea", "korean", "韩国", "k-pop", "kpop"]):
        score += 10
    if any(w in blob for w in JK_POSITIVE_WORDS):
        score += 8
    return score



@dataclass
class BgmCandidate:
    title: str
    webpage_url: str
    duration: float | None
    view_count: int | None
    uploader: str | None
    query: str
    score: float
    reason: str
    upload_date: str | None = None


def norm(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip().lower()


def load_cache() -> dict:
    try:
        if CACHE_PATH.exists():
            return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def save_cache(cache: dict) -> None:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")


def add_unique(items: list[str], value: str) -> None:
    value = value.strip()
    if value and value not in items:
        items.append(value)


def parse_fresh_after(intent: str) -> str | None:
    text = intent.strip()
    year = datetime.now().year

    m = re.search(r"(?:今年|本年)\s*(\d{1,2})\s*月(?:后|以后|之后)", text)
    if m:
        month = int(m.group(1))
        if 1 <= month <= 12:
            return f"{year:04d}-{month:02d}-01"

    m = re.search(r"(\d{4})\s*年\s*(\d{1,2})\s*月(?:后|以后|之后)", text)
    if m:
        y = int(m.group(1))
        month = int(m.group(2))
        if 1 <= month <= 12:
            return f"{y:04d}-{month:02d}-01"

    if any(k in text for k in ["今年新歌", "今年的新歌", "2026新歌", "2026年新歌"]):
        return f"{year:04d}-01-01"

    return None


def constraints_from_intent(intent: str) -> dict:
    low = norm(intent)
    western = any(k in low for k in [
        "欧美", "英文", "英语", "western", "english", "us pop", "uk pop", "欧美音乐", "欧美歌"
    ])
    fashion = any(k in low for k in [
        "穿搭", "服装", "女装", "博主", "outfit", "fashion", "ootd", "lookbook", "reels"
    ])
    kpop = any(k in low for k in [
        "韩国女团", "韩女", "韩团", "kpop", "k-pop", "韩系女团"
    ]) and not western
    tiktok = any(k in low for k in [
        "tiktok", "抖音", "热门", "爆款", "viral", "reels"
    ])
    fresh_after = parse_fresh_after(intent)
    return {
        "western": western,
        "fashion": fashion,
        "kpop": kpop,
        "tiktok": tiktok,
        "fresh_after": fresh_after,
    }


def build_queries(intent: str) -> list[str]:
    """
    分层搜索，不把所有限制词硬塞进一条 query。
    逻辑：原始词兜底 + 宽泛发现 + 场景桥接 + 平台趋势。
    """
    raw = intent.strip()
    low = norm(raw)
    c = constraints_from_intent(raw)

    if re.match(r"https?://", raw):
        return [raw]

    queries: list[str] = []
    add = lambda q: add_unique(queries, q)

    add(raw)

    year = datetime.now().year

    if c["western"]:
        add(f"new pop songs {year}")
        add(f"best new songs {year}")
        add(f"latest English pop songs {year}")
        add(f"new western pop songs {year}")
        add(f"new US UK pop songs {year}")
        add(f"TikTok viral songs {year}")
        add(f"Reels trending songs {year}")

    if c["fashion"]:
        add(f"fashion reels songs {year}")
        add(f"outfit transition songs {year}")
        add(f"OOTD TikTok songs {year}")
        add(f"fashion vlog pop music {year}")
        add(f"lookbook background music pop {year}")

    if c["fresh_after"]:
        y = c["fresh_after"][:4]
        month = int(c["fresh_after"][5:7])
        add(f"new songs after April {y}" if month <= 4 else f"new songs after {c['fresh_after'][:7]}")
        add(f"latest pop songs {y} official audio")

    if c["kpop"]:
        add("Kpop girl group TikTok viral song official audio")
        add("Kpop girl group official audio new song")
        add("NewJeans official audio")
        add("IVE official audio")
        add("aespa official audio")
        add("LE SSERAFIM official audio")
        add("BLACKPINK official audio")

    if c["tiktok"] and not c["western"] and not c["kpop"]:
        add(f"{raw} TikTok viral audio")
        add(f"TikTok viral songs {year}")
        add(f"Reels trending audio {year}")

    if len(queries) <= 1:
        add(f"{raw} official audio")
        add(f"{raw} TikTok audio")
        add(f"{raw} background music")

    return queries[:10]


def yt_dlp_search(query: str, count: int = 5) -> list[dict]:
    cmd = [
        sys.executable,
        "-m",
        "yt_dlp",
        "--dump-json",
        "--no-playlist",
        "--skip-download",
        f"ytsearch{count}:{query}",
    ]

    try:
        proc = subprocess.run(
            cmd,
            text=True,
            capture_output=True,
            timeout=120,
            encoding="utf-8",
            errors="ignore",
        )
    except subprocess.TimeoutExpired:
        return []

    if proc.returncode != 0:
        return []

    items = []
    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            items.append(json.loads(line))
        except Exception:
            continue
    return items


def get_upload_date(item: dict) -> str | None:
    for key in ["upload_date", "release_date", "timestamp"]:
        value = item.get(key)
        if not value:
            continue
        if key == "timestamp":
            try:
                return datetime.fromtimestamp(float(value), tz=timezone.utc).strftime("%Y%m%d")
            except Exception:
                continue
        value = str(value).strip()
        if re.fullmatch(r"\d{8}", value):
            return value
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            return value.replace("-", "")
    return None


def ymd_to_int(date_text: str | None) -> int | None:
    if not date_text:
        return None
    s = str(date_text).replace("-", "")
    if re.fullmatch(r"\d{8}", s):
        return int(s)
    return None


def contains_any(text: str, words: list[str]) -> bool:
    return any(w in text for w in words)


def score_candidate(item: dict, query: str, intent: str) -> tuple[float, str]:
    c = constraints_from_intent(intent)
    title = norm(item.get("title") or "")
    uploader = norm(item.get("uploader") or item.get("channel") or "")
    merged = f"{title} {uploader}"
    query_low = norm(query)

    duration = item.get("duration")
    view_count = item.get("view_count") or 0
    upload_date = get_upload_date(item)

    score = 0.0
    reasons: list[str] = []

    good_words = [
        "official audio", "official video", "official music video", "official visualizer",
        "lyrics", "lyric video", "audio", "pop", "new song", "single"
    ]
    for w in good_words:
        if w in merged:
            score += 8
            reasons.append(f"+{w}")

    bad_words = [
        "cover", "karaoke", "reaction", "tutorial", "lesson",
        "1 hour", "one hour", "hour loop", "playlist", "compilation",
        "slowed reverb only", "piano", "instrumental cover",
        "top 20", "top 50", "top 100", "best songs", "spotify",
        "nonstop", "mix 2026", "full album", "greatest hits"
    ]
    for w in bad_words:
        if w in merged:
            score -= 25
            reasons.append(f"-{w}")

    dance_noise = ["dance practice", "choreography", "live stage", "fancam"]
    for w in dance_noise:
        if w in merged:
            score -= 30
            reasons.append(f"-{w}")

    kpop_words = [
        "newjeans", "blackpink", "ive", "aespa", "le sserafim", "twice",
        "itzy", "gidle", "(g)i-dle", "babymonster", "nmixx",
        "kpop", "k-pop", "korean"
    ]

    if c["western"]:
        if contains_any(merged, kpop_words):
            score -= 90
            reasons.append("-western_excludes_kpop")
        if any(k in merged for k in ["english", "western", "us pop", "uk pop", "pop"]):
            score += 20
            reasons.append("+western")
    elif c["kpop"]:
        if contains_any(merged, kpop_words):
            score += 45
            reasons.append("+kpop")

    if c["fashion"]:
        fashion_words = ["fashion", "outfit", "ootd", "lookbook", "reels", "vlog"]
        if contains_any(merged, fashion_words) or contains_any(query_low, fashion_words):
            score += 20
            reasons.append("+fashion_scene")
        else:
            score += 5
            reasons.append("+fashion_intent")

    if c["tiktok"]:
        if any(k in merged for k in ["tiktok", "viral", "reels", "shorts"]):
            score += 15
            reasons.append("+platform")

    try:
        d = float(duration or 0)
        if 70 <= d <= 330:
            score += 18
            reasons.append("+duration")
        elif 45 <= d < 70 or 330 < d <= 420:
            score += 6
            reasons.append("+duration_ok")
        elif d > 900:
            score -= 35
            reasons.append("-too_long")
    except Exception:
        pass

    try:
        if view_count:
            score += min(18, math.log10(max(1, int(view_count))) * 2.8)
            reasons.append("+views")
    except Exception:
        pass

    fresh_after = c.get("fresh_after")
    if fresh_after:
        cutoff = ymd_to_int(fresh_after)
        up = ymd_to_int(upload_date)
        if up is None:
            score -= 8
            reasons.append("-unknown_upload_date")
        elif cutoff and up >= cutoff:
            score += 35
            reasons.append("+fresh_after")
        else:
            score -= 100
            reasons.append("-older_than_required")

    for token in re.split(r"[\s,，。/]+", query_low):
        if len(token) >= 4 and token in merged:
            score += 3

    return score, ",".join(reasons[:14])


def resolve(intent: str, max_per_query: int = 5) -> dict:
    intent = intent.strip()
    jk_mode = jk_required(intent)
    if jk_mode:
        intent = jk_reinforce_intent(intent)
    if not intent:
        raise ValueError("BGM 描述为空")

    constraints = constraints_from_intent(intent)

    if re.match(r"https?://", intent):
        return {
            "intent": intent,
            "resolved_query": intent,
            "selected_url": intent,
            "selected_title": intent,
            "score": 999,
            "reason": "用户直接提供 BGM 链接",
            "constraints": constraints,
            "selected_upload_date": None,
            "confidence_note": "用户直接提供链接，未做发布时间判断",
            "candidates": [],
        }

    cache = load_cache()
    cache_key = f"{CACHE_VERSION}|{norm(intent)}"
    if cache_key in cache:
        cached = cache[cache_key]
        cached["from_cache"] = True
        return cached

    queries = build_queries(intent)
    if jk_mode:
        strong_queries = [
            "TikTok Japan OOTD fashion outfit trending song 2026",
            "TikTok Korea OOTD fashion outfit trending song 2026",
            "Japanese TikTok fashion outfit viral song 2026",
            "Korean TikTok fashion outfit viral song 2026",
            "J-pop K-pop TikTok outfit lookbook trending song 2026",
        ]
        queries = list(dict.fromkeys(strong_queries + queries))[:10]

    all_candidates: list[BgmCandidate] = []

    for q in queries:
        print(f"搜索 BGM 候选：{q}", file=sys.stderr)
        items = yt_dlp_search(q, count=max_per_query)
        for item in items:
            url = item.get("webpage_url") or item.get("original_url") or item.get("url")
            title = item.get("title") or ""
            if not url or not title:
                continue
            score, reason = score_candidate(item, q, intent)
            all_candidates.append(
                BgmCandidate(
                    title=title,
                    webpage_url=url,
                    duration=item.get("duration"),
                    view_count=item.get("view_count"),
                    uploader=item.get("uploader") or item.get("channel"),
                    query=q,
                    score=score,
                    reason=reason,
                    upload_date=get_upload_date(item),
                )
            )

    if not all_candidates:
        result = {
            "intent": intent,
            "resolved_query": intent,
            "selected_url": intent,
            "selected_title": intent,
            "score": 0,
            "reason": "未搜索到候选，回退为原始搜索词",
            "constraints": constraints,
            "selected_upload_date": None,
            "confidence_note": "未搜索到候选",
            "queries": queries,
            "candidates": [],
        }
        cache[cache_key] = result
        save_cache(cache)
        return result

    if jk_mode:
        before_filter = len(all_candidates)
        all_candidates = [
            c for c in all_candidates
            if not jk_is_bad_candidate(c.title, c.query, c.uploader)
        ]
        print(f"日韩TikTok候选过滤：{before_filter} -> {len(all_candidates)}", file=sys.stderr)
        if not all_candidates:
            raise ValueError("没有找到符合日韩/TikTok/OOTD约束的 BGM 候选，已拒绝回退到无关歌曲。")

    by_url: dict[str, BgmCandidate] = {}
    for c in all_candidates:
        old = by_url.get(c.webpage_url)
        if not old or c.score > old.score:
            by_url[c.webpage_url] = c

    ranked = sorted(by_url.values(), key=lambda x: x.score, reverse=True)
    best = ranked[0]

    if constraints.get("fresh_after") and not best.upload_date:
        confidence_note = "已按风格筛选，但未能可靠确认发布时间"
    elif constraints.get("fresh_after") and best.upload_date:
        confidence_note = f"已按风格和发布时间筛选，候选上传日期：{best.upload_date}"
    else:
        confidence_note = "已按风格和可用元数据筛选"

    result = {
        "intent": intent,
        "resolved_query": best.webpage_url,
        "selected_url": best.webpage_url,
        "selected_title": best.title,
        "score": best.score,
        "reason": best.reason,
        "query_used": best.query,
        "constraints": constraints,
        "selected_upload_date": best.upload_date,
        "confidence_note": confidence_note,
        "queries": queries,
        "candidates": [asdict(x) for x in ranked[:10]],
    }

    cache[cache_key] = result
    save_cache(cache)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--intent", required=True)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--max-per-query", type=int, default=5)
    args = parser.parse_args()

    result = resolve(args.intent, max_per_query=args.max_per_query)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(result.get("selected_url") or args.intent)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
