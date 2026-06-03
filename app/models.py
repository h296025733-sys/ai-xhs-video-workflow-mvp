from typing import Any, Literal

from pydantic import BaseModel, Field


class UploadRecord(BaseModel):
    asset_id: str = Field(description="素材唯一 ID，后续分析、镜头分段和处理包生成都使用该 ID。")
    original_filename: str = Field(description="上传时的原始文件名。")
    saved_path: str = Field(description="视频文件在本机保存后的完整路径。")
    upload_time: str = Field(description="上传时间，使用 UTC ISO 格式。")
    content_type: str | None = Field(default=None, description="上传文件的 MIME 类型，可能由客户端提供。")
    size_bytes: int = Field(description="上传文件大小，单位为字节。")


class VideoMetadata(BaseModel):
    filename: str = Field(description="视频文件名。")
    file_size_bytes: int = Field(description="视频文件大小，单位为字节。")
    duration: float | None = Field(default=None, description="视频时长，单位为秒。")
    width: int | None = Field(default=None, description="视频宽度，单位为像素。")
    height: int | None = Field(default=None, description="视频高度，单位为像素。")
    frame_rate: float | None = Field(default=None, description="视频帧率。")
    has_audio: bool = Field(default=False, description="是否检测到音频流。")
    video_codec: str | None = Field(default=None, description="视频编码格式，例如 h264。")
    audio_codec: str | None = Field(default=None, description="音频编码格式，例如 aac。")
    raw_probe: dict[str, Any] = Field(default_factory=dict, description="ffprobe 返回的原始结构化信息，便于后续扩展。")


class SceneSegment(BaseModel):
    scene_id: int = Field(description="镜头序号，从 1 开始。")
    start_time: float = Field(description="镜头开始时间，单位为秒。")
    end_time: float = Field(description="镜头结束时间，单位为秒。")
    duration: float = Field(description="镜头持续时间，单位为秒。")
    keyframe_path: str | None = Field(default=None, description="该镜头关键帧图片在本机的完整路径。")
    notes: str = Field(description="镜头分段说明，用于提示是否为检测结果或兜底结果。")
    is_too_short: bool = Field(default=False, description="是否短于 0.5 秒，疑似无效尾帧、转场残留或黑帧。")
    quality_type: str = Field(default="normal", description="片段质量类型，例如 normal、too_short、short_but_possible、long_scene。")
    quality_note_zh: str = Field(default="常规镜头片段。", description="中文质量提示，用于人工审核。")


SceneRole = Literal[
    "hook_opening",
    "full_body",
    "side_view",
    "walking_motion",
    "turn_motion",
    "detail_fabric",
    "detail_shoes",
    "detail_bag",
    "atmosphere",
    "low_value",
    "unknown",
]

KeepDecision = Literal["keep", "maybe", "cut", "unknown"]


class SceneLabel(BaseModel):
    scene_id: int = Field(description="镜头序号，与 scene_segments.json 中的 scene_id 对应。")
    start_time: float = Field(description="镜头开始时间，单位为秒。")
    end_time: float = Field(description="镜头结束时间，单位为秒。")
    duration: float = Field(description="镜头持续时间，单位为秒。")
    keyframe_path: str | None = Field(default=None, description="该镜头关键帧图片在本机的完整路径。")
    suggested_tags: list[str] = Field(
        default_factory=list,
        description="系统建议标签。当前版本不做真实视觉理解，通常为空或仅包含低置信度提示。",
    )
    manual_tags: list[str] = Field(default_factory=list, description="人工填写的镜头标签，例如 全身展示、鞋子细节、包包展示。")
    scene_role: SceneRole = Field(default="unknown", description="镜头角色，未人工确认前默认为 unknown。")
    keep_decision: KeepDecision = Field(default="unknown", description="保留决策，未人工确认前默认为 unknown。")
    edit_note: str = Field(default="", description="人工剪辑备注，例如适合作为开场、可做细节补充、节奏偏慢。")
    risk_note: str = Field(default="", description="人工风险备注，例如水印、搬运感、音乐版权、人脸授权等。")


