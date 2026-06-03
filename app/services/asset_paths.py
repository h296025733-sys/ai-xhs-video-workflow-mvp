from pathlib import Path
import shutil

from app.config import JOBS_DIR, OUTPUTS_DIR, UPLOADS_DIR, asset_folder_name, find_legacy_or_named_output_dir, make_unique_dir


def create_asset_dirs(asset_id: str, original_filename: str) -> dict[str, str]:
    folder_name = asset_folder_name(asset_id, original_filename)
    upload_dir = make_unique_dir(UPLOADS_DIR, folder_name)
    output_dir = OUTPUTS_DIR / folder_name
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    return {
        "upload_dir": str(upload_dir),
        "output_dir": str(output_dir),
        "output_dir_name": output_dir.name,
        "output_folder_name": output_dir.name,
    }


def resolve_output_dir(asset_id: str, job: dict | None = None, original_filename: str | None = None, create: bool = False) -> Path:
    if job:
        stored = job.get("output_dir") or (job.get("package") or {}).get("output_dir")
        if stored and Path(stored).exists():
            return Path(stored)

    found = find_legacy_or_named_output_dir(asset_id)
    if found:
        return found

    if create:
        folder_name = asset_folder_name(asset_id, original_filename)
        output_dir = OUTPUTS_DIR / folder_name
        output_dir.mkdir(parents=True, exist_ok=True)
        return output_dir

    return OUTPUTS_DIR / asset_id


def resolve_output_folder_name(asset_id: str, job: dict | None = None, output_dir: Path | None = None) -> str:
    if job and job.get("output_dir_name"):
        return str(job["output_dir_name"])
    if job and job.get("output_folder_name"):
        return str(job["output_folder_name"])
    if output_dir:
        return output_dir.name
    return resolve_output_dir(asset_id, job).name


def read_job_if_exists(asset_id: str) -> dict | None:
    path = JOBS_DIR / f"{asset_id}.json"
    if not path.exists():
        return None
    import json

    return json.loads(path.read_text(encoding="utf-8"))
