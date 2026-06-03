from pathlib import Path

from app.models import SceneSegment, VideoMetadata
from app.services.media_extract import create_contact_sheet, extract_frame
from app.services.media_probe import MediaToolError, command_available, scenedetect_available


def _scene_output_dir(output_dir: Path) -> Path:
    path = output_dir / "keyframes"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _detect_with_pyscenedetect(video_path: Path, duration: float | None) -> list[tuple[float, float]]:
    from scenedetect import ContentDetector, detect

    scene_list = detect(str(video_path), ContentDetector(threshold=27.0))
    segments: list[tuple[float, float]] = []
    for start, end in scene_list:
        start_sec = round(start.get_seconds(), 3)
        end_sec = round(end.get_seconds(), 3)
        if end_sec > start_sec:
            segments.append((start_sec, end_sec))
    if not segments and duration:
        segments.append((0.0, round(duration, 3)))
    return segments


def _detect_with_ffmpeg_fallback(duration: float | None) -> list[tuple[float, float]]:
    if not duration or duration <= 0:
        return [(0.0, 0.1)]
    if duration <= 4:
        return [(0.0, round(duration, 3))]
    # Fallback chunks are only review anchors, not edit cut points.
    step = 4.0
    segments: list[tuple[float, float]] = []
    current = 0.0
    while current < duration:
        end = min(current + step, duration)
        segments.append((round(current, 3), round(end, 3)))
        current = end
    return segments


def scene_quality(duration: float) -> tuple[bool, str, str]:
    if duration < 0.5:
        return True, "too_short", "片段过短，疑似尾帧、黑帧、转场残留或无效片段，不建议作为独立剪辑片段。"
    if duration < 1.2:
        return False, "short_but_possible", "短镜头，可能是图集轮播或快节奏剪辑中的有效画面，需人工确认。"
    if duration >= 5:
        return False, "long_scene", "长镜头，建议查看内部采样图，不要只依赖单张关键帧。"
    return False, "normal", "常规镜头片段。"


def detect_scenes(video_path: Path, output_dir: Path, metadata: VideoMetadata) -> tuple[list[SceneSegment], Path]:
    if not command_available("ffmpeg"):
        raise MediaToolError("提取镜头关键帧需要 ffmpeg，但当前 PATH 中未检测到 ffmpeg。")

    used_fallback = False
    if scenedetect_available():
        try:
            raw_segments = _detect_with_pyscenedetect(video_path, metadata.duration)
        except Exception:
            used_fallback = True
            raw_segments = _detect_with_ffmpeg_fallback(metadata.duration)
    else:
        used_fallback = True
        raw_segments = _detect_with_ffmpeg_fallback(metadata.duration)

    keyframe_dir = _scene_output_dir(output_dir)
    scenes: list[SceneSegment] = []
    for idx, (start, end) in enumerate(raw_segments, start=1):
        duration = round(max(end - start, 0), 3)
        midpoint = start + max((end - start) / 2, 0)
        keyframe = keyframe_dir / f"scene_{idx:03d}.jpg"
        extract_frame(video_path, keyframe, midpoint)
        is_too_short, quality_type, quality_note_zh = scene_quality(duration)
        notes = (
            "使用兜底时间段生成，仅作为人工预览锚点，不应直接视为自动剪辑点。"
            if used_fallback
            else "已检测到镜头边界；剪辑前请人工确认服装动作、细节展示和画面质量。"
        )
        scenes.append(
            SceneSegment(
                scene_id=idx,
                start_time=round(start, 3),
                end_time=round(end, 3),
                duration=duration,
                keyframe_path=str(keyframe),
                notes=notes,
                is_too_short=is_too_short,
                quality_type=quality_type,
                quality_note_zh=quality_note_zh,
            )
        )

    contact_sheet = create_contact_sheet(scenes, output_dir / "scene_contact_sheet.jpg")
    return scenes, contact_sheet
