from __future__ import annotations

import re
import zipfile
from pathlib import Path

from src.browser.download_utils import sanitize_filename
from src.documents.rr_extractor import normalize_rr_number


def _safe_target(base_dir: Path, member_name: str) -> Path:
    # SPP archives are external input, so extracted paths are normalized and
    # checked to prevent zip-slip writes outside the target directory.
    parts = [sanitize_filename(part) for part in Path(member_name).parts if part not in ("", ".", "..")]
    target = base_dir.joinpath(*parts)
    resolved_base = base_dir.resolve()
    resolved_target = target.resolve()
    if resolved_base not in resolved_target.parents and resolved_target != resolved_base:
        raise ValueError(f"Unsafe zip path: {member_name}")
    return target


def extract_matching(zip_path: Path, target_dir: Path, suffixes: tuple[str, ...]) -> list[Path]:
    target_dir.mkdir(parents=True, exist_ok=True)
    extracted: list[Path] = []
    with zipfile.ZipFile(zip_path) as archive:
        for member in archive.infolist():
            if member.is_dir():
                continue
            if not member.filename.lower().endswith(suffixes):
                continue
            target = _safe_target(target_dir, member.filename)
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(member) as source, target.open("wb") as output:
                output.write(source.read())
            extracted.append(target)
    return extracted


def extract_pdfs(zip_path: Path, target_dir: Path) -> list[Path]:
    return extract_matching(zip_path, target_dir, (".pdf",))


def extract_first_recommendation_report(zip_path: Path, rr_number: str, target_dir: Path) -> Path | None:
    target_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as archive:
        for member in archive.infolist():
            if member.is_dir():
                continue
            name = Path(member.filename).name
            if not (name.lower().endswith(".docx") and "recommendation report" in name.lower()):
                continue
            target = _safe_target(target_dir, name)
            with archive.open(member) as source, target.open("wb") as output:
                output.write(source.read())
            return target
    return None
