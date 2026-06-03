import base64
import html
import json
from pathlib import Path

from app.models import SceneLabel, SceneSegment, VideoMetadata
from app.services.asset_paths import read_job_if_exists, resolve_output_dir, resolve_output_folder_name
from app.services.fashion_edit_planner import build_metadata_summary


SCENE_ROLE_LABELS = {
    "hook_opening": "开场钩子",
    "full_body": "全身穿搭展示",
    "side_view": "侧身展示",
    "walking_motion": "走路动态",
    "turn_motion": "转身动态",
    "detail_fabric": "面料细节",
    "detail_shoes": "鞋子细节",
    "detail_bag": "包包/配饰",
    "atmosphere": "氛围镜头",
    "low_value": "低价值片段",
    "unknown": "待判断",
}

KEEP_DECISION_LABELS = {
    "keep": "保留",
    "maybe": "待定",
    "cut": "删除",
    "unknown": "待判断",
}


def scene_labels_path(asset_id: str) -> Path:
    return resolve_output_dir(asset_id, read_job_if_exists(asset_id)) / "scene_labels.json"


def scene_segments_path(asset_id: str) -> Path:
    return resolve_output_dir(asset_id, read_job_if_exists(asset_id)) / "scene_segments.json"


def _load_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def _save_json(path: Path, data: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _load_scene_segments(asset_id: str) -> list[SceneSegment]:
    path = scene_segments_path(asset_id)
    if not path.exists():
        raise FileNotFoundError("未找到 scene_segments.json，请先执行 /detect-scenes/{asset_id} 或 /extract-package/{asset_id}。")
    return [SceneSegment(**item) for item in _load_json(path)]


def default_label_from_scene(scene: SceneSegment) -> SceneLabel:
    return SceneLabel(
        scene_id=scene.scene_id,
        start_time=scene.start_time,
        end_time=scene.end_time,
        duration=scene.duration,
        keyframe_path=scene.keyframe_path,
        suggested_tags=[],
        manual_tags=[],
        scene_role="unknown",
        keep_decision="unknown",
        edit_note="待人工确认该镜头是否适合保留、作为开场或作为细节补充。",
        risk_note="待人工检查水印、搬运痕迹、音乐版权、人脸授权和平台风险。",
    )


def initialize_scene_labels(asset_id: str, overwrite: bool = False) -> list[SceneLabel]:
    path = scene_labels_path(asset_id)
    if path.exists() and not overwrite:
        return [SceneLabel(**item) for item in _load_json(path)]

    scenes = _load_scene_segments(asset_id)
    labels = [default_label_from_scene(scene) for scene in scenes]
    save_scene_labels(asset_id, labels)
    return labels


def save_scene_labels(asset_id: str, labels: list[SceneLabel]) -> Path:
    path = scene_labels_path(asset_id)
    _save_json(path, [label.model_dump() for label in labels])
    return path


def build_label_table(labels: list[SceneLabel]) -> str:
    lines = [
        "| scene_id | time | suggested_tags | manual_tags | scene_role | keep_decision | edit_note | risk_note |",
        "|---:|---|---|---|---|---|---|---|",
    ]
    for label in labels:
        lines.append(
            "| "
            f"{label.scene_id} | "
            f"{label.start_time:.3f}s - {label.end_time:.3f}s | "
            f"{', '.join(label.suggested_tags) or '无'} | "
            f"{', '.join(label.manual_tags) or '待填写'} | "
            f"{SCENE_ROLE_LABELS.get(label.scene_role, label.scene_role)} | "
            f"{KEEP_DECISION_LABELS.get(label.keep_decision, label.keep_decision)} | "
            f"{label.edit_note or '待填写'} | "
            f"{label.risk_note or '待填写'} |"
        )
    return "\n".join(lines)


def build_human_review_report(asset_id: str, metadata: VideoMetadata, labels: list[SceneLabel]) -> str:
    return f"""# 人工镜头标注与审核报告

## 重要说明

当前系统已经完成镜头切分、关键帧提取和总览图生成，但还没有完成服装内容的自动视觉理解。
下表中的 `scene_role`、`keep_decision`、`manual_tags`、`edit_note` 和 `risk_note` 需要人工审核填写；后续也可以接 AI 视觉模型辅助生成候选标签。

## 素材基本信息

- asset_id：{asset_id}
{build_metadata_summary(metadata)}

## 镜头分段与待标注项

{build_label_table(labels)}

## 建议人工判断的问题

1. 这个镜头是否清楚展示服装？
2. 是否包含鞋子、包包、配饰、面料、腰线、袖口、拉链、纽扣等细节？
3. 是否适合作为开场钩子，还是更适合作为中段细节补充？
4. 是否应该保留、待定或删除？
5. 是否存在水印、搬运痕迹、音乐版权、人脸授权、品牌露出或平台风险？

## 后续使用

- 审核后的 `scene_labels.json` 可以交给 n8n、AI API、剪映/CapCut 草稿工具或 FFmpeg 模板渲染使用。
- 自动剪辑前必须保留人工审核节点，不应仅凭镜头切分结果直接发布或硬剪。
"""


def _image_to_data_uri(path_value: str | None) -> str | None:
    if not path_value:
        return None
    path = Path(path_value)
    if not path.exists():
        return None
    mime = "image/jpeg"
    data = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{data}"


def _read_optional_json(path: Path) -> object | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _read_optional_text(path: Path, limit: int = 1200) -> str | None:
    if not path.exists():
        return None
    text = path.read_text(encoding="utf-8")
    return text[:limit]


def build_review_page_html(asset_id: str, metadata: dict | None, labels: list[SceneLabel]) -> str:
    job = read_job_if_exists(asset_id)
    output_dir = resolve_output_dir(asset_id, job)
    output_folder_name = resolve_output_folder_name(asset_id, job, output_dir)
    video_profile = _read_optional_json(output_dir / "video_profile.json") or {}
    similar_groups = _read_optional_json(output_dir / "similar_scene_groups.json") or []
    structure_summary = _read_optional_text(output_dir / "structure_review_summary.md")
    human_review = _read_optional_text(output_dir / "human_review_report.md")
    contact_sheet_uri = _image_to_data_uri(str(output_dir / "scene_contact_sheet.jpg"))
    sample_sheet_uri = _image_to_data_uri(str(output_dir / "scene_samples_contact_sheet.jpg"))
    metadata = metadata or {}
    rows = []
    for label in labels:
        keyframe_uri = _image_to_data_uri(label.keyframe_path)
        image_html = (
            f'<img src="{keyframe_uri}" alt="scene {label.scene_id} keyframe" />'
            if keyframe_uri
            else '<div class="missing">关键帧缺失</div>'
        )
        rows.append(
            f"""
            <article class="scene">
              <div class="thumb">{image_html}</div>
              <div class="scene-body">
                <h3>Scene {label.scene_id}</h3>
                <p class="time">{label.start_time:.3f}s - {label.end_time:.3f}s，持续 {label.duration:.3f}s</p>
                <dl>
                  <dt>系统建议标签</dt><dd>{html.escape(", ".join(label.suggested_tags) or "暂无。当前版本不做真实视觉理解。")}</dd>
                  <dt>人工标签</dt><dd>{html.escape(", ".join(label.manual_tags) or "待填写")}</dd>
                  <dt>镜头角色</dt><dd>{html.escape(SCENE_ROLE_LABELS.get(label.scene_role, label.scene_role))}</dd>
                  <dt>保留建议</dt><dd>{html.escape(KEEP_DECISION_LABELS.get(label.keep_decision, label.keep_decision))}</dd>
                  <dt>剪辑备注</dt><dd>{html.escape(label.edit_note or "待填写")}</dd>
                  <dt>风险备注</dt><dd>{html.escape(label.risk_note or "待填写")}</dd>
                </dl>
              </div>
            </article>
            """
        )

    contact_sheet_html = (
        f'<img class="contact-sheet" src="{contact_sheet_uri}" alt="scene contact sheet" />'
        if contact_sheet_uri
        else '<p class="missing">未找到 scene_contact_sheet.jpg，请先执行镜头分段或生成处理包。</p>'
    )
    sample_sheet_html = (
        f'<img class="contact-sheet" src="{sample_sheet_uri}" alt="long scene sample contact sheet" />'
        if sample_sheet_uri
        else '<p class="notice">当前素材未生成长镜头内部采样图，通常表示未检测到需要内部采样的长镜头。</p>'
    )
    similar_html = "<p class=\"notice\">未触发图集轮播相似镜头分析。</p>"
    if similar_groups:
        items = []
        for group in similar_groups:
            items.append(
                f"<li>Group {html.escape(str(group.get('group_id')))}：Scene "
                f"{html.escape(', '.join(str(x) for x in group.get('scene_ids', [])))}。"
                f"{html.escape(str(group.get('similarity_note_zh', '')))} "
                f"{html.escape(str(group.get('recommended_action_zh', '')))}</li>"
            )
        similar_html = f"<ul>{''.join(items)}</ul>"
    summary_source = structure_summary or human_review or "暂无结构化审核摘要。"
    summary_html = f"<pre>{html.escape(summary_source)}</pre>"
    type_notice = ""
    if video_profile.get("video_type") == "one_take_full_body_or_closeup":
        type_notice = "该素材疑似一镜到底视频，请优先查看长镜头内部采样图。"
    elif video_profile.get("video_type") == "slideshow_lookbook":
        type_notice = "该素材疑似图集轮播，请筛选重复镜头，选择最适合作为开场、全身展示、细节补充的画面。"
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>素材审核页 - {html.escape(asset_id)}</title>
  <style>
    body {{ margin: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; color: #172026; background: #f6f7f9; }}
    header {{ padding: 28px 36px; background: #ffffff; border-bottom: 1px solid #d9dee5; }}
    main {{ padding: 24px 36px 40px; max-width: 1180px; margin: 0 auto; }}
    h1 {{ margin: 0 0 10px; font-size: 26px; }}
    h2 {{ margin-top: 28px; font-size: 20px; }}
    .notice {{ color: #5b6573; line-height: 1.7; }}
    .meta, .scene {{ background: #ffffff; border: 1px solid #d9dee5; border-radius: 8px; padding: 18px; }}
    .meta-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 10px 18px; }}
    .contact-sheet {{ max-width: 100%; border: 1px solid #d9dee5; border-radius: 6px; background: #fff; }}
    .scene {{ display: grid; grid-template-columns: 220px 1fr; gap: 18px; margin: 14px 0; }}
    .thumb img {{ width: 100%; border-radius: 6px; border: 1px solid #d9dee5; }}
    .scene h3 {{ margin: 0 0 6px; }}
    .time {{ margin: 0 0 12px; color: #667085; }}
    dl {{ display: grid; grid-template-columns: 120px 1fr; gap: 8px 14px; margin: 0; }}
    dt {{ color: #667085; }}
    dd {{ margin: 0; }}
    .missing {{ color: #9a3412; background: #fff7ed; border: 1px solid #fed7aa; border-radius: 6px; padding: 12px; }}
    @media (max-width: 720px) {{ main, header {{ padding-left: 18px; padding-right: 18px; }} .scene {{ grid-template-columns: 1fr; }} dl {{ grid-template-columns: 1fr; }} }}
  </style>
</head>
<body>
  <header>
    <h1>服装视频镜头标注与审核页</h1>
    <p class="notice">当前页面用于人工审核辅助。系统只完成镜头切分和关键帧提取，不代表已经自动理解服装内容，也不代表可以自动发布。</p>
  </header>
  <main>
    <section class="meta">
      <h2>素材基本信息</h2>
      <div class="meta-grid">
        <div><strong>asset_id：</strong>{html.escape(asset_id)}</div>
        <div><strong>输出文件夹：</strong>{html.escape(output_folder_name)}</div>
        <div><strong>文件名：</strong>{html.escape(str(metadata.get("filename", "未知")))}</div>
        <div><strong>时长：</strong>{html.escape(str(metadata.get("duration", "未知")))}s</div>
        <div><strong>分辨率：</strong>{html.escape(str(metadata.get("width", "未知")))} x {html.escape(str(metadata.get("height", "未知")))}</div>
        <div><strong>视频类型：</strong>{html.escape(str(video_profile.get("video_type_zh", "未生成")))}</div>
      </div>
      <p class="notice">{html.escape(str(video_profile.get("recommended_review_strategy_zh", type_notice)))}</p>
    </section>
    <section>
      <h2>镜头关键帧总览</h2>
      {contact_sheet_html}
    </section>
    <section>
      <h2>长镜头内部采样</h2>
      {sample_sheet_html}
    </section>
    <section>
      <h2>图集轮播/相似镜头提示</h2>
      {similar_html}
    </section>
    <section>
      <h2>结构化审核摘要</h2>
      {summary_html}
    </section>
    <section>
      <h2>逐镜头审核</h2>
      {''.join(rows)}
    </section>
  </main>
</body>
</html>
"""
