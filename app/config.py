import re
from pathlib import Path


APP_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = APP_DIR.parent
STORAGE_DIR = APP_DIR / "storage"
UPLOADS_DIR = STORAGE_DIR / "uploads"
OUTPUTS_DIR = STORAGE_DIR / "outputs"
JOBS_DIR = STORAGE_DIR / "jobs"
MATERIAL_POOL_DIR = STORAGE_DIR / "material_pool"
PROMPTS_DIR = APP_DIR / "prompts"


def ensure_storage_dirs() -> None:
    for path in (UPLOADS_DIR, OUTPUTS_DIR, JOBS_DIR, MATERIAL_POOL_DIR):
        path.mkdir(parents=True, exist_ok=True)


def safe_filename_stem(filename: str | None) -> str:
    raw = Path(filename or "video").stem.strip() or "video"
    cleaned = re.sub(r'[\\/:*?"<>|]', "_", raw)
    cleaned = re.sub(r"\s+", "_", cleaned)
    cleaned = re.sub(r"_+", "_", cleaned).strip("._ ")
    return cleaned or "video"


def asset_folder_name(asset_id: str, original_filename: str | None) -> str:
    return safe_filename_stem(original_filename)


def make_unique_dir(base_dir: Path, folder_name: str) -> Path:
    candidate = base_dir / folder_name
    if not candidate.exists():
        candidate.mkdir(parents=True, exist_ok=True)
        return candidate
    suffix = 2
    while True:
        candidate = base_dir / f"{folder_name}__{suffix}"
        if not candidate.exists():
            candidate.mkdir(parents=True, exist_ok=True)
            return candidate
        suffix += 1


def find_legacy_or_named_output_dir(asset_id: str) -> Path | None:
    legacy = OUTPUTS_DIR / asset_id
    if legacy.exists():
        return legacy
    return None


ensure_storage_dirs()
