from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict

import yaml


SPP_BASE_URL = "https://www.spp.org"
DOCUMENT_SEARCH_PATH = "/spp-documents-filings/"

RR_MASTER_QUERY = "RR Master List"
CUF_QUERY = "CUF Meeting Materials"
SUF_QUERY = "SUF Meeting Materials"
PROTOCOL_QUERY = "Integrated Marketplace Protocols"

LOW_TEXT_CHAR_THRESHOLD = 50


@dataclass(frozen=True)
class AppConfig:
    downloads_dir: Path
    extracted_dir: Path
    state_file: Path
    reports_dir: Path
    logs_dir: Path
    logging_level: str


def load_config(path: str = "config.yaml") -> AppConfig:
    with open(path, "r", encoding="utf-8") as handle:
        raw: Dict[str, Any] = yaml.safe_load(handle) or {}

    paths = raw.get("paths", {})
    logging = raw.get("logging", {})
    return AppConfig(
        downloads_dir=Path(paths.get("downloads_dir", "data/downloads")),
        extracted_dir=Path(paths.get("extracted_dir", "data/extracted")),
        state_file=Path(paths.get("state_file", "data/state/metadata.json")),
        reports_dir=Path(paths.get("reports_dir", "data/reports")),
        logs_dir=Path(paths.get("logs_dir", "logs")),
        logging_level=str(logging.get("level", "INFO")).upper(),
    )


def ensure_runtime_dirs(config: AppConfig) -> None:
    for directory in (
        config.downloads_dir,
        config.extracted_dir,
        config.state_file.parent,
        config.reports_dir,
        config.logs_dir,
    ):
        directory.mkdir(parents=True, exist_ok=True)
