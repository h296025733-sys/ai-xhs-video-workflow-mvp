import os
import random
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel, Field

from app.quick_bgm.bgm_search_downloader import search_and_download_bgm
from app.quick_bgm.media import QuickBgmMediaError, extract_video_cover, media_duration_seconds, run_quick_bgm_job
from app.quick_bgm.store import (
    BGM_LIBRARY_DIR,
    QUICK_UPLOADS_DIR,
    add_bgm_record,
    compact_bgm_record,
    get_automation_job,
    get_batch,
    get_bgm,
    get_job,
    find_xhs_import_record,
    increment_bgm_usage,
    list_automation_jobs,
    list_available_bgm,
    list_batches,
    list_bgm,
    list_jobs,
    make_automation_item,
    make_batch_item,
    make_job,
    new_automation_job,
    new_batch,
    refresh_automation_job_counts,
    refresh_batch_counts,
    safe_filename,
    save_automation_job,
    save_batch,
    save_job,
    upsert_xhs_import_record,
    update_automation_job,
    update_job,
)
from app.quick_bgm.xhs_adapter import import_xiaohongshu_video
from app.quick_bgm.xhs_creator_importer import XHS_CREATOR_DOWNLOADS_DIR, download_note_video, import_creator_items, preview_note_link


router = APIRouter(prefix="/quick-bgm", tags=["快速换 BGM"])
DEFAULT_CREATOR_URL = "https://www.xiaohongshu.com/user/profile/YOUR_CREATOR_ID?xsec_token=YOUR_XSEC_TOKEN_HERE&xsec_source=pc_search"


class QuickBgmAutomationCreateRequest(BaseModel):
    source_type: str = Field(default="manual")
    video_paths: list[str] | None = None
    note_urls: list[str] | None = None
    creator_home_url: str | None = None
    job_ids: list[str] | None = None
    limit: int = Field(default=10, ge=1)
    replace_audio: bool = True
    bgm_strategy: str = "top_used_random"
    bgm_id: str | None = None
    bgm_query: str | None = None
    bgm_start_seconds: float = 0
    force_reimport: bool = False
    dry_run: bool = False


@router.get("/page", response_class=HTMLResponse, summary="服装短视频快速处理工作台")
def quick_bgm_page() -> HTMLResponse:
    return HTMLResponse(content=_page_html(), media_type="text/html; charset=utf-8")


@router.get("/xhs-creator/page", response_class=HTMLResponse, summary="小红书博主批量换 BGM 页面")
def xhs_creator_page() -> HTMLResponse:
    # 旧入口保留，但内容统一跳转到老板可看的主工作台，避免两个页面割裂。
    return HTMLResponse(content=_page_html(), media_type="text/html; charset=utf-8")


@router.get("/bgm", summary="查看 BGM 库")
def get_bgm_library() -> dict:
    return {
        "items": [compact_bgm_record(item) for item in list_bgm()],
        "message_zh": "BGM 库读取成功，已按可用状态和使用次数排序。",
    }


@router.get("/bgm/{bgm_id}/file", summary="预览 BGM 音频")
def get_bgm_file(bgm_id: str) -> FileResponse:
    bgm = get_bgm(bgm_id)
    if not bgm or not bgm.get("local_file_path"):
        raise HTTPException(status_code=404, detail="未找到 BGM 文件。")
    path = Path(bgm["local_file_path"])
    if not path.exists():
        raise HTTPException(status_code=404, detail="BGM 文件不存在，请重新上传。")
    return FileResponse(path, filename=path.name)


@router.get("/bgm/{bgm_id}/info", summary="读取 BGM 信息")
def get_bgm_info(bgm_id: str) -> dict:
    bgm = get_bgm(bgm_id)
    if not bgm:
        raise HTTPException(status_code=404, detail="未找到 BGM。")
    info = compact_bgm_record(bgm)
    if info.get("duration_seconds") is None:
        info["duration_seconds"] = media_duration_seconds(bgm.get("local_file_path"))
    return {"bgm": info, "message_zh": "BGM 信息读取成功。"}


@router.post("/bgm/upload", summary="上传 BGM 并加入本地库")
async def upload_bgm(
    file: UploadFile = File(...),
    song_name: str | None = Form(default=None),
    artist_name: str | None = Form(default=None),
    bgm_name: str | None = Form(default=None),
) -> dict:
    original_filename = Path(file.filename or "bgm.mp3").name
    filename = safe_filename(original_filename, "bgm.mp3")
    if Path(filename).suffix.lower() not in {".mp3", ".m4a", ".wav", ".aac", ".flac", ".opus", ".webm"}:
        raise HTTPException(status_code=400, detail="请上传 mp3、m4a、wav、aac、flac、opus 等音频文件。")
    BGM_LIBRARY_DIR.mkdir(parents=True, exist_ok=True)
    target = BGM_LIBRARY_DIR / f"{Path(filename).stem}__{len(list_bgm()) + 1}{Path(filename).suffix or '.mp3'}"
    size = 0
    with target.open("wb") as buffer:
        while chunk := await file.read(1024 * 1024):
            size += len(chunk)
            buffer.write(chunk)
    duration = media_duration_seconds(target)
    record = add_bgm_record(
        song_name=song_name,
        artist_name=artist_name,
        bgm_name=bgm_name,
        original_filename=original_filename,
        local_file_path=str(target),
        source_type="upload",
        duration_seconds=duration,
    )
    compact = compact_bgm_record(record)
    compact["duration_seconds"] = duration
    return {"bgm": compact, "size_bytes": size, "duration_seconds": duration, "message_zh": "BGM 已上传并加入本地库。"}


@router.post("/bgm/search-download", summary="在线搜索并下载最相关 BGM")
def search_download_bgm(
    query: str = Form(...),
    artist_name: str | None = Form(default=None),
    prefer_source: str | None = Form(default=None),
) -> dict:
    if not query.strip():
        raise HTTPException(status_code=400, detail="请输入 BGM 名称或关键词。")
    result = search_and_download_bgm(query.strip(), prefer_source=prefer_source)
    if not result.get("ok"):
        return {"ok": False, "message_zh": result["message_zh"], "failure_reason": result.get("failure_reason")}
    duration = media_duration_seconds(result["local_file_path"])
    record = add_bgm_record(
        song_name=result.get("song_name"),
        artist_name=artist_name or result.get("artist_name"),
        original_filename=result["original_filename"],
        local_file_path=result["local_file_path"],
        source_type="search_download",
        source_query=query.strip(),
        source_url=result.get("source_url"),
        duration_seconds=duration,
    )
    compact = compact_bgm_record(record)
    compact["duration_seconds"] = duration
    return {"ok": True, "bgm": compact, "message_zh": "在线搜索下载成功，已加入 BGM 库。"}


@router.post("/video/upload", summary="上传一个或多个本地视频")
async def upload_video(files: list[UploadFile] | None = File(default=None), file: UploadFile | None = File(default=None)) -> dict:
    upload_files = files or ([file] if file else [])
    if not upload_files:
        raise HTTPException(status_code=400, detail="请先选择视频文件。")
    jobs = []
    for upload in upload_files:
        filename = safe_filename(upload.filename, "video.mp4")
        target_job = make_job(
            input_type="upload",
            source_url=None,
            original_video_path=None,
            original_filename=filename,
            message_zh="视频已上传，等待选择 BGM。",
        )
        target_dir = QUICK_UPLOADS_DIR / target_job["job_id"]
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / filename
        size = 0
        with target.open("wb") as buffer:
            while chunk := await upload.read(1024 * 1024):
                size += len(chunk)
                buffer.write(chunk)
        duration = media_duration_seconds(target)
        cover = extract_video_cover(target, target_dir / "cover.jpg")
        target_job["original_video_path"] = str(target)
        target_job["size_bytes"] = size
        target_job["video_duration_seconds"] = duration
        target_job["cover_image_path"] = cover
        save_job(target_job)
        jobs.append(target_job)
    return {"jobs": jobs, "video_id": jobs[0]["job_id"] if jobs else None, "message_zh": "视频上传成功，已加入待处理列表。"}


@router.post("/xiaohongshu/import", summary="通过小红书链接导入视频")
def import_xiaohongshu(source_url: str = Form(...)) -> dict:
    result = import_xiaohongshu_video(source_url)
    if not result.get("ok"):
        job = make_job(
            input_type="xiaohongshu_link",
            source_url=source_url,
            original_video_path=None,
            original_filename=None,
            status="failed",
            message_zh=result["message_zh"],
        )
        job["failure_reason"] = result.get("failure_reason")
        save_job(job)
        return {"ok": False, "job": job, "message_zh": result["message_zh"]}

    local_path = result["local_file_path"]
    job = make_job(
        input_type="xiaohongshu_link",
        source_url=source_url,
        original_video_path=local_path,
        original_filename=Path(local_path).name,
        video_duration_seconds=media_duration_seconds(local_path),
        message_zh="小红书视频已导入，等待选择 BGM。",
    )
    cover = extract_video_cover(local_path, Path(local_path).with_suffix(".cover.jpg"))
    if cover:
        job["cover_image_path"] = cover
        save_job(job)
    return {"ok": True, "job": job, "message_zh": result["message_zh"]}


@router.post("/jobs/create", summary="创建换 BGM 任务")
def create_job(
    video_id: str | None = Form(default=None),
    job_id: str | None = Form(default=None),
    bgm_id: str | None = Form(default=None),
    replace_audio: bool = Form(default=True),
    bgm_start_seconds: float = Form(default=0),
) -> dict:
    source_id = video_id or job_id
    if not source_id:
        raise HTTPException(status_code=400, detail="请先上传视频。")
    source_job = get_job(source_id)
    if not source_job or not source_job.get("original_video_path"):
        raise HTTPException(status_code=404, detail="未找到可用的视频，请先上传视频。")

    bgm = get_bgm(bgm_id) if bgm_id else None
    if replace_audio and not bgm:
        raise HTTPException(status_code=400, detail="请选择一个 BGM。")

    job = make_job(
        input_type=source_job.get("input_type") or "upload",
        source_url=source_job.get("source_url"),
        original_video_path=source_job.get("original_video_path"),
        original_filename=source_job.get("original_filename"),
        bgm_id=bgm.get("bgm_id") if bgm else None,
        bgm_name=bgm.get("display_name") if bgm else None,
        replace_audio=replace_audio,
        bgm_start_seconds=bgm_start_seconds,
        video_duration_seconds=source_job.get("video_duration_seconds") or media_duration_seconds(source_job.get("original_video_path")),
        message_zh="换 BGM 任务已创建，等待生成预览。",
    )
    if source_job.get("cover_image_path"):
        job["cover_image_path"] = source_job.get("cover_image_path")
        save_job(job)
    return {"job": job, "message_zh": "任务已创建。"}


@router.post("/jobs/{job_id}/run", summary="执行换 BGM 任务")
def run_job(job_id: str) -> dict:
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="未找到任务。")
    job = update_job(job_id, status="processing", message_zh="正在生成预览视频。", failure_reason=None)
    try:
        bgm = get_bgm(job["bgm_id"]) if job.get("bgm_id") else None
        done = run_quick_bgm_job(job, bgm)
        if done.get("replace_audio") and done.get("bgm_id"):
            increment_bgm_usage(done["bgm_id"])
    except QuickBgmMediaError as exc:
        failed = update_job(job_id, status="failed", message_zh="生成失败，请检查视频、BGM 或 ffmpeg。", failure_reason=str(exc))
        return {"job": failed, "message_zh": failed["message_zh"]}
    return {"job": done, "message_zh": done["message_zh"]}


