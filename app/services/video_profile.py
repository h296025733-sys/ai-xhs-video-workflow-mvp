import json
import math
from pathlib import Path

import cv2
import numpy as np

from app.models import SceneSegment, VideoMetadata
from app.services.media_extract import extract_frame


def _mean(values: list[float]) -> float:
    return round(sum(values) / len(values), 3) if values else 0.0


def build_video_profile(asset_id: str, metadata: VideoMetadata, scenes: list[SceneSegment]) -> dict:
    durations = [scene.duration for scene in scenes]
    scene_count = len(scenes)
    short_scene_count = sum(1 for value in durations if value < 1.2)
    long_scene_count = sum(1 for value in durations if value >= 5)
    avg_scene_duration = _mean(durations)
    min_scene_duration = round(min(durations), 3) if durations else 0.0
    max_scene_duration = round(max(durations), 3) if durations else 0.0
    between_half_and_2_5 = sum(1 for value in durations if 0.5 <= value <= 2.5)
    under_one = sum(1 for value in durations if value < 1.0)
    majority_half_to_2_5 = scene_count > 0 and between_half_and_2_5 / scene_count >= 0.6
    majority_under_one = scene_count > 0 and under_one / scene_count >= 0.6

    if scene_count == 1 and (metadata.duration or 0) > 5:
        video_type = "one_take_full_body_or_closeup"
        video_type_zh = "疑似一镜到底全身展示或近景/口播型视频"
        confidence_note_zh = "该素材只有 1 个长镜头。当前规则无法判断它是全身展示还是近景/口播，需要人工结合长镜头采样图确认。"
        recommended_review_strategy_zh = "请优先查看 scene_samples_contact_sheet.jpg，选择适合开场、完整穿搭展示、细节补充或删除的时间点。"
    elif scene_count >= 8 and majority_under_one:
        video_type = "fast_cut"
        video_type_zh = "疑似快剪视频"
        confidence_note_zh = "多数镜头短于 1 秒，可能是快节奏剪辑或转场密集素材。"
        recommended_review_strategy_zh = "请重点检查过短片段、转场残留和字幕遮挡，不要把 0.5 秒以上短镜头默认删除。"
    elif scene_count >= 8 and majority_half_to_2_5:
        video_type = "slideshow_lookbook"
        video_type_zh = "疑似图集轮播 / OOTD 拼接型视频"
        confidence_note_zh = "多数镜头集中在 0.5 到 2.5 秒之间，可能是图集轮播或穿搭拼接。"
        recommended_review_strategy_zh = "请筛选重复镜头，选择最适合作为开场、全身展示、细节补充和氛围表达的画面。"
    elif 2 <= scene_count <= 7 and 2 <= avg_scene_duration <= 6:
        video_type = "normal_cut"
        video_type_zh = "普通切镜视频"
        confidence_note_zh = "镜头数量和平均时长较适合人工逐段审核。"
        recommended_review_strategy_zh = "请根据 scene_contact_sheet.jpg 逐镜头标注开场、全身展示、动态展示、细节和低价值片段。"
    else:
        video_type = "unknown"
        video_type_zh = "未知结构类型"
        confidence_note_zh = "当前规则无法稳定判断视频结构类型。"
        recommended_review_strategy_zh = "请人工查看关键帧总览图和镜头标签，再决定剪辑策略。"

    return {
        "asset_id": asset_id,
        "filename": metadata.filename,
        "duration": metadata.duration,
        "scene_count": scene_count,
        "avg_scene_duration": avg_scene_duration,
        "min_scene_duration": min_scene_duration,
        "max_scene_duration": max_scene_duration,
        "short_scene_count": short_scene_count,
        "long_scene_count": long_scene_count,
        "video_type": video_type,
        "video_type_zh": video_type_zh,
        "confidence_note_zh": confidence_note_zh,
        "recommended_review_strategy_zh": recommended_review_strategy_zh,
    }


