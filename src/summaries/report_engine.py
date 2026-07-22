"""Summarization engines behind a single interface.

The report builder depends only on `ReportEngine.generate(...)`. Two concrete
engines implement it:

- `ClaudeCodeEngine` shells out to the bundled Claude Code CLI in headless mode,
  reusing the user's existing login (no API key, no separate billing).
- `StubEngine` returns canned structured output so the ingestion, contract, and
  HTML rendering can be built and tested without any model access.

The documented headless pattern is `<data> | claude -p "<instruction>"`: the
instruction goes in the `-p` argument, and the bulk document text is piped via
stdin (which avoids Windows command-line length limits).
"""
from __future__ import annotations

import json
import logging
import re
import subprocess
from pathlib import Path
from typing import Protocol

LOGGER = logging.getLogger(__name__)

_EXTENSIONS_GLOB = ".vscode/extensions"
_VERSION_RE = re.compile(r"anthropic\.claude-code-(\d+)\.(\d+)\.(\d+)")


class EngineError(RuntimeError):
    """Raised when a summarization engine fails to produce usable output."""


class ReportEngine(Protocol):
    def generate(self, instruction: str, context: str) -> dict:
        """Return the parsed JSON report object for the given prompt."""
        ...


def discover_claude_binary(home: Path | None = None) -> Path | None:
    """Find the newest bundled Claude Code CLI under the VSCode extensions dir."""
    home = home or Path.home()
    ext_dir = home / _EXTENSIONS_GLOB
    if not ext_dir.exists():
        return None
    candidates: list[tuple[tuple[int, int, int], Path]] = []
    for child in ext_dir.iterdir():
        match = _VERSION_RE.search(child.name)
        binary = child / "resources" / "native-binary" / "claude.exe"
        if match and binary.exists():
            version = (int(match.group(1)), int(match.group(2)), int(match.group(3)))
            candidates.append((version, binary))
    if not candidates:
        return None
    return max(candidates, key=lambda item: item[0])[1]


def _extract_json(text: str) -> dict:
    """Pull a JSON object out of model output, tolerating markdown fences."""
    stripped = text.strip()
    # Strip a leading ```json / ``` fence if present.
    fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", stripped, re.DOTALL)
    if fence:
        stripped = fence.group(1).strip()
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        pass
    # Fall back to the first balanced {...} span.
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(stripped[start : end + 1])
        except json.JSONDecodeError as exc:
            raise EngineError(f"Engine returned non-JSON output: {exc}") from exc
    raise EngineError("Engine output contained no JSON object")


class ClaudeCodeEngine:
    def __init__(self, binary: Path | str | None = None, model: str = "", timeout: int = 600) -> None:
        resolved = Path(binary) if binary else discover_claude_binary()
        if not resolved or not Path(resolved).exists():
            raise EngineError(
                "Claude Code CLI not found. Set report.claude_code_binary in config.yaml "
                "or install the VSCode extension."
            )
        self.binary = str(resolved)
        self.model = model
        self.timeout = timeout

    def generate(self, instruction: str, context: str) -> dict:
        cmd = [self.binary, "-p", instruction, "--output-format", "json"]
        if self.model:
            cmd += ["--model", self.model]
        LOGGER.info("Invoking Claude Code headless: %s", Path(self.binary).name)
        try:
            proc = subprocess.run(
                cmd,
                input=context,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=self.timeout,
            )
        except subprocess.TimeoutExpired as exc:
            raise EngineError(f"Claude Code headless timed out after {self.timeout}s") from exc
        if proc.returncode != 0:
            raise EngineError(f"Claude Code exited {proc.returncode}: {proc.stderr.strip()[:500]}")
        try:
            envelope = json.loads(proc.stdout)
        except json.JSONDecodeError as exc:
            raise EngineError(f"Could not parse CLI envelope: {exc}; stdout head: {proc.stdout[:300]}") from exc
        if envelope.get("is_error"):
            raise EngineError(f"Claude Code reported an error: {envelope.get('result', '')[:500]}")
        result_text = envelope.get("result", "")
        if not result_text:
            raise EngineError("Claude Code returned an empty result")
        return _extract_json(result_text)


class StubEngine:
    """Returns a fixed, contract-shaped report for offline development/testing."""

    def __init__(self, payload: dict | None = None) -> None:
        self._payload = payload or _SAMPLE_REPORT

    def generate(self, instruction: str, context: str) -> dict:
        LOGGER.info("Using stub summarization engine (no model call)")
        return self._payload


def build_engine(engine_name: str, *, binary: str = "", model: str = "") -> ReportEngine:
    if engine_name == "stub":
        return StubEngine()
    if engine_name == "claude_code":
        return ClaudeCodeEngine(binary=binary or None, model=model)
    raise EngineError(f"Unknown report engine: {engine_name!r} (expected 'claude_code' or 'stub')")


# A minimal but structurally complete sample so the renderer has something real
# to lay out when running offline. Content is illustrative, not sourced.
_SAMPLE_REPORT: dict = {
    "meta": {
        "cuf_date": "June 18, 2026",
        "suf_date": "April 9, 2026",
        "generated": "",
        "sources_line": "CUF Jun 18, 2026 · SUF Apr 9, 2026",
        "files_read": ["(02) Agenda", "(06) CROW 6 Upgrade", "(07) Markets Releases"],
        "files_skipped": [{"name": "Action Items", "reason": "image PDF, no text layer"}],
    },
    "areas": [
        {
            "key": "rto_markets",
            "summary": "Web services V23/V18 confirmed; fall settlement bundle coming.",
            "items": [
                {
                    "tag": "CUF · 6/18",
                    "title": "Energy V23 & Market V18 web services",
                    "detail": "Activation MTE 9/28, PROD 11/2; V22/V17 retirement TBD.",
                    "dates": [{"label": "Activation", "value": "MTE 9/28, PROD 11/2"}],
                    "sources": [{"label": "Markets Releases — CUF June 2026, p.2-3", "url": ""}],
                }
            ],
        },
        {"key": "asset_operations", "summary": "CROW 6 upgrade heading to production.", "items": []},
        {"key": "transmissions", "summary": "Order 881 schedule reframed.", "items": []},
        {"key": "etrm", "summary": "SPP West live; WEIS winding down.", "items": []},
        {"key": "optimization", "summary": "Storage calibration change live with RTOE.", "items": []},
    ],
    "timeline": [
        {"date": "Apr 1, 2026", "label": "RTO Expansion go-live", "past": True},
        {"date": "Jul 28, 2026", "label": "CROW 6 Upgrade — production", "past": False},
    ],
    "narrative": [
        {
            "heading": "RTO Expansion go-live and WEIS wind-down",
            "paragraphs": ["RTO Expansion went live across the Western Interconnection on April 1, 2026."],
            "impact": "Impactful: new settlement charge/credit types → RTO Markets settlement config.",
            "sources": [{"label": "SUF Meeting Materials 20260409, p.6", "url": ""}],
        }
    ],
}
