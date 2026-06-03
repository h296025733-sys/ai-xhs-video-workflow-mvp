import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import Body, FastAPI, File, HTTPException, Path as ApiPath, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import Response

from app.config import JOBS_DIR, ensure_storage_dirs
from app.models import (
    AssetListItem,
    AssetStatus,
    CandidateActionResponse,
    CandidateCreateRequest,
    CandidateListResponse,
    GuideResponse,
    HealthResponse,
    PackageResponse,
    PrepareProcessingResponse,
    SceneDetectResponse,
    SceneLabelsResponse,
    SceneLabelsSaveRequest,
    SourceDiscoveryResponse,
    UploadRecord,
    UploadVideoResponse,
    VideoMetadata,
    WatchCreateRequest,
    WatchlistResponse,
    XiaohongshuSearchRequest,
)
from app.material_pool.store import (
    add_candidate,
    add_candidate_to_watchlist,
    add_watch_item,
    find_candidate,
    list_candidates,
    list_watchlist,
    update_candidate_status,
)
from app.services.media_probe import MediaToolError, command_available, probe_video, python_version, scenedetect_available
from app.services.package_builder import build_package, save_json
from app.services.asset_paths import create_asset_dirs, resolve_output_dir, resolve_output_folder_name
from app.services.scene_detect import detect_scenes
from app.services.scene_labels import build_review_page_html, initialize_scene_labels, save_scene_labels
from app.quick_bgm.media import ffmpeg_path, ffprobe_path
from app.source_discovery.xiaohongshu import search_xiaohongshu
from app.quick_bgm.router import router as quick_bgm_router


class AsciiJSONResponse(JSONResponse):
    """用 ASCII-safe JSON 输出中文，避免 Windows PowerShell/curl 管道出现编码解析问题。"""

    def render(self, content: object) -> bytes:
        return json.dumps(
            content,
            ensure_ascii=True,
            allow_nan=False,
            indent=None,
            separators=(",", ":"),
        ).encode("utf-8")


APP_DESCRIPTION = """
这是一个面向服装电商 TikTok 本地化的素材处理 MVP。

当前版本聚焦本地视频上传、视频基础信息分析、镜头分段、关键帧提取和素材处理包生成。
它不会自动下载小红书素材，不做去水印，不自动发布 TikTok，也不会调用收费 AI API。

接口路径和核心 JSON 字段名保持英文，便于后续接入 n8n、脚本、AI API、剪映/CapCut 草稿工具、FFmpeg 模板渲染和 TikTok API。
中文说明主要用于让运营、主管和非开发同事理解每个接口的作用。
"""

TAGS_METADATA = [
    {"name": "系统检查", "description": "查看服务状态、依赖可用性和中文使用指南。"},
    {"name": "素材上传", "description": "上传本地视频素材，并生成后续处理使用的 asset_id。"},
    {"name": "视频分析", "description": "读取视频基础信息，包括时长、分辨率、帧率、编码格式和音频流。"},
    {"name": "镜头分段", "description": "进行镜头/场景分段，并提取关键帧和总览图。"},
    {"name": "镜头标注", "description": "读取、保存人工镜头标签，并生成中文审核页面。"},
    {"name": "素材处理包", "description": "生成面向服装电商 TikTok 本地化的处理包。"},
    {"name": "素材查询", "description": "查看单个素材或全部素材的处理状态。"},
    {"name": "素材池", "description": "候选素材池、人工添加、选中/放弃/追更和准备处理入口。"},
    {"name": "素材发现", "description": "小红书 mock 搜索和博主追更列表。"},
]

app = FastAPI(
    title="服装电商 TikTok 本地化素材处理 MVP",
    description=APP_DESCRIPTION,
    version="0.1.0",
    openapi_tags=TAGS_METADATA,
    default_response_class=AsciiJSONResponse,
)
app.include_router(quick_bgm_router)


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> Response:
    return AsciiJSONResponse(status_code=exc.status_code, content={"detail": exc.detail}, headers=exc.headers)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError) -> Response:
    return AsciiJSONResponse(status_code=422, content={"detail": exc.errors(), "message_zh": "请求参数校验失败。"})


def _job_path(asset_id: str) -> Path:
    return JOBS_DIR / f"{asset_id}.json"


def _read_job(asset_id: str) -> dict:
    path = _job_path(asset_id)
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"未找到素材 asset_id：{asset_id}")
    return json.loads(path.read_text(encoding="utf-8"))


