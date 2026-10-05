"""Async message queue for decoupled channel-agent communication."""

import asyncio

from loguru import logger

from jafta.bus.events import InboundMessage, OutboundMessage


class MessageBus:
    """
    Async message bus that decouples chat channels from the agent core.

    Channels push messages to the inbound queue, and the agent processes
    them and pushes responses to the outbound queue.

    Le code possono essere limitate (``maxsize``) per fornire backpressure su
    dispositivi con poca memoria (Android). ``maxsize <= 0`` significa coda
    illimitata (comportamento storico, usato di default e in tutti i test).
    """

    def __init__(self, *, inbound_maxsize: int = 0, outbound_maxsize: int = 0):
        self.inbound: asyncio.Queue[InboundMessage] = asyncio.Queue(
            maxsize=max(0, inbound_maxsize)
        )
        self.outbound: asyncio.Queue[OutboundMessage] = asyncio.Queue(
            maxsize=max(0, outbound_maxsize)
        )
        self._dropped_outbound = 0
        # Stato degli stream sotto backpressure (solo su coda limitata, v.
        # ``try_publish_outbound``): il testo visto per ogni stream aperto, gli
        # stream che hanno perso almeno un delta, e gli ``stream_end`` che non
        # sono entrati in coda e aspettano il prossimo messaggio della chat.
        self._stream_texts: dict[tuple[str, str, str], list[str]] = {}
        self._degraded_streams: set[tuple[str, str, str]] = set()
        self._pending_stream_ends: dict[tuple[str, str], list[OutboundMessage]] = {}

    async def publish_inbound(self, msg: InboundMessage) -> None:
        """Publish a message from a channel to the agent.

        Su coda limitata, blocca il produttore quando è piena: è la backpressure
        corretta (un agente lento deve rallentare l'intake dei messaggi)."""
        await self.inbound.put(msg)

    async def consume_inbound(self) -> InboundMessage:
        """Consume the next inbound message (blocks until available)."""
        return await self.inbound.get()

    async def publish_outbound(self, msg: OutboundMessage) -> None:
        """Publish a response from the agent to channels (blocking).

        Da usare per i messaggi che NON devono mai essere persi (risposta finale,
        turn_end). Per i messaggi transient usare ``try_publish_outbound``.

        Prima del messaggio passano gli ``stream_end`` della stessa chat che la
        coda piena aveva respinto (v. ``try_publish_outbound``): chiudono il
        loro stream, e vanno davanti al finale del turno."""
        for end in self._pending_stream_ends.pop((msg.channel, msg.chat_id), ()):
            await self.outbound.put(end)
        if msg.metadata.get("_turn_end") and self._stream_texts:
            # Un turno interrotto (``/stop``) può lasciare uno stream senza
            # ``stream_end``: il suo testo non serve più a nessuno.
            for key in [k for k in self._stream_texts if k[:2] == (msg.channel, msg.chat_id)]:
                self._forget_stream(key)
        await self.outbound.put(msg)

    async def consume_outbound(self) -> OutboundMessage:
        """Consume the next outbound message (blocks until available)."""
        return await self.outbound.get()

    def try_publish_outbound(self, msg: OutboundMessage) -> bool:
        """Accoda senza bloccare; ritorna ``False`` (scartato) se la coda outbound
        è piena.

        Pensato per i messaggi transient (stream delta, progress, reasoning) su
        code limitate. Su coda illimitata (default) non scarta mai → identico a
        ``publish_outbound``.

        **Un delta perso non si perde per sempre.** Il finale di un turno
        streammato è ``_streamed`` e non si rispedisce alla WebUI, quindi il
        testo di un delta scartato mancava dalla bolla e dal transcript (512
        parole su 800, misurato). Per questo, su coda limitata, il bus tiene il
        testo di ogni stream aperto; se ne ha scartato anche un solo delta, lo
        ``stream_end`` di quello stream parte con il testo intero del segmento
        in ``_stream_full_text``, che il canale usa al posto dei delta (il
        client sostituisce il blocco, il transcript riscrive la riga). E se è lo
        ``stream_end`` stesso a non entrare in coda, lo si tiene da parte: esce
        prima del prossimo messaggio della stessa chat, transient o bloccante
        (il finale o il ``turn_end`` arrivano sempre). Mai dopo: i frame del
        segmento successivo che lo scavalcassero chiuderebbero la bolla
        sbagliata, e il testo intero dell'end in ritardo la duplicherebbe.
        """
        key = self._stream_key(msg)
        is_end = bool(key and msg.metadata.get("_stream_end"))
        if key is not None:
            if msg.metadata.get("_stream_delta") and msg.content:
                self._stream_texts.setdefault(key, []).append(msg.content)
            if is_end and key in self._degraded_streams:
                msg = self._authoritative_end(msg, key)
        try:
            # Un end trattenuto che non entra vuol dire coda piena: *msg* non
            # entrerebbe comunque, e così non lo scavalca.
            self._flush_pending_ends_nowait(msg.channel, msg.chat_id)
            self.outbound.put_nowait(msg)
        except asyncio.QueueFull:
            self._dropped_outbound += 1
            if self._dropped_outbound % 100 == 1:
                logger.warning(
                    "Outbound queue full; dropped {} transient message(s) so far",
                    self._dropped_outbound,
                )
            if key is not None:
                if is_end:
                    # Il testo intero viaggia solo se lo stream ha perso delta
                    # (già allegato sopra): se manca solo l'end, il canale ha
                    # già tutto il testo nel suo buffer.
                    self._pending_stream_ends.setdefault(
                        (msg.channel, msg.chat_id), [],
                    ).append(msg)
                    self._forget_stream(key)
                else:
                    self._degraded_streams.add(key)
            return False
        if is_end and key is not None:
            self._forget_stream(key)
        return True

    def _flush_pending_ends_nowait(self, channel: str, chat_id: str) -> None:
        """Accoda gli end trattenuti della chat, in ordine; ``QueueFull`` se non entrano.

        Quelli che non entrano restano trattenuti, davanti a tutto il resto.
        """
        pending = self._pending_stream_ends.get((channel, chat_id))
        while pending:
            self.outbound.put_nowait(pending[0])
            pending.pop(0)
        self._pending_stream_ends.pop((channel, chat_id), None)

    def _stream_key(self, msg: OutboundMessage) -> tuple[str, str, str] | None:
        """Chiave dello stream di *msg*, o ``None`` se non è un delta/end da seguire.

        Su coda illimitata niente si scarta, quindi non serve tenere nulla.
        """
        if self.outbound.maxsize <= 0:
            return None
        meta = msg.metadata or {}
        if not (meta.get("_stream_delta") or meta.get("_stream_end")):
            return None
        return (msg.channel, msg.chat_id, str(meta.get("_stream_id") or ""))

    def _authoritative_end(
        self, msg: OutboundMessage, key: tuple[str, str, str],
    ) -> OutboundMessage:
        """Lo ``stream_end`` di *msg* con il testo intero dello stream."""
        return OutboundMessage(
            channel=msg.channel,
            chat_id=msg.chat_id,
            content=msg.content,
            media=msg.media,
            metadata={
                **msg.metadata,
                "_stream_full_text": "".join(self._stream_texts.get(key, ())),
            },
            buttons=msg.buttons,
        )

    def _forget_stream(self, key: tuple[str, str, str]) -> None:
        self._stream_texts.pop(key, None)
        self._degraded_streams.discard(key)

    @property
    def outbound_size(self) -> int:
        """Number of pending outbound messages."""
        return self.outbound.qsize()
