import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

import httpx

from app.quick_bgm.store import QUICK_BGM_DIR, make_batch_item


XHS_CREATOR_DOWNLOADS_DIR = QUICK_BGM_DIR / "xhs_creator_downloads"


def import_creator_items(creator_home_url: str, limit: int = 10, mode: str = "auto") -> dict:
    limit = min(max(int(limit or 10), 1), 10)
    selected_mode = (mode or os.getenv("XHS_CREATOR_IMPORT_MODE") or "auto").strip().lower()

    if selected_mode == "disabled":
        return _failed("自动抓取服务暂未配置，可先使用人工粘贴作品链接或上传视频。", "XHS_CREATOR_IMPORT_MODE=disabled。")
    if selected_mode == "manual_links":
        return _failed("请粘贴具体作品链接后再批量处理。", "manual_links 模式不能从博主主页自动获取作品列表。")
    if selected_mode == "xhs_downloader_api":
        return _import_by_xhs_downloader_api(creator_home_url, limit)
    if selected_mode == "xhs_downloader_cli":
        return _import_by_xhs_downloader_cli(creator_home_url, limit)
    if selected_mode == "xhs_mcp":
        return _import_by_xhs_mcp(creator_home_url, limit)

    if selected_mode == "auto":
        reasons = []
        if os.getenv("XHS_DOWNLOADER_API_BASE_URL"):
            result = _import_by_xhs_downloader_api(creator_home_url, limit)
            if result.get("ok"):
                return result
            reasons.append(result.get("failure_reason"))
        if os.getenv("XHS_DOWNLOADER_CLI_PATH") or os.getenv("XHS_DOWNLOADER_PROJECT_DIR"):
            result = _import_by_xhs_downloader_cli(creator_home_url, limit)
            if result.get("ok"):
                return result
            reasons.append(result.get("failure_reason"))
        if os.getenv("XHS_MCP_BASE_URL"):
            result = _import_by_xhs_mcp(creator_home_url, limit)
            if result.get("ok"):
                return result
            reasons.append(result.get("failure_reason"))
        direct = _import_by_direct_profile_html(creator_home_url, limit)
        if direct.get("ok"):
            return direct
        reasons.append(direct.get("failure_reason"))
        return _failed(
            "自动抓取服务暂未配置，可先使用人工粘贴作品链接或上传视频。",
            "；".join(str(reason) for reason in reasons if reason)
            or "未配置 XHS-Downloader API/CLI 或 xiaohongshu-mcp；直接访问主页也未提取到作品列表，通常需要 Cookie/登录态。",
        )

    return _failed("小红书导入模式不支持，可先使用人工粘贴作品链接。", f"不支持的模式：{selected_mode}")