def _write_job(asset_id: str, job: dict) -> None:
    JOBS_DIR.mkdir(parents=True, exist_ok=True)
    _job_path(asset_id).write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8")


def _video_path_from_job(job: dict) -> Path:
    upload = job.get("upload") or {}
    path = Path(upload.get("saved_path", ""))
    if not path.exists():
        raise HTTPException(status_code=404, detail="上传视频文件在本机磁盘中不存在，请检查素材是否被移动或删除。")
    return path


def _output_files(asset_id: str) -> list[str]:
    job = None
    try:
        job = _read_job(asset_id)
    except HTTPException:
        job = None
    output_dir = resolve_output_dir(asset_id, job)
    if not output_dir.exists():
        return []
    return sorted(str(path) for path in output_dir.rglob("*") if path.is_file())


@app.get(
    "/health",
    response_model=HealthResponse,
    tags=["系统检查"],
    summary="检查服务与本地依赖状态",
    description="返回 FastAPI 服务状态、Python 版本、当前工作目录，以及 ffmpeg、ffprobe、scenedetect 是否可用。",
)
def health() -> dict:
    """检查服务状态和本地视频处理依赖是否可用。"""
    return {
        "status": "ok",
        "status_zh": "服务正常",
        "python_version": python_version(),
        "cwd": os.getcwd(),
        "ffmpeg_available": command_available("ffmpeg") or ffmpeg_path() is not None,
        "ffprobe_available": command_available("ffprobe") or ffprobe_path() is not None,
        "scenedetect_available": scenedetect_available(),
    }


@app.get(
    "/guide",
    response_model=GuideResponse,
    tags=["系统检查"],
    summary="查看中文使用指南",
    description="返回面向中文使用者的项目说明、推荐测试顺序、接口用途、输出位置和后续接入方向。",
)
def guide() -> dict:
    """返回中文使用指南，方便运营、主管和非开发同事快速理解这套 MVP。"""
    return {
        "title": "服装电商 TikTok 本地化素材处理 MVP 使用指南",
        "purpose": "把本地服装视频素材整理成可分析、可审核、可本地化、可继续接自动化工作流的素材处理包。",
        "recommended_test_order": [
            "GET /health：确认服务和本地依赖可用。",
            "POST /upload-video：上传一个本地视频，获得 asset_id。",
            "POST /analyze-video/{asset_id}：读取视频基础信息。",
            "POST /detect-scenes/{asset_id}：进行镜头分段并生成关键帧总览图。",
            "POST /extract-package/{asset_id}：生成完整素材处理包。",
            "GET /assets/{asset_id}：查看单个素材状态和输出文件。",
            "GET /assets：查看所有素材列表。",
        ],
        "endpoints": {
            "GET /health": "检查服务状态、Python 版本、工作目录、ffmpeg、ffprobe 和 scenedetect 是否可用。",
            "POST /upload-video": "上传一个本地视频素材，并生成唯一素材 ID。",
            "POST /analyze-video/{asset_id}": "分析视频基础信息，包括时长、分辨率、帧率、编码格式和音频流情况。",
            "POST /detect-scenes/{asset_id}": "对视频进行镜头分段，并提取关键帧，方便判断服装展示、细节特写和转身动态等画面。",
            "POST /extract-package/{asset_id}": "生成素材处理包，包括封面、音频、镜头分段、关键帧总览图、本地化请求文档和审核清单。",
            "GET /scene-labels/{asset_id}": "读取镜头标签；如果标签文件不存在，会根据 scene_segments.json 初始化默认待判断标签。",
            "POST /scene-labels/{asset_id}": "保存人工填写的镜头标签，不覆盖原始 scene_segments.json。",
            "GET /review-page/{asset_id}": "打开中文只读审核页，查看素材信息、关键帧总览和逐镜头标签。",
            "GET /assets/{asset_id}": "查看某个素材的上传记录、分析结果、镜头分段和输出文件列表。",
            "GET /assets": "查看所有素材的处理状态概览。",
        },
        "output_location": "app/storage/outputs/{asset_id}/",
        "not_in_scope": [
            "不做小红书自动下载。",
            "不做去水印。",
            "不做 TikTok 自动发布。",
            "不调用收费 AI API，也不要求填写 API Key。",
            "第一版不按固定时间轴硬剪视频。",
        ],
        "future_integrations": [
            "n8n 工作流编排。",
            "AI 视觉模型和韩语/日语文案模型。",
            "剪映/CapCut 草稿工具或 pyJianYingDraft。",
            "FFmpeg 竖屏模板渲染。",
            "TikTok API 与发布后数据监控。",
        ],
    }