class AssetStatus(BaseModel):
    asset_id: str = Field(description="素材唯一 ID。")
    status: str | None = Field(default=None, description="素材当前处理状态。")
    original_filename: str | None = Field(default=None, description="原始视频文件名。")
    output_dir: str | None = Field(default=None, description="素材输出目录。")
    output_dir_name: str | None = Field(default=None, description="输出目录名，使用原视频文件名安全化后的纯名字。")
    output_folder_name: str | None = Field(default=None, description="更适合人工查找的输出文件夹名。")
    upload: UploadRecord | None = Field(default=None, description="上传文件记录。")
    metadata: VideoMetadata | None = Field(default=None, description="视频基础分析结果。")
    scenes: list[SceneSegment] | None = Field(default=None, description="镜头分段结果。")
    output_files: list[str] = Field(default_factory=list, description="已经生成的输出文件列表。")


class HealthResponse(BaseModel):
    status: str = Field(description="服务状态，正常时为 ok。")
    status_zh: str = Field(description="中文服务状态说明。")
    python_version: str = Field(description="当前 Python 版本。")
    cwd: str = Field(description="FastAPI 服务当前工作目录。")
    ffmpeg_available: bool = Field(description="ffmpeg 是否可用。")
    ffprobe_available: bool = Field(description="ffprobe 是否可用。")
    scenedetect_available: bool = Field(description="PySceneDetect / scenedetect 是否可用。")


class UploadVideoResponse(BaseModel):
    asset_id: str = Field(description="素材唯一 ID。")
    original_filename: str | None = Field(default=None, description="原始视频文件名。")
    output_dir: str | None = Field(default=None, description="素材输出目录。")
    output_dir_name: str | None = Field(default=None, description="输出目录名，使用原视频文件名安全化后的纯名字。")
    output_folder_name: str | None = Field(default=None, description="更适合人工查找的输出文件夹名。")
    message_zh: str = Field(description="中文上传结果说明。")
    file: UploadRecord = Field(description="上传文件记录。")


class SceneDetectResponse(BaseModel):
    asset_id: str = Field(description="素材唯一 ID。")
    message_zh: str = Field(description="中文镜头分段结果说明。")
    scenes: list[SceneSegment] = Field(description="镜头分段列表。")
    scene_contact_sheet: str = Field(description="关键帧总览图路径。")


class SceneLabelsResponse(BaseModel):
    asset_id: str = Field(description="素材唯一 ID。")
    scenes: list[SceneLabel] = Field(description="镜头标签列表。")
    message_zh: str = Field(description="中文结果说明。")


class SceneLabelsSaveRequest(BaseModel):
    scenes: list[SceneLabel] = Field(description="要保存的人工镜头标签列表。")


class PackageResponse(BaseModel):
    asset_id: str = Field(description="素材唯一 ID。")
    output_dir: str = Field(description="素材处理包输出目录。")
    output_dir_name: str | None = Field(default=None, description="输出目录名，使用原视频文件名安全化后的纯名字。")
    output_folder_name: str | None = Field(default=None, description="更适合人工查找的输出文件夹名。")
    original_filename: str | None = Field(default=None, description="原始视频文件名。")
    message_zh: str | None = Field(default=None, description="中文处理结果说明。")
    metadata: dict[str, Any] = Field(description="视频元信息。")
    scenes: list[dict[str, Any]] = Field(description="镜头分段结果。")
    files: list[str] = Field(description="处理包内生成的文件列表。")


class AssetListItem(BaseModel):
    asset_id: str = Field(description="素材唯一 ID。")
    original_filename: str | None = Field(default=None, description="原始文件名。")
    output_dir: str | None = Field(default=None, description="素材输出目录。")
    output_dir_name: str | None = Field(default=None, description="输出目录名，使用原视频文件名安全化后的纯名字。")
    output_folder_name: str | None = Field(default=None, description="更适合人工查找的输出文件夹名。")
    upload_time: str | None = Field(default=None, description="上传时间。")
    is_analyzed: bool = Field(description="是否已经完成视频基础分析。")
    has_scene_segments: bool = Field(description="是否已经生成镜头分段。")
    has_package: bool = Field(description="是否已经生成素材处理包。")