def _post_xhs_downloader_detail(api_base: str, payload: dict, timeout: int = 90, retries: int = 2) -> dict:
    """稳定调用本机 XHS-Downloader /xhs/detail。

    之前在项目进程里直接用 httpx 调 127.0.0.1:5556，偶发 WinError 10054；
    PowerShell 直接调用却正常。这里改用标准库 urllib，并显式 Connection: close，
    同时做少量重试，降低本地连接被重置对页面预览的影响。
    """
    url = f"{api_base.rstrip('/')}/xhs/detail"
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    last_error: Exception | None = None

    for attempt in range(retries + 1):
        try:
            req = Request(
                url,
                data=body,
                method="POST",
                headers={
                    "Content-Type": "application/json; charset=utf-8",
                    "Accept": "application/json",
                    "Connection": "close",
                    "User-Agent": "quick-bgm-workbench/1.0",
                },
            )
            with urlopen(req, timeout=timeout) as resp:
                raw = resp.read()
                text = raw.decode("utf-8", errors="replace")
                return json.loads(text)
        except HTTPError as exc:
            # HTTP 502/500 可能是 XHS-Downloader 内部一次请求失败，允许重试。
            last_error = exc
            if exc.code not in {500, 502, 503, 504}:
                break
        except (URLError, ConnectionResetError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            last_error = exc

        if attempt < retries:
            time.sleep(1.2 + attempt * 1.3)

    if last_error:
        raise last_error
    raise RuntimeError("XHS-Downloader API 未返回数据。")


def _friendly_api_error(exc: Exception) -> str:
    text = str(exc)
    if isinstance(exc, HTTPError):
        return f"XHS-Downloader 返回 HTTP {exc.code}，可能是小红书请求被阻断、Cookie 失效或本地服务内部错误。"
    if "10054" in text or "Connection reset" in text or "远程主机强迫关闭" in text:
        return "本地 5556 服务连接被重置。请保持 XHS-Downloader 只启动一个实例，稍后单条重试。"
    if "Connection refused" in text or "actively refused" in text or "无法连接" in text:
        return "XHS-Downloader 5556 服务未启动或已退出。"
    if "timed out" in text or "timeout" in text.lower():
        return "XHS-Downloader 响应超时，可能是网络慢或小红书侧风控。"
    return text


def _first_present(data: dict, keys: list[str]) -> str | int | float | None:
    for key in keys:
        value = data.get(key)
        if value not in (None, ""):
            return value
    return None


def _metrics_from_note(note: dict) -> dict:
    return {
        "liked_count": _first_present(note, ["点赞数量", "点赞数", "liked_count", "likes"]),
        "collected_count": _first_present(note, ["收藏数量", "收藏数", "collected_count", "collects"]),
        "comment_count": _first_present(note, ["评论数量", "评论数", "comment_count", "comments"]),
    }


def _deep_text_contains_video_marker(value) -> bool:
    """尽量宽松地判断 XHS-Downloader 返回内容里是否包含视频线索。"""
    if value is None:
        return False
    if isinstance(value, str):
        t = value.lower()
        return (
            ".mp4" in t
            or "video" in t
            or "stream" in t
            or "m3u8" in t
            or "视频" in value
            or "动态" in value
        )
    if isinstance(value, dict):
        for k, v in value.items():
            key = str(k).lower()
            if any(x in key for x in ["video", "stream", "mp4", "视频", "下载地址", "动态地址"]):
                return True
            if _deep_text_contains_video_marker(v):
                return True
        return False
    if isinstance(value, list):
        return any(_deep_text_contains_video_marker(x) for x in value)
    return False


def _deep_first_video_url(value) -> str:
    """从任意嵌套结构里尽量找第一个视频 URL。"""
    if value is None:
        return ""
    if isinstance(value, str):
        t = value.strip()
        low = t.lower()
        if t.startswith("http") and (".mp4" in low or "video" in low or "stream" in low or "m3u8" in low):
            return t
        return ""
    if isinstance(value, dict):
        for v in value.values():
            found = _deep_first_video_url(v)
            if found:
                return found
        return ""
    if isinstance(value, list):
        for x in value:
            found = _deep_first_video_url(x)
            if found:
                return found
        return ""
    return ""


def preview_note_link(note_url: str) -> dict:
    """只读取作品信息，不下载文件，用于页面候选素材预览。"""
    api_base = (os.getenv("XHS_DOWNLOADER_API_BASE_URL") or "").rstrip("/")
    note_id = _note_id_from_url(note_url)
    fallback = {
        "ok": False,
        "note_url": note_url,
        "note_id": note_id,
        "title": note_id or "小红书作品",
        "author": "",
        "note_type_zh": "未知",
        "is_video": False,
        "status_zh": "需要人工确认",
        "failure_reason": "XHS-Downloader API 未配置，无法预览作品类型。",
    }
    if not api_base:
        return fallback

    payload = {"url": note_url, "download": False, "skip": False}
    cookie = os.getenv("XHS_COOKIE")
    if cookie:
        payload["cookie"] = cookie
    try:
        data = _post_xhs_downloader_detail(api_base, payload, timeout=90)
    except Exception as exc:
        fallback["failure_reason"] = f"作品预览失败：{_friendly_api_error(exc)}"
        return fallback

    note = data.get("data") if isinstance(data, dict) else None
    if not isinstance(note, dict):
        fallback["failure_reason"] = data.get("message") if isinstance(data, dict) else "XHS-Downloader 未返回作品详情。"
        return fallback

    note_type = str(note.get("作品类型") or note.get("type") or note.get("note_type") or "未知")
    download_urls = (
        note.get("下载地址")
        or note.get("视频下载地址")
        or note.get("video_download_url")
        or note.get("video_url")
        or note.get("video_urls")
        or note.get("video")
        or []
    )
    live_urls = note.get("动图地址") or note.get("live_urls") or []
    deep_video_url = _deep_first_video_url(note)
    is_video = (
        "视频" in note_type
        or "video" in note_type.lower()
        or any(".mp4" in str(url).lower() or "stream" in str(url).lower() for url in (download_urls if isinstance(download_urls, list) else [download_urls]))
        or bool(deep_video_url)
        or _deep_text_contains_video_marker(note)
    )
    title = note.get("作品标题") or note.get("标题") or note_id or "小红书作品"
    author = note.get("作者昵称") or note.get("作者") or ""
    preview_url = _first_url([note.get("封面地址"), note.get("封面"), note.get("cover"), note.get("cover_url")] + list(live_urls or []) + list(download_urls or []), want_video=False)
    preview_video_url = _first_url(download_urls if isinstance(download_urls, list) else [download_urls], want_video=True) or deep_video_url
    metrics = _metrics_from_note(note)
    return {
        "ok": True,
        "note_url": note_url,
        "note_id": note.get("作品ID") or note_id,
        "title": title,
        "author": author,
        "publish_time": _first_present(note, ["发布时间", "time", "publish_time"]),
        "note_type_zh": "视频" if is_video else (note_type if note_type != "未知" else "图文/未知"),
        "is_video": bool(is_video),
        "status_zh": "可处理" if is_video else "当前不处理",
        "failure_reason": "" if is_video else "图文作品没有视频轨道，当前不进入换 BGM 流程。",
        "preview_url": preview_url or "",
        "preview_video_url": preview_video_url or "",
        "video_download_url": preview_video_url or "",
        "liked_count": metrics["liked_count"],
        "collected_count": metrics["collected_count"],
        "comment_count": metrics["comment_count"],
        "metrics": metrics,
        "raw_message": data.get("message") if isinstance(data, dict) else "",
    }

def download_note_video(note_url: str, download_dir: Path | None = None) -> dict:
    download_dir = download_dir or XHS_CREATOR_DOWNLOADS_DIR
    download_dir.mkdir(parents=True, exist_ok=True)
    api_base = (os.getenv("XHS_DOWNLOADER_API_BASE_URL") or "").rstrip("/")
    if api_base:
        result = _download_note_by_api(note_url, download_dir)
        if result.get("ok"):
            return result
    if os.getenv("XHS_DOWNLOADER_CLI_PATH") or os.getenv("XHS_DOWNLOADER_PROJECT_DIR"):
        result = _download_note_by_cli(note_url, download_dir)
        if result.get("ok"):
            return result
    return {
        "ok": False,
        "message_zh": "作品下载失败，需要人工处理。",
        "failure_reason": "XHS-Downloader API/CLI 未配置，无法下载作品视频。",
    }


def _failed(message_zh: str, failure_reason: str) -> dict:
    return {"ok": False, "items": [], "message_zh": message_zh, "failure_reason": failure_reason}


def _import_by_xhs_downloader_api(creator_home_url: str, limit: int) -> dict:
    api_base = (os.getenv("XHS_DOWNLOADER_API_BASE_URL") or "").rstrip("/")
    if not api_base:
        return _failed("XHS-Downloader API 未配置，可先使用人工粘贴作品链接。", "XHS_DOWNLOADER_API_BASE_URL 未配置。")
    return _failed(
        "主页作品列表没拿到，可先使用人工粘贴作品链接。",
        "已核对 XHS-Downloader 当前 API：只确认提供 / 和 /xhs/detail；/xhs/detail 需要单条作品链接，不支持直接传博主主页获取最近作品。",
    )


def _import_by_xhs_downloader_cli(creator_home_url: str, limit: int) -> dict:
    command = _cli_command()
    if not command:
        return _failed("XHS-Downloader CLI 未配置，可先使用人工粘贴作品链接。", "XHS_DOWNLOADER_CLI_PATH / XHS_DOWNLOADER_PROJECT_DIR 未配置。")
    if "/user/profile/" in creator_home_url:
        return _failed(
            "主页作品列表没拿到，可先使用人工粘贴作品链接。",
            "XHS-Downloader README 将账号发布作品链接提取放在油猴脚本能力里；当前未发现稳定 CLI 主页列表接口。",
        )
    try:
        completed = subprocess.run(
            command + [creator_home_url],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=180,
            check=False,
        )
    except Exception as exc:
        return _failed("主页作品列表没拿到，可先使用人工粘贴作品链接。", f"XHS-Downloader CLI 启动失败：{exc}")
    if completed.returncode != 0:
        return _failed("主页作品列表没拿到，可先使用人工粘贴作品链接。", f"XHS-Downloader CLI 执行失败：{completed.stderr.strip() or completed.stdout.strip()}")
    try:
        data = json.loads(completed.stdout)
    except json.JSONDecodeError:
        data = {"raw_text": completed.stdout}
    items = _normalize_items(data, limit)
    if not items:
        return _failed("主页作品列表没拿到，可先使用人工粘贴作品链接。", "XHS-Downloader CLI 未输出可解析的作品列表。")
    return {"ok": True, "items": items, "message_zh": "已通过 XHS-Downloader CLI 获取作品列表。"}


def _import_by_xhs_mcp(creator_home_url: str, limit: int) -> dict:
    base = (os.getenv("XHS_MCP_BASE_URL") or "").rstrip("/")
    if not base:
        return _failed("xiaohongshu-mcp 未配置，可先使用人工粘贴作品链接。", "XHS_MCP_BASE_URL 未配置。")
    try:
        response = httpx.post(f"{base}/creator/notes", json={"url": creator_home_url, "limit": limit}, timeout=90)
        response.raise_for_status()
        data = response.json()
    except Exception as exc:
        return _failed("主页作品列表没拿到，可先使用人工粘贴作品链接。", f"xiaohongshu-mcp 调用失败，可能需要 API Key/Cookie/服务启动：{exc}")
    items = _normalize_items(data, limit)
    if not items:
        return _failed("主页作品列表没拿到，可先使用人工粘贴作品链接。", "xiaohongshu-mcp 返回作品列表为空。")
    return {"ok": True, "items": items, "message_zh": "已通过 xiaohongshu-mcp 获取作品列表。"}


def _import_by_direct_profile_html(creator_home_url: str, limit: int) -> dict:
    headers = {
        "user-agent": "Mozilla/5.0",
        "referer": "https://www.xiaohongshu.com/",
    }
    cookie = os.getenv("XHS_COOKIE")
    if cookie:
        headers["cookie"] = cookie
    try:
        response = httpx.get(creator_home_url, headers=headers, follow_redirects=True, timeout=30)
    except Exception as exc:
        return _failed("主页作品列表没拿到，可先使用人工粘贴作品链接。", f"直接访问主页失败：{exc}")
    text = response.text
    if response.status_code >= 400:
        return _failed("主页作品列表没拿到，可先使用人工粘贴作品链接。", f"直接访问主页 HTTP {response.status_code}，可能需要 Cookie/登录态。")

    note_ids = []
    for pattern in (r"/explore/([0-9a-zA-Z]+)", r'"noteId"\s*:\s*"([0-9a-zA-Z]+)"', r'"note_id"\s*:\s*"([0-9a-zA-Z]+)"'):
        for note_id in re.findall(pattern, text):
            if note_id not in note_ids:
                note_ids.append(note_id)
            if len(note_ids) >= limit:
                break
        if len(note_ids) >= limit:
            break
    if not note_ids:
        reason = "直接访问主页未提取到作品列表"
        if not cookie:
            reason += "，当前未提供 XHS_COOKIE，可能需要登录态。"
        return _failed("主页作品列表没拿到，可先使用人工粘贴作品链接。", reason)
    items = [
        make_batch_item(
            note_id=note_id,
            note_url=f"https://www.xiaohongshu.com/explore/{note_id}",
            title=f"小红书作品 {index + 1}",
            is_video=True,
            status="need_manual",
            failure_reason="已提取作品链接，但未配置下载工具，需人工确认或配置 XHS-Downloader。",
        )
        for index, note_id in enumerate(note_ids[:limit])
    ]
    return {"ok": True, "items": items, "message_zh": "已从主页 HTML 提取到疑似作品链接，但仍需要下载工具。"}


def _normalize_items(data: dict | list, limit: int) -> list[dict]:
    raw_items = data if isinstance(data, list) else (
        data.get("items")
        or data.get("notes")
        or data.get("data", {}).get("items")
        or data.get("data", {}).get("notes")
        or []
    )
    items = []
    for raw in raw_items[:limit]:
        if not isinstance(raw, dict):
            continue
        note_url = raw.get("note_url") or raw.get("url") or raw.get("share_url")
        note_id = raw.get("note_id") or raw.get("id") or _note_id_from_url(note_url)
        is_video = bool(raw.get("is_video", raw.get("type") in {"video", "normal"} or raw.get("video_download_url") or raw.get("video_url")))
        local_path = raw.get("local_video_path") or raw.get("path") or raw.get("video_path")
        status = "downloaded" if local_path else "pending"
        items.append(
            make_batch_item(
                note_url=note_url,
                note_id=note_id,
                title=raw.get("title") or raw.get("desc") or "小红书作品",
                author=raw.get("author") or raw.get("author_name") or raw.get("nickname"),
                publish_time=raw.get("publish_time") or raw.get("time"),
                cover_url=raw.get("cover_url") or raw.get("cover") or raw.get("preview_url"),
                is_video=is_video,
                video_download_url=raw.get("video_download_url") or raw.get("video_url") or raw.get("download_url"),
                preview_video_url=raw.get("preview_video_url") or raw.get("video_download_url") or raw.get("video_url") or raw.get("download_url"),
                liked_count=raw.get("liked_count") or raw.get("likes"),
                collected_count=raw.get("collected_count") or raw.get("collects"),
                comment_count=raw.get("comment_count") or raw.get("comments"),
                metrics=raw.get("metrics") or {},
                local_video_path=local_path,
                status=status,
            )
        )
    return items


def _first_url(values, want_video: bool = False) -> str:
    for value in values or []:
        if not value:
            continue
        if isinstance(value, (list, tuple)):
            nested = _first_url(value, want_video=want_video)
            if nested:
                return nested
        text = str(value)
        lower = text.lower()
        if not (text.startswith("http://") or text.startswith("https://")):
            continue
        is_mp4 = ".mp4" in lower or "video" in lower
        if want_video and is_mp4:
            return text
        if not want_video and not is_mp4:
            return text
    return ""


def _note_id_from_url(url: str | None) -> str | None:
    if not url:
        return None
    parsed = urlparse(url)
    parts = [part for part in parsed.path.split("/") if part]
    return parts[-1] if parts else None


def _cli_command() -> list[str] | None:
    cli_path = os.getenv("XHS_DOWNLOADER_CLI_PATH")
    if cli_path:
        return [cli_path]
    project_dir = os.getenv("XHS_DOWNLOADER_PROJECT_DIR")
    if project_dir:
        runner = shutil.which("python")
        if runner:
            return [runner, str(Path(project_dir) / "main.py")]
    return None


def _xhs_downloader_download_root() -> Path | None:
    configured = os.getenv("XHS_DOWNLOADER_DOWNLOAD_DIR")
    if configured:
        return Path(configured)
    project_dir = os.getenv("XHS_DOWNLOADER_PROJECT_DIR")
    if project_dir:
        return Path(project_dir) / "Volume" / "Download"
    return None


def _download_note_by_api(note_url: str, download_dir: Path) -> dict:
    """对接 JoeanAmier/XHS-Downloader V2.8 的实际 API：POST /xhs/detail。

    该 API 会把文件下载到 XHS-Downloader 自己的 Volume/Download 目录，
    通常不会直接返回本地路径；所以这里用“调用前后新增 mp4”来定位文件，
    再复制到当前项目的 xhs_creator_downloads 目录，方便后续换 BGM。
    """
    api_base = (os.getenv("XHS_DOWNLOADER_API_BASE_URL") or "").rstrip("/")
    if not api_base:
        return {"ok": False, "message_zh": "作品下载失败，需要人工处理。", "failure_reason": "XHS_DOWNLOADER_API_BASE_URL 未配置。"}

    source_root = _xhs_downloader_download_root()
    before_files = set()
    if source_root and source_root.exists():
        before_files = {str(path) for path in source_root.rglob("*.mp4")}

    payload = {"url": note_url, "download": True, "skip": False}
    cookie = os.getenv("XHS_COOKIE")
    if cookie:
        payload["cookie"] = cookie

    try:
        data = _post_xhs_downloader_detail(api_base, payload, timeout=240)
    except Exception as exc:
        return {"ok": False, "message_zh": "作品下载失败，需要人工处理。", "failure_reason": f"XHS-Downloader API 调用失败：{_friendly_api_error(exc)}"}

    note = data.get("data") if isinstance(data, dict) else None
    note_type = str((note or {}).get("作品类型") or "")
    download_urls = (note or {}).get("下载地址") or []
    if note and note_type and "视频" not in note_type and not any(".mp4" in str(url).lower() for url in download_urls):
        return {"ok": False, "message_zh": "已跳过图文作品。", "failure_reason": "不是视频作品。"}

    candidates: list[Path] = []
    if source_root and source_root.exists():
        after_files = [path for path in source_root.rglob("*.mp4") if path.is_file()]
        new_files = [path for path in after_files if str(path) not in before_files]
        candidates = new_files or sorted(after_files, key=lambda path: path.stat().st_mtime, reverse=True)[:1]

    if not candidates:
        return {
            "ok": False,
            "message_zh": "作品下载失败，需要人工处理。",
            "failure_reason": "XHS-Downloader API 已返回，但没有在 Volume/Download 找到 mp4。请确认 XHS_DOWNLOADER_PROJECT_DIR 或 XHS_DOWNLOADER_DOWNLOAD_DIR。",
        }

    source = max(candidates, key=lambda path: path.stat().st_mtime)
    download_dir.mkdir(parents=True, exist_ok=True)
    target = download_dir / source.name
    if source.resolve() != target.resolve():
        shutil.copy2(source, target)

    return {"ok": True, "local_video_path": str(target), "message_zh": "视频已通过 XHS-Downloader API 下载。"}


def _download_note_by_cli(note_url: str, download_dir: Path) -> dict:
    command = _cli_command()
    if not command:
        return {"ok": False, "message_zh": "作品下载失败，需要人工处理。", "failure_reason": "XHS-Downloader CLI 未配置。"}
    try:
        completed = subprocess.run(
            command + [note_url, str(download_dir)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=180,
            check=False,
        )
    except Exception as exc:
        return {"ok": False, "message_zh": "作品下载失败，需要人工处理。", "failure_reason": f"XHS-Downloader CLI 启动失败：{exc}"}
    if completed.returncode != 0:
        return {"ok": False, "message_zh": "作品下载失败，需要人工处理。", "failure_reason": completed.stderr.strip() or "XHS-Downloader CLI 执行失败。"}
    files = [path for path in download_dir.rglob("*") if path.is_file() and path.suffix.lower() in {".mp4", ".mov", ".m4v"}]
    if not files:
        return {"ok": False, "message_zh": "作品下载失败，需要人工处理。", "failure_reason": "XHS-Downloader CLI 执行完成，但没有找到视频文件。"}
    return {"ok": True, "local_video_path": str(max(files, key=lambda path: path.stat().st_mtime)), "message_zh": "视频已下载。"}
