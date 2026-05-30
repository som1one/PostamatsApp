"""Per-worker support-chat connection hub.

This module owns the **in-memory, per-worker** registry of live WebSocket
connections and the logic that fans a :class:`~backend.realtime.events.ChatEvent`
out to the right local sockets, plus the Redis pub/sub plumbing that lets a
multi-worker deployment deliver an event produced on one worker to sockets held
by another (design → *Connection Hub interface* and *Redis pub/sub channel
design*; Requirements 15.1, 15.2, 15.3).

Responsibilities
----------------

* **Registry.** Track local *client* sockets grouped by ``conversation_id`` and
  local *operator* sockets together with the ``conversation_id`` each operator
  currently has open (used to filter conversation-scoped operator events).
* **Pure recipient selection.** :meth:`ConnectionHub.select_recipients` computes
  *which* local sockets an event should go to, with **no socket I/O**. Keeping
  selection pure and separate from the awaited sends makes it directly unit-/
  property-testable (design Property 18, task 4.3).
* **Local dispatch.** :meth:`ConnectionHub.dispatch_local` selects recipients and
  then performs the awaited sends, guarding each one so a single dead socket
  cannot break the fan-out loop (dead sockets are unregistered).
* **Cross-worker fan-out.** :meth:`ConnectionHub.publish` pushes the event to the
  single ``support:events`` Redis channel (and nothing else), while
  :meth:`ConnectionHub.deliver` does the full producer-side delivery
  (``dispatch_local`` + ``publish``) and :meth:`ConnectionHub.run_subscriber`
  consumes the channel and dispatches what *other* workers publish.

Delivery model (``deliver`` vs ``publish`` vs ``dispatch_local``)
-----------------------------------------------------------------

Three deliberately separate operations, so callers compose exactly the behavior
they need and each piece stays independently testable:

* :meth:`dispatch_local` — send to matching **local** sockets only. Pure-local;
  no Redis.
* :meth:`publish` — push the event to the Redis bus **only**. Pure-Redis; no
  local sends. A no-op when ``get_redis_client()`` is ``None`` (Redis down): it
  never raises, because the event is assumed already persisted upstream
  (persist-before-publish, Requirements 14.1/15.1/15.3).
* :meth:`deliver` — the producer-side convenience: ``dispatch_local`` **then**
  ``publish``. Local delivery happens first so same-worker recipients never wait
  on the Redis round-trip and still receive the event when Redis is down; the
  publish then fans the event out to the other workers.

Recipient-selection rule (design Property 18)
---------------------------------------------

Selection keys purely off the event's :class:`~backend.realtime.events.Audience`
and its ``conversation_id`` — it never inspects the event ``type`` — which keeps
the rule clean and trivially testable:

* :attr:`Audience.CLIENT` → the client sockets registered for the event's
  ``conversation_id`` (no operators).
* :attr:`Audience.OPERATORS` → **all** local operator sockets. These are the
  *list-level* events (``unread.update``, ``conversation.updated``,
  ``assignment.changed``, ``status.changed`` at the list level) that every
  operator's list view cares about regardless of which conversation they
  currently have open.
* :attr:`Audience.BOTH` → the union of the *client* rule and the
  *conversation-scoped operator* rule: the conversation's client sockets **plus**
  only those operator sockets whose currently-open conversation equals the
  event's ``conversation_id``. These are the conversation-scoped events
  (``message.new``) that only matter to an operator while they are actively
  looking at that conversation.

Note on same-worker duplicate delivery
---------------------------------------

When the producing worker calls :meth:`deliver`, it dispatches locally **and**
publishes to Redis. Because this worker's own :meth:`run_subscriber` is also
subscribed to ``support:events``, it will receive the event it just published and
dispatch it locally a second time. This is intentional and harmless: it keeps
local delivery independent of the Redis round-trip (so it still works when Redis
is down) while the client-side message-list merge reducer deduplicates by message
``id`` (design Property 8), and the list-level events (unread/assignment/status)
are idempotent "latest value wins" updates. Avoiding the duplicate would require
tagging published frames with an origin-worker id, which would change the
on-the-wire bus envelope owned by :mod:`backend.realtime.events`; the
dedup-on-receive approach is the design's chosen tradeoff.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

from backend.core.redis import get_redis_client
from backend.realtime.events import Audience, ChatEvent

logger = logging.getLogger(__name__)


#: The single Redis pub/sub channel every chat event is published to. A single
#: channel avoids subscribe/unsubscribe churn as operators open/close
#: conversations; each worker filters events it does not need in-memory (design
#: → *Redis pub/sub channel design*).
SUPPORT_EVENTS_CHANNEL = "support:events"


#: A connected WebSocket. The hub treats sockets opaquely: it only requires that
#: a socket be hashable (identity is fine) and expose an awaitable ``send_json``
#: or, failing that, an awaitable ``send_text``. Typed as ``Any`` so tests and
#: the gateway can pass lightweight stand-ins without importing Starlette here.
Socket = Any


def _normalize_conversation_id(conversation_id: Any) -> str | None:
    """Coerce a conversation id to the ``str`` key form used by the registries.

    Returns ``None`` unchanged so events not tied to a conversation never match a
    keyed client bucket.
    """
    if conversation_id is None:
        return None
    return str(conversation_id)


@dataclass(frozen=True)
class LocalRecipients:
    """Recipient selection split into client vs operator sockets.

    Splitting recipients this way lets :meth:`ConnectionHub.dispatch_local`
    unregister a dead socket against the *correct* registry on send failure. It
    is an internal helper value; the public, property-tested entry point is
    :meth:`ConnectionHub.select_recipients`, which returns the flat union.
    """

    clients: frozenset
    operators: frozenset

    @property
    def all(self) -> frozenset:
        """The union of client and operator recipient sockets."""
        return self.clients | self.operators


class ConnectionHub:
    """Per-worker WebSocket registry, local dispatcher, and Redis bridge.

    A single module-level instance is shared per worker via
    :func:`get_connection_hub`; the WS gateway (task 4.4) and the app lifecycle
    wiring (task 5.3) both resolve the hub through that accessor. This class does
    no global work on import and opens no Redis connection until
    :meth:`run_subscriber` runs.
    """

    def __init__(self) -> None:
        # Client sockets grouped by conversation id: { conversation_id -> {socket} }.
        self._clients: dict[str, set[Socket]] = {}
        # Operator sockets mapped to the conversation each currently has open
        # (``None`` when the operator is on the list view with nothing open).
        self._operators: dict[Socket, str | None] = {}
        # The background Redis subscriber task, when running.
        self._subscriber_task: asyncio.Task[None] | None = None

    # ------------------------------------------------------------------
    # Registry mutations (synchronous, in-memory)
    # ------------------------------------------------------------------

    def register_client(self, conversation_id: Any, socket: Socket) -> None:
        """Register a client ``socket`` as a participant of ``conversation_id``."""
        cid = _normalize_conversation_id(conversation_id)
        if cid is None:
            # A client socket is always bound to a concrete conversation; ignore
            # a missing id rather than creating an unreachable ``None`` bucket.
            return
        self._clients.setdefault(cid, set()).add(socket)

    def unregister_client(self, conversation_id: Any, socket: Socket) -> None:
        """Remove a client ``socket`` from ``conversation_id`` (idempotent)."""
        cid = _normalize_conversation_id(conversation_id)
        if cid is None:
            return
        sockets = self._clients.get(cid)
        if not sockets:
            return
        sockets.discard(socket)
        if not sockets:
            # Drop empty buckets so the registry does not grow without bound.
            del self._clients[cid]

    def register_operator(self, socket: Socket) -> None:
        """Register an operator ``socket`` with no conversation open yet.

        Idempotent: re-registering an already-known operator preserves whichever
        conversation it currently has open.
        """
        self._operators.setdefault(socket, None)

    def unregister_operator(self, socket: Socket) -> None:
        """Remove an operator ``socket`` from the registry (idempotent)."""
        self._operators.pop(socket, None)

    def set_operator_open_conversation(self, socket: Socket, conversation_id: Any) -> None:
        """Set which conversation an operator ``socket`` currently has open.

        Pass ``conversation_id=None`` when the operator returns to the list view.
        Registers the operator if it is not already known, so callers can use
        this without a separate :meth:`register_operator` call.
        """
        self._operators[socket] = _normalize_conversation_id(conversation_id)

    # ------------------------------------------------------------------
    # Pure recipient selection (no I/O) — design Property 18
    # ------------------------------------------------------------------

    def select_recipients(self, event: ChatEvent) -> set[Socket]:
        """Compute the set of local sockets ``event`` should be delivered to.

        Pure function of the current registry state plus the event's audience and
        conversation id — performs **no** socket I/O — so task 4.3's property test
        (design Property 18) can exercise the routing rule in isolation. Returns a
        plain ``set`` (the union of client and operator recipients). See the
        module docstring for the full rule.
        """
        split = self._select_recipients_split(event)
        return set(split.all)

    def _select_recipients_split(self, event: ChatEvent) -> LocalRecipients:
        """Recipient selection split into ``clients`` / ``operators``.

        Internal counterpart to :meth:`select_recipients`; the split lets
        :meth:`dispatch_local` unregister a failed send against the right
        registry. Equally pure — no socket I/O.
        """
        cid = _normalize_conversation_id(event.conversation_id)

        clients: frozenset = frozenset()
        operators: frozenset = frozenset()

        if event.audience in (Audience.CLIENT, Audience.BOTH) and cid is not None:
            # Client recipients are always the sockets registered for this
            # conversation (snapshot into a new set to decouple from the registry).
            clients = frozenset(self._clients.get(cid, ()))

        if event.audience == Audience.OPERATORS:
            # List-level operator events go to every connected operator.
            operators = frozenset(self._operators.keys())
        elif event.audience == Audience.BOTH:
            # Conversation-scoped operator events go only to operators whose
            # currently-open conversation matches this event's conversation.
            if cid is not None:
                operators = frozenset(
                    socket
                    for socket, open_cid in self._operators.items()
                    if open_cid == cid
                )

        return LocalRecipients(clients=clients, operators=operators)

    # ------------------------------------------------------------------
    # Local dispatch (awaited sends)
    # ------------------------------------------------------------------

    async def dispatch_local(self, event: ChatEvent) -> None:
        """Send ``event`` to its matching local sockets.

        Picks recipients via the pure selector, then awaits a send per socket.
        Each send is guarded so one dead socket cannot break the loop; sockets
        that fail are unregistered against the correct registry afterwards.
        """
        recipients = self._select_recipients_split(event)
        if not recipients.clients and not recipients.operators:
            return

        frame = event.to_frame()
        conversation_id = event.conversation_id

        dead_clients: list[Socket] = []
        for socket in recipients.clients:
            if not await _safe_send(socket, frame):
                dead_clients.append(socket)

        dead_operators: list[Socket] = []
        for socket in recipients.operators:
            if not await _safe_send(socket, frame):
                dead_operators.append(socket)

        for socket in dead_clients:
            self.unregister_client(conversation_id, socket)
        for socket in dead_operators:
            self.unregister_operator(socket)

    # ------------------------------------------------------------------
    # Cross-worker fan-out via Redis
    # ------------------------------------------------------------------

    async def publish(self, event: ChatEvent) -> None:
        """Publish ``event`` to the Redis bus (and nothing else).

        Pure-Redis: this performs **no** local delivery — use :meth:`deliver` for
        the full producer-side path, or call :meth:`dispatch_local` yourself.

        The event is assumed already persisted upstream (persist-before-publish,
        Requirements 14.1/15.1). If ``get_redis_client()`` returns ``None`` (Redis
        down) the publish is skipped without raising — durability is unaffected
        (Requirement 15.3) and cross-worker/offline recipients reconcile via REST
        history on reconnect (Requirement 15.4). A transient publish failure is
        logged and swallowed for the same reason.
        """
        client = get_redis_client()
        if client is None:
            return

        try:
            await client.publish(SUPPORT_EVENTS_CHANNEL, event.to_bus_json())
        except Exception:
            logger.warning(
                "Failed to publish support chat event to Redis; "
                "local recipients already delivered, others reconcile on reconnect",
                exc_info=True,
            )

    async def deliver(self, event: ChatEvent) -> None:
        """Full producer-side delivery: dispatch locally, then publish to Redis.

        Local delivery happens first so same-worker recipients never wait on the
        Redis round-trip (and still receive the event when Redis is down); the
        publish then fans the event out to the other workers. Call this after the
        event's message has been persisted.
        """
        await self.dispatch_local(event)
        await self.publish(event)

    async def run_subscriber(self) -> None:
        """Background task: consume ``support:events`` and dispatch each event.

        Subscribes to the single channel, rebuilds every received frame with
        :meth:`ChatEvent.from_bus_json`, and hands it to :meth:`dispatch_local`.
        If Redis is unavailable the hub runs in local-only mode: this returns
        immediately so the app still starts without Redis (Requirement 15.3).
        Cancellation (app shutdown) is propagated; any other error is logged so a
        transient bus hiccup does not crash the worker.
        """
        client = get_redis_client()
        if client is None:
            logger.info(
                "Redis unavailable; support chat running in local-only mode "
                "(no cross-worker fan-out)"
            )
            return

        pubsub = client.pubsub()
        try:
            await pubsub.subscribe(SUPPORT_EVENTS_CHANNEL)
            async for message in pubsub.listen():
                if not message or message.get("type") != "message":
                    # Skip subscribe confirmations and keepalives.
                    continue
                raw = message.get("data")
                if raw is None:
                    continue
                if isinstance(raw, bytes):
                    raw = raw.decode("utf-8")
                try:
                    event = ChatEvent.from_bus_json(raw)
                except Exception:
                    logger.warning(
                        "Discarding malformed support chat bus message", exc_info=True
                    )
                    continue
                await self.dispatch_local(event)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Support chat Redis subscriber stopped unexpectedly")
        finally:
            await _close_pubsub(pubsub)

    # ------------------------------------------------------------------
    # Lifecycle helpers (wiring is task 5.3)
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start the background Redis subscriber task if not already running."""
        if self._subscriber_task is None or self._subscriber_task.done():
            self._subscriber_task = asyncio.create_task(self.run_subscriber())

    async def stop(self) -> None:
        """Cancel and await the background subscriber task (idempotent)."""
        task = self._subscriber_task
        self._subscriber_task = None
        if task is None:
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("Error while stopping support chat Redis subscriber")


