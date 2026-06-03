from __future__ import annotations

import hashlib
import re
from pathlib import Path
from urllib.parse import unquote

import requests


def sanitize_filename(name: str) -> str:
    cleaned = unquote(name).strip()
    cleaned = "".join("_" if ch in '<>:"/\\|?*' else ch for ch in cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip(" .")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download_to_path(
    url: str,
    path: Path,
    timeout: int = 120,
    session: requests.Session | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    requester = session if session is not None else requests
    with requester.get(url, stream=True, timeout=timeout) as response:
        response.raise_for_status()
        with path.open("wb") as handle:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    handle.write(chunk)
