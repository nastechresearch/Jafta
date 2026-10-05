"""Adapter di route HTTP per il file-manager del workspace (estratto da ws_http).

Stesso pattern router di ``SkillsRoutes``/``WikiRoutes``. Le operazioni su file
passano tutte per ``webui.workspace_files.validate_path`` (che delega al gate
unico symlink-safe/fail-closed del core — Fase 2).

Qui vivono solo letture e operazioni con parametri corti. La **scrittura** non
c'è di proposito: il contenuto di un file non può viaggiare su questo trasporto
(l'hook di handshake di ``websockets`` non legge body; query string e header
stanno in 8192 byte per riga e in ISO-8859-1), quindi ``workspace.write`` è un
comando dell'RPC WebSocket — v. ``webui.commands`` e ``channels.ws_rpc``.

Non ci sono nemmeno cancellazione, rinomina e copia: fino al 26/09/2026 erano
GET di questo router, cioe' scritture sul disco su una superficie di sola
lettura. Sono i comandi ``workspace.delete``/``rename``/``copy``, autenticati
all'handshake. Resta ``mkdir``, un parametro corto e idempotente.
"""

from __future__ import annotations

import asyncio
import mimetypes
from collections.abc import Callable
from pathlib import Path
from urllib.parse import quote

from websockets.datastructures import Headers
from websockets.http11 import Request as WsRequest
from websockets.http11 import Response

from jafta.channels.http_utils import (
    http_error,
    http_json_response,
    parse_query,
    query_first,
)

# A livello di modulo perché ora la traduce ``dispatch``; il resto di
# ``workspace_files`` resta importato dentro gli handler.
from jafta.webui.workspace_files import WorkspaceBinaryFileError, os_error_text


