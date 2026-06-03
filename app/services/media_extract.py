import math
import subprocess
from pathlib import Path

import cv2
import numpy as np

from app.models import SceneSegment, VideoMetadata
from app.services.media_probe import MediaToolError, command_available


def run_ffmpeg(args: list[str]) -> None:
    if not command_available("ffmpeg"):
        raise MediaToolError("未检测到 ffmpeg。请安装 FFmpeg，并确认 ffmpeg 已加入 PATH。")
    completed = subprocess.run(["ffmpeg", "-y", *args], capture_output=True, text=True)
    if completed.returncode != 0:
        raise MediaToolError(completed.stderr.strip() or "ffmpeg 命令执行失败，请检查视频文件和本地 FFmpeg 环境。")


def extract_frame(video_path: Path, output_path: Path, timestamp: float = 0.0) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    run_ffmpeg(
        [
            "-ss",
            str(max(timestamp, 0.0)),
            "-i",
            str(video_path),
            "-frames:v",
            "1",
            "-q:v",
            "2",
            str(output_path),
        ]
    )
    return output_path


def extract_thumbnail(video_path: Path, output_path: Path, metadata: VideoMetadata | None = None) -> Path:
    duration = metadata.duration if metadata and metadata.duration else 0
    timestamp = min(max(duration * 0.1, 0), 2.0) if duration else 0
    return extract_frame(video_path, output_path, timestamp)


def extract_audio_wav(video_path: Path, output_path: Path, metadata: VideoMetadata) -> str:
    if not metadata.has_audio:
        return "No audio stream found; audio.wav was not generated."
    output_path.parent.mkdir(parents=True, exist_ok=True)
    run_ffmpeg(["-i", str(video_path), "-vn", "-acodec", "pcm_s16le", "-ar", "44100", "-ac", "2", str(output_path)])
    return "audio.wav generated."


def create_contact_sheet(scenes: list[SceneSegment], output_path: Path, thumb_width: int = 320) -> Path:
    images: list[np.ndarray] = []
    for scene in scenes:
        if not scene.keyframe_path:
            continue
        image = cv2.imread(scene.keyframe_path)
        if image is None:
            continue
        h, w = image.shape[:2]
        ratio = thumb_width / max(w, 1)
        resized = cv2.resize(image, (thumb_width, max(int(h * ratio), 1)))
        label = f"#{scene.scene_id} {scene.start_time:.1f}-{scene.end_time:.1f}s"
        cv2.rectangle(resized, (0, 0), (thumb_width, 28), (0, 0, 0), -1)
        cv2.putText(resized, label, (8, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1, cv2.LINE_AA)
        images.append(resized)

    if not images:
        raise MediaToolError("没有可用关键帧，无法生成 scene_contact_sheet.jpg。")

    cell_h = max(img.shape[0] for img in images)
    cols = min(3, len(images))
    rows = math.ceil(len(images) / cols)
    sheet = np.full((rows * cell_h, cols * thumb_width, 3), 245, dtype=np.uint8)

    for idx, img in enumerate(images):
        row, col = divmod(idx, cols)
        y = row * cell_h
        x = col * thumb_width
        sheet[y : y + img.shape[0], x : x + img.shape[1]] = img

    output_path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(output_path), sheet)
    return output_path
