from __future__ import annotations
import argparse
import json
import re
from datetime import datetime
from pathlib import Path


def norm(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def parse_int(text: str, default: int | None = None) -> int | None:
    try:
        return int(text)
    except Exception:
        return default


def extract_embedded_json(text: str) -> dict | None:
    """
    预留给 OpenClaw/AI 使用：
    如果将来 AI 在消息里附加 XHS_INTENT_JSON {...}，优先读取它。
    """
    m = re.search(r"XHS_INTENT_JSON\s*[:：]\s*(\{.*?\})\s*$", text, flags=re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except Exception:
        return None


def parse_author(text: str) -> dict:
    url = None
    m = re.search(r"https?://www\.xiaohongshu\.com/user/profile/[^\s，。；;]+", text)
    if m:
        url = m.group(0).strip()

    xhs_id = None
    m = re.search(r"(?:小红书号|小红书ID|xhs号|账号|号)\s*[:：]?\s*([A-Za-z0-9_-]{4,})", text, flags=re.I)
    if m:
        xhs_id = m.group(1).strip()

    # 兼容：处理小红书号 795931083
    m = re.search(r"小红书号\s*([A-Za-z0-9_-]{4,})", text)
    if m:
        xhs_id = m.group(1).strip()

    return {
        "url": url,
        "xhs_id": xhs_id,
        "raw_query": xhs_id or url,
    }


def parse_date_range(text: str) -> dict:
    t = text

    # 明确区间：7-15天、7到15天、十天到两周前这种先做数字版
    m = re.search(
        r"(?:最近|近|最新|第)?\s*(\d{1,3})\s*(?:-|~|－|||到|至)\s*(?:第)?\s*(\d{1,3})\s*天(?:内|前|以内|之间)?",
        t,
    )
    if m:
        a, b = int(m.group(1)), int(m.group(2))
        lo, hi = sorted([a, b])
        return {
            "type": "range_days_ago",
            "min_days_ago": lo,
            "max_days_ago": hi,
            "label": f"{lo}-{hi}天前",
            "confidence": 0.98,
            "source": "explicit_numeric_range",
        }

    # 不要最近一周，半个月内
    if re.search(r"(?:不要|排除|跳过).{0,8}(?:最近一周|近一周|最近7天|近7天)", t) and re.search(r"(?:半个月|15天|十五天)", t):
        return {
            "type": "range_days_ago",
            "min_days_ago": 7,
            "max_days_ago": 15,
            "label": "7-15天前",
            "confidence": 0.88,
            "source": "exclude_recent_week_with_half_month",
        }

    # 上周之前、半个月内
    if re.search(r"(?:上周之前|一周前|7天前)", t) and re.search(r"(?:半个月|15天|十五天)", t):
        return {
            "type": "range_days_ago",
            "min_days_ago": 7,
            "max_days_ago": 15,
            "label": "7-15天前",
            "confidence": 0.82,
            "source": "week_before_half_month",
        }

    # 最近一周 / 最近7天
    if re.search(r"最近一周|近一周|最近\s*7\s*天|近\s*7\s*天", t):
        return {
            "type": "within_days",
            "min_days_ago": 0,
            "max_days_ago": 7,
            "label": "最近7天内",
            "confidence": 0.96,
            "source": "recent_week",
        }

    # 最近一个月 / 30天
    if re.search(r"最近一个月|近一个月|最近\s*30\s*天|近\s*30\s*天", t):
        return {
            "type": "within_days",
            "min_days_ago": 0,
            "max_days_ago": 30,
            "label": "最近30天内",
            "confidence": 0.96,
            "source": "recent_month",
        }

    # 最近 N 天
    m = re.search(r"(?:最近|近|最新)\s*(\d{1,3})\s*天(?:内|以内)?", t)
    if m:
        d = max(1, min(int(m.group(1)), 365))
        return {
            "type": "within_days",
            "min_days_ago": 0,
            "max_days_ago": d,
            "label": f"最近{d}天内",
            "confidence": 0.92,
            "source": "recent_n_days",
        }

    return {
        "type": "none",
        "min_days_ago": None,
        "max_days_ago": None,
        "label": "不限制",
        "confidence": 0.4,
        "source": "not_found",
    }


def parse_limit(text: str) -> dict:
    patterns = [
        r"(?:取|抓|采集|处理|生成)\s*(\d+)\s*(?:条|个)",
        r"(\d+)\s*(?:条|个)\s*(?:视频|作品|笔记)",
    ]
    for p in patterns:
        m = re.search(p, text)
        if m:
            n = max(1, min(int(m.group(1)), 50))
            return {"value": n, "confidence": 0.95, "source": p}
    return {"value": 5, "confidence": 0.5, "source": "default"}


def parse_min_likes(text: str) -> dict:
    patterns = [
        r"(?:点赞|赞)\s*(?:大于|超过|>=|不少于|至少)\s*(\d+)",
        r"(\d+)\s*(?:赞|点赞)以上",
    ]
    for p in patterns:
        m = re.search(p, text)
        if m:
            return {"value": int(m.group(1)), "confidence": 0.95, "source": p}
    return {"value": 0, "confidence": 0.5, "source": "default"}


def parse_bgm_start(text: str) -> dict:
    patterns = [
        r"(?:BGM|bgm|音乐|配乐)?\s*从第?\s*(\d+(?:\.\d+)?)\s*秒开始",
        r"(?:BGM|bgm|音乐|配乐)?\s*从\s*(\d+(?:\.\d+)?)\s*s\s*开始",
        r"(?:BGM|bgm|音乐|配乐)?\s*起始(?:秒数|位置)?\s*(\d+(?:\.\d+)?)",
    ]
    for p in patterns:
        m = re.search(p, text, flags=re.I)
        if m:
            return {"value": float(m.group(1)), "confidence": 0.95, "source": p}
    return {"value": 0.0, "confidence": 0.5, "source": "default"}


def parse_bgm_intent(text: str) -> dict:
    url = None
    m = re.search(r"(?:BGM|bgm|音乐|配乐)[^\n\r]*(https?://[^\s，。；;]+)", text, flags=re.I)
    if m:
        url = m.group(1).strip().rstrip("。；;,，")

    value = None
    patterns = [
        r"(?:BGM|bgm)\s*(?:用|使用|换成|选择|找|搜索)\s*(.+)",
        r"(?:音乐|配乐)\s*(?:用|使用|换成|选择|找|搜索)\s*(.+)",
    ]

    for p in patterns:
        m = re.search(p, text, flags=re.I | re.S)
        if not m:
            continue

        value = m.group(1).strip()

        stop_patterns = [
            r"从第?\s*\d+(?:\.\d+)?\s*秒开始",
            r"从\s*\d+(?:\.\d+)?\s*s\s*开始",
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

        value = value[:cut].strip(" ，。；;、")
        break

    if url:
        return {
            "mode": "url",
            "intent": url,
            "constraints": {},
            "confidence": 0.99,
            "source": "explicit_url",
        }

    if not value:
        return {
            "mode": "missing",
            "intent": None,
            "constraints": {},
            "confidence": 0.3,
            "source": "not_found",
        }

    low = value.lower()
    western = any(k in low or k in value for k in ["欧美", "英文", "英语", "western", "english", "us pop", "uk pop"])
    kpop = any(k in low or k in value for k in ["韩国女团", "韩团", "kpop", "k-pop", "韩系女团"]) and not western
    fashion = any(k in low or k in value for k in ["穿搭", "服装", "女装", "博主", "outfit", "fashion", "ootd", "lookbook"])
    tiktok = any(k in low or k in value for k in ["tiktok", "抖音", "热门", "爆款", "viral", "reels"])

    year = datetime.now().year
    fresh_after = None
    m = re.search(r"(?:今年|本年)\s*(\d{1,2})\s*月(?:后|以后|之后)", value)
    if m:
        month = int(m.group(1))
        if 1 <= month <= 12:
            fresh_after = f"{year:04d}-{month:02d}-01"

    m = re.search(r"(\d{4})\s*年\s*(\d{1,2})\s*月(?:后|以后|之后)", value)
    if m:
        y = int(m.group(1))
        month = int(m.group(2))
        if 1 <= month <= 12:
            fresh_after = f"{y:04d}-{month:02d}-01"

    return {
        "mode": "search",
        "intent": value,
        "constraints": {
            "western": western,
            "kpop": kpop,
            "fashion": fashion,
            "tiktok": tiktok,
            "fresh_after": fresh_after,
            "avoid": ["cover", "reaction", "tutorial", "1 hour", "dance practice"],
        },
        "confidence": 0.82 if value else 0.3,
        "source": "rule_bgm_intent",
    }


def parse_flags(text: str) -> dict:
    dry_run = any(x in text.lower() for x in ["dry-run", "dry run", "先看看", "先筛选", "预览", "不要生成", "不生成"])
    original_only = any(x in text for x in ["只要原视频", "只下载原视频", "不换BGM", "不要换BGM", "保留原声"])
    force = any(x in text for x in ["强制重新处理", "强制重做", "重新处理", "force_reimport", "force-reimport"])
    formal = any(x in text for x in ["正式生成", "开始生成", "生成成品", "直接生成"])
    return {
        "dry_run": dry_run,
        "original_only": original_only,
        "force": force,
        "formal_generate": formal and not dry_run,
    }


def normalize_intent(text: str) -> dict:
    text = norm(text)
    embedded = extract_embedded_json(text)
    if embedded:
        embedded.setdefault("_source", "embedded_ai_json")
        embedded.setdefault("raw_text", text)
        return embedded

    date_range = parse_date_range(text)
    bgm = parse_bgm_intent(text)
    flags = parse_flags(text)

    result = {
        "schema_version": "xhs_intent_v1",
        "raw_text": text,
        "author": parse_author(text),
        "filters": {
            "date_range": date_range,
            "min_likes": parse_min_likes(text),
            "limit": parse_limit(text),
        },
        "bgm": {
            **bgm,
            "start_seconds": parse_bgm_start(text),
        },
        "mode": flags,
        "safety": {
            "requires_clarification": False,
            "clarification_reason": None,
        },
        "_source": "rule_fallback",
    }

    if flags["formal_generate"] and (not flags["original_only"]) and bgm["mode"] == "missing":
        result["safety"]["requires_clarification"] = True
        result["safety"]["clarification_reason"] = "正式生成且需要换BGM，但没有识别到BGM要求。"

    if date_range["type"] == "none":
        result["safety"]["date_range_unclear"] = True
    else:
        result["safety"]["date_range_unclear"] = False

    return result



def build_canonical_message(intent: dict) -> str:
    """
    把结构化意图转成旧链路稳定可解析的标准中文指令。
    作用：AI/规则先理解，执行层只吃确定格式，减少误解。
    """
    parts: list[str] = []

    author = intent.get("author") or {}
    xhs_id = author.get("xhs_id")
    url = author.get("url")
    raw_query = author.get("raw_query")

    if url:
        parts.append(f"处理作者主页 {url}")
    elif xhs_id:
        parts.append(f"处理小红书号 {xhs_id}")
    elif raw_query:
        parts.append(f"处理小红书作者 {raw_query}")
    else:
        parts.append("处理小红书作者")

    filters = intent.get("filters") or {}
    date_range = filters.get("date_range") or {}
    date_label = date_range.get("label")
    min_likes = (filters.get("min_likes") or {}).get("value", 0)
    limit = (filters.get("limit") or {}).get("value", 5)

    if date_label and date_label != "不限制":
        parts.append(f"{date_label}点赞大于{int(min_likes or 0)}的视频")
    else:
        parts.append(f"点赞大于{int(min_likes or 0)}的视频")

    parts.append(f"取{int(limit or 5)}条")

    mode = intent.get("mode") or {}
    bgm = intent.get("bgm") or {}
    original_only = bool(mode.get("original_only"))

    if original_only:
        parts.append("只下载原视频，保留原声")
    else:
        bgm_intent = bgm.get("intent")
        if bgm_intent:
            parts.append(f"BGM用{bgm_intent}")
        start_seconds = ((bgm.get("start_seconds") or {}).get("value", 0.0))
        try:
            start_seconds = float(start_seconds or 0)
        except Exception:
            start_seconds = 0.0
        if start_seconds:
            if start_seconds.is_integer():
                parts.append(f"从第{int(start_seconds)}秒开始")
            else:
                parts.append(f"从第{start_seconds}秒开始")

    if mode.get("dry_run"):
        parts.append("先dry-run，只筛选，不生成视频")
    elif mode.get("formal_generate"):
        parts.append("正式生成")

    if mode.get("force"):
        parts.append("强制重新处理")

    return "，".join(parts)


def normalize_and_build_message(text: str) -> tuple[dict, str]:
    data = normalize_intent(text)
    return data, build_canonical_message(data)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--text", default="")
    parser.add_argument("--message-file", default="")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    text = args.text or ""
    if args.message_file:
        text += "\n" + Path(args.message_file).read_text(encoding="utf-8")

    data = normalize_intent(text)
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(data, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
