"""HTTP route adapter for the local OpenCode runtime API.

Keep Runtime route handlers here, not in ``channels/websocket.py``.
The websocket channel owns transport concerns; this module owns Runtime
request mapping and response shaping.

**No secret ever travels in an HTTP request.** The four writes that carry
a secret are not here: the provider key (``provider/update``,
``provider-models``), the Telegram token (``telegram/save``) and the SSH
password (``ssh/host/save``) went into the query string, which is logged
and visible in tracebacks. They are WebSocket RPC commands in
``webui/commands.py`` (``settings.provider.models``/``update``,
``telegram.save``, ``ssh.host.save``). This module only serves read-only
status and write operations that do not carry credentials — install/start/
stop/delete are user-triggered actions that the Kotlin side authorizes via
the foreground service notification and the existing battery/permission
gates.
"""

from __future__ import annotations

from typing import Any

from websockets.http11 import Request as WsRequest
from websockets.http11 import Response

from jafta.bus.queue import MessageBus
from jafta.channels.http_utils import http_error, http_json_response, http_response
from jafta.webui.runtime_api import (
    RuntimeStatus,
    runtime_delete,
    runtime_diagnostics,
    runtime_install,
    runtime_start,
    runtime_status,
    runtime_stop,
)

# ---------------------------------------------------------------------------
# Read endpoints
# ---------------------------------------------------------------------------


async def _status(request: WsRequest, bus: MessageBus) -> Response:
    """Current runtime status — polled by the UI during install."""
    status: RuntimeStatus = runtime_status()
    return http_json_response(
        {
            "phase": status.phase,
            "progress": status.progress,
            "detail": status.detail,
            "note_key": status.note_key,
            "healthy": status.healthy,
            "port": status.port,
            "abi_supported": status.abi_supported,
        }
    )


async def _diagnostics(request: WsRequest, bus: MessageBus) -> Response:
    """Full diagnostics payload (disk, memory, PID, uptime, log tail)."""
    return http_json_response(runtime_diagnostics())


# ---------------------------------------------------------------------------
# Write endpoints — no secrets, user-triggered actions
# ---------------------------------------------------------------------------


async def _install(request: WsRequest, bus: MessageBus) -> Response:
    """Start full install: download rootfs + OpenCode, extract, activate, start."""
    ok = runtime_install()
    return http_response(200, b"") if ok else http_error(500, "install could not start")


async def _start(request: WsRequest, bus: MessageBus) -> Response:
    """Start an already-installed runtime."""
    ok = runtime_start()
    return http_response(200, b"") if ok else http_error(500, "start could not start")


async def _stop(request: WsRequest, bus: MessageBus) -> Response:
    """Stop the running runtime."""
    ok = runtime_stop()
    return http_response(200, b"") if ok else http_error(500, "stop could not start")


async def _delete(request: WsRequest, bus: MessageBus) -> Response:
    """Delete everything: rootfs, binaries, logs, cache."""
    ok = runtime_delete()
    return http_response(200, b"") if ok else http_error(500, "delete could not start")


# ---------------------------------------------------------------------------
# Route table
# ---------------------------------------------------------------------------

RUNTIME_ROUTES: dict[str, tuple[str, Any]] = {
    # reads
    "GET /api/runtime/status": (_status, "runtime.status"),
    "GET /api/runtime/diagnostics": (_diagnostics, "runtime.diagnostics"),
    # writes — no secrets, no query-string credentials
    "POST /api/runtime/install": (_install, "runtime.install"),
    "POST /api/runtime/start": (_start, "runtime.start"),
    "POST /api/runtime/stop": (_stop, "runtime.stop"),
    "POST /api/runtime/delete": (_delete, "runtime.delete"),
}
