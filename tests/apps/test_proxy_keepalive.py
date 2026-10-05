"""Il proxy della vista esterna e le connessioni keep-alive.

Il proxy riscriveva solo la **prima** richiesta di una connessione (Host,
prefisso di ``baseUrl``, cookie-capability tolto) e poi pompava byte grezzi: la
seconda richiesta della stessa connessione keep-alive arrivava al server
dell'utente com'era, con il cookie ``jafta_app_view`` dentro e l'``Host`` del
proxy. Adesso una connessione porta **una** richiesta: al server si chiede
``Connection: close``, al browser si risponde ``Connection: close``, e dopo il
body della prima richiesta non si inoltra altro. Resta fuori l'upgrade
WebSocket, che dopo il 101 non e' piu' HTTP.
"""

from __future__ import annotations

import asyncio

import pytest

from jafta.apps import proxy as proxy_mod
from jafta.apps.proxy import COOKIE_NAME, AppViewProxy


class _KeepAliveUpstream:
    """Un server che tiene viva la connessione e serve tutte le richieste che arrivano.

    Ignora ``Connection: close`` di proposito: e' il caso peggiore, e la
    protezione non deve dipendere dalla buona educazione del server.
    """

    def __init__(self, response_headers: bytes = b"Connection: keep-alive\r\n"):
        self.seen: list[str] = []
        self._headers = response_headers
        self.server = None
        self.port = None

    async def start(self):
        self.server = await asyncio.start_server(self._handle, "127.0.0.1", 0)
        self.port = self.server.sockets[0].getsockname()[1]

    async def _handle(self, reader, writer):
        buf = bytearray()
        try:
            while True:
                while b"\r\n\r\n" not in buf:
                    chunk = await reader.read(4096)
                    if not chunk:
                        return
                    buf.extend(chunk)
                head, _, rest = bytes(buf).partition(b"\r\n\r\n")
                buf = bytearray(rest)
                self.seen.append(head.decode("latin-1"))
                writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n" + self._headers
                             + b"\r\nOK")
                await writer.drain()
        finally:
            writer.close()

    async def close(self):
        self.server.close()
        await self.server.wait_closed()


@pytest.fixture
async def keepalive(monkeypatch):
    monkeypatch.setattr(proxy_mod, "validate_app_server_target", lambda url: (True, ""))
    up = _KeepAliveUpstream()
    await up.start()
    p = AppViewProxy("telecomando", f"http://127.0.0.1:{up.port}/base")
    await p.start()
    try:
        yield p, up
    finally:
        await p.close()
        await up.close()


def _get(path: str, cap: str) -> bytes:
    return (f"GET {path} HTTP/1.1\r\nHost: 127.0.0.1\r\n"
            f"Cookie: {COOKIE_NAME}={cap}; sid=abc\r\n\r\n").encode()


async def _exchange(port: int, data: bytes) -> bytes:
    """Come un browser: legge una risposta intera (``Content-Length``) e chiude.

    Non aspetta l'EOF del proxy: con un server che tiene viva la connessione
    l'EOF arriva solo dopo che il client ha chiuso, come col browser vero.
    """
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    writer.write(data)
    await writer.drain()
    try:
        head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=3)
        length = 0
        for line in head.decode("latin-1").split("\r\n")[1:]:
            name, _, value = line.partition(":")
            if name.strip().lower() == "content-length":
                length = int(value.strip())
        body = await asyncio.wait_for(reader.readexactly(length), timeout=3)
        return head + body
    finally:
        writer.close()


async def _read_all(port: int, data: bytes) -> bytes:
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    writer.write(data)
    await writer.drain()
    try:
        return await asyncio.wait_for(reader.read(-1), timeout=3)
    finally:
        writer.close()


async def test_a_second_request_on_the_connection_never_reaches_the_server_raw(keepalive):
    p, up = keepalive

    await _exchange(p.port, _get("/uno", p._cap) + _get("/due", p._cap))
    await asyncio.sleep(0.1)

    assert len(up.seen) == 1, up.seen
    for head in up.seen:
        assert p._cap not in head and COOKIE_NAME not in head, head
        assert f"Host: 127.0.0.1:{up.port}" in head, head
        assert head.startswith("GET /base/"), head


async def test_a_client_that_reuses_the_connection_is_not_forwarded(keepalive):
    """Il test qui sopra manda le due richieste insieme: la seconda arriva nei
    byte gia' letti con la testa, e non passa mai dal ciclo che scarta quel che
    il client manda **dopo** il body. Un client che ignora ``Connection: close``
    e riusa la connessione a risposta ricevuta, invece, ci passa: la seconda
    richiesta deve morire li', non arrivare cruda al server."""
    p, up = keepalive

    reader, writer = await asyncio.open_connection("127.0.0.1", p.port)
    try:
        writer.write(_get("/uno", p._cap))
        await writer.drain()
        await asyncio.wait_for(reader.readuntil(b"OK"), timeout=3)

        writer.write(_get("/due", p._cap))
        await writer.drain()
        await asyncio.sleep(0.2)
    finally:
        writer.close()

    assert [h.splitlines()[0] for h in up.seen] == ["GET /base/uno HTTP/1.1"]
    assert all(p._cap not in head for head in up.seen)


async def test_the_server_is_asked_to_close_and_the_browser_is_told_so(keepalive):
    p, up = keepalive

    out = await _exchange(p.port, _get("/uno", p._cap))

    head = out.decode("latin-1").split("\r\n\r\n")[0]
    assert "Connection: close" in head
    assert "keep-alive" not in head.lower()
    assert "Connection: close" in up.seen[0]


async def test_a_websocket_upgrade_still_goes_through(monkeypatch):
    """Dopo il 101 la connessione non e' piu' HTTP: niente ``close`` imposto."""
    monkeypatch.setattr(proxy_mod, "validate_app_server_target", lambda url: (True, ""))
    seen: list[str] = []

    async def _ws(reader, writer):
        buf = bytearray()
        while b"\r\n\r\n" not in buf:
            buf.extend(await reader.read(4096))
        head, _, rest = bytes(buf).partition(b"\r\n\r\n")
        seen.append(head.decode("latin-1"))
        writer.write(b"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\n"
                     b"Connection: Upgrade\r\n\r\n")
        await writer.drain()
        while len(rest) < 5:
            rest += await reader.read(5 - len(rest))
        writer.write(b"frame:" + rest)
        await writer.drain()
        writer.close()

    server = await asyncio.start_server(_ws, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    p = AppViewProxy("ws", f"http://127.0.0.1:{port}")
    await p.start()
    try:
        out = await _read_all(
            p.port,
            (f"GET /socket HTTP/1.1\r\nHost: h\r\nUpgrade: websocket\r\n"
             f"Connection: Upgrade\r\nCookie: {COOKIE_NAME}={p._cap}\r\n\r\nhello").encode(),
        )
    finally:
        await p.close()
        server.close()
        await server.wait_closed()

    assert "Connection: Upgrade" in seen[0] and "Upgrade: websocket" in seen[0]
    assert out.startswith(b"HTTP/1.1 101")
    assert b"Connection: Upgrade" in out
    assert out.endswith(b"frame:hello")
