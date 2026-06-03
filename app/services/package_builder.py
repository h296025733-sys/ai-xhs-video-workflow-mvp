import json
import shutil
from pathlib import Path

from app.config import OUTPUTS_DIR
from app.models import SceneSegment, VideoMetadata
from app.services.fashion_edit_planner import build_fashion_edit_plan, build_metadata_summary, build_scene_summary
from app.services.media_extract import extract_audio_wav, extract_thumbnail
from app.services.media_probe import probe_video
from app.services.prompt_builder import build_localization_request, build_review_checklist, load_prompt, write_text
from app.services.scene_detect import detect_scenes
from app.services.scene_labels import build_human_review_report, initialize_scene_labels
from app.services.video_profile import (
    analyze_similar_scenes,
    build_structure_review_summary,
    build_video_profile,
    generate_long_scene_samples,
)


def save_json(path: Path, data: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def build_package(asset_id: str, video_path: Path, original_filename: str, output_dir: Path | None = None) -> dict[str, object]:
    output_dir = output_dir or (OUTPUTS_DIR / asset_id)
    output_dir.mkdir(parents=True, exist_ok=True)

    metadata = probe_video(video_path, original_filename)
    save_json(output_dir / "metadata.json", metadata.model_dump())

    thumbnail_path = extract_thumbnail(video_path, output_dir / "thumbnail.jpg", metadata)
    audio_note = extract_audio_wav(video_path, output_dir / "audio.wav", metadata)

    scenes, contact_sheet = detect_scenes(video_path, output_dir, metadata)
    save_json(output_dir / "scene_segments.json", [scene.model_dump() for scene in scenes])
    labels = initialize_scene_labels(asset_id)
    video_profile = build_video_profile(asset_id, metadata, scenes)
    save_json(output_dir / "video_profile.json", video_profile)
    long_scene_samples = generate_long_scene_samples(video_path, output_dir, scenes, metadata.duration)
    similar_scene_groups = analyze_similar_scenes(output_dir, scenes, video_profile)
    write_text(
        output_dir / "structure_review_summary.md",
        build_structure_review_summary(asset_id, output_dir.name, video_profile, long_scene_samples, similar_scene_groups),
    )

    metadata_summary = build_metadata_summary(metadata)
    scene_summary = build_scene_summary(scenes)
    write_text(output_dir / "fashion_edit_plan.md", build_fashion_edit_plan(metadata, scenes, labels, video_profile))
    write_text(output_dir / "human_review_report.md", build_human_review_report(asset_id, metadata, labels))
    write_text(output_dir / "localization_request_ko.md", build_localization_request("ko", metadata_summary, scene_summary))
    write_text(output_dir / "localization_request_ja.md", build_localization_request("ja", metadata_summary, scene_summary))
    caption_prompt = load_prompt("caption_style_prompt.md")
    write_text(output_dir / "caption_style_request.md", f"{caption_prompt}\n\n## 素材信息\n\n{metadata_summary}\n\n## 镜头结构\n\n{scene_summary}\n")
    write_text(output_dir / "review_checklist.md", build_review_checklist(metadata_summary, scene_summary))
    write_text(
        output_dir / "package_summary.md",
        "\n".join(
            [
                "# 素材处理包摘要",
                "",
                f"- asset_id: {asset_id}",
                f"- 原始文件名: {original_filename}",
                f"- 输出目录: {output_dir}",
                f"- 输出文件夹名: {output_dir.name}",
                f"- 视频类型判断: {video_profile.get('video_type')}（{video_profile.get('video_type_zh')}）",
                f"- 缩略图: {thumbnail_path}",
                f"- 音频: {audio_note}",
                f"- 镜头数量: {len(scenes)}",
                f"- 镜头总览图: {contact_sheet}",
                f"- 长镜头内部采样: {'已生成' if long_scene_samples else '未发现需要内部采样的长镜头'}",
                f"- 图集轮播相似镜头分析: {'已生成提示' if similar_scene_groups else '未触发图集轮播相似镜头分析'}",
                "",
                "当前处理包不包含自动发布、不包含去水印、不调用收费 AI API。",
            ]
        ),
    )

    return {
        "asset_id": asset_id,
        "original_filename": original_filename,
        "output_dir": str(output_dir),
        "output_dir_name": output_dir.name,
        "output_folder_name": output_dir.name,
        "metadata": metadata.model_dump(),
        "scenes": [scene.model_dump() for scene in scenes],
        "files": sorted(str(path) for path in output_dir.rglob("*") if path.is_file()),
    }


def copy_scene_outputs_to_package(asset_id: str, scene_dir: Path) -> None:
    output_dir = OUTPUTS_DIR / asset_id
    output_dir.mkdir(parents=True, exist_ok=True)
    for name in ("scene_segments.json", "scene_contact_sheet.jpg"):
        src = scene_dir / name
        if src.exists():
            shutil.copy2(src, output_dir / name)
