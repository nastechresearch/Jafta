"""Runtime API — policy layer for the local OpenCode runtime.

The Kotlin `RuntimeBridge` owns the mechanics (foreground service, process,
state). This module owns the policy: what phases are shown, how progress is
shaped for the UI, what is safe to expose, and the poll budget.

Mirrors the split in `power.py` / `PowerBridge`: Python decides *when* and
*what to show*; Kotlin does the heavy lifting.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from loguru import logger

# `from java import jclass` is only available under the Chaquopy runtime.
# We import it lazily inside the wrapper class.


# ---------------------------------------------------------------------------
# Phase constants — the UI knows these; never expose a raw Kotlin enum value
# ---------------------------------------------------------------------------

_PHASE_ABSENT = "absent"
_PHASE_DOWNLOADING = "downloading"
_PHASE_EXTRACTING = "extracting"
_PHASE_ACTIVATING = "activating"
_PHASE_STARTING = "starting"
_PHASE_READY = "ready"
_PHASE_ERROR = "error"
_PHASE_UNSUPPORTED = "unsupported"
_PHASE_PROMPT = "prompt"          # terminal for the process, waiting for human

# i18n keys for the note line — the UI never receives a literal string
_NOTE_KEYS = {
    _PHASE_ABSENT: "runtime.status.absent",
    _PHASE_DOWNLOADING: "runtime.status.downloading",
    _PHASE_EXTRACTING: "runtime.status.extracting",
    _PHASE_ACTIVATING: "runtime.status.activating",
    _PHASE_STARTING: "runtime.status.starting",
    _PHASE_READY: "runtime.status.ready",
    _PHASE_ERROR: "runtime.status.error",
    _PHASE_UNSUPPORTED: "runtime.status.unsupported",
    _PHASE_PROMPT: "runtime.status.prompt",
}

# ---------------------------------------------------------------------------
# RuntimeBridge binding (Chaquopy)
# ---------------------------------------------------------------------------

class _RuntimeBridge:
    """Thin wrapper around the Chaquopy jclass. Never raises to Python."""

    def __init__(self) -> None:
        try:
            from java import jclass
            self._bridge = jclass("com.nastechresearch.jafta.RuntimeBridge")()
        except Exception as e:
            logger.error("RuntimeBridge init failed: {}", e)
            self._bridge = None

    def _call(self, method: str, default: Any) -> Any:
        if self._bridge is None:
            return default
        try:
            return getattr(self._bridge, method)()
        except Exception as e:          # noqa: BLE001 — boundary, never raise
            logger.error("RuntimeBridge.{}: {}", method, e)
            return default

    def status(self) -> str:           # JSON from Kotlin
        return self._call("status", '{"phase":"error","detail":"bridge unavailable"}')

    def install(self) -> bool:
        return self._call("install", False)

    def start(self) -> bool:
        return self._call("start", False)

    def stop(self) -> bool:
        return self._call("stop", False)

    def delete(self) -> bool:
        return self._call("delete", False)

    def diagnostics(self) -> str:
        return self._call("diagnostics", '{"error":"diagnostics unavailable"}')

    def supports_abi(self) -> bool:
        return self._call("supportsAbi", False)

    def installed_port(self) -> int:
        return self._call("installedPort", -1)

    def is_healthy(self) -> bool:
        return self._call("isHealthy", False)


_BRIDGE = _RuntimeBridge()

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class RuntimeStatus:
    """What the UI receives — already shaped, with i18n keys only."""

    phase: str
    progress: int
    detail: str
    note_key: str
    healthy: bool
    port: int
    abi_supported: bool


def _map_phase(kotlin_phase: str) -> str:
    """Kotlin enum → UI phase. Unknown → error (safe default)."""
    return {
        "Disconnected": _PHASE_ABSENT,
        "Connecting": _PHASE_DOWNLOADING,   # Kotlin doesn't distinguish download/extract/activate
        "Connected": _PHASE_READY,
        "Failed": _PHASE_ERROR,
        "Unavailable": _PHASE_UNSUPPORTED,
    }.get(kotlin_phase, _PHASE_ERROR)


def _shape_status(raw: str) -> RuntimeStatus:
    """Parse Kotlin JSON, map to UI shape with i18n keys only."""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        logger.error("RuntimeBridge.status returned invalid JSON: {}", raw)
        return RuntimeStatus(
            phase=_PHASE_ERROR,
            progress=0,
            detail="bridge returned invalid JSON",
            note_key=_NOTE_KEYS[_PHASE_ERROR],
            healthy=False,
            port=-1,
            abi_supported=False,
        )

    kotlin_phase = data.get("phase", "Failed")
    phase = _map_phase(kotlin_phase)
    progress = max(0, min(100, int(data.get("progress", 0))))
    detail = data.get("detail", "")
    healthy = data.get("healthy", False)
    port = data.get("port", -1)
    abi_ok = data.get("abiSupported", False)

    note_key = _NOTE_KEYS.get(phase, _NOTE_KEYS[_PHASE_ERROR])

    return RuntimeStatus(
        phase=phase,
        progress=progress,
        detail=detail,
        note_key=note_key,
        healthy=healthy,
        port=port,
        abi_supported=abi_ok,
    )


# ---------------------------------------------------------------------------
# Public functions — used by routes and by the WebSocket progress stream
# ---------------------------------------------------------------------------


def runtime_status() -> RuntimeStatus:
    """Current runtime status, shaped for the UI."""
    return _shape_status(_BRIDGE.status())


def runtime_install() -> bool:
    """Start full install (download + extract + activate + start)."""
    return _BRIDGE.install()


def runtime_start() -> bool:
    """Start an already-installed runtime."""
    return _BRIDGE.start()


def runtime_stop() -> bool:
    """Stop the running runtime."""
    return _BRIDGE.stop()


def runtime_delete() -> bool:
    """Delete everything (rootfs, binaries, logs, cache)."""
    return _BRIDGE.delete()


def runtime_diagnostics() -> dict:
    """Diagnostics as a parsed dict (disk, memory, PID, uptime, log tail)."""
    try:
        return json.loads(_BRIDGE.diagnostics())
    except json.JSONDecodeError:
        return {"error": "diagnostics unavailable"}


def runtime_abi_supported() -> bool:
    return _BRIDGE.supports_abi()


def runtime_installed_port() -> int:
    return _BRIDGE.installed_port()


def runtime_is_healthy() -> bool:
    return _BRIDGE.is_healthy()