@app.post(
    "/source-discovery/xiaohongshu/search",
    response_model=SourceDiscoveryResponse,
    tags=["素材发现"],
    summary="小红书候选素材搜索",
    description="默认使用 mock 模式生成小红书候选素材并写入候选池。external 模式仅预留 adapter 配置，不强依赖真实第三方服务。",
)
def xiaohongshu_search(payload: XiaohongshuSearchRequest) -> dict:
    """搜索或模拟生成小红书候选素材，当前默认 mock/manual 可用。"""
    return search_xiaohongshu(
        keyword=payload.keyword,
        limit=payload.limit,
        mode=payload.mode,
        selected_region=payload.selected_region,
        selected_style=payload.selected_style,
    )


@app.get(
    "/material-pool/candidates",
    response_model=CandidateListResponse,
    tags=["素材池"],
    summary="查看候选素材池",
    description="查看自动抓取和人工录入统一进入的候选素材池。",
)
def get_material_candidates() -> dict:
    """返回当前候选素材池。"""
    return {"candidates": list_candidates(), "message_zh": "候选素材池读取成功。"}


@app.post(
    "/material-pool/candidates",
    response_model=CandidateActionResponse,
    tags=["素材池"],
    summary="人工新增候选素材",
    description="人工录入一个候选素材。未提供的字段会使用合理默认值，source_type 默认为 manual，status 默认为 candidate。",
)
def create_material_candidate(payload: CandidateCreateRequest) -> dict:
    """人工添加候选素材到统一素材池。"""
    candidate = add_candidate(payload.model_dump(), source_type="manual")
    return {"candidate_id": candidate["candidate_id"], "candidate": candidate, "message_zh": "人工候选素材已加入素材池。"}


def _change_candidate_status(candidate_id: str, status: str, message: str) -> dict:
    try:
        candidate = update_candidate_status(candidate_id, status)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"未找到候选素材 candidate_id：{candidate_id}") from exc
    return {"candidate_id": candidate_id, "candidate": candidate, "message_zh": message}


@app.post(
    "/material-pool/candidates/{candidate_id}/select",
    response_model=CandidateActionResponse,
    tags=["素材池"],
    summary="标记候选素材为已选中",
)
def select_material_candidate(candidate_id: str = ApiPath(..., description="候选素材 ID。")) -> dict:
    """把候选素材标记为已选中。"""
    return _change_candidate_status(candidate_id, "selected", "候选素材已标记为已选中。")


@app.post(
    "/material-pool/candidates/{candidate_id}/reject",
    response_model=CandidateActionResponse,
    tags=["素材池"],
    summary="标记候选素材为已放弃",
)
def reject_material_candidate(candidate_id: str = ApiPath(..., description="候选素材 ID。")) -> dict:
    """把候选素材标记为已放弃。"""
    return _change_candidate_status(candidate_id, "rejected", "候选素材已标记为已放弃。")


@app.post(
    "/material-pool/candidates/{candidate_id}/watch",
    response_model=CandidateActionResponse,
    tags=["素材池"],
    summary="加入长期追更",
    description="把候选素材标记为长期追更，并基于作者信息写入 watchlist。当前不做真实追更抓取。",
)
def watch_material_candidate(candidate_id: str = ApiPath(..., description="候选素材 ID。")) -> dict:
    """把候选素材加入长期追更。"""
    result = _change_candidate_status(candidate_id, "watching", "候选素材已标记为长期追更，并写入追更博主列表。")
    add_candidate_to_watchlist(result["candidate"])
    return result