@router.get("/jobs/{job_id}", summary="查看任务状态")
def get_job_status(job_id: str) -> dict:
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="未找到任务。")
    return {"job": job}


@router.get("/jobs", summary="查看快速换 BGM 任务列表")
def get_jobs() -> dict:
    return {"jobs": list_jobs(), "message_zh": "任务列表读取成功。"}


@router.get("/files/{job_id}/source", summary="预览原视频")
def get_source_file(job_id: str) -> FileResponse:
    job = get_job(job_id)
    if not job or not job.get("original_video_path"):
        raise HTTPException(status_code=404, detail="未找到原视频。")
    path = Path(job["original_video_path"])
    if not path.exists():
        raise HTTPException(status_code=404, detail="原视频文件不存在。")
    return FileResponse(path, media_type="video/mp4", filename=path.name)


@router.get("/files/{job_id}/output", summary="预览或下载输出视频")
def get_output_file(job_id: str) -> FileResponse:
    job = get_job(job_id)
    if not job or not job.get("output_video_path"):
        raise HTTPException(status_code=404, detail="任务还没有生成输出视频。")
    path = Path(job["output_video_path"])
    if not path.exists():
        raise HTTPException(status_code=404, detail="输出视频文件不存在。")
    return FileResponse(path, media_type="video/mp4", filename=path.name)


@router.get("/files/{job_id}/cover", summary="预览视频封面")
def get_cover_file(job_id: str) -> FileResponse:
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="未找到任务。")
    cover_path = job.get("cover_image_path")
    path = Path(cover_path) if cover_path else None
    if not path or not path.exists():
        for candidate in (job.get("output_video_path"), job.get("original_video_path")):
            if not candidate:
                continue
            source = Path(candidate)
            if not source.exists():
                continue
            generated = extract_video_cover(source, source.with_suffix(".cover.jpg"))
            if generated:
                job["cover_image_path"] = generated
                save_job(job)
                path = Path(generated)
                break
    if not path or not path.exists():
        raise HTTPException(status_code=404, detail="暂无封面图。")
    return FileResponse(path, media_type="image/jpeg", filename=path.name)


@router.get("/media-info", summary="读取视频或音频时长")
def get_media_info(job_id: str | None = Query(default=None), bgm_id: str | None = Query(default=None)) -> dict:
    if job_id:
        job = get_job(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="未找到视频任务。")
        duration = job.get("video_duration_seconds") or media_duration_seconds(job.get("original_video_path"))
        return {"duration_seconds": duration, "message_zh": "视频时长读取成功。" if duration is not None else "视频时长暂未读取到。"}
    if bgm_id:
        bgm = get_bgm(bgm_id)
        if not bgm:
            raise HTTPException(status_code=404, detail="未找到 BGM。")
        duration = bgm.get("duration_seconds") or media_duration_seconds(bgm.get("local_file_path"))
        return {"duration_seconds": duration, "message_zh": "BGM 时长读取成功。" if duration is not None else "BGM 时长暂未读取到。"}
    raise HTTPException(status_code=400, detail="请提供 job_id 或 bgm_id。")


@router.post("/automation/create", summary="创建 OpenClaw 可调用的自动换 BGM 任务")
def create_quick_bgm_automation(payload: QuickBgmAutomationCreateRequest) -> dict:
    source_type = (payload.source_type or "manual").strip()
    if source_type not in {"local_file", "xhs_note_links", "xhs_creator_profile", "uploaded_video", "manual"}:
        raise HTTPException(status_code=400, detail="source_type 不支持，请使用 local_file、xhs_note_links、xhs_creator_profile、uploaded_video 或 manual。")

    limit = min(max(int(payload.limit or 10), 1), 10)
    source_payload = {
        "video_paths": payload.video_paths or [],
        "note_urls": payload.note_urls or [],
        "creator_home_url": payload.creator_home_url,
        "job_ids": payload.job_ids or [],
        "limit": limit,
    }
    job = new_automation_job(
        source_type=source_type,
        source_payload=source_payload,
        bgm_strategy=payload.bgm_strategy or "top_used_random",
        bgm_id=payload.bgm_id,
        bgm_query=payload.bgm_query,
        selected_bgm_id=None,
        selected_bgm_name=None,
        replace_audio=payload.replace_audio,
        bgm_start_seconds=payload.bgm_start_seconds,
        dry_run=payload.dry_run,
        force_reimport=payload.force_reimport,
        items=[],
        message_zh="自动化任务已创建，正在准备素材和 BGM。",
    )

    bgm, bgm_error = _select_automation_bgm(payload)
    if bgm:
        job["selected_bgm_id"] = bgm.get("bgm_id")
        job["selected_bgm_name"] = bgm.get("display_name") or bgm.get("bgm_name") or bgm.get("song_name")

    items = _prepare_automation_items(payload, job["automation_job_id"], limit)
    if bgm_error:
        for item in items:
            if item.get("status") in {"ready", "pending"}:
                item["status"] = "need_manual"
                item["status_zh"] = "需要人工处理"
                item["failure_reason"] = bgm_error
        if not items:
            items.append(make_automation_item(input_type=source_type, status="need_manual", failure_reason=bgm_error, title="BGM 未就绪"))
        job["message_zh"] = bgm_error
    elif not items:
        job["message_zh"] = "没有可处理的素材，请传入本地视频路径、小红书作品链接，或先通过网页上传视频。"
    elif payload.dry_run:
        job["message_zh"] = "dry_run 已完成：仅预览将处理的素材和 BGM，不生成视频。"
    else:
        ready_count = sum(1 for item in items if item.get("status") == "ready")
        if ready_count:
            job["message_zh"] = f"自动化任务已创建，可处理 {ready_count} 条素材。"
        else:
            first_reason = next((item.get("failure_reason") for item in items if item.get("failure_reason")), "")
            job["message_zh"] = first_reason or "当前没有可处理素材，请查看 items 中的 failure_reason。"

    job["items"] = items
    saved = save_automation_job(job)
    return _automation_response(saved)


@router.get("/automation", summary="查看 OpenClaw 自动化任务列表")
def list_quick_bgm_automation_jobs() -> dict:
    return {
        "items": [_automation_response(job, include_items=False) for job in list_automation_jobs()],
        "message_zh": "自动化任务列表读取成功。",
    }


@router.get("/automation/{automation_job_id}", summary="查看 OpenClaw 自动化任务状态")
def get_quick_bgm_automation_job(automation_job_id: str) -> dict:
    job = get_automation_job(automation_job_id)
    if not job:
        raise HTTPException(status_code=404, detail="未找到自动化任务。")
    return _automation_response(job)


@router.post("/automation/{automation_job_id}/run", summary="执行 OpenClaw 自动换 BGM 任务")
def run_quick_bgm_automation_job(automation_job_id: str) -> dict:
    job = get_automation_job(automation_job_id)
    if not job:
        raise HTTPException(status_code=404, detail="未找到自动化任务。")
    if job.get("dry_run"):
        job["message_zh"] = "这是 dry_run 任务，只用于预览，不会执行生成。请重新创建 dry_run=false 的任务后再 run。"
        save_automation_job(job)
        return _automation_response(job)

    bgm = get_bgm(job.get("selected_bgm_id")) if job.get("selected_bgm_id") else None
    if job.get("replace_audio") and not _is_bgm_available(bgm):
        reason = "BGM 不可用，请先上传 BGM、选择可用 bgm_id，或使用 bgm_strategy=local_random/top_used_random。"
        for item in job.get("items") or []:
            if item.get("status") == "ready":
                item["status"] = "need_manual"
                item["status_zh"] = "需要人工处理"
                item["failure_reason"] = reason
        job["message_zh"] = reason
        save_automation_job(job)
        return _automation_response(job)

    ready_items = [item for item in job.get("items") or [] if item.get("status") == "ready"]
    if not ready_items:
        job["message_zh"] = "当前没有可执行的素材，请查看 items 中的 failure_reason。"
        save_automation_job(job)
        return _automation_response(job)

    job["status"] = "processing"
    job["status_zh"] = "处理中"
    job["message_zh"] = "自动化任务处理中。"
    save_automation_job(job)

    for item in job.get("items") or []:
        if item.get("status") != "ready":
            continue
        _run_automation_item(job, item, bgm)
        save_automation_job(job)

    done_count = sum(1 for item in job.get("items") or [] if item.get("status") == "done")
    failed_count = sum(1 for item in job.get("items") or [] if item.get("status") in {"failed", "need_manual"})
    job["message_zh"] = f"自动化任务执行完成：成功 {done_count} 条，失败或需人工处理 {failed_count} 条。"
    saved = save_automation_job(job)
    return _automation_response(saved)


@router.post("/automation/{automation_job_id}/clear-failed", summary="清理自动化任务中的失败项")
def clear_failed_quick_bgm_automation_items(automation_job_id: str) -> dict:
    job = get_automation_job(automation_job_id)
    if not job:
        raise HTTPException(status_code=404, detail="未找到自动化任务。")
    before = len(job.get("items") or [])
    job["items"] = [item for item in job.get("items") or [] if item.get("status") not in {"failed", "need_manual"}]
    removed = before - len(job["items"])
    job["message_zh"] = f"已清理 {removed} 条失败或需人工处理的素材。"
    saved = save_automation_job(job)
    response = _automation_response(saved)
    response["removed_count"] = removed
    return response


@router.post("/xhs-creator/import", summary="导入小红书博主最近作品并批量换 BGM")
def import_xhs_creator(
    creator_home_url: str = Form(...),
    limit: int = Form(default=10),
    bgm_id: str | None = Form(default=None),
    bgm_strategy: str = Form(default="selected"),
    replace_audio: bool = Form(default=True),
    bgm_start_seconds: float = Form(default=0),
    mode: str = Form(default="auto"),
) -> dict:
    bgm = get_bgm(bgm_id) if bgm_id else None
    batch = new_batch(
        creator_home_url=creator_home_url,
        import_mode=mode,
        requested_limit=min(limit, 10),
        selected_bgm_id=bgm.get("bgm_id") if bgm else None,
        selected_bgm_name=bgm.get("display_name") if bgm else None,
        bgm_strategy=bgm_strategy,
        replace_audio=replace_audio,
        bgm_start_seconds=bgm_start_seconds,
        message_zh="正在尝试获取博主最近作品。",
    )
    batch["status"] = "fetching"
    batch["status_zh"] = "正在获取作品"
    save_batch(batch)

    result = import_creator_items(creator_home_url, limit=min(limit, 10), mode=mode)
    if not result.get("ok"):
        batch["status"] = "failed"
        batch["status_zh"] = "失败"
        batch["message_zh"] = result["message_zh"]
        batch["failure_reason"] = result.get("failure_reason")
        save_batch(refresh_batch_counts(batch))
        return {"batch": batch, "message_zh": batch["message_zh"]}

    batch["items"] = result.get("items") or []
    batch["message_zh"] = result.get("message_zh") or "已获取作品，开始下载和换 BGM。"
    _download_missing_items(batch)
    _process_batch_items(batch)
    for item in batch.get("items") or []:
        if item.get("note_url"):
            upsert_xhs_import_record(
                note_id=item.get("note_id"),
                note_url=item.get("note_url"),
                title=item.get("title"),
                author=item.get("author"),
                publish_time=item.get("publish_time"),
                note_type="视频" if item.get("is_video") else "图文/未知",
                is_video=item.get("is_video"),
                metrics=item.get("metrics") or {},
                cover_url=item.get("cover_url"),
                video_download_url=item.get("video_download_url") or item.get("preview_video_url"),
                is_imported=True,
                is_processed=item.get("status") == "done",
                processed_job_id=item.get("quick_bgm_job_id"),
            )
    save_batch(refresh_batch_counts(batch))
    return {"batch": batch, "message_zh": batch["message_zh"]}


