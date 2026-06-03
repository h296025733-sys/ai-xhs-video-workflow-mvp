from app.models import SceneLabel, SceneSegment, VideoMetadata
from app.services.prompt_builder import load_prompt


def build_scene_summary(scenes: list[SceneSegment]) -> str:
    if not scenes:
        return "暂无镜头分段结果。"
    lines = ["| scene_id | start | end | duration | keyframe | notes |", "|---:|---:|---:|---:|---|---|"]
    for scene in scenes:
        lines.append(
            f"| {scene.scene_id} | {scene.start_time:.3f}s | {scene.end_time:.3f}s | "
            f"{scene.duration:.3f}s | {scene.keyframe_path or ''} | {scene.notes} |"
        )
    return "\n".join(lines)


def build_metadata_summary(metadata: VideoMetadata) -> str:
    return "\n".join(
        [
            f"- 文件名：{metadata.filename}",
            f"- 文件大小：{metadata.file_size_bytes} bytes",
            f"- 时长：{metadata.duration}s",
            f"- 分辨率：{metadata.width}x{metadata.height}",
            f"- 帧率：{metadata.frame_rate}",
            f"- 是否有音频：{metadata.has_audio}",
            f"- 视频编码：{metadata.video_codec}",
            f"- 音频编码：{metadata.audio_codec}",
        ]
    )


def build_label_summary(labels: list[SceneLabel] | None) -> str:
    if not labels:
        return "暂无 scene_labels.json 或尚未完成人工标注。待人工标注后再生成更准确剪辑建议。"
    lines = [
        "| scene_id | manual_tags | scene_role | keep_decision | edit_note | risk_note |",
        "|---:|---|---|---|---|---|",
    ]
    has_manual_input = False
    for label in labels:
        if label.manual_tags or label.scene_role != "unknown" or label.keep_decision != "unknown":
            has_manual_input = True
        lines.append(
            f"| {label.scene_id} | {', '.join(label.manual_tags) or '待填写'} | "
            f"{label.scene_role} | {label.keep_decision} | {label.edit_note or '待填写'} | {label.risk_note or '待填写'} |"
        )
    if not has_manual_input:
        lines.append("")
        lines.append("> 当前标签仍为默认值。请先由人工审核每个镜头，再基于标签生成更准确的剪辑策略。")
    return "\n".join(lines)


def build_label_based_recommendations(labels: list[SceneLabel] | None) -> str:
    if not labels:
        return "- 待人工标注后再生成更准确剪辑建议。当前只能基于镜头切分和关键帧做初步审核。"

    keep = [label for label in labels if label.keep_decision == "keep"]
    maybe = [label for label in labels if label.keep_decision == "maybe"]
    cut = [label for label in labels if label.keep_decision == "cut"]
    openings = [label for label in labels if label.scene_role == "hook_opening"]
    details = [label for label in labels if label.scene_role in {"detail_fabric", "detail_shoes", "detail_bag"}]
    motion = [label for label in labels if label.scene_role in {"walking_motion", "turn_motion", "side_view", "full_body"}]

    if not (keep or maybe or cut or openings or details or motion):
        return "\n".join(
            [
                "- 当前 scene_labels.json 仍是默认待判断状态。",
                "- 请先人工标注每个镜头的 scene_role、keep_decision、manual_tags、edit_note 和 risk_note。",
                "- 标注完成后，可按开场钩子、全身展示、动态展示、细节补充、低价值片段的顺序组织剪辑。",
            ]
        )

    return "\n".join(
        [
            f"- 开场候选：{', '.join(f'Scene {x.scene_id}' for x in openings) or '暂无明确标注'}。",
            f"- 主体展示候选：{', '.join(f'Scene {x.scene_id}' for x in motion) or '暂无明确标注'}。",
            f"- 细节补充候选：{', '.join(f'Scene {x.scene_id}' for x in details) or '暂无明确标注'}。",
            f"- 明确保留：{', '.join(f'Scene {x.scene_id}' for x in keep) or '暂无'}。",
            f"- 待定复核：{', '.join(f'Scene {x.scene_id}' for x in maybe) or '暂无'}。",
            f"- 建议删除：{', '.join(f'Scene {x.scene_id}' for x in cut) or '暂无'}。",
            "- 如果 risk_note 中出现水印、搬运、音乐版权、人脸授权等风险，应先处理授权与审核，再进入剪辑或发布流程。",
        ]
    )


