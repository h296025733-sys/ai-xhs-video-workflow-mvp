import json
import os
import subprocess
from pathlib import Path


def import_xiaohongshu_video(source_url: str) -> dict:
    mode = (os.getenv("XHS_DOWNLOAD_MODE") or "disabled").strip().lower()
    if mode in {"", "disabled", "off"}:
        return {
            "ok": False,
            "message_zh": "小红书链接解析服务暂未配置，请先人工上传视频。",
            "failure_reason": "XHS_DOWNLOAD_MODE 未配置。",
        }

    if mode == "api":
        return _import_by_api(source_url)
    if mode == "cli":
        return _import_by_cli(source_url)

    return {
        "ok": False,
        "message_zh": "小红书链接解析模式不支持，请先人工上传视频。",
        "failure_reason": f"不支持的 XHS_DOWNLOAD_MODE：{mode}",
    }


def _import_by_api(source_url: str) -> dict:
    api_base_url = (os.getenv("XHS_DOWNLOADER_API_BASE_URL") or "").rstrip("/")
    if not api_base_url:
        return {
            "ok": False,
            "message_zh": "小红书链接解析服务暂未配置，请先人工上传视频。",
            "failure_reason": "XHS_DOWNLOADER_API_BASE_URL 未配置。",
        }
    try:
        import httpx

        response = httpx.post(f"{api_base_url}/download", json={"url": source_url}, timeout=60)
        response.raise_for_status()
        data = response.json()
    except Exception as exc:
        return {"ok": False, "message_zh": "小红书链接解析失败，请先人工上传视频。", "failure_reason": str(exc)}

    local_path = data.get("local_file_path") or data.get("path") or data.get("video_path")
    if local_path and Path(local_path).exists():
        return {"ok": True, "local_file_path": local_path, "message_zh": "小红书视频已解析并保存到本地。"}
    return {
        "ok": False,
        "message_zh": "小红书链接解析失败，请先人工上传视频。",
        "failure_reason": "解析服务没有返回可用的本地视频路径。",
    }


def _import_by_cli(source_url: str) -> dict:
    command = os.getenv("XHS_DOWNLOADER_CMD")
    if not command:
        return {
            "ok": False,
            "message_zh": "小红书链接解析服务暂未配置，请先人工上传视频。",
            "failure_reason": "XHS_DOWNLOADER_CMD 未配置。",
        }
    try:
        completed = subprocess.run(
            [command, source_url],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
            check=False,
        )
    except Exception as exc:
        return {"ok": False, "message_zh": "小红书链接解析失败，请先人工上传视频。", "failure_reason": str(exc)}

    if completed.returncode != 0:
        return {
            "ok": False,
            "message_zh": "小红书链接解析失败，请先人工上传视频。",
            "failure_reason": completed.stderr.strip() or "命令执行失败。",
        }

    output = completed.stdout.strip()
    local_path = None
    try:
        data = json.loads(output)
        local_path = data.get("local_file_path") or data.get("path") or data.get("video_path")
    except json.JSONDecodeError:
        local_path = output.splitlines()[-1] if output else None

    if local_path and Path(local_path).exists():
        return {"ok": True, "local_file_path": local_path, "message_zh": "小红书视频已解析并保存到本地。"}
    return {
        "ok": False,
        "message_zh": "小红书链接解析失败，请先人工上传视频。",
        "failure_reason": "命令没有返回可用的本地视频路径。",
    }
