from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class StoredFile:
    source: Path
    destination: Path
    existed: bool


class LocalSharePointClient:
    """Filesystem mirror for the future SharePoint library layout."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def store_file(self, source: Path, folder: str) -> StoredFile:
        # V1 mirrors the future SharePoint layout locally and never overwrites
        # an already mirrored file with the same name.
        destination = self.root / folder / source.name
        destination.parent.mkdir(parents=True, exist_ok=True)
        existed = destination.exists()
        if not existed:
            shutil.copy2(source, destination)
        return StoredFile(source=source, destination=destination, existed=existed)
