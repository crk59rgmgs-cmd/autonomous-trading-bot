"""Persistent bot state.

GitHub Actions runners are ephemeral, so peak equity -- which the drawdown
kill switch depends on -- must be persisted between runs. The workflow commits
``logs/state.json`` back to the repository so the value survives.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from .logger import LOG_DIR, get_logger, utcnow

log = get_logger("state")

STATE_FILE = LOG_DIR / "state.json"

DEFAULT_STATE: Dict[str, Any] = {
    "peak_equity": 0.0,
    "halted": False,
    "halt_reason": "",
    "last_run": None,
    "runs": 0,
}


def load_state(path: Path = STATE_FILE) -> Dict[str, Any]:
    state = dict(DEFAULT_STATE)
    if not path.exists():
        log.info("No prior state file at %s; starting fresh.", path)
        return state
    try:
        with open(path, "r", encoding="utf-8") as handle:
            stored = json.load(handle)
        if isinstance(stored, dict):
            state.update(stored)
    except (json.JSONDecodeError, OSError) as exc:
        log.warning("Could not read state file %s (%s); using defaults.", path, exc)
    return state


def save_state(state: Dict[str, Any], path: Path = STATE_FILE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    state["last_run"] = utcnow().isoformat(timespec="seconds")
    tmp = path.with_suffix(".json.tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(state, handle, indent=2, sort_keys=True)
            handle.write("\n")
        tmp.replace(path)  # atomic, avoids a truncated file on crash
    except OSError as exc:
        log.error("Failed to persist state to %s: %s", path, exc)


def update_peak_equity(state: Dict[str, Any], equity: float) -> float:
    peak = max(float(state.get("peak_equity") or 0.0), float(equity))
    state["peak_equity"] = peak
    return peak