@app.post(
    "/material-pool/candidates/{candidate_id}/prepare-processing",
    response_model=PrepareProcessingResponse,
    tags=["素材池"],
    summary="准备进入现有视频处理链路",
    description="检查候选素材是否已有本地文件。不会强行下载，也不会破坏 /upload-video。",
)
def prepare_candidate_processing(candidate_id: str = ApiPath(..., description="候选素材 ID。")) -> dict:
    """检查候选素材是否具备进入现有视频处理链路的本地文件条件。"""
    candidate = find_candidate(candidate_id)
    if not candidate:
        raise HTTPException(status_code=404, detail=f"未找到候选素材 candidate_id：{candidate_id}")
    local_file_path = candidate.get("local_file_path")
    if local_file_path and Path(local_file_path).exists():
        return {
            "candidate_id": candidate_id,
            "can_process": True,
            "local_file_path": local_file_path,
            "message_zh": "该素材已有本地文件，可以进入后续视频处理链路。",
            "next_action_zh": "请使用现有 /upload-video 或后续素材池入口把本地文件送入处理流程。",
        }
    return {
        "candidate_id": candidate_id,
        "can_process": False,
        "local_file_path": local_file_path,
        "message_zh": "当前候选素材只有链接或本地文件不存在，需要先下载或人工上传视频后再处理。",
        "next_action_zh": "本轮不自动下载；请人工上传本地视频，或后续接入小红书下载 adapter。",
    }


@app.get(
    "/source-discovery/watchlist",
    response_model=WatchlistResponse,
    tags=["素材发现"],
    summary="查看长期追更博主",
    description="查看长期追更博主列表。后续可由 OpenClaw / xiaohongshu-mcp 定时任务接入。",
)
def get_source_watchlist() -> dict:
    """查看追更博主列表。"""
    return {"watchlist": list_watchlist(), "message_zh": "长期追更列表读取成功。"}


@app.post(
    "/source-discovery/watchlist",
    response_model=WatchlistResponse,
    tags=["素材发现"],
    summary="添加长期追更博主",
    description="人工添加一个长期追更博主。本轮只保存信息，不做真实抓取。",
)
def create_source_watch(payload: WatchCreateRequest) -> dict:
    """添加追更博主。"""
    item = add_watch_item(payload.model_dump())
    return {"watchlist": list_watchlist(), "message_zh": f"已添加长期追更博主：{item['author_name']}。"}


@app.post(
    "/upload-video",
    response_model=UploadVideoResponse,
    tags=["素材上传"],
    summary="上传本地视频素材",
    description="上传一个本地视频素材，并生成唯一素材 ID，后续分析、镜头分段和处理包生成都基于该 ID 执行。",
)
async def upload_video(file: UploadFile = File(..., description="要上传的本地视频文件。")) -> dict:
    """上传一个视频素材，保存到本机 uploads 目录，并记录素材 ID 和文件信息。"""
    ensure_storage_dirs()
    asset_id = uuid.uuid4().hex
    filename = Path(file.filename or "uploaded_video").name
    dirs = create_asset_dirs(asset_id, filename)
    asset_dir = Path(dirs["upload_dir"])
    saved_path = asset_dir / filename
    size = 0
    with saved_path.open("wb") as buffer:
        while chunk := await file.read(1024 * 1024):
            size += len(chunk)
            buffer.write(chunk)

    record = UploadRecord(
        asset_id=asset_id,
        original_filename=filename,
        saved_path=str(saved_path),
        upload_time=datetime.now(timezone.utc).isoformat(),
        content_type=file.content_type,
        size_bytes=size,
    )
    created_at = datetime.now(timezone.utc).isoformat()
    _write_job(
        asset_id,
        {
            "asset_id": asset_id,
            "original_filename": filename,
            "upload_dir": dirs["upload_dir"],
            "output_dir": dirs["output_dir"],
            "output_dir_name": dirs["output_dir_name"],
            "output_folder_name": dirs["output_folder_name"],
            "created_at": created_at,
            "upload": record.model_dump(),
            "status": "uploaded",
        },
    )
    return {
        "asset_id": asset_id,
        "original_filename": filename,
        "output_dir": dirs["output_dir"],
        "output_dir_name": dirs["output_dir_name"],
        "output_folder_name": dirs["output_folder_name"],
        "message_zh": "视频上传成功，后续接口请使用该 asset_id。",
        "file": record.model_dump(),
    }


@app.post(
    "/analyze-video/{asset_id}",
    response_model=VideoMetadata,
    tags=["视频分析"],
    summary="分析视频基础信息",
    description="分析视频基础信息，包括文件名、文件大小、时长、分辨率、帧率、是否有音频流、视频编码和音频编码。",
)
def analyze_video(
    asset_id: str = ApiPath(..., description="素材唯一 ID，由 /upload-video 返回。"),
) -> dict:
    """读取视频基础元信息，供后续镜头分段、剪辑建议和本地化文档使用。"""
    job = _read_job(asset_id)
    video_path = _video_path_from_job(job)
    try:
        metadata = probe_video(video_path, job["upload"]["original_filename"])
    except MediaToolError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    job["metadata"] = metadata.model_dump()
    job["status"] = "analyzed"
    _write_job(asset_id, job)
    return metadata.model_dump()


