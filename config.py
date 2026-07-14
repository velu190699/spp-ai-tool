from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict

import yaml
from dotenv import load_dotenv

# Load secrets (e.g. SLACK_WEBHOOK_URL) from a local .env if present. The .env is
# gitignored, so credentials never live in config.yaml.
load_dotenv()


SPP_BASE_URL = "https://www.spp.org"
DOCUMENT_SEARCH_PATH = "/spp-documents-filings/"

RR_MASTER_QUERY = "RR Master List"
CUF_QUERY = "CUF"
SUF_QUERY = "SUF"
PROTOCOL_QUERY = "Integrated Marketplace Protocols"

LOW_TEXT_CHAR_THRESHOLD = 50


@dataclass(frozen=True)
class AppConfig:
    cuf_dir: Path
    suf_dir: Path
    protocols_dir: Path
    recommendation_reports_dir: Path
    rr_master_list_dir: Path
    state_file: Path
    reports_dir: Path
    published_reports_dir: Path
    settlement_reports_dir: Path
    logs_dir: Path
    logging_level: str
    sharepoint_base_url: str
    sharepoint_sync_root: Path
    sharepoint_tenant_id: str
    sharepoint_client_id: str
    sharepoint_client_secret: str
    report_engine: str
    claude_code_binary: str
    report_model: str
    slack_webhook_url: str
    slack_bot_token: str
    slack_channel: str


def _expand_path(value: str) -> Path:
    """Expand ${ENV_VAR}/%VAR% and ~ in a configured path, then make a Path.

    Lets config.yaml stay machine-agnostic: instead of hard-coding a per-user
    absolute path (which two teammates would keep overwriting for each other),
    it can reference ${SPP_SYNC_ROOT}, defined in each person's local .env.
    """
    return Path(os.path.expanduser(os.path.expandvars(str(value))))


def load_config(path: str = "config.yaml") -> AppConfig:
    with open(path, "r", encoding="utf-8") as handle:
        raw: Dict[str, Any] = yaml.safe_load(handle) or {}

    paths = raw.get("paths", {})
    logging = raw.get("logging", {})
    sharepoint = raw.get("sharepoint", {})
    report = raw.get("report", {})
    slack = raw.get("slack", {})
    return AppConfig(
        cuf_dir=_expand_path(paths.get("cuf_dir", "data/CUF")),
        suf_dir=_expand_path(paths.get("suf_dir", "data/SUF")),
        protocols_dir=_expand_path(paths.get("protocols_dir", "data/Protocols")),
        recommendation_reports_dir=_expand_path(paths.get("recommendation_reports_dir", "data/Recommendation_Reports")),
        rr_master_list_dir=_expand_path(paths.get("rr_master_list_dir", "data/RR_Master_List")),
        state_file=_expand_path(paths.get("state_file", "data/state/metadata.json")),
        reports_dir=_expand_path(paths.get("reports_dir", "data/reports")),
        # Where the final HTML report is published. Defaults to reports_dir so
        # runs without this key keep their old behavior; set it to the synced
        # SharePoint "Reports" folder to publish there.
        published_reports_dir=_expand_path(paths.get("published_reports_dir", paths.get("reports_dir", "data/reports"))),
        settlement_reports_dir=_expand_path(paths.get("settlement_reports_dir", "data/reports/settlement")),
        logs_dir=_expand_path(paths.get("logs_dir", "logs")),
        logging_level=str(logging.get("level", "INFO")).upper(),
        sharepoint_base_url=str(sharepoint.get("base_url", "")).rstrip("/"),
        sharepoint_sync_root=_expand_path(sharepoint.get("sync_root", "")),
        # Microsoft Graph credentials for the RR settlement pipeline's --links
        # mode (live SharePoint share-link download). Secrets only, no
        # config.yaml fallback — set them in .env, same as Slack's tokens.
        sharepoint_tenant_id=os.getenv("SHAREPOINT_TENANT_ID", "").strip(),
        sharepoint_client_id=os.getenv("SHAREPOINT_CLIENT_ID", "").strip(),
        sharepoint_client_secret=os.getenv("SHAREPOINT_CLIENT_SECRET", "").strip(),
        report_engine=str(report.get("engine", "claude_code")),
        # Blank -> auto-discover the newest VSCode extension build. Per-machine
        # override via CLAUDE_CODE_BINARY in .env, same pattern as the secrets.
        claude_code_binary=str(report.get("claude_code_binary", "") or os.getenv("CLAUDE_CODE_BINARY", "")).strip(),
        report_model=str(report.get("model", "")),
        # Slack delivery. Prefer env vars (kept in .env, gitignored) and fall
        # back to optional values in config.yaml. A bot token + channel takes
        # precedence over the webhook; either path is enough on its own.
        slack_webhook_url=str(slack.get("webhook_url", "") or os.getenv("SLACK_WEBHOOK_URL", "")).strip(),
        slack_bot_token=str(slack.get("bot_token", "") or os.getenv("SLACK_BOT_TOKEN", "")).strip(),
        slack_channel=str(slack.get("channel", "") or os.getenv("SLACK_CHANNEL", "")).strip(),
    )


def ensure_runtime_dirs(config: AppConfig) -> None:
    for directory in (
        config.cuf_dir,
        config.suf_dir,
        config.protocols_dir,
        config.recommendation_reports_dir,
        config.rr_master_list_dir,
        config.state_file.parent,
        config.reports_dir,
        config.published_reports_dir,
        config.settlement_reports_dir,
        config.logs_dir,
    ):
        directory.mkdir(parents=True, exist_ok=True)
