"""Support-chat realtime event/envelope schema.

This module defines the WebSocket protocol vocabulary for the support chat
(see ``.kiro/specs/support-chat/design.md`` → *WebSocket protocol* and
*Redis pub/sub channel design*):

* **Inbound action types** — frames a client or operator sends to the server.
* **Outbound event types** — frames the server sends back to a client/operator.
* **Audience hint** — ``client`` / ``operators`` / ``both``; used by the
  connection hub to decide which locally-held sockets an event is delivered to.
* **:class:`ChatEvent`** — the canonical outbound envelope. It can be rendered
  to the JSON *wire frame* (``{ type, ...payload }``) that goes over a socket,
  and to a richer *bus payload* (carrying ``conversationId`` + ``audience``) so
  other workers can route an event received from the single ``support:events``
  Redis channel.
* **Message serializer** — turns a ``SupportMessage`` ORM row (or any object
  exposing the same attributes) into the canonical wire dict
  ``{ id, conversationId, seq, authorType, authorName, body, createdAt }`` that
  matches the :class:`backend.schemas.support_schemas.Message` Pydantic model.
* **Builder helpers** — small constructors for the common outbound events, each
  returning a :class:`ChatEvent` tagged with the correct audience.

This module is intentionally **pure**: importing it performs no I/O, opens no
sockets, touches no database, and talks to no Redis. The serializer reads only
the attributes of an already-loaded ORM object (or its fields); it never issues
a query. Keeping it side-effect-free makes the protocol trivially unit- and
property-testable and safe to import from anywhere.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - typing only, avoids importing the ORM at runtime
    from backend.models.support_message import SupportMessage


# ---------------------------------------------------------------------------
# Inbound action types (client / operator -> server)
# ---------------------------------------------------------------------------


class Action:
    """Inbound action ``type`` discriminators sent by a client or operator.

    See the design's *Envelope* table. ``message.send`` is allowed from both a
    client and an operator (operators additionally carry a ``conversationId``);
    the remaining actions are operator-only, except ``ping`` which is a keepalive
    available to both.
    """

    MESSAGE_SEND = "message.send"
    CONVERSATION_OPEN = "conversation.open"
    CONVERSATION_MARK_READ = "conversation.markRead"
    CONVERSATION_ASSIGN = "conversation.assign"
    CONVERSATION_SET_STATUS = "conversation.setStatus"
    PING = "ping"


#: Every recognised inbound action ``type``. The gateway uses this to reject
#: unknown action frames before dispatching.
INBOUND_ACTIONS: frozenset[str] = frozenset(
    {
        Action.MESSAGE_SEND,
        Action.CONVERSATION_OPEN,
        Action.CONVERSATION_MARK_READ,
        Action.CONVERSATION_ASSIGN,
        Action.CONVERSATION_SET_STATUS,
        Action.PING,
    }
)


# ---------------------------------------------------------------------------
# Outbound event types (server -> client / operator)
# ---------------------------------------------------------------------------


class Event:
    """Outbound event ``type`` discriminators sent by the server.

    See the design's *Envelope* table for the payload and recipients of each.
    """

    MESSAGE_ACK = "message.ack"
    MESSAGE_NEW = "message.new"
    UNREAD_UPDATE = "unread.update"
    CONVERSATION_UPDATED = "conversation.updated"
    ASSIGNMENT_CHANGED = "assignment.changed"
    STATUS_CHANGED = "status.changed"
    ERROR = "error"
    PONG = "pong"


#: Every recognised outbound event ``type``.
OUTBOUND_EVENTS: frozenset[str] = frozenset(
    {
        Event.MESSAGE_ACK,
        Event.MESSAGE_NEW,
        Event.UNREAD_UPDATE,
        Event.CONVERSATION_UPDATED,
        Event.ASSIGNMENT_CHANGED,
        Event.STATUS_CHANGED,
        Event.ERROR,
        Event.PONG,
    }
)


# ---------------------------------------------------------------------------
# Audience hint
# ---------------------------------------------------------------------------


class Audience(str, Enum):
    """Who an outbound event should be delivered to.

    The connection hub uses this hint when it receives an event (locally or from
    the Redis bus) to pick recipient sockets:

    * :attr:`CLIENT` — the owning conversation's client socket(s) only.
    * :attr:`OPERATORS` — all connected operator sockets (list-level updates);
      conversation-scoped operator events are further filtered by the operator
      socket's currently-open conversation.
    * :attr:`BOTH` — the conversation's client(s) *and* operators.

    Being a ``str`` enum, the values serialize directly to JSON for the bus.
    """

    CLIENT = "client"
    OPERATORS = "operators"
    BOTH = "both"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _enum_value(value: Any) -> Any:
    """Return the underlying value of an :class:`enum.Enum`, else ``value``.

    Lets serializers accept either an enum member (e.g. ``MessageAuthorType`` /
    ``ConversationStatus``) or its already-resolved string value.
    """
    return value.value if isinstance(value, Enum) else value


# ---------------------------------------------------------------------------
# Message serializer
# ---------------------------------------------------------------------------


def serialize_message(message: "SupportMessage", author_name: str | None = None) -> dict[str, Any]:
    """Serialize a ``SupportMessage`` ORM row into the canonical wire dict.

    Produces ``{ id, conversationId, seq, authorType, authorName, body,
    createdAt }`` matching :class:`backend.schemas.support_schemas.Message`.

    The function is pure and does no database access: it reads only attributes
    already present on ``message`` (so a detached/expunged row or a simple stub
    with the same fields works just as well).

    UUIDs are rendered with :func:`str` and ``createdAt`` with ``.isoformat()``
    so the result is directly JSON-serializable.

    ``author_name`` is the resolved display name to expose on the wire. For an
    operator message the router/service passes the admin's name; for a client
    message it may be left as ``None`` (or a generic label resolved by the
    caller). This serializer deliberately does not look names up — keeping name
    resolution at the call site avoids any query here.
    """
    created_at = getattr(message, "created_at", None)
    return {
        "id": str(message.id),
        "conversationId": str(message.conversation_id),
        "seq": message.seq,
        "authorType": _enum_value(message.author_type),
        "authorName": author_name,
        "body": message.body,
        "createdAt": created_at.isoformat() if created_at is not None else None,
    }


# ---------------------------------------------------------------------------
# ChatEvent envelope
# ---------------------------------------------------------------------------


@dataclass
class ChatEvent:
    """An outbound chat event ready to be delivered and/or fanned out.

    Attributes:
        type: One of the :class:`Event` discriminators.
        audience: Who the connection hub should deliver this event to.
        payload: The event-specific body. Its keys are spread directly into the
            WebSocket wire frame, so they must already be JSON-serializable and
            camelCase (e.g. ``conversationId``, ``message``, ``unreadCount``).
        conversation_id: The conversation this event concerns, used for bus
            routing. ``None`` for events not tied to a single conversation
            (e.g. a sender-directed ``error``/``pong``).
    """

    type: str
    audience: Audience
    payload: dict[str, Any] = field(default_factory=dict)
    conversation_id: str | None = None

    def to_frame(self) -> dict[str, Any]:
        """Render the JSON wire frame sent over a socket: ``{ type, ...payload }``.

        The audience and ``conversation_id`` are routing metadata and are *not*
        part of the frame (though a payload may itself carry ``conversationId``).
        """
        return {"type": self.type, **self.payload}

    def to_frame_json(self) -> str:
        """Return :meth:`to_frame` rendered as a JSON string."""
        return json.dumps(self.to_frame())

    def to_bus_dict(self) -> dict[str, Any]:
        """Render the Redis-bus payload.

        Includes ``audience`` and ``conversationId`` alongside the raw payload so
        a subscribing worker can rebuild the event and route it to the correct
        local sockets without re-deriving anything.
        """
        return {
            "type": self.type,
            "audience": self.audience.value,
            "conversationId": self.conversation_id,
            "payload": self.payload,
        }

    def to_bus_json(self) -> str:
        """Return :meth:`to_bus_dict` rendered as a JSON string for publishing."""
        return json.dumps(self.to_bus_dict())

    @classmethod
    def from_bus_dict(cls, data: dict[str, Any]) -> "ChatEvent":
        """Reconstruct a :class:`ChatEvent` from a :meth:`to_bus_dict` payload."""
        return cls(
            type=data["type"],
            audience=Audience(data["audience"]),
            payload=data.get("payload") or {},
            conversation_id=data.get("conversationId"),
        )

    @classmethod
    def from_bus_json(cls, raw: str) -> "ChatEvent":
        """Reconstruct a :class:`ChatEvent` from a :meth:`to_bus_json` string."""
        return cls.from_bus_dict(json.loads(raw))


# ---------------------------------------------------------------------------
# Builder helpers for common events
# ---------------------------------------------------------------------------


def make_message_new(message_dict: dict[str, Any]) -> ChatEvent:
    """Build a ``message.new`` event for a freshly persisted message.

    Delivered to the conversation's participants *and* operators
    (:attr:`Audience.BOTH`). ``message_dict`` is the output of
    :func:`serialize_message`.
    """
    return ChatEvent(
        type=Event.MESSAGE_NEW,
        audience=Audience.BOTH,
        payload={
            "conversationId": message_dict.get("conversationId"),
            "message": message_dict,
        },
        conversation_id=message_dict.get("conversationId"),
    )


def make_unread_update(conversation_id: Any, count: int) -> ChatEvent:
    """Build an ``unread.update`` event (operators only)."""
    cid = str(conversation_id)
    return ChatEvent(
        type=Event.UNREAD_UPDATE,
        audience=Audience.OPERATORS,
        payload={"conversationId": cid, "unreadCount": count},
        conversation_id=cid,
    )


def make_conversation_updated(conversation_dict: dict[str, Any]) -> ChatEvent:
    """Build a ``conversation.updated`` event carrying a conversation summary.

    Delivered to operators (list-level update). ``conversation_dict`` is the
    serialized conversation summary (status, assignee, preview, lastMessageAt).
    """
    cid = conversation_dict.get("id")
    return ChatEvent(
        type=Event.CONVERSATION_UPDATED,
        audience=Audience.OPERATORS,
        payload={"conversation": conversation_dict},
        conversation_id=str(cid) if cid is not None else None,
    )


def make_assignment_changed(
    conversation_id: Any, assigned_operator: dict[str, Any] | None
) -> ChatEvent:
    """Build an ``assignment.changed`` event (operators only).

    ``assigned_operator`` is the serialized assignee (``{ id, name }``) or
    ``None`` when the conversation has been released to unassigned.
    """
    cid = str(conversation_id)
    return ChatEvent(
        type=Event.ASSIGNMENT_CHANGED,
        audience=Audience.OPERATORS,
        payload={"conversationId": cid, "assignedOperator": assigned_operator},
        conversation_id=cid,
    )


def make_status_changed(conversation_id: Any, status: Any) -> ChatEvent:
    """Build a ``status.changed`` event.

    Delivered to operators *and* the conversation's client
    (:attr:`Audience.BOTH`). ``status`` may be a ``ConversationStatus`` enum or
    its string value.
    """
    cid = str(conversation_id)
    return ChatEvent(
        type=Event.STATUS_CHANGED,
        audience=Audience.BOTH,
        payload={"conversationId": cid, "status": _enum_value(status)},
        conversation_id=cid,
    )


def make_error(code: str, message: str, clientMsgId: str | None = None) -> ChatEvent:
    """Build an ``error`` event returned to the sender.

    Errors are written straight back to the originating socket by the gateway,
    so they are not fanned out over the bus; the audience is a neutral default
    and is not used for routing. ``clientMsgId`` is echoed when the error relates
    to a specific outbound ``message.send`` so the sender can correlate it.
    """
    payload: dict[str, Any] = {"code": code, "message": message}
    if clientMsgId is not None:
        payload["clientMsgId"] = clientMsgId
    return ChatEvent(type=Event.ERROR, audience=Audience.CLIENT, payload=payload)


def make_ack(clientMsgId: str | None, message_dict: dict[str, Any]) -> ChatEvent:
    """Build a ``message.ack`` event confirming persistence to the sender.

    Delivered directly to the originating socket by the gateway (not bus-routed).
    ``message_dict`` is the serialized persisted message; ``clientMsgId`` echoes
    the sender's optimistic-id so it can reconcile its local pending message.
    """
    return ChatEvent(
        type=Event.MESSAGE_ACK,
        audience=Audience.CLIENT,
        payload={"clientMsgId": clientMsgId, "message": message_dict},
        conversation_id=message_dict.get("conversationId"),
    )


def make_pong() -> ChatEvent:
    """Build a ``pong`` keepalive reply returned to the sender."""
    return ChatEvent(type=Event.PONG, audience=Audience.CLIENT, payload={})