@app.post(
    "/detect-scenes/{asset_id}",
    response_model=SceneDetectResponse,
    tags=["镜头分段"],
    summary="进行镜头分段并提取关键帧",
    description="对视频进行镜头/场景分段，并为每个镜头提取一张关键帧，同时生成 scene_contact_sheet.jpg，方便人工快速判断服装展示、细节特写、转身动态和氛围镜头。",
)
def detect_video_scenes(
    asset_id: str = ApiPath(..., description="素材唯一 ID，由 /upload-video 返回。"),
) -> dict:
    """进行镜头分段，提取关键帧，并生成关键帧总览图。"""
    job = _read_job(asset_id)
    video_path = _video_path_from_job(job)
    try:
        metadata = probe_video(video_path, job["upload"]["original_filename"])
        scene_dir = resolve_output_dir(asset_id, job, job["upload"]["original_filename"], create=True)
        scenes, contact_sheet = detect_scenes(video_path, scene_dir, metadata)
    except MediaToolError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    job["metadata"] = metadata.model_dump()
    job["scenes"] = [scene.model_dump() for scene in scenes]
    job["output_dir"] = str(scene_dir)
    job["output_dir_name"] = scene_dir.name
    job["output_folder_name"] = scene_dir.name
    job["status"] = "scenes_detected"
    _write_job(asset_id, job)
    save_json(scene_dir / "scene_segments.json", [scene.model_dump() for scene in scenes])
    return {
        "asset_id": asset_id,
        "message_zh": "镜头分段完成，已生成关键帧和 scene_contact_sheet.jpg。",
        "scenes": job["scenes"],
        "scene_contact_sheet": str(contact_sheet),
    }


@app.post(
    "/extract-package/{asset_id}",
    response_model=PackageResponse,
    tags=["素材处理包"],
    summary="生成素材处理包",
    description="生成素材处理包，包括封面、音频、视频元信息、镜头分段、关键帧总览图、服装类剪辑建议、韩语/日语本地化请求文档和人工审核清单。",
)
def extract_package(
    asset_id: str = ApiPath(..., description="素材唯一 ID，由 /upload-video 返回。"),
) -> dict:
    """生成完整素材处理包，为后续 AI 本地化、人工审核和剪辑工具接入做准备。"""
    job = _read_job(asset_id)
    video_path = _video_path_from_job(job)
    try:
        output_dir = resolve_output_dir(asset_id, job, job["upload"]["original_filename"], create=True)
        package = build_package(asset_id, video_path, job["upload"]["original_filename"], output_dir=output_dir)
    except MediaToolError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    job["metadata"] = package["metadata"]
    job["scenes"] = package["scenes"]
    job["output_dir"] = package["output_dir"]
    job["output_dir_name"] = package["output_dir_name"]
    job["output_folder_name"] = package["output_folder_name"]
    job["package"] = {"output_dir": package["output_dir"], "files": package["files"]}
    job["status"] = "package_generated"
    _write_job(asset_id, job)
    package["message_zh"] = "素材处理包生成完成。"
    return package


