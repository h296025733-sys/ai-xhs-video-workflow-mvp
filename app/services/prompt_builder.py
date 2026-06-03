from pathlib import Path

from app.config import PROMPTS_DIR


def load_prompt(name: str) -> str:
    path = PROMPTS_DIR / name
    return path.read_text(encoding="utf-8")


def build_localization_request(locale: str, metadata_summary: str, scene_summary: str) -> str:
    prompt_file = "ko_localization_prompt.md" if locale == "ko" else "ja_localization_prompt.md"
    return "\n\n".join(
        [
            load_prompt(prompt_file),
            "## 素材元信息",
            metadata_summary,
            "## 镜头结构",
            scene_summary,
            "## 输出要求",
            "当前 MVP 不调用 AI API。请在后续接入模型时，把本文件作为输入上下文。",
        ]
    )


def build_review_checklist(metadata_summary: str, scene_summary: str) -> str:
    return "\n\n".join(
        [
            load_prompt("review_checklist_prompt.md"),
            "## 待审核素材信息",
            metadata_summary,
            "## 镜头结构",
            scene_summary,
        ]
    )


def write_text(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path
