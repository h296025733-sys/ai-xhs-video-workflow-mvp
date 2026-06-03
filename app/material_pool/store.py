import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from app.config import MATERIAL_POOL_DIR


CANDIDATES_PATH = MATERIAL_POOL_DIR / "candidates.json"
WATCHLIST_PATH = MATERIAL_POOL_DIR / "watchlist.json"

SOURCE_TYPE_ZH = {"auto": "自动抓取", "manual": "人工录入"}
SOURCE_PLATFORM_ZH = {
    "xiaohongshu": "小红书",
    "douyin": "抖音",
    "tiktok": "TikTok",
    "instagram": "Instagram",
    "local_upload": "本地上传",
    "other": "其他",
}
REGION_ZH = {"japan": "日本", "korea": "韩国", "unknown": "未指定"}
STYLE_ZH = {
    "cute": "可爱",
    "sexy": "性感",
    "youth": "青春",
    "commute": "通勤",
    "premium": "高级感",
    "other": "其他",
    "unknown": "未指定",
}
STATUS_ZH = {
    "candidate": "候选素材",
    "selected": "已选中",
    "rejected": "已放弃",
    "watching": "长期追更",
    "downloaded": "已下载",
    "processing": "处理中",
    "done": "已完成",
    "failed": "失败",
}
PROCESS_STRATEGY_ZH = {
    "manual_first": "优先人工素材",
    "auto_first": "优先自动抓取素材",
    "random_mix": "自动/人工随机混合",
    "manual_only": "只处理人工素材",
    "auto_only": "只处理自动抓取素材",
    "selected_only": "只处理已勾选素材",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ensure_file(path: Path) -> None:
    MATERIAL_POOL_DIR.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text("[]", encoding="utf-8")


def read_list(path: Path) -> list[dict]:
    _ensure_file(path)
    return json.loads(path.read_text(encoding="utf-8"))


def write_list(path: Path, rows: list[dict]) -> None:
    MATERIAL_POOL_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")


def list_candidates() -> list[dict]:
    return read_list(CANDIDATES_PATH)


def save_candidates(candidates: list[dict]) -> None:
    write_list(CANDIDATES_PATH, candidates)


def list_watchlist() -> list[dict]:
    return read_list(WATCHLIST_PATH)


def save_watchlist(items: list[dict]) -> None:
    write_list(WATCHLIST_PATH, items)


def normalize_candidate(data: dict, source_type: str = "manual", status: str = "candidate") -> dict:
    timestamp = now_iso()
    source_platform = data.get("source_platform") or "other"
    selected_region = data.get("selected_region") or "unknown"
    selected_style = data.get("selected_style") or "unknown"
    tags = data.get("tags") or []
    if isinstance(tags, str):
        tags = [tags]
    return {
        "candidate_id": data.get("candidate_id") or uuid.uuid4().hex,
        "source_type": source_type,
        "source_type_zh": SOURCE_TYPE_ZH.get(source_type, source_type),
        "source_platform": source_platform,
        "source_platform_zh": SOURCE_PLATFORM_ZH.get(source_platform, "其他"),
        "source_url": data.get("source_url"),
        "local_file_path": data.get("local_file_path"),
        "title": data.get("title") or "未命名候选素材",
        "description": data.get("description") or "",
        "author_name": data.get("author_name") or "未知作者",
        "author_profile_url": data.get("author_profile_url"),
        "follower_count": data.get("follower_count"),
        "like_count": data.get("like_count"),
        "collect_count": data.get("collect_count"),
        "comment_count": data.get("comment_count"),
        "play_count": data.get("play_count"),
        "publish_time": data.get("publish_time"),
        "tags": tags,
        "cover_url": data.get("cover_url"),
        "selected_region": selected_region,
        "selected_region_zh": REGION_ZH.get(selected_region, "未指定"),
        "selected_style": selected_style,
        "selected_style_zh": STYLE_ZH.get(selected_style, "未指定"),
        "score": data.get("score", 0),
        "reason_for_selection": data.get("reason_for_selection") or "人工录入候选，待进一步筛选。",
        "risk_notes": data.get("risk_notes") or "",
        "status": status,
        "status_zh": STATUS_ZH.get(status, status),
        "failure_reason": data.get("failure_reason"),
        "created_at": data.get("created_at") or timestamp,
        "updated_at": timestamp,
    }


def add_candidate(data: dict, source_type: str = "manual") -> dict:
    candidates = list_candidates()
    candidate = normalize_candidate(data, source_type=source_type)
    candidates.append(candidate)
    save_candidates(candidates)
    return candidate


def find_candidate(candidate_id: str) -> dict | None:
    return next((item for item in list_candidates() if item.get("candidate_id") == candidate_id), None)


def update_candidate_status(candidate_id: str, status: str) -> dict:
    candidates = list_candidates()
    for item in candidates:
        if item.get("candidate_id") == candidate_id:
            item["status"] = status
            item["status_zh"] = STATUS_ZH.get(status, status)
            item["updated_at"] = now_iso()
            save_candidates(candidates)
            return item
    raise KeyError(candidate_id)


def normalize_watch_item(data: dict) -> dict:
    timestamp = now_iso()
    platform = data.get("source_platform") or "xiaohongshu"
    region = data.get("selected_region") or "unknown"
    style = data.get("selected_style") or "unknown"
    return {
        "watch_id": data.get("watch_id") or uuid.uuid4().hex,
        "source_platform": platform,
        "source_platform_zh": SOURCE_PLATFORM_ZH.get(platform, "其他"),
        "author_name": data.get("author_name") or "未知作者",
        "author_profile_url": data.get("author_profile_url"),
        "follower_count": data.get("follower_count"),
        "reason_for_watch": data.get("reason_for_watch") or "由候选素材加入长期追更。",
        "selected_region": region,
        "selected_region_zh": REGION_ZH.get(region, "未指定"),
        "selected_style": style,
        "selected_style_zh": STYLE_ZH.get(style, "未指定"),
        "priority": data.get("priority", 3),
        "enabled": data.get("enabled", True),
        "last_checked_at": data.get("last_checked_at"),
        "last_item_id": data.get("last_item_id"),
        "notes": data.get("notes") or "",
        "created_at": data.get("created_at") or timestamp,
        "updated_at": timestamp,
    }


def add_watch_item(data: dict) -> dict:
    items = list_watchlist()
    item = normalize_watch_item(data)
    items.append(item)
    save_watchlist(items)
    return item


def add_candidate_to_watchlist(candidate: dict) -> dict:
    return add_watch_item(
        {
            "source_platform": candidate.get("source_platform"),
            "author_name": candidate.get("author_name"),
            "author_profile_url": candidate.get("author_profile_url"),
            "follower_count": candidate.get("follower_count"),
            "reason_for_watch": f"候选素材「{candidate.get('title', '未命名')}」被加入长期追更。",
            "selected_region": candidate.get("selected_region"),
            "selected_style": candidate.get("selected_style"),
            "notes": "本轮不做真实追更抓取，后续由 OpenClaw / xiaohongshu-mcp 定时任务接入。",
        }
    )