@app.get(
    "/scene-labels/{asset_id}",
    response_model=SceneLabelsResponse,
    tags=["镜头标注"],
    summary="读取镜头标签",
    description="读取某个素材的镜头标签。如果 scene_labels.json 不存在，则根据 scene_segments.json 初始化默认标签文件。默认标签不会假装已经识别服装内容，scene_role 和 keep_decision 均为 unknown。",
)
def get_scene_labels(
    asset_id: str = ApiPath(..., description="素材唯一 ID，由 /upload-video 返回。"),
) -> dict:
    """读取或初始化镜头标签，供人工审核和后续 AI 视觉模型接入使用。"""
    _read_job(asset_id)
    try:
        labels = initialize_scene_labels(asset_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {
        "asset_id": asset_id,
        "scenes": [label.model_dump() for label in labels],
        "message_zh": "镜头标签已读取。未人工填写前，标签状态为待判断。",
    }


@app.post(
    "/scene-labels/{asset_id}",
    response_model=SceneLabelsResponse,
    tags=["镜头标注"],
    summary="保存人工镜头标签",
    description="保存人工填写的镜头标签到 scene_labels.json。该接口不会覆盖 scene_segments.json，适合后续把人工标签交给 n8n、AI API、剪映/CapCut 或 FFmpeg 模板渲染。",
)
def post_scene_labels(
    asset_id: str = ApiPath(..., description="素材唯一 ID，由 /upload-video 返回。"),
    payload: SceneLabelsSaveRequest = Body(..., description="人工镜头标签 JSON。"),
) -> dict:
    """保存人工镜头标签，不修改原始镜头分段结果。"""
    _read_job(asset_id)
    save_scene_labels(asset_id, payload.scenes)
    return {
        "asset_id": asset_id,
        "scenes": [label.model_dump() for label in payload.scenes],
        "message_zh": "人工镜头标签已保存到 scene_labels.json。",
    }


@app.get(
    "/review-page/{asset_id}",
    response_class=HTMLResponse,
    tags=["镜头标注"],
    summary="打开中文素材审核页",
    description="生成一个简单的中文 HTML 审核页面，展示素材基础信息、scene_contact_sheet.jpg、每个 scene 的关键帧、当前标签、保留建议和备注。页面只作为审核辅助，不代表自动发布。",
)
def review_page(
    asset_id: str = ApiPath(..., description="素材唯一 ID，由 /upload-video 返回。"),
) -> HTMLResponse:
    """生成只读中文审核页，方便非开发同事查看镜头分段和人工标签。"""
    job = _read_job(asset_id)
    try:
        labels = initialize_scene_labels(asset_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    metadata = job.get("metadata")
    html = build_review_page_html(asset_id, metadata, labels)
    return HTMLResponse(content=html, media_type="text/html; charset=utf-8")


@app.get(
    "/assets/{asset_id}",
    response_model=AssetStatus,
    tags=["素材查询"],
    summary="查看单个素材状态",
    description="查看某个素材的处理状态，包括上传记录、视频分析结果、镜头分段结果和已经生成的输出文件列表。",
)
def get_asset(
    asset_id: str = ApiPath(..., description="素材唯一 ID，由 /upload-video 返回。"),
) -> dict:
    """查看单个素材的当前状态和输出文件。"""
    job = _read_job(asset_id)
    return {
        "asset_id": asset_id,
        "status": job.get("status"),
        "original_filename": job.get("original_filename") or (job.get("upload") or {}).get("original_filename"),
        "output_dir": str(resolve_output_dir(asset_id, job)),
        "output_dir_name": resolve_output_folder_name(asset_id, job),
        "output_folder_name": resolve_output_folder_name(asset_id, job),
        "upload": job.get("upload"),
        "metadata": job.get("metadata"),
        "scenes": job.get("scenes"),
        "output_files": _output_files(asset_id),
    }


@app.get(
    "/assets",
    response_model=list[AssetListItem],
    tags=["素材查询"],
    summary="查看所有素材列表",
    description="返回所有已上传素材的状态概览，包括是否已分析、是否已生成镜头分段、是否已生成素材处理包。",
)
def list_assets() -> list[dict]:
    """查看所有素材的处理状态概览。"""
    ensure_storage_dirs()
    assets = []
    for path in sorted(JOBS_DIR.glob("*.json")):
        job = json.loads(path.read_text(encoding="utf-8"))
        asset_id = job.get("asset_id", path.stem)
        upload = job.get("upload") or {}
        output_dir = resolve_output_dir(asset_id, job)
        output_files = sorted(str(path) for path in output_dir.rglob("*") if path.is_file()) if output_dir.exists() else []
        assets.append(
            {
                "asset_id": asset_id,
                "original_filename": upload.get("original_filename"),
                "output_dir": str(output_dir),
                "output_dir_name": resolve_output_folder_name(asset_id, job, output_dir),
                "output_folder_name": resolve_output_folder_name(asset_id, job, output_dir),
                "upload_time": upload.get("upload_time"),
                "is_analyzed": bool(job.get("metadata")),
                "has_scene_segments": bool(job.get("scenes")) or (output_dir / "scene_segments.json").exists(),
                "has_package": bool(job.get("package")) or bool(output_files),
            }
        )
    return assets