@router.post("/xhs-creator/preview-links", summary="预览小红书作品链接，区分视频和图文")
async def xhs_creator_preview_links(request: Request, note_urls: str | None = Form(default=None)) -> dict:
    """预览小红书作品链接。

    页面使用 FormData 传 note_urls；为了便于 PowerShell / 调试，也兼容 JSON：
    {"note_urls": "..."} 或 {"links": ["..."]}。
    """
    if not note_urls:
        content_type = request.headers.get("content-type", "")
        if "application/json" in content_type:
            try:
                body = await request.json()
            except Exception:
                body = {}
            if isinstance(body, dict):
                raw = body.get("note_urls") or body.get("links") or body.get("urls") or ""
                if isinstance(raw, list):
                    note_urls = "\n".join(str(x) for x in raw)
                else:
                    note_urls = str(raw)
    note_urls = note_urls or ""

    urls = [line.strip() for line in note_urls.replace(",", "\n").replace(" ", "\n").splitlines() if line.strip()]
    urls = [url for url in urls if "xiaohongshu.com" in url or "xhslink.com" in url]
    urls = urls[:20]
    if not urls:
        raise HTTPException(status_code=400, detail="请至少粘贴一条小红书作品链接。")

    candidates = []
    for index, url in enumerate(urls, 1):
        # XHS-Downloader / 小红书侧对连续请求比较敏感；这里顺序处理，避免一次性打爆本地 5556。
        item = preview_note_link(url)
        item["index"] = index
        record = find_xhs_import_record(item.get("note_id"), item.get("note_url") or url)
        item["already_imported"] = bool(record and record.get("is_imported"))
        item["already_processed"] = bool(record and record.get("is_processed"))
        if item["already_processed"]:
            item["duplicate_status_zh"] = "已处理过"
        elif item["already_imported"]:
            item["duplicate_status_zh"] = "已存在"
        else:
            item["duplicate_status_zh"] = ""
        if item.get("ok"):
            upsert_xhs_import_record(
                note_id=item.get("note_id"),
                note_url=item.get("note_url") or url,
                title=item.get("title"),
                author=item.get("author"),
                publish_time=item.get("publish_time"),
                note_type=item.get("note_type_zh"),
                is_video=item.get("is_video"),
                metrics=item.get("metrics") or {},
                cover_url=item.get("preview_url"),
                video_download_url=item.get("video_download_url") or item.get("preview_video_url"),
                is_imported=True,
            )
        candidates.append(item)
        if index < len(urls):
            time.sleep(1.2)

    video_count = sum(1 for item in candidates if item.get("is_video"))
    failed_count = sum(1 for item in candidates if not item.get("ok"))
    message = f"已预览 {len(candidates)} 条作品，其中视频 {video_count} 条。图文作品不会进入换 BGM 流程。"
    if failed_count:
        message += f" 有 {failed_count} 条暂时预览失败，可稍后单独重试或重新粘贴。"
    return {
        "items": candidates,
        "total_count": len(candidates),
        "video_count": video_count,
        "failed_count": failed_count,
        "message_zh": message,
    }


@router.post("/xhs-creator/manual-links", summary="人工粘贴作品链接批量处理")
def xhs_creator_manual_links(
    note_urls: str = Form(...),
    creator_home_url: str | None = Form(default=None),
    bgm_id: str | None = Form(default=None),
    bgm_strategy: str = Form(default="selected"),
    replace_audio: bool = Form(default=True),
    bgm_start_seconds: float = Form(default=0),
) -> dict:
    urls = [line.strip() for line in note_urls.replace(",", "\n").replace(" ", "\n").splitlines() if line.strip()]
    urls = [url for url in urls if "xiaohongshu.com" in url or "xhslink.com" in url]
    if not urls:
        raise HTTPException(status_code=400, detail="请至少粘贴一条作品链接。")
    bgm = get_bgm(bgm_id) if bgm_id else None
    batch = new_batch(
        creator_home_url=creator_home_url,
        import_mode="manual_links",
        requested_limit=min(len(urls), 10),
        selected_bgm_id=bgm.get("bgm_id") if bgm else None,
        selected_bgm_name=bgm.get("display_name") if bgm else None,
        bgm_strategy=bgm_strategy,
        replace_audio=replace_audio,
        bgm_start_seconds=bgm_start_seconds,
        message_zh="已创建人工作品链接批次。",
    )
    batch["items"] = [make_batch_item(note_url=url, status="pending") for url in urls[:10]]
    _download_missing_items(batch)
    _process_batch_items(batch)
    for item in batch.get("items") or []:
        if item.get("note_url"):
            upsert_xhs_import_record(
                note_id=item.get("note_id"),
                note_url=item.get("note_url"),
                title=item.get("title"),
                author=item.get("author"),
                publish_time=item.get("publish_time"),
                note_type="视频" if item.get("is_video") else "图文/未知",
                is_video=item.get("is_video"),
                metrics=item.get("metrics") or {},
                cover_url=item.get("cover_url"),
                video_download_url=item.get("video_download_url") or item.get("preview_video_url"),
                is_imported=True,
                is_processed=item.get("status") == "done",
                processed_job_id=item.get("quick_bgm_job_id"),
            )
    save_batch(refresh_batch_counts(batch))
    return {"batch": batch, "message_zh": "人工作品链接批次已创建。"}


@router.get("/xhs-creator/batches", summary="查看小红书批量处理批次")
def get_xhs_creator_batches() -> dict:
    return {"batches": list_batches(), "message_zh": "批次列表读取成功。"}


@router.get("/xhs-creator/batches/{batch_id}", summary="查看单个小红书批次详情")
def get_xhs_creator_batch(batch_id: str) -> dict:
    batch = get_batch(batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="未找到批次。")
    return {"batch": batch}


@router.post("/xhs-creator/batches/{batch_id}/run", summary="对已有本地视频的批次执行换 BGM")
def run_xhs_creator_batch(batch_id: str, force: bool = Form(default=False)) -> dict:
    batch = get_batch(batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="未找到批次。")
    _process_batch_items(batch, force=force)
    save_batch(refresh_batch_counts(batch))
    return {"batch": batch, "message_zh": "批次换 BGM 处理已执行。"}


def _select_automation_bgm(payload: QuickBgmAutomationCreateRequest) -> tuple[dict | None, str | None]:
    if not payload.replace_audio:
        return None, None
    strategy = payload.bgm_strategy or "top_used_random"
    if strategy == "selected":
        if not payload.bgm_id:
            return None, "bgm_strategy=selected 时必须传入 bgm_id。"
        bgm = get_bgm(payload.bgm_id)
        if not _is_bgm_available(bgm):
            return None, "指定 BGM 不存在或本地文件不可用，请先上传 BGM 或换一个 bgm_id。"
        return bgm, None
    if strategy == "top_used_random":
        pool = list_available_bgm()
        if not pool:
            return None, "BGM 库里没有可用 BGM，请先上传 BGM 或使用 bgm_strategy=search_download。"
        max_usage = max(int(item.get("usage_count") or 0) for item in pool)
        top_pool = [item for item in pool if int(item.get("usage_count") or 0) == max_usage]
        return random.choice(top_pool or pool), None
    if strategy == "local_random":
        pool = list_available_bgm()
        if not pool:
            return None, "BGM 库里没有可用 BGM，请先上传 BGM 或使用 bgm_strategy=search_download。"
        return random.choice(pool), None
    if strategy == "search_download":
        query = (payload.bgm_query or "").strip()
        if not query:
            return None, "bgm_strategy=search_download 时必须传入 bgm_query。"
        if payload.dry_run:
            return {"display_name": f"将在线搜索下载：{query}", "source_type": "search_download", "source_query": query}, None
        result = search_and_download_bgm(query, prefer_source="ytdlp")
        if not result.get("ok"):
            reason = result.get("message_zh") or result.get("failure_reason") or "在线搜索下载暂未成功，请改用本地上传 BGM。"
            return None, f"在线搜索下载暂未成功，请改用本地上传 BGM。原因：{reason}"
        duration = media_duration_seconds(result["local_file_path"])
        record = add_bgm_record(
            song_name=result.get("song_name"),
            artist_name=result.get("artist_name"),
            original_filename=result["original_filename"],
            local_file_path=result["local_file_path"],
            source_type="search_download",
            source_query=query,
            source_url=result.get("source_url"),
            duration_seconds=duration,
        )
        return record, None
    return None, "bgm_strategy 不支持，请使用 selected、top_used_random、local_random 或 search_download。"


def _is_bgm_available(bgm: dict | None) -> bool:
    if not bgm:
        return False
    path = Path(bgm.get("local_file_path") or "")
    return bool(bgm.get("is_available", True) and path.exists())


def _prepare_automation_items(payload: QuickBgmAutomationCreateRequest, automation_job_id: str, limit: int) -> list[dict]:
    source_type = (payload.source_type or "manual").strip()
    if source_type == "local_file":
        return _prepare_local_file_items(payload.video_paths or [])
    if source_type == "uploaded_video":
        return _prepare_uploaded_video_items(payload.job_ids or [])
    if source_type == "xhs_note_links":
        return _prepare_xhs_note_items(payload.note_urls or [], automation_job_id, payload.dry_run, payload.force_reimport)
    if source_type == "xhs_creator_profile":
        return _prepare_xhs_profile_items(payload.creator_home_url, limit)
    if source_type == "manual":
        if payload.video_paths:
            return _prepare_local_file_items(payload.video_paths)
        if payload.note_urls:
            return _prepare_xhs_note_items(payload.note_urls, automation_job_id, payload.dry_run, payload.force_reimport)
        return [make_automation_item(input_type="manual", status="need_manual", title="人工输入", failure_reason="manual 模式需要传入 video_paths 或 note_urls。")]
    return []


def _prepare_local_file_items(video_paths: list[str]) -> list[dict]:
    items = []
    for raw_path in video_paths:
        path_text = str(raw_path or "").strip().strip('"')
        path = Path(path_text).expanduser() if path_text else None
        if path and path.exists() and path.is_file():
            items.append(
                make_automation_item(
                    input_type="local_file",
                    title=path.name,
                    local_video_path=str(path.resolve()),
                    video_duration_seconds=media_duration_seconds(path),
                    status="ready",
                )
            )
        else:
            items.append(
                make_automation_item(
                    input_type="local_file",
                    title=Path(path_text).name if path_text else "本地文件",
                    local_video_path=path_text or None,
                    status="failed",
                    failure_reason="本地视频文件不存在，请检查 video_paths。",
                )
            )
    return items


