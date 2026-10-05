"""Due reload di Telegram ravvicinati non lasciano un poller orfano.

``reload_telegram`` ferma il canale vecchio, rilegge la config e ne crea uno
nuovo. Senza serializzazione, un secondo reload arrivato mentre il primo
aspettava lo ``stop()`` trovava il posto vuoto, creava il suo canale, e poi il
primo sovrascriveva ``channels["telegram"]`` col proprio: il canale del secondo
restava a fare long polling, mai fermato — 409 da Telegram e update doppi.
"""

from __future__ import annotations

import asyncio

from jafta.bus.queue import MessageBus
from jafta.channels.dispatcher import WebSocketDispatcher
from jafta.config.schema import Config

TOKEN = "123456789:AAtestTOKENtestTOKENtestTOKEN"


class _FakeTelegram:
    instances: list[_FakeTelegram] = []

    def __init__(self, *_args, **_kwargs) -> None:
        self.started = False
        self.stopped = False
        _FakeTelegram.instances.append(self)

    async def start(self) -> None:
        self.started = True

    async def stop(self) -> None:
        # Lo stop vero cancella il poller e chiude l'API: qualche await.
        await asyncio.sleep(0.01)
        self.stopped = True


def _config() -> Config:
    return Config.model_validate({"telegram": {"enabled": True, "botToken": TOKEN}})


async def test_concurrent_reloads_leave_exactly_one_live_channel(monkeypatch) -> None:
    _FakeTelegram.instances = []
    monkeypatch.setattr("jafta.channels.telegram.TelegramChannel", _FakeTelegram)
    monkeypatch.setattr("jafta.config.loader.load_config", _config)
    dispatcher = WebSocketDispatcher(_config(), MessageBus())
    assert isinstance(dispatcher.channels["telegram"], _FakeTelegram)

    await asyncio.gather(dispatcher.reload_telegram(), dispatcher.reload_telegram())
    await asyncio.gather(*dispatcher._hot_tasks)

    live = [t for t in _FakeTelegram.instances if not t.stopped]
    assert live == [dispatcher.channels["telegram"]]
    assert len(_FakeTelegram.instances) == 3  # l'originale + uno per reload


async def test_a_failing_stop_still_lets_the_reload_proceed(monkeypatch) -> None:
    class _Broken(_FakeTelegram):
        async def stop(self) -> None:
            raise RuntimeError("boom")

    _FakeTelegram.instances = []
    monkeypatch.setattr("jafta.channels.telegram.TelegramChannel", _Broken)
    monkeypatch.setattr("jafta.config.loader.load_config", _config)
    dispatcher = WebSocketDispatcher(_config(), MessageBus())
    old = dispatcher.channels["telegram"]

    await dispatcher.reload_telegram()

    assert dispatcher.channels["telegram"] is not old


async def test_stop_cancels_the_poller_even_if_typing_fails() -> None:
    """Un'eccezione nello stop del typing lasciava vivo il long polling."""
    from jafta.channels.telegram import TelegramChannel
    from jafta.config.schema import TelegramConfig

    class _API:
        closed = False

        async def get_updates(self, offset, timeout_s):
            await asyncio.sleep(30)
            return []

        async def close(self) -> None:
            self.closed = True

    api = _API()
    channel = TelegramChannel(
        TelegramConfig(enabled=True, bot_token="TOKEN"), MessageBus(), api=api,
    )

    async def _boom() -> None:
        raise RuntimeError("typing stop failed")

    channel._typing.stop = _boom
    starting = asyncio.create_task(channel.start())
    await asyncio.sleep(0.01)
    poller = channel._poll_task

    try:
        await channel.stop()
    except RuntimeError:
        pass

    await asyncio.wait_for(starting, timeout=1)
    assert poller is not None and poller.done()
    assert api.closed
