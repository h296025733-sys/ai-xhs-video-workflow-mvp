import os
import shutil
import subprocess
import sys
from pathlib import Path

from app.quick_bgm.media import ffmpeg_path
from app.quick_bgm.store import BGM_LIBRARY_DIR, parse_bgm_filename, safe_filename


AUDIO_EXTENSIONS = {".mp3", ".m4a", ".wav", ".aac", ".flac", ".opus", ".webm"}


def search_and_download_bgm(query: str, prefer_source: str | None = None) -> dict:
    mode = (prefer_source or os.getenv("BGM_SEARCH_DOWNLOAD_MODE") or "disabled").strip().lower()
    if mode in {"", "disabled", "off"}:
        return {
            "ok": False,
            "message_zh": "在线搜索下载暂未启用，请先使用本地上传 BGM。",
            "failure_reason": "BGM_SEARCH_DOWNLOAD_MODE 未启用。",
        }

    if mode == "spotdl":
        return _download_with_spotdl(query)
    if mode in {"ytdlp", "yt-dlp"}:
        return _download_with_ytdlp(query)

    return {
        "ok": False,
        "message_zh": "在线搜索下载暂未成功，请先使用本地上传 BGM。",
        "failure_reason": f"不支持的 BGM_SEARCH_DOWNLOAD_MODE：{mode}",
    }


def _binary(env_name: str, default_name: str) -> list[str] | None:
    configured = os.getenv(env_name)
    if configured:
        return [configured]
    found = shutil.which(default_name)
    if found:
        return [found]
    if default_name == "yt-dlp":
        try:
            import yt_dlp  # noqa: F401

            return [sys.executable, "-m", "yt_dlp"]
        except Exception:
            return None
    if default_name == "spotdl":
        try:
            import spotdl  # noqa: F401

            return [sys.executable, "-m", "spotdl"]
        except Exception:
            return None
    return None


def _download_dir(prefix: str, query: str) -> Path:
    safe_query = safe_filename(query, "bgm_query")
    target = BGM_LIBRARY_DIR / "search_downloads" / f"{prefix}__{safe_query[:60]}"
    target.mkdir(parents=True, exist_ok=True)
    return target


def _latest_audio_file(target_dir: Path) -> Path | None:
    files = [path for path in target_dir.rglob("*") if path.is_file() and path.suffix.lower() in AUDIO_EXTENSIONS]
    return max(files, key=lambda path: path.stat().st_mtime) if files else None


def _download_with_spotdl(query: str) -> dict:
    binary = _binary("SPOTDL_BIN", "spotdl")
    if not binary:
        return {
            "ok": False,
            "message_zh": "在线搜索下载暂未成功，请先使用本地上传 BGM。",
            "failure_reason": "spotDL 未安装或未加入 PATH。",
        }
    target_dir = _download_dir("spotdl", query)
    cmd = binary + ["download", query, "--output", str(target_dir)]
    completed = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=240)
    if completed.returncode != 0:
        return {
            "ok": False,
            "message_zh": "在线搜索下载暂未成功，请先使用本地上传 BGM。",
            "failure_reason": (completed.stderr or completed.stdout or "spotDL 下载失败。").strip()[-500:],
        }
    audio_path = _latest_audio_file(target_dir)
    if not audio_path:
        return {
            "ok": False,
            "message_zh": "在线搜索下载暂未成功，请先使用本地上传 BGM。",
            "failure_reason": "spotDL 执行完成，但没有找到下载后的音频文件。",
        }
    song_name, artist_name = parse_bgm_filename(audio_path.name)
    return {
        "ok": True,
        "local_file_path": str(audio_path),
        "original_filename": audio_path.name,
        "song_name": song_name,
        "artist_name": artist_name,
        "source_type": "search_download",
        "source_query": query,
        "source_url": None,
        "message_zh": "已搜索并下载最相关 BGM。",
    }


def _looks_like_url(value: str) -> bool:
    return value.startswith(("http://", "https://"))


def _download_with_ytdlp(query: str) -> dict:
    binary = _binary("YTDLP_BIN", "yt-dlp")
    if not binary:
        return {
            "ok": False,
            "message_zh": "在线搜索下载暂未成功，请先使用本地上传 BGM。",
            "failure_reason": "yt-dlp 未安装或未加入 PATH。",
        }
    target_dir = _download_dir("ytdlp", query)
    target = query if _looks_like_url(query) else f"ytsearch1:{query}"
    cmd = list(binary)
    ffmpeg = ffmpeg_path()
    if ffmpeg:
        cmd.extend(["--ffmpeg-location", str(ffmpeg)])
    cmd.extend([
        "--no-playlist",
        "-x",
        "--audio-format",
        "mp3",
        "--audio-quality",
        "0",
        "--match-filter",
        "duration < 600",
        "--max-filesize",
        "20M",
        "-o",
        str(target_dir / "%(title)s - %(uploader)s.%(ext)s"),
        target,
    ])
    completed = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=240)
    if completed.returncode != 0:
        return {
            "ok": False,
            "message_zh": "在线搜索下载暂未成功，请先使用本地上传 BGM。",
            "failure_reason": (completed.stderr or completed.stdout or "yt-dlp 下载失败。").strip()[-500:],
        }
    audio_path = _latest_audio_file(target_dir)
    if not audio_path:
        return {
            "ok": False,
            "message_zh": "在线搜索下载暂未成功，请先使用本地上传 BGM。",
            "failure_reason": "yt-dlp 执行完成，但没有找到下载后的音频文件。",
        }
    song_name, artist_name = parse_bgm_filename(audio_path.name)
    return {
        "ok": True,
        "local_file_path": str(audio_path),
        "original_filename": audio_path.name,
        "song_name": song_name,
        "artist_name": artist_name,
        "source_type": "search_download",
        "source_query": query,
        "source_url": query if _looks_like_url(query) else None,
        "message_zh": "已搜索并下载最相关 BGM。",
    }