def _sample_ratios(duration: float) -> list[float]:
    if duration <= 12:
        return [0.1, 0.3, 0.5, 0.7, 0.9]
    if duration <= 20:
        return [i / 8 for i in range(1, 8)]
    count = min(12, max(9, math.ceil(duration / 2)))
    return [(i + 1) / (count + 1) for i in range(count)]


def _contact_sheet_from_paths(items: list[dict], output_path: Path, thumb_width: int = 240) -> Path | None:
    images: list[np.ndarray] = []
    for item in items:
        image = cv2.imread(item["sample_path"])
        if image is None:
            continue
        h, w = image.shape[:2]
        ratio = thumb_width / max(w, 1)
        resized = cv2.resize(image, (thumb_width, max(int(h * ratio), 1)))
        label = f"S{item['scene_id']} #{item['sample_id']} {item['timestamp']:.1f}s"
        cv2.rectangle(resized, (0, 0), (thumb_width, 28), (0, 0, 0), -1)
        cv2.putText(resized, label, (8, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)
        images.append(resized)
    if not images:
        return None
    cell_h = max(img.shape[0] for img in images)
    cols = min(4, len(images))
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


def generate_long_scene_samples(video_path: Path, output_dir: Path, scenes: list[SceneSegment], video_duration: float | None) -> list[dict]:
    should_sample = (len(scenes) == 1 and (video_duration or 0) > 5) or any(scene.duration > 5 for scene in scenes)
    if not should_sample:
        (output_dir / "long_scene_samples.json").write_text("[]", encoding="utf-8")
        return []

    sample_dir = output_dir / "scene_samples"
    sample_dir.mkdir(parents=True, exist_ok=True)
    samples: list[dict] = []
    for scene in scenes:
        if not (scene.duration > 5 or (len(scenes) == 1 and scene.duration > 5)):
            continue
        for idx, ratio in enumerate(_sample_ratios(scene.duration), start=1):
            timestamp = round(scene.start_time + scene.duration * ratio, 3)
            sample_path = sample_dir / f"scene_{scene.scene_id:03d}_sample_{idx:02d}.jpg"
            extract_frame(video_path, sample_path, timestamp)
            samples.append(
                {
                    "scene_id": scene.scene_id,
                    "sample_id": idx,
                    "timestamp": timestamp,
                    "sample_path": str(sample_path),
                    "purpose": "long_scene_internal_review",
                    "note_zh": "该帧来自长镜头内部采样，用于人工判断服装展示动作、姿态变化、表情、细节和适合剪辑的时间点；不代表系统已经理解画面内容。",
                }
            )

    (output_dir / "long_scene_samples.json").write_text(json.dumps(samples, ensure_ascii=False, indent=2), encoding="utf-8")
    if samples:
        _contact_sheet_from_paths(samples, output_dir / "scene_samples_contact_sheet.jpg")
    return samples


def _average_hash(image_path: str, size: int = 8) -> np.ndarray | None:
    image = cv2.imread(image_path, cv2.IMREAD_GRAYSCALE)
    if image is None:
        return None
    resized = cv2.resize(image, (size, size))
    return resized > resized.mean()


def analyze_similar_scenes(output_dir: Path, scenes: list[SceneSegment], video_profile: dict) -> list[dict]:
    if video_profile.get("video_type") != "slideshow_lookbook":
        groups: list[dict] = []
        (output_dir / "similar_scene_groups.json").write_text(json.dumps(groups, ensure_ascii=False, indent=2), encoding="utf-8")
        return groups

    hashes: dict[int, np.ndarray] = {}
    for scene in scenes:
        if scene.keyframe_path:
            value = _average_hash(scene.keyframe_path)
            if value is not None:
                hashes[scene.scene_id] = value

    visited: set[int] = set()
    groups = []
    group_id = 1
    for scene_id, hash_value in hashes.items():
        if scene_id in visited:
            continue
        members = [scene_id]
        visited.add(scene_id)
        for other_id, other_hash in hashes.items():
            if other_id in visited:
                continue
            distance = int(np.count_nonzero(hash_value != other_hash))
            if distance <= 6:
                members.append(other_id)
                visited.add(other_id)
        if len(members) > 1:
            groups.append(
                {
                    "group_id": group_id,
                    "scene_ids": members,
                    "similarity_note_zh": "这些镜头的关键帧在简单图像哈希上较相似，可能存在重复或近似穿搭展示。该判断不是服装语义识别。",
                    "recommended_action_zh": "建议人工从该组中选择 1 到 3 个最清晰、最适合作为开场、全身展示或细节补充的镜头。",
                }
            )
            group_id += 1

    if not groups:
        groups.append(
            {
                "group_id": 1,
                "scene_ids": [scene.scene_id for scene in scenes],
                "similarity_note_zh": "该素材疑似图集轮播，存在多个穿搭展示镜头；简单相似度未形成明确分组。",
                "recommended_action_zh": "建议人工选择 1 到 3 个最优镜头保留，并删除重复、模糊或信息量低的画面。",
            }
        )

    (output_dir / "similar_scene_groups.json").write_text(json.dumps(groups, ensure_ascii=False, indent=2), encoding="utf-8")
    return groups


def build_structure_review_summary(asset_id: str, output_folder_name: str, video_profile: dict, samples: list[dict], similar_groups: list[dict]) -> str:
    has_long_scene = video_profile.get("long_scene_count", 0) > 0
    has_too_short = video_profile.get("min_scene_duration", 0) < 0.5
    is_slideshow = video_profile.get("video_type") == "slideshow_lookbook"
    review_order = [
        "先查看 video_profile.json，确认视频结构类型。",
        "查看 scene_contact_sheet.jpg，快速理解镜头结构。",
    ]
    if samples:
        review_order.append("优先查看 scene_samples_contact_sheet.jpg，确认长镜头内部动作和可剪时间点。")
    if is_slideshow:
        review_order.append("查看 similar_scene_groups.json，筛选重复或相似镜头。")
    review_order.append("填写 scene_labels.json，再决定保留、待定或删除。")

    type_tip = "该素材疑似一镜到底视频，镜头切分结果较少。建议不要只看 scene_contact_sheet.jpg，应优先查看 scene_samples_contact_sheet.jpg，选择适合开场、展示细节、保留或删除的时间点。"
    if is_slideshow:
        type_tip = "该素材疑似图集轮播 / OOTD 拼接型视频。建议筛选重复镜头，选择最适合作为开场、全身展示、细节补充的画面。"
    elif video_profile.get("video_type") == "normal_cut":
        type_tip = "该素材疑似普通切镜视频。建议按 scene_contact_sheet.jpg 逐镜头人工标注。"

    return "\n".join(
        [
            "# 视频结构化审核摘要",
            "",
            f"- asset_id：{asset_id}",
            f"- 当前输出目录名：{output_folder_name}",
            f"- 视频类型判断：{video_profile.get('video_type')}（{video_profile.get('video_type_zh')}）",
            f"- 镜头数量：{video_profile.get('scene_count')}",
            f"- 是否存在长镜头：{'是' if has_long_scene else '否'}",
            f"- 是否存在过短片段：{'是' if has_too_short else '否'}",
            f"- 是否疑似图集轮播：{'是' if is_slideshow else '否'}",
            f"- 是否需要优先查看长镜头采样图：{'是' if samples else '否'}",
            f"- 是否需要人工做重复镜头筛选：{'是' if similar_groups else '否'}",
            "",
            "## 结构判断说明",
            "",
            str(video_profile.get("confidence_note_zh")),
            "",
            "## 审核建议",
            "",
            type_tip,
            "",
            "## 推荐审核顺序",
            "",
            *[f"{idx}. {item}" for idx, item in enumerate(review_order, start=1)],
            "",
            "当前判断为规则辅助，不代表 AI 已经理解服装内容。",
        ]
    )