class GuideResponse(BaseModel):
    title: str = Field(description="指南标题。")
    purpose: str = Field(description="当前项目用途。")
    recommended_test_order: list[str] = Field(description="推荐测试顺序。")
    endpoints: dict[str, str] = Field(description="每个接口的作用说明。")
    output_location: str = Field(description="输出文件所在位置。")
    not_in_scope: list[str] = Field(description="当前版本明确不做的事情。")
    future_integrations: list[str] = Field(description="后续可接入方向。")


class CandidateCreateRequest(BaseModel):
    source_url: str | None = Field(default=None, description="素材来源链接，例如小红书或抖音链接。")
    title: str | None = Field(default=None, description="候选素材标题。")
    author_name: str | None = Field(default=None, description="作者名称。")
    source_platform: str = Field(default="other", description="来源平台，例如 xiaohongshu、douyin、local_upload。")
    selected_region: str = Field(default="unknown", description="目标地区：japan/korea/unknown。")
    selected_style: str = Field(default="unknown", description="内容风格：cute/sexy/youth/commute/premium/other/unknown。")
    tags: list[str] = Field(default_factory=list, description="候选素材标签。")
    reason_for_selection: str | None = Field(default=None, description="人工推荐理由。")
    local_file_path: str | None = Field(default=None, description="本地视频文件路径，可为空。")


class CandidateActionResponse(BaseModel):
    candidate_id: str = Field(description="候选素材 ID。")
    candidate: dict[str, Any] = Field(description="候选素材详情。")
    message_zh: str = Field(description="中文操作结果。")


class CandidateListResponse(BaseModel):
    candidates: list[dict[str, Any]] = Field(description="候选素材列表。")
    message_zh: str = Field(description="中文结果说明。")


class PrepareProcessingResponse(BaseModel):
    candidate_id: str = Field(description="候选素材 ID。")
    can_process: bool = Field(description="是否已经具备进入现有视频处理链路的本地文件条件。")
    local_file_path: str | None = Field(default=None, description="本地文件路径。")
    message_zh: str = Field(description="中文处理提示。")
    next_action_zh: str = Field(description="下一步建议。")


class XiaohongshuSearchRequest(BaseModel):
    keyword: str = Field(description="搜索关键词，例如 韩系穿搭。")
    limit: int = Field(default=5, ge=1, le=20, description="返回候选数量，默认 5。")
    mode: str = Field(default="mock", description="搜索模式：mock/manual/external。")
    selected_region: str = Field(default="unknown", description="目标地区：japan/korea/unknown。")
    selected_style: str = Field(default="unknown", description="内容风格。")


class SourceDiscoveryResponse(BaseModel):
    candidates: list[dict[str, Any]] = Field(description="写入候选池的素材。")
    message_zh: str = Field(description="中文结果说明。")
    mode_used: str = Field(description="实际使用模式。")
    next_action_zh: str = Field(description="下一步建议。")


class WatchCreateRequest(BaseModel):
    source_platform: str = Field(default="xiaohongshu", description="来源平台。")
    author_name: str = Field(description="博主名称。")
    author_profile_url: str | None = Field(default=None, description="博主主页链接。")
    follower_count: int | None = Field(default=None, description="粉丝数。")
    reason_for_watch: str | None = Field(default=None, description="追更原因。")
    selected_region: str = Field(default="unknown", description="适合地区。")
    selected_style: str = Field(default="unknown", description="适合风格。")
    priority: int = Field(default=3, description="优先级，数字越小越优先。")
    enabled: bool = Field(default=True, description="是否启用追更。")
    notes: str | None = Field(default=None, description="备注。")


class WatchlistResponse(BaseModel):
    watchlist: list[dict[str, Any]] = Field(description="追更博主列表。")
    message_zh: str = Field(description="中文结果说明。")
