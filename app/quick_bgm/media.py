import os
import re
import shutil
import subprocess
from pathlib import Path

from app.quick_bgm.store import QUICK_OUTPUTS_DIR, safe_stem, update_job


class QuickBgmMediaError(RuntimeError):
    pass


def command_path(name: str, env_name: str) -> str | None:
    configured = os.getenv(env_name)
    if configured:
        return configured
    return shutil.which(name)


def ffmpeg_path() -> str | None:
    existing = command_path("ffmpeg", "FFMPEG_PATH")
    if existing:
        return existing
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None



def ffprobe_path() -> str | None:
    existing = command_path("ffprobe", "FFPROBE_PATH")
    if existing:
        return existing
    ffmpeg = ffmpeg_path()
    if ffmpeg:
        candidate = Path(ffmpeg).with_name("ffprobe.exe" if os.name == "nt" else "ffprobe")
        if candidate.exists():
            return str(candidate)
    return shutil.which("ffprobe")


def media_duration_seconds(path: str | Path | None) -> float | None:
    """读取音频/视频时长，失败时返回 None，避免影响主流程。"""
    if not path:
        return None
    source = Path(path)
    if not source.exists():
        return None
    ffprobe = ffprobe_path()
    if not ffprobe:
        return _media_duration_by_ffmpeg(source)
    cmd = [
        ffprobe,
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(source),
    ]
    try:
        completed = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
    except Exception:
        return None
    if completed.returncode != 0:
        return _media_duration_by_ffmpeg(source)
    try:
        duration = float((completed.stdout or "").strip())
    except ValueError:
        return _media_duration_by_ffmpeg(source)
    return round(duration, 3) if duration >= 0 else None


def _media_duration_by_ffmpeg(source: Path) -> float | None:
    ffmpeg = ffmpeg_path()
    if not ffmpeg:
        return None
    cmd = [ffmpeg, "-hide_banner", "-i", str(source)]
    try:
        completed = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
    except Exception:
        return None
    text = (completed.stderr or "") + "\n" + (completed.stdout or "")
    match = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", text)
    if not match:
        return None
    hours = int(match.group(1))
    minutes = int(match.group(2))
    seconds = float(match.group(3))
    duration = hours * 3600 + minutes * 60 + seconds
    return round(duration, 3) if duration >= 0 else None


def extract_video_cover(source: str | Path | None, output_path: str | Path, at_seconds: float = 0.1) -> str | None:
    if not source:
        return None
    source_path = Path(source)
    if not source_path.exists():
        return None
    ffmpeg = ffmpeg_path()
    if not ffmpeg:
        return None
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        ffmpeg,
        "-y",
        "-ss",
        str(max(float(at_seconds or 0), 0)),
        "-i",
        str(source_path),
        "-frames:v",
        "1",
        "-q:v",
        "2",
        str(target),
    ]
    try:
        completed = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
    except Exception:
        return None
    if completed.returncode != 0 or not target.exists():
        return None
    return str(target)


def run_quick_bgm_job(job: dict, bgm: dict | None) -> dict:
    source = Path(job.get("original_video_path") or "")
    if not source.exists():
        raise QuickBgmMediaError("原视频文件不存在，请重新上传视频。")

    output_dir = QUICK_OUTPUTS_DIR / job["job_id"]
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{safe_stem(job.get('original_filename'), 'video')}__换BGM__{job['updated_at'].replace(':', '').replace('-', '')}.mp4"

    if not job.get("replace_audio"):
        shutil.copy2(source, output_path)
        cover_path = output_dir / f"{safe_stem(job.get('original_filename'), 'video')}__cover.jpg"
        cover = extract_video_cover(output_path, cover_path) or job.get("cover_image_path")
        return update_job(
            job["job_id"],
            output_video_path=str(output_path),
            cover_image_path=cover,
            status="done",
            message_zh="已保留原声，未替换 BGM。",
            failure_reason=None,
        )

    if not bgm:
        raise QuickBgmMediaError("请先选择一个 BGM。")
    bgm_path = Path(bgm.get("local_file_path") or "")
    if not bgm_path.exists():
        raise QuickBgmMediaError("BGM 文件不存在，请重新上传 BGM。")

    ffmpeg = ffmpeg_path()
    if not ffmpeg:
        raise QuickBgmMediaError("未检测到 ffmpeg，无法生成换 BGM 视频。")

    bgm_start_seconds = max(float(job.get("bgm_start_seconds") or 0), 0)
    cmd = [
        ffmpeg,
        "-y",
        "-i",
        str(source),
        "-stream_loop",
        "-1",
    ]
    if bgm_start_seconds > 0:
        cmd.extend(["-ss", str(bgm_start_seconds)])
    cmd.extend(
        [
        "-i",
        str(bgm_path),
        "-map",
        "0:v:0",
        "-map",
        "1:a:0",
        "-c:v",
        "copy",
        "-c:a",
        "aac",
        "-shortest",
        "-movflags",
        "+faststart",
        str(output_path),
        ]
    )
    completed = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if completed.returncode != 0:
        fallback = cmd.copy()
        fallback[fallback.index("copy")] = "libx264"
        completed = subprocess.run(fallback, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if completed.returncode != 0:
        raise QuickBgmMediaError((completed.stderr or completed.stdout or "ffmpeg 处理失败。").strip()[-800:])

    cover_path = output_dir / f"{safe_stem(job.get('original_filename'), 'video')}__cover.jpg"
    cover = extract_video_cover(output_path, cover_path) or job.get("cover_image_path")
    return update_job(
        job["job_id"],
        output_video_path=str(output_path),
        cover_image_path=cover,
        status="done",
        message_zh="换 BGM 视频已生成，可以预览或下载。",
        failure_reason=None,
    )
