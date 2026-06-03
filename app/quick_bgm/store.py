import json
import re
from threading import RLock
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from app.config import STORAGE_DIR


QUICK_BGM_DIR = STORAGE_DIR / "quick_bgm"
QUICK_UPLOADS_DIR = QUICK_BGM_DIR / "uploads"
BGM_LIBRARY_DIR = QUICK_BGM_DIR / "bgm_library"
QUICK_OUTPUTS_DIR = QUICK_BGM_DIR / "outputs"
BGM_LIBRARY_PATH = QUICK_BGM_DIR / "bgm_library.json"
JOBS_PATH = QUICK_BGM_DIR / "jobs.json"
XHS_CREATOR_BATCHES_PATH = QUICK_BGM_DIR / "xhs_creator_batches.json"
XHS_IMPORTED_NOTES_PATH = QUICK_BGM_DIR / "xhs_imported_notes.json"
AUTOMATION_JOBS_PATH = QUICK_BGM_DIR / "automation_jobs.json"
_LIST_LOCK = RLock()

REGION_ZH = {
    "japan": "日本",
    "korea": "韩国",
    "general": "通用",
    "unknown": "未指定",
}
STYLE_ZH = {
    "cute": "可爱",
    "youth": "青春",
    "commute": "通勤",
    "premium": "高级感",
    "sexy": "性感",
    "gentle": "温柔",
    "general": "通用",
    "unknown": "未指定",
}
INPUT_TYPE_ZH = {"upload": "本地上传", "xiaohongshu_link": "小红书作品", "xiaohongshu_creator": "小红书博主主页"}
REPLACE_AUDIO_ZH = {True: "替换原声", False: "保留原声"}
STATUS_ZH = {
    "pending": "等待处理",
    "processing": "处理中",
    "done": "已完成",
    "failed": "失败",
}
BGM_SOURCE_TYPE_ZH = {"upload": "本地上传", "search_download": "在线搜索下载"}
AVAILABILITY_STATUS_ZH = {
    "usable": "可使用",
    "download_failed": "下载失败",
    "need_upload": "需上传",
    "unknown": "未知",
}
BGM_STRATEGY_ZH = {
    "selected": "使用指定 BGM",
    "top_used_random": "从热门 BGM 中随机",
    "local_random": "从本地 BGM 库随机",
    "search_download": "在线搜索下载 BGM",
}
AUTOMATION_SOURCE_TYPE_ZH = {
    "local_file": "本地文件",
    "xhs_note_links": "小红书作品链接",
    "xhs_creator_profile": "小红书博主主页",
    "uploaded_video": "已上传视频",
    "manual": "人工输入",
}
AUTOMATION_STATUS_ZH = {
    "pending": "等待处理",
    "ready": "可处理",
    "processing": "处理中",
    "done": "已完成",
    "partial_done": "部分完成",
    "failed": "失败",
    "need_manual": "需要人工处理",
    "skipped": "已跳过",
}
XHS_IMPORT_MODE_ZH = {
    "auto": "自动判断",
    "xhs_downloader_api": "XHS-Downloader API",
    "xhs_downloader_cli": "XHS-Downloader CLI",
    "xhs_mcp": "小红书 MCP",
    "manual_links": "人工作品链接",
    "disabled": "未启用",
}
XHS_ITEM_STATUS_ZH = {
    "pending": "等待处理",
    "fetching": "正在获取作品",
    "downloading": "正在下载",
    "downloaded": "已下载",
    "processing": "正在换 BGM",
    "done": "已完成",
    "partial_done": "部分完成",
    "failed": "失败",
    "need_manual": "需要人工处理",
    "skipped": "已跳过",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_quick_bgm_dirs() -> None:
    for path in (QUICK_BGM_DIR, QUICK_UPLOADS_DIR, BGM_LIBRARY_DIR, QUICK_OUTPUTS_DIR):
        path.mkdir(parents=True, exist_ok=True)
    for path in (BGM_LIBRARY_PATH, JOBS_PATH, XHS_CREATOR_BATCHES_PATH, XHS_IMPORTED_NOTES_PATH, AUTOMATION_JOBS_PATH):
        if not path.exists():
            path.write_text("[]", encoding="utf-8")


def safe_filename(filename: str | None, fallback: str) -> str:
    raw = Path(filename or fallback).name.strip() or fallback
    cleaned = re.sub(r'[\\/:*?"<>|]', "_", raw)
    cleaned = re.sub(r"\s+", "_", cleaned)
    return cleaned.strip("._ ") or fallback


def safe_stem(filename: str | None, fallback: str = "video") -> str:
    return Path(safe_filename(filename, fallback)).stem or fallback


def normalize_note_url(url: str | None) -> str:
    if not url:
        return ""
    text = url.strip()
    try:
        parsed = urlparse(text)
    except Exception:
        return text
    if not parsed.netloc:
        return text
    keep_params = []
    for key, value in parse_qsl(parsed.query, keep_blank_values=True):
        if key in {"xsec_token", "xsec_source"}:
            keep_params.append((key, value))
    query = urlencode(sorted(keep_params))
    path = parsed.path.rstrip("/")
    return urlunparse((parsed.scheme or "https", parsed.netloc.lower(), path, "", query, ""))


def xhs_record_key(note_id: str | None = None, note_url: str | None = None) -> str:
    if note_id:
        return f"note:{str(note_id).strip()}"
    normalized = normalize_note_url(note_url)
    return f"url:{normalized}" if normalized else ""


def parse_bgm_filename(filename: str | None) -> tuple[str, str]:
    stem = Path(filename or "BGM").name
    stem = Path(stem).stem.strip() or "BGM"
    for delimiter in (" - ", "—", "－", "_", "-"):
        if delimiter in stem:
            left, right = stem.split(delimiter, 1)
            song = left.strip() or stem
            artist = right.strip()
            return song, artist
    return stem, "未填写"


def make_display_name(song_name: str | None, artist_name: str | None) -> str:
    song = (song_name or "未命名 BGM").strip()
    artist = (artist_name or "").strip()
    return f"{song} - {artist}" if artist and artist != "未填写" else song


def _read_list(path: Path) -> list[dict[str, Any]]:
    ensure_quick_bgm_dirs()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        data = []
    return data if isinstance(data, list) else []


def _write_list(path: Path, rows: list[dict[str, Any]]) -> None:
    ensure_quick_bgm_dirs()
    temp_path = path.with_name(f"{path.name}.{uuid.uuid4().hex}.tmp")
    temp_path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    temp_path.replace(path)


def normalize_bgm_record(item: dict[str, Any]) -> dict[str, Any]:
    song_name = item.get("song_name") or item.get("bgm_name") or safe_stem(item.get("original_filename"), "BGM")
    artist_name = item.get("artist_name") or "未填写"
    source_type = item.get("source_type") or "upload"
    local_file_path = item.get("local_file_path")
    is_available = item.get("is_available")
    if is_available is None:
        is_available = bool(local_file_path and Path(local_file_path).exists())
    availability_status = item.get("availability_status") or ("usable" if is_available else "unknown")
    normalized = dict(item)
    normalized.update(
        {
            "song_name": song_name,
            "artist_name": artist_name,
            "display_name": item.get("display_name") or make_display_name(song_name, artist_name),
            "bgm_name": item.get("bgm_name") or make_display_name(song_name, artist_name),
            "source_type": source_type,
            "source_type_zh": BGM_SOURCE_TYPE_ZH.get(source_type, source_type),
            "usage_count": int(item.get("usage_count") or 0),
            "is_available": bool(is_available),
            "availability_status": availability_status,
            "availability_status_zh": AVAILABILITY_STATUS_ZH.get(availability_status, availability_status),
            "duration_seconds": item.get("duration_seconds"),
        }
    )
    return normalized


def compact_bgm_record(item: dict[str, Any]) -> dict[str, Any]:
    normalized = normalize_bgm_record(item)
    return {
        "bgm_id": normalized.get("bgm_id"),
        "song_name": normalized.get("song_name"),
        "artist_name": normalized.get("artist_name"),
        "display_name": normalized.get("display_name"),
        "source_type_zh": normalized.get("source_type_zh"),
        "usage_count": normalized.get("usage_count"),
        "availability_status_zh": normalized.get("availability_status_zh"),
        "source_type": normalized.get("source_type"),
        "duration_seconds": normalized.get("duration_seconds"),
        "is_available": normalized.get("is_available"),
    }


def list_bgm() -> list[dict[str, Any]]:
    rows = [normalize_bgm_record(item) for item in _read_list(BGM_LIBRARY_PATH)]
    return sorted(rows, key=lambda item: (not item.get("is_available"), -int(item.get("usage_count") or 0), item.get("created_at") or ""))


def get_bgm(bgm_id: str) -> dict[str, Any] | None:
    return next((item for item in list_bgm() if item.get("bgm_id") == bgm_id), None)


def add_bgm_record(
    *,
    song_name: str | None = None,
    artist_name: str | None = None,
    bgm_name: str | None = None,
    original_filename: str,
    local_file_path: str,
    source_type: str = "upload",
    source_query: str | None = None,
    source_url: str | None = None,
    tags: list[str] | None = None,
    region: str = "unknown",
    style: str = "unknown",
    duration_seconds: float | None = None,
) -> dict[str, Any]:
    rows = _read_list(BGM_LIBRARY_PATH)
    timestamp = now_iso()
    parsed_song, parsed_artist = parse_bgm_filename(original_filename)
    final_song = (song_name or bgm_name or parsed_song).strip()
    final_artist = (artist_name or parsed_artist or "未填写").strip()
    display_name = make_display_name(final_song, final_artist)
    record = {
        "bgm_id": uuid.uuid4().hex,
        "song_name": final_song,
        "artist_name": final_artist,
        "display_name": display_name,
        "bgm_name": display_name,
        "original_filename": original_filename,
        "local_file_path": local_file_path,
        "source_type": source_type,
        "source_type_zh": BGM_SOURCE_TYPE_ZH.get(source_type, source_type),
        "source_query": source_query,
        "source_url": source_url,
        "duration_seconds": duration_seconds,
        "usage_count": 0,
        "is_available": True,
        "availability_status": "usable",
        "availability_status_zh": "可使用",
        "tags": tags or [],
        "region": region,
        "region_zh": REGION_ZH.get(region, "未指定"),
        "style": style,
        "style_zh": STYLE_ZH.get(style, "未指定"),
        "created_at": timestamp,
        "updated_at": timestamp,
    }
    rows.append(record)
    _write_list(BGM_LIBRARY_PATH, rows)
    return record


def increment_bgm_usage(bgm_id: str) -> dict[str, Any] | None:
    rows = _read_list(BGM_LIBRARY_PATH)
    updated = None
    for item in rows:
        if item.get("bgm_id") == bgm_id:
            item["usage_count"] = int(item.get("usage_count") or 0) + 1
            item["updated_at"] = now_iso()
            updated = normalize_bgm_record(item)
            break
    _write_list(BGM_LIBRARY_PATH, rows)
    return updated


def find_xhs_import_record(note_id: str | None = None, note_url: str | None = None) -> dict[str, Any] | None:
    key = xhs_record_key(note_id, note_url)
    if not key:
        return None
    for item in _read_list(XHS_IMPORTED_NOTES_PATH):
        if item.get("dedupe_key") == key:
            return item
    normalized_url = normalize_note_url(note_url)
    if normalized_url:
        for item in _read_list(XHS_IMPORTED_NOTES_PATH):
            if normalize_note_url(item.get("note_url") or item.get("raw_note_url")) == normalized_url:
                return item
    return None


def upsert_xhs_import_record(
    *,
    note_id: str | None = None,
    note_url: str | None = None,
    title: str | None = None,
    author: str | None = None,
    publish_time: str | None = None,
    note_type: str | None = None,
    is_video: bool | None = None,
    metrics: dict[str, Any] | None = None,
    cover_url: str | None = None,
    video_download_url: str | None = None,
    is_imported: bool = True,
    is_processed: bool | None = None,
    processed_job_id: str | None = None,
) -> dict[str, Any]:
    rows = _read_list(XHS_IMPORTED_NOTES_PATH)
    normalized_url = normalize_note_url(note_url)
    key = xhs_record_key(note_id, normalized_url or note_url)
    if not key:
        key = f"url:{uuid.uuid4().hex}"
    now = now_iso()
    existing_index = None
    existing: dict[str, Any] = {}
    for index, item in enumerate(rows):
        if item.get("dedupe_key") == key:
            existing_index = index
            existing = dict(item)
            break
    processed = bool(existing.get("is_processed")) if is_processed is None else bool(is_processed)
    record = {
        "record_id": existing.get("record_id") or uuid.uuid4().hex,
        "dedupe_key": key,
        "note_id": note_id or existing.get("note_id"),
        "note_url": normalized_url or existing.get("note_url") or note_url,
        "raw_note_url": note_url or existing.get("raw_note_url"),
        "title": title or existing.get("title") or "小红书作品",
        "author": author or existing.get("author") or "",
        "publish_time": publish_time or existing.get("publish_time"),
        "note_type": note_type or existing.get("note_type") or ("视频" if is_video else "图文/未知"),
        "metrics": metrics or existing.get("metrics") or {},
        "cover_url": cover_url or existing.get("cover_url"),
        "video_download_url": video_download_url or existing.get("video_download_url"),
        "is_imported": bool(is_imported or existing.get("is_imported")),
        "is_processed": processed,
        "processed_job_id": processed_job_id or existing.get("processed_job_id"),
        "first_imported_at": existing.get("first_imported_at") or now,
        "last_imported_at": now,
        "last_processed_at": now if processed and (is_processed or processed_job_id) else existing.get("last_processed_at"),
    }
    if existing_index is None:
        rows.append(record)
    else:
        rows[existing_index] = record
    _write_list(XHS_IMPORTED_NOTES_PATH, rows)
    return record


def list_jobs() -> list[dict[str, Any]]:
    return sorted(_read_list(JOBS_PATH), key=lambda item: item.get("created_at") or "", reverse=True)


def get_job(job_id: str) -> dict[str, Any] | None:
    return next((item for item in _read_list(JOBS_PATH) if item.get("job_id") == job_id), None)


def save_job(job: dict[str, Any]) -> dict[str, Any]:
    rows = _read_list(JOBS_PATH)
    found = False
    for index, item in enumerate(rows):
        if item.get("job_id") == job.get("job_id"):
            rows[index] = job
            found = True
            break
    if not found:
        rows.append(job)
    _write_list(JOBS_PATH, rows)
    return job


def make_job(
    *,
    input_type: str,
    source_url: str | None,
    original_video_path: str | None,
    original_filename: str | None,
    bgm_id: str | None = None,
    bgm_name: str | None = None,
    replace_audio: bool = True,
    bgm_start_seconds: float = 0,
    video_duration_seconds: float | None = None,
    status: str = "pending",
    message_zh: str = "等待选择 BGM 并生成预览。",
) -> dict[str, Any]:
    timestamp = now_iso()
    job = {
        "job_id": uuid.uuid4().hex,
        "input_type": input_type,
        "input_type_zh": INPUT_TYPE_ZH.get(input_type, input_type),
        "source_url": source_url,
        "original_video_path": original_video_path,
        "original_filename": original_filename,
        "bgm_id": bgm_id,
        "bgm_name": bgm_name,
        "replace_audio": replace_audio,
        "replace_audio_zh": REPLACE_AUDIO_ZH[bool(replace_audio)],
        "bgm_start_seconds": max(float(bgm_start_seconds or 0), 0),
        "video_duration_seconds": video_duration_seconds,
        "output_video_path": None,
        "status": status,
        "status_zh": STATUS_ZH.get(status, status),
        "message_zh": message_zh,
        "failure_reason": None,
        "created_at": timestamp,
        "updated_at": timestamp,
    }
    return save_job(job)


def update_job(job_id: str, **changes: Any) -> dict[str, Any]:
    job = get_job(job_id)
    if not job:
        raise KeyError(job_id)
    job.update(changes)
    if "status" in changes:
        job["status_zh"] = STATUS_ZH.get(changes["status"], changes["status"])
    if "replace_audio" in changes:
        job["replace_audio_zh"] = REPLACE_AUDIO_ZH[bool(changes["replace_audio"])]
    if "bgm_start_seconds" in changes:
        job["bgm_start_seconds"] = max(float(changes["bgm_start_seconds"] or 0), 0)
    job["updated_at"] = now_iso()
    return save_job(job)


def list_available_bgm() -> list[dict[str, Any]]:
    return [item for item in list_bgm() if item.get("is_available") and item.get("local_file_path") and Path(item["local_file_path"]).exists()]


def list_batches() -> list[dict[str, Any]]:
    return sorted(_read_list(XHS_CREATOR_BATCHES_PATH), key=lambda item: item.get("created_at") or "", reverse=True)


def get_batch(batch_id: str) -> dict[str, Any] | None:
    return next((item for item in _read_list(XHS_CREATOR_BATCHES_PATH) if item.get("batch_id") == batch_id), None)


def save_batch(batch: dict[str, Any]) -> dict[str, Any]:
    rows = _read_list(XHS_CREATOR_BATCHES_PATH)
    found = False
    for index, item in enumerate(rows):
        if item.get("batch_id") == batch.get("batch_id"):
            rows[index] = batch
            found = True
            break
    if not found:
        rows.append(batch)
    _write_list(XHS_CREATOR_BATCHES_PATH, rows)
    return batch


def new_batch(
    *,
    creator_home_url: str | None,
    import_mode: str,
    requested_limit: int,
    selected_bgm_id: str | None,
    selected_bgm_name: str | None,
    bgm_strategy: str,
    replace_audio: bool,
    bgm_start_seconds: float,
    message_zh: str,
) -> dict[str, Any]:
    timestamp = now_iso()
    return {
        "batch_id": uuid.uuid4().hex,
        "creator_home_url": creator_home_url,
        "creator_name": None,
        "import_mode": import_mode,
        "import_mode_zh": XHS_IMPORT_MODE_ZH.get(import_mode, import_mode),
        "requested_limit": min(max(int(requested_limit or 10), 1), 10),
        "actual_found_count": 0,
        "video_found_count": 0,
        "downloaded_count": 0,
        "processed_count": 0,
        "failed_count": 0,
        "selected_bgm_id": selected_bgm_id,
        "selected_bgm_name": selected_bgm_name,
        "bgm_strategy": bgm_strategy,
        "bgm_strategy_zh": BGM_STRATEGY_ZH.get(bgm_strategy, bgm_strategy),
        "replace_audio": bool(replace_audio),
        "replace_audio_zh": REPLACE_AUDIO_ZH[bool(replace_audio)],
        "bgm_start_seconds": max(float(bgm_start_seconds or 0), 0),
        "status": "pending",
        "status_zh": XHS_ITEM_STATUS_ZH["pending"],
        "message_zh": message_zh,
        "created_at": timestamp,
        "updated_at": timestamp,
        "items": [],
    }


def make_batch_item(**data: Any) -> dict[str, Any]:
    status = data.get("status") or "pending"
    return {
        "item_id": data.get("item_id") or uuid.uuid4().hex,
        "note_url": data.get("note_url"),
        "note_id": data.get("note_id"),
        "title": data.get("title") or "未命名作品",
        "publish_time": data.get("publish_time"),
        "author": data.get("author"),
        "cover_url": data.get("cover_url"),
        "is_video": bool(data.get("is_video", True)),
        "video_download_url": data.get("video_download_url"),
        "preview_video_url": data.get("preview_video_url"),
        "liked_count": data.get("liked_count"),
        "collected_count": data.get("collected_count"),
        "comment_count": data.get("comment_count"),
        "metrics": data.get("metrics") or {},
        "local_video_path": data.get("local_video_path"),
        "output_video_path": data.get("output_video_path"),
        "status": status,
        "status_zh": XHS_ITEM_STATUS_ZH.get(status, status),
        "failure_reason": data.get("failure_reason"),
        "quick_bgm_job_id": data.get("quick_bgm_job_id"),
    }


def refresh_batch_counts(batch: dict[str, Any]) -> dict[str, Any]:
    items = batch.get("items") or []
    batch["actual_found_count"] = len(items)
    batch["video_found_count"] = sum(1 for item in items if item.get("is_video"))
    batch["downloaded_count"] = sum(1 for item in items if item.get("local_video_path"))
    batch["processed_count"] = sum(1 for item in items if item.get("status") == "done")
    batch["failed_count"] = sum(1 for item in items if item.get("status") in {"failed", "need_manual"})
    if batch["processed_count"] and batch["processed_count"] < len(items):
        batch["status"] = "partial_done"
    elif batch["processed_count"] and batch["processed_count"] == len(items):
        batch["status"] = "done"
    elif batch["failed_count"]:
        batch["status"] = "failed"
    batch["status_zh"] = XHS_ITEM_STATUS_ZH.get(batch["status"], batch["status"])
    batch["updated_at"] = now_iso()
    return batch


def automation_source_type_zh(source_type: str | None) -> str:
    key = source_type or "manual"
    return AUTOMATION_SOURCE_TYPE_ZH.get(key, key)


def automation_status_zh(status: str | None) -> str:
    key = status or "pending"
    return AUTOMATION_STATUS_ZH.get(key, key)


def automation_bgm_strategy_zh(strategy: str | None) -> str:
    key = strategy or "selected"
    return BGM_STRATEGY_ZH.get(key, key)


def make_automation_item(**data: Any) -> dict[str, Any]:
    status = data.get("status") or "pending"
    input_type = data.get("input_type") or "manual"
    return {
        "item_id": data.get("item_id") or uuid.uuid4().hex,
        "input_type": input_type,
        "input_type_zh": data.get("input_type_zh") or automation_source_type_zh(input_type),
        "source_url": data.get("source_url"),
        "local_video_path": data.get("local_video_path"),
        "title": data.get("title") or data.get("original_filename") or "未命名视频",
        "author_name": data.get("author_name") or data.get("author") or "",
        "cover_url": data.get("cover_url") or data.get("preview_url"),
        "preview_video_url": data.get("preview_video_url") or data.get("video_download_url"),
        "quick_bgm_job_id": data.get("quick_bgm_job_id"),
        "output_video_path": data.get("output_video_path"),
        "preview_url": data.get("preview_url"),
        "download_url": data.get("download_url"),
        "video_duration_seconds": data.get("video_duration_seconds"),
        "status": status,
        "status_zh": automation_status_zh(status),
        "failure_reason": data.get("failure_reason"),
        "note_id": data.get("note_id"),
        "note_url": data.get("note_url") or data.get("source_url"),
        "publish_time": data.get("publish_time"),
        "metrics": data.get("metrics") or {},
    }


def list_automation_jobs() -> list[dict[str, Any]]:
    rows = [refresh_automation_job_counts(dict(item)) for item in _read_list(AUTOMATION_JOBS_PATH)]
    return sorted(rows, key=lambda item: item.get("created_at") or "", reverse=True)


def get_automation_job(automation_job_id: str) -> dict[str, Any] | None:
    return next((item for item in _read_list(AUTOMATION_JOBS_PATH) if item.get("automation_job_id") == automation_job_id), None)


def save_automation_job(job: dict[str, Any]) -> dict[str, Any]:
    job["updated_at"] = now_iso()
    job = refresh_automation_job_counts(job)
    with _LIST_LOCK:
        rows = _read_list(AUTOMATION_JOBS_PATH)
        found = False
        for index, item in enumerate(rows):
            if item.get("automation_job_id") == job.get("automation_job_id"):
                rows[index] = job
                found = True
                break
        if not found:
            rows.append(job)
        _write_list(AUTOMATION_JOBS_PATH, rows)
    return job


def new_automation_job(
    *,
    source_type: str,
    source_payload: dict[str, Any],
    bgm_strategy: str,
    bgm_id: str | None,
    bgm_query: str | None,
    selected_bgm_id: str | None,
    selected_bgm_name: str | None,
    replace_audio: bool,
    bgm_start_seconds: float,
    dry_run: bool,
    force_reimport: bool,
    items: list[dict[str, Any]] | None = None,
    status: str = "pending",
    message_zh: str = "自动化任务已创建。",
) -> dict[str, Any]:
    timestamp = now_iso()
    return {
        "automation_job_id": uuid.uuid4().hex,
        "source_type": source_type,
        "source_type_zh": automation_source_type_zh(source_type),
        "source_payload": source_payload,
        "bgm_strategy": bgm_strategy,
        "bgm_strategy_zh": automation_bgm_strategy_zh(bgm_strategy),
        "bgm_id": bgm_id,
        "bgm_query": bgm_query,
        "selected_bgm_id": selected_bgm_id,
        "selected_bgm_name": selected_bgm_name,
        "replace_audio": bool(replace_audio),
        "replace_audio_zh": REPLACE_AUDIO_ZH[bool(replace_audio)],
        "bgm_start_seconds": max(float(bgm_start_seconds or 0), 0),
        "dry_run": bool(dry_run),
        "force_reimport": bool(force_reimport),
        "status": status,
        "status_zh": automation_status_zh(status),
        "message_zh": message_zh,
        "created_at": timestamp,
        "updated_at": timestamp,
        "item_count": len(items or []),
        "ready_count": 0,
        "done_count": 0,
        "failed_count": 0,
        "items": items or [],
    }


def update_automation_job(automation_job_id: str, **changes: Any) -> dict[str, Any]:
    job = get_automation_job(automation_job_id)
    if not job:
        raise KeyError(automation_job_id)
    job.update(changes)
    if "source_type" in changes:
        job["source_type_zh"] = automation_source_type_zh(changes["source_type"])
    if "bgm_strategy" in changes:
        job["bgm_strategy_zh"] = automation_bgm_strategy_zh(changes["bgm_strategy"])
    if "replace_audio" in changes:
        job["replace_audio_zh"] = REPLACE_AUDIO_ZH[bool(changes["replace_audio"])]
    if "status" in changes:
        job["status_zh"] = automation_status_zh(changes["status"])
    job["updated_at"] = now_iso()
    return save_automation_job(job)


def refresh_automation_job_counts(job: dict[str, Any]) -> dict[str, Any]:
    items = job.get("items") or []
    total = len(items)
    ready_count = sum(1 for item in items if item.get("status") == "ready")
    done_count = sum(1 for item in items if item.get("status") == "done")
    failed_count = sum(1 for item in items if item.get("status") in {"failed", "need_manual"})
    skipped_count = sum(1 for item in items if item.get("status") == "skipped")
    processing_count = sum(1 for item in items if item.get("status") == "processing")

    job["item_count"] = total
    job["ready_count"] = ready_count
    job["done_count"] = done_count
    job["failed_count"] = failed_count

    status = job.get("status") or "pending"
    if processing_count:
        status = "processing"
    elif total and done_count == total:
        status = "done"
    elif total and done_count and done_count + failed_count + skipped_count == total:
        status = "partial_done" if failed_count or skipped_count else "done"
    elif total and ready_count and not done_count:
        status = "ready"
    elif total and failed_count == total:
        status = "failed"
    elif total and skipped_count == total:
        status = "skipped"
    elif not total and status not in {"failed", "need_manual"}:
        status = "pending"

    job["status"] = status
    job["status_zh"] = automation_status_zh(status)
    job["source_type_zh"] = automation_source_type_zh(job.get("source_type"))
    job["bgm_strategy_zh"] = automation_bgm_strategy_zh(job.get("bgm_strategy"))
    job["replace_audio_zh"] = REPLACE_AUDIO_ZH[bool(job.get("replace_audio", True))]
    job["updated_at"] = job.get("updated_at") or now_iso()
    return job