class WorkspaceRoutes:
    """Route ``/api/workspace/*``: letture del file manager, piu' ``mkdir``."""

    def __init__(
        self,
        *,
        check_api_token: Callable[[WsRequest], bool],
        get_workspace_root: Callable[[], Path],
    ) -> None:
        self._check_api_token = check_api_token
        self._get_workspace_root = get_workspace_root

    def _require_workspace_flag(
        self, attr: str, status: int, message: str
    ) -> Response | None:
        """Verifica un flag booleano di ``config.workspace``, fail-closed.

        Ritorna una ``Response`` di errore se il flag è disattivato oppure se
        ``load_config()`` solleva: in quest'ultimo caso NON si prosegue mai
        verso l'operazione filesystem (503), così un errore di config non
        scavalca silenziosamente il gate di sicurezza.
        """
        from jafta.config.loader import load_config

        try:
            allowed = bool(getattr(load_config().workspace, attr))
        except Exception:
            return http_error(503, "workspace configuration unavailable")
        if not allowed:
            return http_error(status, message)
        return None

    def _check_workspace_enabled(self) -> Response | None:
        return self._require_workspace_flag("enabled", 503, "workspace is disabled")

    async def dispatch(self, request: WsRequest, path: str) -> Response | None:
        """Auth, gate e traduzione degli errori del filesystem: qui, una volta.

        Gli handler ripetevano identici il controllo del token, il gate
        ``workspace.enabled`` e la stessa scala a quattro rami — cioè il modo
        più facile per lasciarne uno che risponde 500 dove gli altri
        rispondono 404. ``backup_routes.dispatch`` faceva già così.

        Il lookup dell'handler resta **prima** dell'auth: un path che non è di
        questo router deve continuare a tornare ``None`` senza che gli venga
        chiesto un token.
        """
        handlers = {
            "/api/workspace/list": self._list,
            "/api/workspace/read": self._read,
            "/api/workspace/mkdir": self._mkdir,
            "/api/workspace/download": self._download,
        }
        handler = handlers.get(path)
        if handler is None:
            return None
        if not self._check_api_token(request):
            return http_error(401, "Unauthorized")
        err = self._check_workspace_enabled()
        if err:
            return err
        try:
            return await handler(request)
        except WorkspaceBinaryFileError:
            # 415: il client (viewer workspace) reagisce delegando l'apertura
            # all'app di sistema via bridge nativo. Solo ``_read`` la solleva,
            # ma sta prima perché è più specifica di ``OSError``.
            return http_error(415, "binary file")
        except ValueError as e:
            return http_error(400, str(e))
        except FileNotFoundError:
            return http_error(404, "path not found")
        except PermissionError:
            return http_error(403, "permission denied")
        except OSError as e:
            # Il perche', non il dove: ``str(e)`` porta il percorso assoluto
            # della cartella privata dell'app.
            return http_error(400, os_error_text(e))

    async def _list(self, request: WsRequest) -> Response:
        from jafta.webui.workspace_files import list_directory, validate_path

        query = parse_query(request.path)
        rel_path = query_first(query, "path") or ""
        workspace_root = self._get_workspace_root()
        full_path = validate_path(workspace_root, rel_path)
        # Il disco fuori dal loop: una cartella grande
        # sono centinaia di ``stat``, e un file da aprire fino a ``max_size`` di
        # ``read_bytes`` — in cui il gateway non risponderebbe a nessuno.
        items = await asyncio.to_thread(
            list_directory, full_path, workspace_root=workspace_root
        )
        return http_json_response({"items": items, "path": rel_path})

    async def _read(self, request: WsRequest) -> Response:
        from jafta.webui.workspace_files import (
            read_file,
            validate_path,
        )

        query = parse_query(request.path)
        rel_path = query_first(query, "path") or ""
        workspace_root = self._get_workspace_root()
        full_path = validate_path(workspace_root, rel_path)
        from jafta.config.loader import load_config

        try:
            max_size = load_config().workspace.max_file_size
        except Exception:
            max_size = 1_000_000
        content = await asyncio.to_thread(read_file, full_path, max_size=max_size)
        return http_json_response({"content": content, "path": rel_path})

    async def _mkdir(self, request: WsRequest) -> Response:
        err = self._require_workspace_flag(
            "allow_write", 403, "workspace writes are disabled"
        )
        if err:
            return err
        from jafta.webui.workspace_files import create_directory, validate_path

        query = parse_query(request.path)
        rel_path = query_first(query, "path") or ""
        workspace_root = self._get_workspace_root()
        full_path = validate_path(workspace_root, rel_path)
        create_directory(full_path)
        return http_json_response({"success": True, "path": rel_path})

    async def _download(self, request: WsRequest) -> Response:
        from jafta.webui.workspace_files import read_download, validate_path

        query = parse_query(request.path)
        rel_path = query_first(query, "path") or ""
        workspace_root = self._get_workspace_root()
        full_path = validate_path(workspace_root, rel_path)
        try:
            data = await asyncio.to_thread(read_download, full_path)
        except IsADirectoryError:
            return http_error(400, "cannot download a directory")

        content_type = mimetypes.guess_type(full_path.name)[0] or "application/octet-stream"
        headers = Headers(
            [
                ("Content-Type", content_type),
                ("Content-Disposition", content_disposition(full_path.name)),
                # Il tipo lo decide l'estensione: che il browser non ne indovini
                # un altro dal contenuto (un ``.txt`` che «sembra» HTML).
                ("X-Content-Type-Options", "nosniff"),
            ]
        )
        return Response(200, "OK", headers, data)


def content_disposition(name: str) -> str:
    """``attachment`` con il nome del file, per qualunque nome (RFC 6266).

    Il nome finiva crudo fra virgolette: un'emoji o un
    accento facevano rifiutare l'header a ``websockets`` — 500 invece del file —,
    un ``"`` chiudeva il valore prima del tempo, e su POSIX un nome puo'
    contenere un a-capo, cioe' un header in piu'. Due parametri: ``filename*``
    in UTF-8 percent-encodato, che e' quello che i browser usano, e ``filename``
    in ASCII stampabile per chi non lo capisce, con ``\\`` e ``"`` escapati e
    tutto il resto sostituito da ``_``.

    Un nome che non e' UTF-8 — su Linux un nome e' fatto di byte, e Python porta
    quelli che non decodifica come surrogati — faceva sollevare ``quote``
    (``UnicodeEncodeError``, cioe' un 500). Quei byte diventano U+FFFD: l'header
    dichiara UTF-8, e i byte grezzi percent-encodati non lo sarebbero.
    """
    fallback = "".join(
        ("\\" + ch if ch in '"\\' else ch) if " " <= ch <= "~" else "_" for ch in name
    )
    readable = name.encode("utf-8", "surrogateescape").decode("utf-8", "replace")
    return f"attachment; filename=\"{fallback}\"; filename*=UTF-8''{quote(readable, safe='')}"