def build_profile_recommendations(video_profile: dict | None) -> str:
    if not video_profile:
        return "- 暂无 video_profile.json。请先生成素材处理包，再结合视频结构类型完善剪辑建议。"
    video_type = video_profile.get("video_type")
    if video_type == "one_take_full_body_or_closeup":
        return "\n".join(
            [
                "- 该素材疑似长镜头/一镜到底素材。",
                "- 请优先查看 `scene_samples_contact_sheet.jpg`，不要只依赖单张关键帧。",
                "- 建议人工选择 3 到 5 个时间点作为候选剪辑点，例如开场动作、完整穿搭展示、细节动作、表情/氛围点。",
                "- 不要直接把整段当作一个不可拆片段；也不要在未看内部采样前判断它缺少服装价值。",
            ]
        )
    if video_type == "slideshow_lookbook":
        return "\n".join(
            [
                "- 该素材疑似图集轮播 / 穿搭拼接素材。",
                "- 请查看 `similar_scene_groups.json`，做重复镜头筛选。",
                "- 建议选择开场钩子、全身展示、细节镜头、氛围镜头，避免所有镜头都保留。",
                "- 简单相似度只用于提示重复风险，不代表系统已经识别具体服装语义。",
            ]
        )
    if video_type == "normal_cut":
        return "\n".join(
            [
                "- 该素材疑似普通切镜视频。",
                "- 可以优先根据 `scene_contact_sheet.jpg` 逐镜头人工标注。",
                "- 标注重点是开场钩子、全身展示、动态展示、细节补充和低价值片段。",
            ]
        )
    return "- 当前视频结构类型暂不明确。请人工结合关键帧总览、长镜头采样和 scene_labels.json 判断剪辑策略。"


def build_fashion_edit_plan(
    metadata: VideoMetadata,
    scenes: list[SceneSegment],
    labels: list[SceneLabel] | None = None,
    video_profile: dict | None = None,
) -> str:
    scene_summary = build_scene_summary(scenes)
    label_summary = build_label_summary(labels)
    label_recommendations = build_label_based_recommendations(labels)
    profile_recommendations = build_profile_recommendations(video_profile)
    return f"""# 服装类 TikTok 剪辑建议

## 第二阶段原则

- 不建议按固定秒数硬剪，也不把“第几秒一定是开头/细节/转场”写死。
- 当前系统只完成“镜头切分、关键帧提取、总览图生成”，还没有完成“视觉理解”。
- `suggested_tags` 不是精准识别结果；未接入视觉模型前，镜头语义标签应视为人工审核/人工填写/待确认。
- 先由人工给 `scene_labels.json` 中每个 scene 打标签，再基于标签生成更可靠的剪辑策略。
- 第一版仍只输出剪辑建议，不直接自动裁切或自动发布。

## 服装电商优先级

1. 优先保留能证明穿着效果的镜头：全身上身效果、侧身展示、转身、走路动态。
2. 保留能支撑购买决策的镜头：面料纹理、版型轮廓、腰线、袖口、拉链、纽扣、口袋、裙摆或裤脚细节。
3. 保留有 TikTok 传播价值的镜头：换装前后对比、表情和氛围感、节奏清晰的动作点。
4. 谨慎使用只有脸部、空镜、无服装信息的片段，除非它能增强风格或情绪。

## 当前素材信息

{build_metadata_summary(metadata)}

## 镜头分段结果

{scene_summary}

## 镜头标签状态

{label_summary}

## 基于标签的剪辑建议

{label_recommendations}

## 基于视频结构类型的建议

{profile_recommendations}

## 通用剪辑策略

- 用镜头类型选择模板，而不是用固定时间点选择模板。
- 每个镜头先人工查看关键帧总览图，再决定是否进入候选素材池。
- 如果镜头里有服装完整轮廓，可作为开场候选；如果只有局部细节，可作为购买理由补充；如果存在换装或动作变化，可作为节奏点。
- 韩日 TikTok 本地化时，字幕重点应服务“场景 + 穿搭利益点”，避免直接翻译中文口播导致表达生硬。
- BGM 和配音建议应基于镜头节奏、目标国家平台审美和品牌调性，不沿用疑似侵权原声。
- 如果标签还没填写，请先完成 `scene_labels.json` 的人工标注，再生成更准确的剪辑建议。

## 后续接口预留

- AI 视觉模型：识别每个 scene 的服装画面类型、商品卖点、风险点。
- pyJianYingDraft / 剪映草稿工具：根据镜头类型生成草稿，不作为当前强依赖。
- CapCut / VectCutAPI：后续作为可选插件接入。
- FFmpeg 模板渲染：后续可按镜头标签生成竖屏模板视频。

## 提示词参考

{load_prompt("fashion_editing_prompt.md")}
"""