async def _safe_send(socket: Socket, frame: dict[str, Any]) -> bool:
    """Send ``frame`` to ``socket``, returning ``True`` on success.

    Prefers an awaitable ``send_json`` and falls back to ``send_text`` with a
    JSON-encoded frame. Any failure is swallowed (logged) and reported as
    ``False`` so the caller can unregister the dead socket and continue the
    fan-out loop.
    """
    try:
        send_json = getattr(socket, "send_json", None)
        if send_json is not None:
            await send_json(frame)
        else:
            import json

            await socket.send_text(json.dumps(frame))
        return True
    except Exception:
        logger.warning(
            "Failed to send support chat frame to a socket; unregistering it",
            exc_info=True,
        )
        return False


async def _close_pubsub(pubsub: Any) -> None:
    """Best-effort unsubscribe + close of a Redis pubsub, swallowing errors."""
    try:
        await pubsub.unsubscribe(SUPPORT_EVENTS_CHANNEL)
    except Exception:
        pass
    aclose = getattr(pubsub, "aclose", None)
    try:
        if aclose is not None:
            await aclose()
        else:  # pragma: no cover - older redis-py fallback
            close = getattr(pubsub, "close", None)
            if close is not None:
                result = close()
                if asyncio.iscoroutine(result):
                    await result
    except Exception:
        pass


#: Shared per-worker hub instance, created lazily by :func:`get_connection_hub`.
_connection_hub: ConnectionHub | None = None


def get_connection_hub() -> ConnectionHub:
    """Return the per-worker :class:`ConnectionHub` singleton.

    The WS gateway (task 4.4) and the service/routers and app lifecycle wiring
    (task 5.3) all resolve the hub through this accessor so they share one
    registry per worker. The instance is created on first use; importing this
    module performs no I/O and opens no Redis connection.
    """
    global _connection_hub
    if _connection_hub is None:
        _connection_hub = ConnectionHub()
    return _connection_hub
