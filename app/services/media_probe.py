import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from app.models import VideoMetadata


class MediaToolError(RuntimeError):
    pass


def command_available(command: str) -> bool:
    return shutil.which(command) is not None


def python_version() -> str:
    return sys.version.split()[0]


def scenedetect_available() -> bool:
    try:
        import scenedetect  # noqa: F401

        return True
    except Exception:
        return False


def _parse_frame_rate(value: str | None) -> float | None:
    if not value:
        return None
    try:
        if "/" in value:
            num, den = value.split("/", 1)
            den_float = float(den)
            if den_float == 0:
                return None
            return round(float(num) / den_float, 3)
        return round(float(value), 3)
    except (TypeError, ValueError):
        return None


def ffprobe_json(video_path: Path) -> dict[str, Any]:
    if not command_available("ffprobe"):
        raise MediaToolError("未检测到 ffprobe。请安装 FFmpeg，并确认 ffprobe 已加入 PATH。")
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(video_path),
    ]
    completed = subprocess.run(cmd, capture_output=True, text=True)
    if completed.returncode != 0:
        raise MediaToolError(completed.stderr.strip() or "ffprobe 读取视频失败，请确认文件格式是否受支持。")
    return json.loads(completed.stdout)


def probe_video(video_path: Path, original_filename: str | None = None) -> VideoMetadata:
    data = ffprobe_json(video_path)
    streams = data.get("streams", [])
    video_stream = next((s for s in streams if s.get("codec_type") == "video"), {})
    audio_stream = next((s for s in streams if s.get("codec_type") == "audio"), {})
    fmt = data.get("format", {})
    duration = video_stream.get("duration") or fmt.get("duration")
    return VideoMetadata(
        filename=original_filename or video_path.name,
        file_size_bytes=video_path.stat().st_size,
        duration=round(float(duration), 3) if duration is not None else None,
        width=video_stream.get("width"),
        height=video_stream.get("height"),
        frame_rate=_parse_frame_rate(video_stream.get("avg_frame_rate") or video_stream.get("r_frame_rate")),
        has_audio=bool(audio_stream),
        video_codec=video_stream.get("codec_name"),
        audio_codec=audio_stream.get("codec_name"),
        raw_probe=data,
    )