def _prepare_uploaded_video_items(job_ids: list[str]) -> list[dict]:
    items = []
    for job_id in job_ids:
        source_job = get_job(job_id)
        path = Path(source_job.get("original_video_path") or "") if source_job else None
        if source_job and path and path.exists():
            items.append(
                make_automation_item(
                    input_type="uploaded_video",
                    title=source_job.get("original_filename") or path.name,
                    local_video_path=str(path),
                    quick_bgm_job_id=None,
                    video_duration_seconds=source_job.get("video_duration_seconds") or media_duration_seconds(path),
                    cover_url=f"/quick-bgm/files/{job_id}/cover",
                    status="ready",
                )
            )
        else:
            items.append(
                make_automation_item(
                    input_type="uploaded_video",
                    title=job_id,
                    status="failed",
                    failure_reason="未找到已上传视频，或原视频文件不存在。",
                )
            )
    return items


def _prepare_xhs_note_items(note_urls: list[str], automation_job_id: str, dry_run: bool, force_reimport: bool) -> list[dict]:
    urls = [str(url).strip() for url in note_urls if str(url).strip()]
    urls = [url for url in urls if "xiaohongshu.com" in url or "xhslink.com" in url][:20]
    if not urls:
        return [make_automation_item(input_type="xhs_note_links", status="failed", title="小红书作品链接", failure_reason="请至少传入一条小红书作品链接。")]

    items = []
    for index, url in enumerate(urls, 1):
        preview = preview_note_link(url)
        record = find_xhs_import_record(preview.get("note_id"), preview.get("note_url") or url)
        item = make_automation_item(
            input_type="xhs_note_links",
            source_url=preview.get("note_url") or url,
            note_url=preview.get("note_url") or url,
            note_id=preview.get("note_id"),
            title=preview.get("title") or f"小红书作品 {index}",
            author_name=preview.get("author"),
            publish_time=preview.get("publish_time"),
            cover_url=preview.get("preview_url"),
            preview_video_url=preview.get("preview_video_url") or preview.get("video_download_url"),
            metrics=preview.get("metrics") or {},
            status="pending",
            failure_reason=preview.get("failure_reason"),
        )
        if not preview.get("ok"):
            item["status"] = "failed"
            item["status_zh"] = "失败"
            item["failure_reason"] = preview.get("failure_reason") or "小红书作品解析失败。"
        elif not preview.get("is_video"):
            item["status"] = "skipped"
            item["status_zh"] = "已跳过"
            item["failure_reason"] = "图文作品，当前不处理。"
        elif record and record.get("is_processed") and not force_reimport:
            item["status"] = "skipped"
            item["status_zh"] = "已跳过"
            item["failure_reason"] = "该作品已处理过。如需重新处理，请设置 force_reimport=true。"
        elif dry_run:
            item["status"] = "ready"
            item["status_zh"] = "可处理"
            item["failure_reason"] = None
        else:
            result = download_note_video(url, XHS_CREATOR_DOWNLOADS_DIR / "automation" / automation_job_id / item["item_id"])
            if result.get("ok"):
                local_path = result["local_video_path"]
                item["local_video_path"] = local_path
                item["video_duration_seconds"] = media_duration_seconds(local_path)
                item["status"] = "ready"
                item["status_zh"] = "可处理"
                item["failure_reason"] = None
            else:
                item["status"] = "need_manual"
                item["status_zh"] = "需要人工处理"
                item["failure_reason"] = result.get("failure_reason") or result.get("message_zh") or "小红书视频下载失败，需要人工上传视频。"

        upsert_xhs_import_record(
            note_id=preview.get("note_id"),
            note_url=preview.get("note_url") or url,
            title=preview.get("title"),
            author=preview.get("author"),
            publish_time=preview.get("publish_time"),
            note_type=preview.get("note_type_zh"),
            is_video=preview.get("is_video"),
            metrics=preview.get("metrics") or {},
            cover_url=preview.get("preview_url"),
            video_download_url=preview.get("video_download_url") or preview.get("preview_video_url"),
            is_imported=bool(preview.get("ok")),
            is_processed=False,
        )
        items.append(item)
        if index < len(urls):
            time.sleep(1.2)
    return items


def _prepare_xhs_profile_items(creator_home_url: str | None, limit: int) -> list[dict]:
    if not creator_home_url:
        return [make_automation_item(input_type="xhs_creator_profile", status="failed", title="小红书博主主页", failure_reason="请传入 creator_home_url。")]

    if os.getenv("XHS_MCP_BASE_URL"):
        result = import_creator_items(creator_home_url, limit=limit, mode="xhs_mcp")
        if result.get("ok"):
            items = []
            for raw in result.get("items") or []:
                status = "ready" if raw.get("is_video") else "skipped"
                items.append(
                    make_automation_item(
                        input_type="xhs_creator_profile",
                        source_url=raw.get("note_url"),
                        note_url=raw.get("note_url"),
                        note_id=raw.get("note_id"),
                        title=raw.get("title"),
                        author_name=raw.get("author"),
                        cover_url=raw.get("cover_url"),
                        preview_video_url=raw.get("preview_video_url") or raw.get("video_download_url"),
                        local_video_path=raw.get("local_video_path"),
                        status=status,
                        failure_reason=None if status == "ready" else "图文作品，当前不处理。",
                    )
                )
            return items

    return [
        make_automation_item(
            input_type="xhs_creator_profile",
            source_url=creator_home_url,
            title="小红书博主主页",
            status="need_manual",
            failure_reason="小红书主页自动获取最近作品暂未配置，请先用油猴脚本提取作品链接，或传入 note_urls。当前主页最近 N 条通常需要 Cookie / 登录态 / MCP / x-mcp 支持。",
        )
    ]


def _run_automation_item(job: dict, item: dict, bgm: dict | None) -> None:
    item["status"] = "processing"
    item["status_zh"] = "处理中"
    item["failure_reason"] = None
    try:
        local_path = item.get("local_video_path")
        if not local_path and item.get("note_url"):
            result = download_note_video(item["note_url"], XHS_CREATOR_DOWNLOADS_DIR / "automation" / job["automation_job_id"] / item["item_id"])
            if result.get("ok"):
                local_path = result["local_video_path"]
                item["local_video_path"] = local_path
            else:
                raise QuickBgmMediaError(result.get("failure_reason") or result.get("message_zh") or "视频下载失败。")
        source = Path(local_path or "")
        if not source.exists():
            raise QuickBgmMediaError("原视频文件不存在，请重新上传或重新导入。")

        input_type = "xiaohongshu_link" if item.get("note_url") or "xiaohongshu.com" in str(item.get("source_url") or "") else "upload"
        quick_job = make_job(
            input_type=input_type,
            source_url=item.get("note_url") or item.get("source_url"),
            original_video_path=str(source),
            original_filename=source.name,
            bgm_id=bgm.get("bgm_id") if bgm else None,
            bgm_name=bgm.get("display_name") if bgm else None,
            replace_audio=bool(job.get("replace_audio")),
            bgm_start_seconds=float(job.get("bgm_start_seconds") or 0),
            video_duration_seconds=item.get("video_duration_seconds") or media_duration_seconds(source),
            message_zh="自动化换 BGM 任务已创建，正在生成预览视频。",
        )
        cover = extract_video_cover(source, source.with_suffix(".cover.jpg"))
        if cover:
            quick_job["cover_image_path"] = cover
            save_job(quick_job)
        done = run_quick_bgm_job(quick_job, bgm)
        if done.get("replace_audio") and done.get("bgm_id"):
            increment_bgm_usage(done["bgm_id"])
        item["quick_bgm_job_id"] = done["job_id"]
        item["output_video_path"] = done.get("output_video_path")
        item["preview_url"] = f"/quick-bgm/files/{done['job_id']}/output"
        item["download_url"] = f"/quick-bgm/files/{done['job_id']}/output"
        item["cover_url"] = item.get("cover_url") or f"/quick-bgm/files/{done['job_id']}/cover"
        item["status"] = "done"
        item["status_zh"] = "已完成"
        item["failure_reason"] = None
        if item.get("note_url"):
            upsert_xhs_import_record(
                note_id=item.get("note_id"),
                note_url=item.get("note_url"),
                title=item.get("title"),
                author=item.get("author_name"),
                publish_time=item.get("publish_time"),
                note_type="视频",
                is_video=True,
                metrics=item.get("metrics") or {},
                cover_url=item.get("cover_url"),
                video_download_url=item.get("preview_video_url"),
                is_imported=True,
                is_processed=True,
                processed_job_id=done["job_id"],
            )
    except QuickBgmMediaError as exc:
        item["status"] = "failed"
        item["status_zh"] = "失败"
        item["failure_reason"] = str(exc)


def _automation_response(job: dict, include_items: bool = True) -> dict:
    job = refresh_automation_job_counts(dict(job))
    selected_bgm = _compact_bgm_for_automation(get_bgm(job.get("selected_bgm_id"))) if job.get("selected_bgm_id") else None
    if not selected_bgm and job.get("selected_bgm_name"):
        selected_bgm = {"bgm_id": job.get("selected_bgm_id"), "display_name": job.get("selected_bgm_name")}
    response = {
        "automation_job_id": job.get("automation_job_id"),
        "status": job.get("status"),
        "status_zh": job.get("status_zh"),
        "message_zh": job.get("message_zh"),
        "item_count": job.get("item_count"),
        "ready_count": job.get("ready_count"),
        "done_count": job.get("done_count"),
        "failed_count": job.get("failed_count"),
        "selected_bgm": selected_bgm,
        "next_action_zh": _automation_next_action(job),
        "created_at": job.get("created_at"),
        "updated_at": job.get("updated_at"),
        "source_type": job.get("source_type"),
        "source_type_zh": job.get("source_type_zh"),
        "bgm_strategy": job.get("bgm_strategy"),
        "bgm_strategy_zh": job.get("bgm_strategy_zh"),
        "replace_audio": job.get("replace_audio"),
        "replace_audio_zh": job.get("replace_audio_zh"),
        "bgm_start_seconds": job.get("bgm_start_seconds"),
        "dry_run": job.get("dry_run"),
    }
    if include_items:
        response["items"] = job.get("items") or []
        response["total_count"] = job.get("item_count")
    return response


def _compact_bgm_for_automation(bgm: dict | None) -> dict | None:
    if not bgm:
        return None
    compact = compact_bgm_record(bgm)
    compact["local_file_path"] = bgm.get("local_file_path")
    return compact


def _automation_next_action(job: dict) -> str:
    if job.get("dry_run"):
        return "这是 dry_run 预览任务；确认素材和 BGM 后，请重新创建 dry_run=false 的任务。"
    if job.get("ready_count"):
        return f"调用 POST /quick-bgm/automation/{job.get('automation_job_id')}/run 执行生成。"
    if job.get("done_count"):
        return "查看 items 中的 output_video_path、preview_url 或 download_url。"
    if job.get("failed_count"):
        return "查看 items 中的 failure_reason；必要时改用本地上传视频或手动传入 note_urls。"
    return "等待传入可处理素材。"


def _choose_bgm(bgm_id: str | None, strategy: str) -> dict | None:
    if strategy == "selected":
        return get_bgm(bgm_id) if bgm_id else None
    pool = list_available_bgm()
    if strategy == "top_used_random":
        pool = pool[:5]
    if strategy == "local_random":
        pool = list_available_bgm()
    return random.choice(pool) if pool else None


def _download_missing_items(batch: dict) -> None:
    for item in batch.get("items") or []:
        if not item.get("is_video"):
            item["status"] = "skipped"
            item["status_zh"] = "已跳过"
            item["failure_reason"] = "不是视频作品。"
            continue
        if item.get("local_video_path"):
            item["status"] = "downloaded"
            item["status_zh"] = "已下载"
            continue
        if not item.get("note_url"):
            item["status"] = "need_manual"
            item["status_zh"] = "需要人工处理"
            item["failure_reason"] = "缺少作品链接，无法下载。"
            continue
        item["status"] = "downloading"
        item["status_zh"] = "正在下载"
        result = download_note_video(item["note_url"], XHS_CREATOR_DOWNLOADS_DIR / batch["batch_id"] / item["item_id"])
        if result.get("ok"):
            item["local_video_path"] = result["local_video_path"]
            item["status"] = "downloaded"
            item["status_zh"] = "已下载"
            item["failure_reason"] = None
        else:
            reason = result.get("failure_reason") or result.get("message_zh")
            item["status"] = "skipped" if "不是视频" in str(reason) else "need_manual"
            item["status_zh"] = "已跳过" if item["status"] == "skipped" else "需要人工处理"
            item["failure_reason"] = reason


def _process_batch_items(batch: dict, force: bool = False) -> None:
    for item in batch.get("items") or []:
        if item.get("status") == "done" and not force:
            continue
        if not item.get("local_video_path"):
            continue
        item["status"] = "processing"
        item["status_zh"] = "正在换 BGM"
        try:
            bgm = _choose_bgm(batch.get("selected_bgm_id"), batch.get("bgm_strategy") or "selected") if batch.get("replace_audio") else None
            if batch.get("replace_audio") and not bgm:
                raise QuickBgmMediaError("BGM 不可用，请先选择或上传一个可用 BGM。")
            job = make_job(
                input_type="xiaohongshu_link",
                source_url=item.get("note_url"),
                original_video_path=item.get("local_video_path"),
                original_filename=Path(item["local_video_path"]).name,
                bgm_id=bgm.get("bgm_id") if bgm else None,
                bgm_name=bgm.get("display_name") if bgm else None,
                replace_audio=bool(batch.get("replace_audio")),
                bgm_start_seconds=float(batch.get("bgm_start_seconds") or 0),
                video_duration_seconds=media_duration_seconds(item.get("local_video_path")),
                message_zh="小红书批量任务创建成功，正在换 BGM。",
            )
            done = run_quick_bgm_job(job, bgm)
            if done.get("replace_audio") and done.get("bgm_id"):
                increment_bgm_usage(done["bgm_id"])
            item["quick_bgm_job_id"] = done["job_id"]
            item["output_video_path"] = done.get("output_video_path")
            item["cover_image_path"] = done.get("cover_image_path")
            item["status"] = "done"
            item["status_zh"] = "已完成"
            item["failure_reason"] = None
        except QuickBgmMediaError as exc:
            item["status"] = "failed"
            item["status_zh"] = "失败"
            item["failure_reason"] = str(exc)


def _page_html() -> str:
    html = r"""
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>服装短视频快速处理工作台</title>
  <style>
    * { box-sizing: border-box; }
    body { margin:0; font-family:"Microsoft YaHei", Arial, sans-serif; background:#f4f6fb; color:#101828; }
    header { background:linear-gradient(135deg,#101828,#1d4ed8); color:#fff; padding:28px 34px; }
    header h1 { margin:0 0 8px; font-size:28px; }
    header p { margin:0; color:#dbeafe; line-height:1.7; }
    main { max-width:1160px; margin:22px auto 70px; padding:0 18px; display:grid; gap:18px; }
    section,.panel { background:#fff; border:1px solid #e5e7eb; border-radius:16px; padding:18px; box-shadow:0 10px 24px rgba(15,23,42,.05); }
    .panel { box-shadow:none; background:#fcfcfd; }
    h2 { margin:0 0 12px; font-size:20px; }
    h3 { margin:0 0 10px; font-size:16px; }
    .sub { color:#667085; font-size:14px; line-height:1.7; margin:6px 0 0; }
    .grid2 { display:grid; grid-template-columns:1fr 1fr; gap:14px; }
    .tabs { display:flex; gap:8px; flex-wrap:wrap; margin:10px 0 14px; }
    .tab { background:#eef2ff; color:#1e3a8a; border:1px solid #c7d2fe; }
    .tab.active { background:#2563eb; color:#fff; border-color:#2563eb; }
    label { display:block; margin:10px 0 7px; font-weight:700; }
    input,textarea,select { width:100%; min-height:42px; border:1px solid #d0d5dd; border-radius:10px; padding:9px 11px; background:#fff; font-family:inherit; }
    textarea { min-height:118px; line-height:1.6; }
    input[type=file] { padding:12px; border:1px dashed #98a2b3; background:#fbfcfe; }
    input[type=checkbox],input[type=radio] { width:auto; min-height:0; margin-right:7px; }
    input[type=range] { padding:0; }
    button { border:0; border-radius:10px; padding:11px 15px; background:#2563eb; color:white; cursor:pointer; font-weight:800; }
    button.secondary { background:#475467; }
    button.ghost { background:#f2f4f7; color:#344054; }
    button:disabled { opacity:.55; cursor:not-allowed; }
    .row { display:flex; gap:10px; flex-wrap:wrap; align-items:center; margin-top:12px; }
    .status { min-height:24px; margin-top:10px; color:#175cd3; font-weight:700; white-space:pre-wrap; }
    .error { color:#b42318; }
    .ok { color:#027a48; }
    .muted { color:#667085; }
    .hidden { display:none !important; }
    .list { display:grid; gap:10px; }
    .bgm-list { max-height:360px; overflow:auto; display:grid; gap:10px; }
    .item { border:1px solid #e5e7eb; border-radius:14px; padding:13px; display:grid; grid-template-columns:1fr auto; gap:12px; align-items:center; background:#fff; }
    .candidate-card { grid-template-columns:150px 1fr auto; align-items:start; }
    .thumb { width:132px; height:176px; object-fit:cover; border-radius:12px; background:#111827; border:1px solid #e5e7eb; }
    .thumb-placeholder { width:132px; height:176px; border-radius:12px; background:#f2f4f7; color:#667085; display:flex; align-items:center; justify-content:center; text-align:center; padding:10px; font-size:13px; border:1px dashed #cbd5e1; }
    .preview-box { margin-top:10px; max-width:520px; }
    .preview-box img { width:100%; max-height:300px; object-fit:cover; border-radius:10px; border:1px solid #e5e7eb; background:#f2f4f7; }
    .result-cover { width:132px; height:176px; object-fit:cover; border-radius:12px; border:1px solid #e5e7eb; background:#f2f4f7; }
    .inline-check { display:inline-flex; align-items:center; gap:4px; margin:0; font-weight:700; color:#344054; }
    .mini-actions { display:flex; gap:8px; flex-wrap:wrap; align-items:center; }
    .item.active { border-color:#2563eb; background:#eff6ff; }
    .item.disabled { background:#f9fafb; opacity:.82; }
    .meta { margin-top:6px; color:#667085; font-size:13px; line-height:1.65; }
    .badge { display:inline-block; padding:3px 8px; border-radius:999px; font-size:12px; background:#eef2ff; color:#1d4ed8; font-weight:800; margin-right:6px; }
    .badge.gray { background:#f2f4f7; color:#344054; }
    .badge.green { background:#ecfdf3; color:#027a48; }
    .badge.red { background:#fef3f2; color:#b42318; }
    .badge.orange { background:#fff7ed; color:#c2410c; }
    video,audio { width:100%; margin-top:10px; border-radius:10px; }
    video { max-height:360px; background:#111827; }
    a.download { display:inline-block; color:#175cd3; font-weight:800; text-decoration:none; margin-top:8px; }
    .step-title { display:flex; justify-content:space-between; gap:10px; align-items:center; flex-wrap:wrap; }
    @media (max-width:900px) { .grid2 { grid-template-columns:1fr; } .item,.candidate-card { grid-template-columns:1fr; } .thumb,.thumb-placeholder,.result-cover { width:100%; max-height:260px; height:auto; min-height:160px; } header { padding:24px 20px; } }
  </style>
</head>
<body>
<header>
  <h1>服装短视频快速处理工作台</h1>
  <p>上传视频、粘贴小红书链接或输入博主主页，选择 BGM，一键生成替换音乐后的预览视频。</p>
</header>
<main>
  <section>
    <div class="step-title">
      <div>
        <h2>一、导入素材</h2>
        <p class="sub">本地视频会直接进入待处理列表；小红书作品会先进入候选素材，视频可勾选，图文会自动跳过。</p>
      </div>
      <button class="ghost" id="clearPendingBtn">清空待处理列表</button>
    </div>
    <div class="tabs">
      <button class="tab active" data-tab="local">本地上传</button>
      <button class="tab" data-tab="links">小红书作品链接</button>
      <button class="tab" data-tab="creator">小红书博主主页</button>
    </div>
    <div id="tab-local" class="panel">
      <h3>本地上传</h3>
      <input id="videoFile" type="file" accept="video/*" multiple />
      <div class="row"><button id="uploadVideoBtn">上传并加入待处理列表</button></div>
      <div id="videoStatus" class="status"></div>
    </div>
    <div id="tab-links" class="panel hidden">
      <h3>小红书作品链接</h3>
      <textarea id="xhsLinks" placeholder="可粘贴单条或多条小红书作品链接，空格或换行分隔。"></textarea>
      <p class="sub">先预览作品类型，再把勾选的视频加入待处理列表。图文作品当前不处理。</p>
      <div class="row"><button id="previewLinksBtn">预览并筛选作品</button></div>
      <div id="xhsLinkStatus" class="status"></div>
    </div>
    <div id="tab-creator" class="panel hidden">
      <h3>小红书博主主页</h3>
      <input id="creatorUrl" type="url" value="__DEFAULT_CREATOR_URL__" />
      <div class="grid2">
        <div><label>获取数量</label><input id="limit" type="number" min="1" max="20" value="10" /></div>
        <div><label>导入模式</label><select id="mode"><option value="auto">自动判断</option><option value="xhs_downloader_api">XHS-Downloader API</option><option value="xhs_downloader_cli">XHS-Downloader CLI</option><option value="xhs_mcp">小红书 MCP</option><option value="manual_links">人工作品链接</option><option value="disabled">未启用</option></select></div>
      </div>
      <p class="sub">当前 XHS-Downloader API 只确认支持单条作品详情。主页最近作品需要额外登录态、Cookie、MCP 或油猴脚本辅助；如果自动获取失败，不影响本地上传和作品链接路线。</p>
      <div class="row"><button class="secondary" id="creatorImportBtn">获取最近作品候选</button></div>
      <div id="creatorStatus" class="status"></div>
    </div>
  </section>

  <section>
    <div class="step-title"><h2>二、候选素材</h2><button class="ghost" id="clearCandidatesBtn">清空候选素材</button></div>
    <p class="sub">视频默认勾选；图文作品不能换 BGM，会显示为“当前不处理”。确认后再加入待处理视频。</p>
    <div class="row mini-actions">
      <button class="ghost" id="selectAllCandidatesBtn">全选视频</button>
      <button class="ghost" id="unselectCandidatesBtn">取消全选</button>
      <button class="ghost" id="invertCandidatesBtn">反选视频</button>
      <label class="inline-check"><input id="skipDuplicate" type="checkbox" checked /> 跳过已存在作品</label>
    </div>
    <div id="candidateList" class="list"></div>
    <div class="row"><button id="addCandidatesBtn">把勾选视频加入待处理列表</button></div>
    <div id="candidateStatus" class="status"></div>
  </section>

  <section>
    <h2>三、选择 BGM</h2>
    <div class="grid2">
      <div class="panel">
        <h3>本地上传 BGM</h3>
        <input id="bgmFile" type="file" accept="audio/*" />
        <div class="grid2"><input id="songName" type="text" placeholder="歌名，可选" /><input id="artistName" type="text" placeholder="作者，可选" /></div>
        <p class="sub">文件名类似“歌名 - 作者.mp3”时，会自动拆出歌名和作者。</p>
        <div class="row"><button id="uploadBgmBtn">上传并加入 BGM 库</button></div>
      </div>
      <div class="panel">
        <h3>在线搜索下载 BGM</h3>
        <input id="bgmQuery" type="text" placeholder="输入 BGM 名称或关键词" />
        <p class="sub">只下载最相关的一条。失败时请改用本地上传 BGM。</p>
        <div class="row"><button class="secondary" id="searchBgmBtn">搜索并下载最相关 BGM</button></div>
      </div>
    </div>
    <div id="bgmStatus" class="status"></div>
    <h3 style="margin-top:18px">我的 BGM 库</h3>
    <div id="bgmList" class="bgm-list"></div>
  </section>

  <section>
    <h2>四、音乐片段选择</h2>
    <div class="panel">
      <div id="selectedBgmText" class="muted">请先选择一个 BGM。</div>
      <audio id="bgmAudio" controls class="hidden"></audio>
      <label>拖动选择 BGM 从哪里开始</label>
      <input id="bgmStartRange" type="range" min="0" max="0" step="0.1" value="0" />
      <input id="bgmStart" type="number" min="0" step="0.1" value="0" />
      <div id="segmentInfo" class="status"></div>
    </div>
  </section>

  <section>
    <h2>五、声音处理</h2>
    <label><input type="radio" name="audioMode" value="false" /> 保留原声</label>
    <label><input type="radio" name="audioMode" value="true" checked /> 去掉原声并替换为 BGM</label>
  </section>

  <section>
    <div class="step-title"><div><h2>六、待处理视频列表</h2><p class="sub">勾选需要处理的视频，同一个 BGM 和音乐片段会批量应用到勾选视频。</p></div><span id="pendingCount" class="badge gray">0 条</span></div>
    <div class="row mini-actions">
      <button class="ghost" id="selectAllPendingBtn">全选</button>
      <button class="ghost" id="unselectPendingBtn">取消全选</button>
      <button class="ghost" id="invertPendingBtn">反选</button>
      <button class="ghost" id="removeSelectedPendingBtn">批量移除</button>
    </div>
    <div id="videoList" class="list"></div>
  </section>

  <section>
    <div class="step-title"><h2>七、生成与结果</h2><button class="ghost" id="clearResultsBtn">清空生成结果</button></div>
    <div class="row"><button id="runBtn">生成预览视频</button></div>
    <div id="jobStatus" class="status"></div>
    <div id="resultList" class="list"></div>
  </section>
</main>
<script>
(function(){
  function el(id){ return document.getElementById(id); }
  var state = { items: [], candidates: [], bgm: null, results: [] };

  function setStatus(id, text, isError){
    var node = el(id);
    if (!node) return;
    node.textContent = text || "";
    node.className = "status" + (isError ? " error" : "");
  }
  function escapeHtml(value){
    return String(value == null ? "" : value).replace(/[&<>\"']/g, function(s){ return {"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[s]; });
  }
  function formatTime(seconds){
    var n = Number(seconds);
    if (!isFinite(n)) return "--:--";
    n = Math.max(0, n);
    var m = Math.floor(n / 60);
    var s = Math.floor(n % 60);
    return String(m).padStart(2,"0") + ":" + String(s).padStart(2,"0");
  }
  function parseLinks(raw){
    var parts = String(raw || "").split(/\s+/);
    var seen = {};
    var out = [];
    for (var i=0; i<parts.length; i++){
      var v = parts[i].trim();
      if (!v) continue;
      if (v.indexOf("xiaohongshu.com") < 0 && v.indexOf("xhslink.com") < 0) continue;
      if (!seen[v]) { seen[v] = true; out.push(v); }
    }
    return out.slice(0, 20);
  }
  function firstSelectedVideoDuration(){
    for (var i=0; i<state.items.length; i++){
      if (state.items[i].checked && state.items[i].videoDuration) return Number(state.items[i].videoDuration);
    }
    return null;
  }
  function updateSegmentInfo(){
    var start = Number(el("bgmStart").value || 0);
    var bgmDuration = state.bgm ? state.bgm.duration : null;
    var videoDuration = firstSelectedVideoDuration();
    var end = videoDuration ? start + videoDuration : null;
    var text = "BGM 总时长：" + formatTime(bgmDuration) + "\n视频时长：" + formatTime(videoDuration) + "\n";
    text += end ? ("将使用音乐片段：" + formatTime(start) + " - " + formatTime(end)) : ("将从 " + formatTime(start) + " 开始使用音乐。");
    if (bgmDuration && end && end > bgmDuration) text += "\nBGM 剩余时长不足，将自动循环补齐。";
    el("segmentInfo").textContent = text;
  }
  function switchImportTab(name){
    var keys = ["local","links","creator"];
    for (var i=0; i<keys.length; i++){
      var key = keys[i];
      el("tab-" + key).classList.toggle("hidden", key !== name);
      var btn = document.querySelector('[data-tab="' + key + '"]');
      if (btn) btn.classList.toggle("active", key === name);
    }
  }
  function addItem(item){
    item.checked = item.checked !== false;
    item.status = item.status || "待处理";
    item.failure = item.failure || "";
    state.items.push(item);
    renderItems();
    updateSegmentInfo();
  }
  function clearPending(){
    state.items = [];
    state.results = [];
    renderItems();
    renderResults();
    updateSegmentInfo();
  }
  function clearCandidates(){
    state.candidates = [];
    renderCandidates();
    setStatus("candidateStatus", "");
  }
  function clearResults(){
    state.results = [];
    renderResults();
    setStatus("jobStatus", "已清空页面上的生成结果。输出文件仍保留在项目目录中，方便需要时找回。", false);
  }
  function setCandidateChecked(mode){
    for (var i=0; i<state.candidates.length; i++){
      var c = state.candidates[i];
      if (!c.is_video) continue;
      if (mode === "all") c.checked = true;
      if (mode === "none") c.checked = false;
      if (mode === "invert") c.checked = !c.checked;
    }
    renderCandidates();
  }
  function setPendingChecked(mode){
    for (var i=0; i<state.items.length; i++){
      var it = state.items[i];
      if (mode === "all") it.checked = true;
      if (mode === "none") it.checked = false;
      if (mode === "invert") it.checked = !it.checked;
    }
    renderItems();
    updateSegmentInfo();
  }
  function removeSelectedPending(){
    var before = state.items.length;
    state.items = state.items.filter(function(x){ return !x.checked; });
    renderItems();
    updateSegmentInfo();
    setStatus("jobStatus", before === state.items.length ? "没有勾选需要移除的视频。" : "已移除勾选的待处理视频。", before === state.items.length);
  }
  function shouldSkipDuplicate(item){
    return !!(el("skipDuplicate") && el("skipDuplicate").checked && item && item.already_imported);
  }
  function countText(value){
    return value === null || value === undefined || value === "" ? "暂无" : String(value);
  }
  function candidateStatsHtml(item){
    return "点赞：" + countText(item.liked_count) + " · 收藏：" + countText(item.collected_count) + " · 评论：" + countText(item.comment_count);
  }
  function itemPreviewHtml(item, idx){
    if (item.jobId) return '<div class="preview-box"><video class="pending-preview" data-index="' + idx + '" controls poster="/quick-bgm/files/' + encodeURIComponent(item.jobId) + '/cover" src="/quick-bgm/files/' + encodeURIComponent(item.jobId) + '/source"></video></div>';
    if (item.previewVideoUrl) return '<div class="preview-box"><video class="pending-preview" data-index="' + idx + '" controls preload="metadata" ' + (item.previewUrl ? 'poster="' + escapeHtml(item.previewUrl) + '"' : '') + ' src="' + escapeHtml(item.previewVideoUrl) + '"></video></div>';
    if (item.previewUrl) return '<div class="preview-box"><img src="' + escapeHtml(item.previewUrl) + '" alt="原视频封面" /></div>';
    return '<div class="thumb-placeholder" style="width:100%;max-width:520px;height:120px">暂无可预览视频，请先下载或人工上传。</div>';
  }
  function resultCoverHtml(result){
    var cover = result.coverUrl || (result.jobId ? "/quick-bgm/files/" + encodeURIComponent(result.jobId) + "/cover" : "");
    return cover ? '<img class="result-cover" src="' + escapeHtml(cover) + '" alt="封面图" />' : '<div class="thumb-placeholder">暂无封面<br>封面用于本地整理和人工上传参考</div>';
  }
  function segmentLabel(start, duration){
    var end = duration ? Number(start || 0) + Number(duration || 0) : null;
    return end ? (formatTime(start) + " - " + formatTime(end)) : (formatTime(start) + " 开始");
  }
  function candidatePreviewHtml(item){
    if (item.preview_video_url) return '<video class="thumb" muted preload="metadata" src="' + escapeHtml(item.preview_video_url) + '#t=0.1"></video>';
    if (item.preview_url) return '<img class="thumb" loading="lazy" src="' + escapeHtml(item.preview_url) + '" />';
    return '<div class="thumb-placeholder">暂无预览图<br>可根据标题和类型判断</div>';
  }
  function addCandidateToPending(index){
    var c = state.candidates[index];
    if (!c || !c.is_video) { setStatus("candidateStatus", "这条不是视频作品，当前不进入换 BGM 流程。", true); return; }
    if (shouldSkipDuplicate(c)) { setStatus("candidateStatus", "该作品已存在。取消“跳过已存在作品”后，可以强制重新导入或重新处理。", true); return; }
    addItem({
      id:"xhs-"+(c.note_id || c.note_url || Math.random()),
      sourceType:c.source_zh === "小红书博主主页" ? "xhs_creator" : "xhs_link",
      sourceTypeZh:c.source_zh || "小红书作品",
      noteUrl:c.note_url,
      jobId:c.job_id || null,
      name:c.title || c.note_id || "小红书视频",
      author:c.author || "",
      publishTime:c.publish_time || "",
      previewUrl:c.preview_url || c.cover_url || "",
      previewVideoUrl:c.preview_video_url || c.video_download_url || "",
      status:c.job_id ? "待处理" : "待下载",
      failure:c.failure_reason || "",
      videoDuration:c.video_duration_seconds || null
    });
    c.checked = false;
    renderCandidates();
    setStatus("candidateStatus", "已加入待处理视频：" + (c.title || c.note_id || "小红书视频"));
  }
  async function generateOneItem(index){
    for (var i=0; i<state.items.length; i++) state.items[i].checked = false;
    if (state.items[index]) state.items[index].checked = true;
    renderItems();
    await generateAll();
  }
  function renderCandidates(){
    var list = el("candidateList");
    list.innerHTML = "";
    if (!state.candidates.length){
      list.innerHTML = '<div class="muted">暂无候选素材。请先预览小红书作品链接，或尝试获取博主主页作品。</div>';
      return;
    }
    for (var i=0; i<state.candidates.length; i++){
      (function(idx){
        var item = state.candidates[idx];
        var isVideo = !!item.is_video;
        var row = document.createElement("div");
        row.className = "item candidate-card" + (isVideo ? "" : " disabled");
        var statusBadge = isVideo ? '<span class="badge green">视频，可处理</span>' : '<span class="badge orange">图文/非视频，当前不处理</span>';
        if (item.failure_reason) statusBadge += '<span class="badge red">需人工确认</span>';
        if (item.duplicate_status_zh) statusBadge += '<span class="badge orange">' + escapeHtml(item.duplicate_status_zh) + '</span>';
        row.innerHTML = candidatePreviewHtml(item) + '<div>' +
          '<label><input type="checkbox" ' + (item.checked && isVideo && !shouldSkipDuplicate(item) ? 'checked ' : '') + (!isVideo || shouldSkipDuplicate(item) ? 'disabled ' : '') + '/>' + escapeHtml(item.title || item.note_id || item.note_url || "小红书作品") + '</label>' +
          '<div class="meta">' +
          '<span class="badge">' + escapeHtml(item.source_zh || "小红书作品") + '</span>' +
          '<span class="badge gray">' + escapeHtml(item.note_type_zh || (isVideo ? "视频" : "图文/未知")) + '</span>' + statusBadge +
          (item.author ? '<br>作者：' + escapeHtml(item.author) : '') +
          '<br>数据：' + escapeHtml(candidateStatsHtml(item)) +
          '<br>发布时间：' + escapeHtml(item.publish_time || "暂无") +
          '<br>状态：' + escapeHtml(item.status_zh || (isVideo ? "可处理" : "当前不处理")) +
          '<br>链接：' + escapeHtml(item.note_url || "") +
          (item.failure_reason ? '<br><span class="error">说明：' + escapeHtml(item.failure_reason) + '</span>' : '') +
          '</div></div>' +
          '<div><button class="ghost" ' + (isVideo ? '' : 'disabled') + '>单条加入</button></div>';
        var checkbox = row.querySelector('input[type="checkbox"]');
        checkbox.onchange = function(e){ item.checked = e.target.checked; };
        row.querySelector('button').onclick = function(){ addCandidateToPending(idx); };
        list.appendChild(row);
      })(i);
    }
  }
  function renderItems(){
    el("pendingCount").textContent = state.items.length + " 条";
    var list = el("videoList");
    list.innerHTML = "";
    if (!state.items.length){
      list.innerHTML = '<div class="muted">暂无待处理视频。请先上传本地视频，或把候选视频加入待处理列表。</div>';
      return;
    }
    for (var i=0; i<state.items.length; i++){
      (function(idx){
        var item = state.items[idx];
        var row = document.createElement("div");
        row.className = "item";
        var preview = itemPreviewHtml(item, idx);
        var badgeClass = item.status === "失败" ? "red" : (item.status === "已完成" ? "green" : "gray");
        row.innerHTML = '<div>' +
          '<label><input type="checkbox" ' + (item.checked ? 'checked ' : '') + '/>' + escapeHtml(item.name || "未命名视频") + '</label>' +
          '<div class="meta"><span class="badge">' + escapeHtml(item.sourceTypeZh || item.sourceType || "未知来源") + '</span>' +
          '<span class="badge ' + badgeClass + '">' + escapeHtml(item.status || "待处理") + '</span>' +
          '视频时长：' + formatTime(item.videoDuration) +
          (item.author ? '<br>作者：' + escapeHtml(item.author) : '') +
          (item.publishTime ? '<br>发布时间：' + escapeHtml(item.publishTime) : '') +
          (item.failure ? '<br><span class="error">失败原因：' + escapeHtml(item.failure) + '</span>' : '') + '</div>' + preview + '</div>' +
          '<div class="mini-actions"><button class="secondary">单条生成</button><button class="ghost">移除</button></div>';
        row.querySelector('input[type="checkbox"]').onchange = function(e){ item.checked = e.target.checked; updateSegmentInfo(); };
        var media = row.querySelector("video.pending-preview");
        if (media){
          media.onloadedmetadata = function(){
            if (!item.videoDuration && isFinite(media.duration)) {
              item.videoDuration = media.duration;
              updateSegmentInfo();
              renderItems();
            }
          };
        }
        var buttons = row.querySelectorAll('button');
        buttons[0].onclick = function(){ generateOneItem(idx); };
        buttons[1].onclick = function(){ state.items.splice(idx, 1); renderItems(); updateSegmentInfo(); };
        list.appendChild(row);
      })(i);
    }
  }
  function renderResults(){
    var list = el("resultList");
    list.innerHTML = "";
    if (!state.results.length){
      list.innerHTML = '<div class="muted">暂无生成结果。生成后可在这里预览、下载，也可以一键清空页面结果。</div>';
      return;
    }
    for (var i=0; i<state.results.length; i++){
      var result = state.results[i];
      var row = document.createElement("div");
      row.className = "item candidate-card";
      if (result.jobId){
        row.innerHTML = resultCoverHtml(result) + '<div><strong>' + escapeHtml(result.name || "处理结果") + '</strong><div class="meta">' +
          '使用的 BGM：' + escapeHtml(result.bgmDisplay || "未替换 BGM") +
          '<br>音乐片段：' + escapeHtml(result.segment || "未设置") +
          '<br>声音处理：' + escapeHtml(result.replaceAudio ? "去掉原声并替换 BGM" : "保留原声") +
          '<br>状态：' + escapeHtml(result.status || "已完成") +
          '<br>封面用于本地整理和人工上传参考。</div><video controls poster="/quick-bgm/files/' + encodeURIComponent(result.jobId) + '/cover" src="/quick-bgm/files/' + encodeURIComponent(result.jobId) + '/output"></video><a class="download" href="/quick-bgm/files/' + encodeURIComponent(result.jobId) + '/output" download>下载处理后视频</a></div>';
      } else {
        row.innerHTML = resultCoverHtml(result) + '<div><strong>' + escapeHtml(result.name || "处理结果") + '</strong><div class="meta error">' + escapeHtml(result.failure || result.status || "处理失败") + '</div></div>';
      }
      list.appendChild(row);
    }
  }
  async function uploadVideo(){
    var files = el("videoFile").files;
    if (!files.length) { setStatus("videoStatus", "请先选择视频文件。", true); return; }
    var form = new FormData();
    for (var i=0; i<files.length; i++) form.append("files", files[i]);
    setStatus("videoStatus", "正在上传视频...");
    var res = await fetch("/quick-bgm/video/upload", { method:"POST", body:form });
    var data = await res.json();
    if (!res.ok) { setStatus("videoStatus", data.detail || "视频上传失败。", true); return; }
    var jobs = data.jobs || [];
    for (var j=0; j<jobs.length; j++){
      addItem({ id:"local-"+jobs[j].job_id, sourceType:"upload", sourceTypeZh:"本地上传", jobId:jobs[j].job_id, name:jobs[j].original_filename, videoDuration:jobs[j].video_duration_seconds, status:"待处理" });
    }
    setStatus("videoStatus", data.message_zh || ("已上传 " + jobs.length + " 个视频。"));
  }
  async function previewXhsLinks(){
    var links = parseLinks(el("xhsLinks").value);
    if (!links.length) { setStatus("xhsLinkStatus", "请先粘贴小红书作品链接。", true); return; }
    var form = new FormData();
    form.append("note_urls", links.join("\n"));
    setStatus("xhsLinkStatus", "正在预览作品类型...");
    var res = await fetch("/quick-bgm/xhs-creator/preview-links", { method:"POST", body:form });
    var data = await res.json();
    if (!res.ok) { setStatus("xhsLinkStatus", data.detail || "作品预览失败。", true); return; }
    state.candidates = (data.items || []).map(function(x){ x.checked = !!x.is_video; x.source_zh = "小红书作品"; return x; });
    renderCandidates();
    setStatus("xhsLinkStatus", data.message_zh || "预览完成。请在候选素材中确认要处理的视频。");
    setStatus("candidateStatus", "已生成候选素材，请勾选视频后加入待处理列表。");
  }
  async function tryCreatorImport(){
    var url = el("creatorUrl").value.trim();
    if (!url) { setStatus("creatorStatus", "请先输入小红书博主主页。", true); return; }
    var form = new FormData();
    form.append("creator_home_url", url);
    form.append("limit", el("limit").value || "10");
    form.append("mode", el("mode").value || "auto");
    form.append("replace_audio", "false");
    form.append("bgm_strategy", "selected");
    form.append("bgm_start_seconds", "0");
    setStatus("creatorStatus", "正在尝试获取主页作品候选...");
    var res = await fetch("/quick-bgm/xhs-creator/import", { method:"POST", body:form });
    var data = await res.json();
    var batch = data.batch || null;
    if (!res.ok || !batch || batch.status === "failed"){
      var reason = batch && batch.failure_reason ? batch.failure_reason : "可能是 Cookie 缺失、登录态失效、xsec_token 失效、请求被小红书阻断，或当前工具不支持直接主页提取。";
      setStatus("creatorStatus", (data.message_zh || "主页作品列表没拿到。") + "\n原因：" + reason + "\n当前主页自动抓取需要额外配置登录态 / Cookie / MCP，且本地 XHS-Downloader API 只确认支持单条作品详情。\n兜底方式：使用 XHS-Downloader 油猴脚本提取作品链接，粘贴到“小红书作品链接”；也可以手动粘贴多条作品链接或人工上传视频。", true);
      return;
    }
    state.candidates = (batch.items || []).map(function(x){
      return { note_url:x.note_url, note_id:x.note_id, title:x.title || x.note_id || "小红书作品", author:x.author || "", publish_time:x.publish_time || "", liked_count:x.liked_count, collected_count:x.collected_count, comment_count:x.comment_count, is_video:!!x.is_video, note_type_zh:x.is_video ? "视频" : "图文/未知", status_zh:x.status_zh || "", checked:!!x.is_video, source_zh:"小红书博主主页", local_video_path:x.local_video_path, job_id:x.quick_bgm_job_id, failure_reason:x.failure_reason || "", preview_url:x.cover_url || x.preview_url || "", preview_video_url:x.preview_video_url || x.video_download_url || "" };
    });
    renderCandidates();
    setStatus("creatorStatus", "已获取候选作品：" + state.candidates.length + " 条。请在候选素材中勾选要处理的视频。");
  }
  function addSelectedCandidates(){
    var count = 0;
    var skipped = 0;
    for (var i=0; i<state.candidates.length; i++){
      var c = state.candidates[i];
      if (!c.checked || !c.is_video) continue;
      if (shouldSkipDuplicate(c)) { skipped += 1; continue; }
      addItem({
        id:"xhs-"+(c.note_id || c.note_url || Math.random()),
        sourceType:c.source_zh === "小红书博主主页" ? "xhs_creator" : "xhs_link",
        sourceTypeZh:c.source_zh || "小红书作品",
        noteUrl:c.note_url,
        jobId:c.job_id || null,
        name:c.title || c.note_id || "小红书视频",
        author:c.author || "",
        publishTime:c.publish_time || "",
        previewUrl:c.preview_url || c.cover_url || "",
        previewVideoUrl:c.preview_video_url || c.video_download_url || "",
        status:c.job_id ? "待处理" : "待下载",
        failure:c.failure_reason || "",
        videoDuration:c.video_duration_seconds || null
      });
      count += 1;
    }
    setStatus("candidateStatus", count ? ("已把 " + count + " 条视频加入待处理列表。" + (skipped ? " 已跳过 " + skipped + " 条重复作品。" : "")) : (skipped ? "已按设置跳过重复作品。取消“跳过已存在作品”后可强制重新导入。" : "没有勾选可处理的视频。"), !count);
  }
  async function uploadBgm(){
    var file = el("bgmFile").files[0];
    if (!file) { setStatus("bgmStatus", "请先选择 BGM 文件。", true); return; }
    var form = new FormData();
    form.append("file", file);
    form.append("song_name", el("songName").value.trim());
    form.append("artist_name", el("artistName").value.trim());
    setStatus("bgmStatus", "正在上传 BGM...");
    var res = await fetch("/quick-bgm/bgm/upload", { method:"POST", body:form });
    var data = await res.json();
    if (!res.ok) { setStatus("bgmStatus", data.detail || "BGM 上传失败。", true); return; }
    await selectBgm(data.bgm);
    setStatus("bgmStatus", data.message_zh || "BGM 已上传。", false);
    await loadBgm();
  }
  async function searchDownloadBgm(){
    var query = el("bgmQuery").value.trim();
    if (!query) { setStatus("bgmStatus", "请输入 BGM 名称。", true); return; }
    var form = new FormData();
    form.append("query", query);
    form.append("prefer_source", "ytdlp");
    setStatus("bgmStatus", "正在搜索并下载 BGM...");
    var res = await fetch("/quick-bgm/bgm/search-download", { method:"POST", body:form });
    var data = await res.json();
    if (!data.ok) { setStatus("bgmStatus", data.message_zh || data.failure_reason || "在线搜索下载暂未成功，请改用本地上传 BGM。", true); return; }
    await selectBgm(data.bgm);
    setStatus("bgmStatus", data.message_zh || "在线搜索下载成功。");
    await loadBgm();
  }
  async function loadBgm(){
    var res = await fetch("/quick-bgm/bgm");
    var data = await res.json();
    var list = el("bgmList");
    list.innerHTML = "";
    var items = data.items || [];
    for (var i=0; i<items.length; i++){
      (function(item){
        var row = document.createElement("div");
        row.className = "item" + (state.bgm && state.bgm.id === item.bgm_id ? " active" : "");
        row.innerHTML = '<div><strong>' + escapeHtml(item.song_name || "未命名 BGM") + '</strong><div class="meta">作者：' + escapeHtml(item.artist_name || "未填写") + ' · 来源：' + escapeHtml(item.source_type_zh || "") + ' · 使用次数：' + (item.usage_count || 0) + ' · 状态：' + escapeHtml(item.availability_status_zh || "") + '</div></div><button ' + (item.is_available ? '' : 'disabled') + '>选择</button>';
        row.querySelector("button").onclick = function(){ selectBgm(item); };
        list.appendChild(row);
      })(items[i]);
    }
  }
  async function selectBgm(item){
    var duration = item.duration_seconds;
    if (duration === null || duration === undefined){
      try { var res = await fetch("/quick-bgm/bgm/" + encodeURIComponent(item.bgm_id) + "/info"); var data = await res.json(); duration = data.bgm ? data.bgm.duration_seconds : null; } catch(e) {}
    }
    state.bgm = { id:item.bgm_id, display:item.display_name || item.song_name || "未命名 BGM", duration:duration };
    el("selectedBgmText").textContent = "当前 BGM：" + state.bgm.display;
    el("bgmAudio").src = "/quick-bgm/bgm/" + encodeURIComponent(item.bgm_id) + "/file";
    el("bgmAudio").classList.remove("hidden");
    el("bgmStartRange").max = duration ? Math.max(0, duration - 0.1) : 0;
    el("bgmStartRange").value = Math.min(Number(el("bgmStart").value || 0), Number(el("bgmStartRange").max || 0));
    updateSegmentInfo();
    await loadBgm();
  }
  async function generateLocalItem(item, replaceAudio, bgmStart){
    var form = new FormData();
    form.append("video_id", item.jobId);
    if (state.bgm && state.bgm.id) form.append("bgm_id", state.bgm.id);
    form.append("replace_audio", replaceAudio ? "true" : "false");
    form.append("bgm_start_seconds", String(bgmStart));
    var createRes = await fetch("/quick-bgm/jobs/create", { method:"POST", body:form });
    var created = await createRes.json();
    if (!createRes.ok) throw new Error(created.detail || "任务创建失败。");
    var runRes = await fetch("/quick-bgm/jobs/" + encodeURIComponent(created.job.job_id) + "/run", { method:"POST" });
    var ran = await runRes.json();
    if (!ran.job || ran.job.status !== "done") throw new Error((ran.job && ran.job.failure_reason) || ran.message_zh || "生成失败。");
    return ran.job;
  }
  async function generateXhsItems(items, replaceAudio, bgmStart){
    var form = new FormData();
    form.append("note_urls", items.map(function(x){ return x.noteUrl; }).join("\n"));
    if (state.bgm && state.bgm.id) form.append("bgm_id", state.bgm.id);
    form.append("bgm_strategy", "selected");
    form.append("replace_audio", replaceAudio ? "true" : "false");
    form.append("bgm_start_seconds", String(bgmStart));
    var res = await fetch("/quick-bgm/xhs-creator/manual-links", { method:"POST", body:form });
    var data = await res.json();
    if (!res.ok) throw new Error(data.detail || "小红书链接批量处理失败。");
    return data.batch;
  }
  async function generateAll(){
    var selected = state.items.filter(function(x){ return x.checked; });
    if (!selected.length) { setStatus("jobStatus", "请先勾选需要处理的视频。", true); return; }
    var replaceAudio = document.querySelector('input[name="audioMode"]:checked').value === "true";
    if (replaceAudio && (!state.bgm || !state.bgm.id)) { setStatus("jobStatus", "请选择一个 BGM。", true); return; }
    el("runBtn").disabled = true;
    state.results = [];
    renderResults();
    var bgmStart = Number(el("bgmStart").value || 0);
    try {
      var localItems = selected.filter(function(x){ return x.jobId; });
      for (var i=0; i<localItems.length; i++){
        var item = localItems[i];
        item.status = "处理中"; renderItems();
        try { var job = await generateLocalItem(item, replaceAudio, bgmStart); item.status = "已完成"; item.resultJobId = job.job_id; state.results.push({ name:item.name, status:"已完成", jobId:job.job_id, bgmDisplay:replaceAudio && state.bgm ? state.bgm.display : "保留原声", segment:replaceAudio ? segmentLabel(bgmStart, item.videoDuration) : "未替换 BGM", replaceAudio:replaceAudio, coverUrl:item.previewUrl || "" }); }
        catch(e){ item.status = "失败"; item.failure = e.message; state.results.push({ name:item.name, status:"失败", failure:e.message, bgmDisplay:replaceAudio && state.bgm ? state.bgm.display : "保留原声", segment:replaceAudio ? segmentLabel(bgmStart, item.videoDuration) : "未替换 BGM", replaceAudio:replaceAudio, coverUrl:item.previewUrl || "" }); }
        renderItems(); renderResults();
      }
      var xhsItems = selected.filter(function(x){ return !x.jobId && x.noteUrl; });
      if (xhsItems.length){
        setStatus("jobStatus", "正在下载并处理小红书视频，请稍等...");
        var batch = await generateXhsItems(xhsItems, replaceAudio, bgmStart);
        var batchItems = batch.items || [];
        for (var j=0; j<batchItems.length; j++){
          var bi = batchItems[j];
          state.results.push({ name:bi.title || bi.note_id || "小红书视频", status:bi.status_zh || bi.status || "完成", jobId:bi.quick_bgm_job_id, failure:bi.failure_reason, bgmDisplay:replaceAudio && state.bgm ? state.bgm.display : "保留原声", segment:replaceAudio ? segmentLabel(bgmStart, null) : "未替换 BGM", replaceAudio:replaceAudio, coverUrl:bi.cover_url || "" });
        }
        renderResults();
      }
      setStatus("jobStatus", "处理完成。可以预览或下载结果。", false);
    } catch(e){
      setStatus("jobStatus", e.message || "生成失败。", true);
    } finally {
      el("runBtn").disabled = false;
      renderItems();
      renderResults();
    }
  }
  function bind(){
    document.querySelectorAll(".tab").forEach(function(btn){ btn.addEventListener("click", function(){ switchImportTab(btn.getAttribute("data-tab")); }); });
    el("clearPendingBtn").addEventListener("click", clearPending);
    el("clearCandidatesBtn").addEventListener("click", clearCandidates);
    el("clearResultsBtn").addEventListener("click", clearResults);
    el("selectAllCandidatesBtn").addEventListener("click", function(){ setCandidateChecked("all"); });
    el("unselectCandidatesBtn").addEventListener("click", function(){ setCandidateChecked("none"); });
    el("invertCandidatesBtn").addEventListener("click", function(){ setCandidateChecked("invert"); });
    el("selectAllPendingBtn").addEventListener("click", function(){ setPendingChecked("all"); });
    el("unselectPendingBtn").addEventListener("click", function(){ setPendingChecked("none"); });
    el("invertPendingBtn").addEventListener("click", function(){ setPendingChecked("invert"); });
    el("removeSelectedPendingBtn").addEventListener("click", removeSelectedPending);
    el("skipDuplicate").addEventListener("change", renderCandidates);
    el("uploadVideoBtn").addEventListener("click", uploadVideo);
    el("previewLinksBtn").addEventListener("click", previewXhsLinks);
    el("creatorImportBtn").addEventListener("click", tryCreatorImport);
    el("addCandidatesBtn").addEventListener("click", addSelectedCandidates);
    el("uploadBgmBtn").addEventListener("click", uploadBgm);
    el("searchBgmBtn").addEventListener("click", searchDownloadBgm);
    el("runBtn").addEventListener("click", generateAll);
    el("bgmStartRange").addEventListener("input", function(){ el("bgmStart").value = el("bgmStartRange").value; updateSegmentInfo(); });
    el("bgmStart").addEventListener("input", function(){ var v = Math.max(0, Number(el("bgmStart").value || 0)); el("bgmStartRange").value = Math.min(v, Number(el("bgmStartRange").max || 0)); updateSegmentInfo(); });
    el("bgmAudio").addEventListener("loadedmetadata", function(){ if (state.bgm && !state.bgm.duration && el("bgmAudio").duration){ state.bgm.duration = el("bgmAudio").duration; el("bgmStartRange").max = Math.max(0, el("bgmAudio").duration - 0.1); updateSegmentInfo(); } });
  }
  window.addEventListener("DOMContentLoaded", function(){ bind(); renderCandidates(); renderItems(); renderResults(); loadBgm(); updateSegmentInfo(); });
})();
</script>
</body>
</html>
"""
    return html.replace("__DEFAULT_CREATOR_URL__", DEFAULT_CREATOR_URL)
