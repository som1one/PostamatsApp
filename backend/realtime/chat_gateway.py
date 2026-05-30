"""Support-chat WebSocket gateway.

This module terminates the two support-chat WebSocket endpoints and wires them
to the durable :mod:`backend.services.support_chat_service` and the per-worker
:class:`backend.realtime.connection_hub.ConnectionHub` (see
``.kiro/specs/support-chat/design.md`` → *WebSocket protocol*, *Connection
authentication*, *Authorization model*):

* ``/ws/support`` — a **client** socket authenticated with the existing user
  JWT passed as a ``?token=`` query parameter. The socket is bound to the
  caller's own conversation (resolved from the authenticated user, never from a
  client-supplied id), so a client can only ever read/write its own thread
  (Requirements 3.3, 5.2, 8.3, 8.4, 8.5).
* ``/ws/helperpanel`` — an **operator** socket authenticated with an admin JWT
  whose role passes :func:`backend.utils.support_auth.operator_has_access`. The
  operator authorization is re-checked at action time for every state-changing
  send (Requirement 8.6).

Both endpoints follow the design's connection-authentication rule: the handshake
is accepted, the token is validated, and on failure the socket is closed with
:data:`backend.utils.support_auth.WS_UNAUTHORIZED_CLOSE_CODE` (4401) **before**
any hub registration, so a rejected connection never receives guest state
(Requirements 3.3, 8.4, 8.5).

Durability comes first (Requirement 14.1): every accepted message is validated,
persisted, and committed in its own short-lived database session before it is
acked to the sender and fanned out via :meth:`ConnectionHub.deliver` (local
dispatch + Redis publish). Per-message sessions are opened, used, committed, and
closed so a long-lived socket never holds a database connection open between
messages.

The endpoints are exposed on a module-level :data:`router`
(:class:`fastapi.APIRouter`) so ``backend/main.py`` can ``include_router`` them
during app wiring (task 5.3). This module is intentionally tolerant of service
functions that land in later tasks (``mark_read``, ``assign``, ``set_status``):
those are resolved dynamically at call time via :func:`_service_fn`, so importing
this gateway never fails even before those functions exist, and an action that
needs a not-yet-implemented function degrades to a graceful ``error`` frame
rather than crashing the socket loop.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional
from uuid import UUID

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from backend.core.database import SessionLocal
from backend.models.enums import ConversationStatus
from backend.realtime.connection_hub import ConnectionHub, get_connection_hub
from backend.realtime.events import (
    Action,
    make_ack,
    make_assignment_changed,
    make_error,
    make_message_new,
    make_pong,
    make_status_changed,
    make_unread_update,
    serialize_message,
)
from backend.models.admin_account import AdminAccount
from backend.models.user import User
from backend.services import support_chat_service
from backend.services.support_chat_service import (
    ConversationForbiddenError,
    ConversationNotFoundError,
    EmptyMessageError,
    MessageTooLongError,
    MessageValidationError,
)
from backend.utils.support_auth import (
    WS_UNAUTHORIZED_CLOSE_CODE,
    authenticate_ws_client,
    authenticate_ws_operator,
)

logger = logging.getLogger(__name__)

#: The gateway's WebSocket routes are registered here so ``backend/main.py`` can
#: ``include_router`` them during app wiring (task 5.3).
router = APIRouter(tags=["support-ws"])


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def _service_fn(name: str):
    """Resolve a :mod:`support_chat_service` callable by name at call time.

    Returns ``None`` when the function is not (yet) defined. This lets the
    gateway reference service operations that land in later tasks (``mark_read``,
    ``assign``, ``set_status``) without failing at import time; an action that
    needs a missing function responds with a graceful ``error`` frame instead.
    """
    fn = getattr(support_chat_service, name, None)
    return fn if callable(fn) else None


def _parse_frame(raw: str) -> Optional[tuple[str, dict[str, Any]]]:
    """Parse a raw text frame into ``(action_type, payload)``.

    Returns ``None`` for any frame that is not a JSON object carrying a string
    ``type`` discriminator, so the caller can answer with an ``error`` frame
    without ever raising into the receive loop.
    """
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    action = data.get("type")
    if not isinstance(action, str):
        return None
    return action, data


def _coerce_uuid(value: Any) -> UUID | None:
    """Coerce a client-supplied conversation id to a :class:`UUID` (or ``None``)."""
    if isinstance(value, UUID):
        return value
    if not isinstance(value, str):
        return None
    try:
        return UUID(value)
    except (ValueError, AttributeError):
        return None


async def _send_event(websocket: WebSocket, event) -> None:
    """Send a :class:`ChatEvent` to ``websocket``, swallowing send failures.

    A failed send (e.g. the peer vanished mid-handler) must not break the
    receive loop; the disconnect will surface on the next ``receive`` and unwind
    cleanly through the endpoint's ``finally`` block.
    """
    try:
        await websocket.send_json(event.to_frame())
    except Exception:  # pragma: no cover - best-effort delivery to one socket
        logger.warning("Failed to send support chat WS frame", exc_info=True)


# ---------------------------------------------------------------------------
# Client endpoint: /ws/support
# ---------------------------------------------------------------------------


@router.websocket("/ws/support")
async def support_client_ws(websocket: WebSocket) -> None:
    """Client support socket.

    Authenticates the ``?token=`` handshake as a client user, binds the socket to
    the caller's own conversation, and relays ``message.send``/``ping`` actions.
    On auth failure the socket is closed with code 4401 before any hub
    registration (Requirements 3.3, 8.4, 8.5).
    """
    await websocket.accept()

    token = websocket.query_params.get("token")
    async with SessionLocal() as db:
        user = await authenticate_ws_client(token, db)
    if user is None:
        await websocket.close(code=WS_UNAUTHORIZED_CLOSE_CODE)
        return

    # Resolve (and persist) the caller's conversation before registering the
    # socket, so fan-out has a concrete conversation id to key off.
    async with SessionLocal() as db:
        conversation = await support_chat_service.get_or_create_conversation(db, user)
        await db.commit()
        conversation_id = str(conversation.id)

    hub = get_connection_hub()
    hub.register_client(conversation_id, websocket)
    try:
        while True:
            raw = await websocket.receive_text()
            await _handle_client_frame(websocket, hub, user, conversation_id, raw)
    except WebSocketDisconnect:
        pass
    finally:
        hub.unregister_client(conversation_id, websocket)


async def _handle_client_frame(
    websocket: WebSocket,
    hub: ConnectionHub,
    user: User,
    conversation_id: str,
    raw: str,
) -> None:
    """Dispatch a single inbound client frame. Never raises into the loop."""
    parsed = _parse_frame(raw)
    if parsed is None:
        await _send_event(
            websocket, make_error("INVALID_FRAME", "Malformed message frame.")
        )
        return

    action, payload = parsed
    if action == Action.PING:
        await _send_event(websocket, make_pong())
        return
    if action == Action.MESSAGE_SEND:
        await _handle_client_message_send(websocket, hub, user, payload)
        return

    # Any other action (including operator-only actions) is not valid for a
    # client socket.
    await _send_event(
        websocket,
        make_error(
            "INVALID_ACTION",
            f"Unsupported action for a client connection: {action}",
            payload.get("clientMsgId"),
        ),
    )


async def _handle_client_message_send(
    websocket: WebSocket,
    hub: ConnectionHub,
    user: User,
    payload: dict[str, Any],
) -> None:
    """Persist a client message, ack the sender, and fan out ``message.new``.

    The conversation is resolved from the authenticated ``user`` inside
    :func:`post_client_message`; a client-supplied ``conversationId`` is ignored,
    so a client can never post into another client's thread (Requirements 2.1,
    8.3, 10.4).
    """
    client_msg_id = payload.get("clientMsgId")
    body = payload.get("body")
    if not isinstance(body, str):
        await _send_event(
            websocket,
            make_error("EMPTY_MESSAGE", "Message body must not be empty.", client_msg_id),
        )
        return

    try:
        async with SessionLocal() as db:
            message = await support_chat_service.post_client_message(db, user, body)
            await db.commit()
            # Serialize while the row is still attached (expire_on_commit=False
            # keeps attributes loaded, but doing it here is unambiguous).
            message_dict = serialize_message(message)
    except EmptyMessageError as exc:
        await _send_event(
            websocket, make_error("EMPTY_MESSAGE", str(exc), client_msg_id)
        )
        return
    except MessageTooLongError as exc:
        await _send_event(
            websocket, make_error("MESSAGE_TOO_LONG", str(exc), client_msg_id)
        )
        return
    except MessageValidationError as exc:  # pragma: no cover - future validators
        await _send_event(
            websocket, make_error("MESSAGE_INVALID", str(exc), client_msg_id)
        )
        return
    except Exception:
        logger.exception("Failed to persist client support message")
        await _send_event(
            websocket,
            make_error("INTERNAL_ERROR", "Failed to send message.", client_msg_id),
        )
        return

    # Persisted: confirm to the sender, then fan out to participants + operators.
    await _send_event(websocket, make_ack(client_msg_id, message_dict))
    await hub.deliver(make_message_new(message_dict))


# ---------------------------------------------------------------------------
# Operator endpoint: /ws/helperpanel
# ---------------------------------------------------------------------------


@router.websocket("/ws/helperpanel")
async def operator_ws(websocket: WebSocket) -> None:
    """Operator support socket.

    Authenticates the ``?token=`` handshake as an admin with operator access and
    relays operator actions. On auth failure the socket is closed with code 4401
    before any hub registration (Requirements 8.2, 8.4, 8.5). The handshake token
    is retained so operator authorization can be re-validated at action time for
    every state-changing send (Requirement 8.6).
    """
    await websocket.accept()

    token = websocket.query_params.get("token")
    async with SessionLocal() as db:
        operator = await authenticate_ws_operator(token, db)
    if operator is None:
        await websocket.close(code=WS_UNAUTHORIZED_CLOSE_CODE)
        return

    hub = get_connection_hub()
    hub.register_operator(websocket)
    try:
        while True:
            raw = await websocket.receive_text()
            await _handle_operator_frame(websocket, hub, operator, token, raw)
    except WebSocketDisconnect:
        pass
    finally:
        hub.unregister_operator(websocket)


async def _handle_operator_frame(
    websocket: WebSocket,
    hub: ConnectionHub,
    operator: AdminAccount,
    token: str | None,
    raw: str,
) -> None:
    """Dispatch a single inbound operator frame. Never raises into the loop."""
    parsed = _parse_frame(raw)
    if parsed is None:
        await _send_event(
            websocket, make_error("INVALID_FRAME", "Malformed message frame.")
        )
        return

    action, payload = parsed

    if action == Action.PING:
        await _send_event(websocket, make_pong())
        return
    if action == Action.CONVERSATION_OPEN:
        await _handle_operator_open(websocket, operator, payload)
        return
    if action == Action.MESSAGE_SEND:
        await _handle_operator_message_send(websocket, hub, operator, token, payload)
        return
    if action == Action.CONVERSATION_MARK_READ:
        await _handle_operator_mark_read(websocket, operator, payload)
        return
    if action == Action.CONVERSATION_ASSIGN:
        await _handle_operator_assign(websocket, hub, operator, payload)
        return
    if action == Action.CONVERSATION_SET_STATUS:
        await _handle_operator_set_status(websocket, hub, operator, payload)
        return

    await _send_event(
        websocket,
        make_error(
            "INVALID_ACTION",
            f"Unsupported action for an operator connection: {action}",
            payload.get("clientMsgId"),
        ),
    )


async def _handle_operator_open(
    websocket: WebSocket,
    operator: AdminAccount,
    payload: dict[str, Any],
) -> None:
    """Set the operator's currently-open conversation and reset their unread.

    Setting the open conversation is purely in-memory and always succeeds; it is
    what makes conversation-scoped ``message.new`` events route to this socket.
    Marking the conversation read (resetting this operator's unread to zero) is
    best-effort: it is skipped gracefully when ``mark_read`` is not yet
    implemented (task 2.9).
    """
    conversation_id = _coerce_uuid(payload.get("conversationId"))
    if conversation_id is None:
        await _send_event(
            websocket, make_error("INVALID_CONVERSATION", "Missing or invalid conversationId.")
        )
        return

    hub = get_connection_hub()
    hub.set_operator_open_conversation(websocket, str(conversation_id))

    mark_read = _service_fn("mark_read")
    if mark_read is None:
        return
    try:
        async with SessionLocal() as db:
            await mark_read(db, operator, conversation_id)
            await db.commit()
    except (ConversationNotFoundError, ConversationForbiddenError):
        # Opening a missing/foreign conversation: leave the socket scoped but do
        # not claim an unread reset.
        return
    except Exception:
        logger.exception("Failed to mark support conversation read on open")
        return

    # Reflect the reset for the acting operator's own view (unread is per-operator,
    # so only the operator who opened it sees zero).
    await _send_event(websocket, make_unread_update(str(conversation_id), 0))


async def _handle_operator_message_send(
    websocket: WebSocket,
    hub: ConnectionHub,
    operator: AdminAccount,
    token: str | None,
    payload: dict[str, Any],
) -> None:
    """Re-authorize, persist an operator reply, ack, and fan out ``message.new``.

    Operator authorization is re-validated from the handshake token at action
    time: a socket whose admin session was revoked or whose role was downgraded
    is rejected and no message is persisted (Requirement 8.6).
    """
    client_msg_id = payload.get("clientMsgId")

    conversation_id = _coerce_uuid(payload.get("conversationId"))
    if conversation_id is None:
        await _send_event(
            websocket,
            make_error("INVALID_CONVERSATION", "Missing or invalid conversationId.", client_msg_id),
        )
        return

    body = payload.get("body")
    if not isinstance(body, str):
        await _send_event(
            websocket,
            make_error("EMPTY_MESSAGE", "Message body must not be empty.", client_msg_id),
        )
        return

    try:
        async with SessionLocal() as db:
            # Re-check operator authorization at action time (Requirement 8.6).
            current = await authenticate_ws_operator(token, db)
            if current is None:
                await _send_event(
                    websocket,
                    make_error(
                        "UNAUTHORIZED",
                        "Operator authorization is no longer valid.",
                        client_msg_id,
                    ),
                )
                return

            message = await support_chat_service.post_operator_message(
                db, current, conversation_id, body
            )
            await db.commit()
            message_dict = serialize_message(message, author_name=current.name)
    except EmptyMessageError as exc:
        await _send_event(websocket, make_error("EMPTY_MESSAGE", str(exc), client_msg_id))
        return
    except MessageTooLongError as exc:
        await _send_event(websocket, make_error("MESSAGE_TOO_LONG", str(exc), client_msg_id))
        return
    except MessageValidationError as exc:  # pragma: no cover - future validators
        await _send_event(websocket, make_error("MESSAGE_INVALID", str(exc), client_msg_id))
        return
    except ConversationNotFoundError as exc:
        await _send_event(websocket, make_error("CONVERSATION_NOT_FOUND", str(exc), client_msg_id))
        return
    except ConversationForbiddenError as exc:
        await _send_event(websocket, make_error("CONVERSATION_FORBIDDEN", str(exc), client_msg_id))
        return
    except Exception:
        logger.exception("Failed to persist operator support message")
        await _send_event(
            websocket,
            make_error("INTERNAL_ERROR", "Failed to send reply.", client_msg_id),
        )
        return

    await _send_event(websocket, make_ack(client_msg_id, message_dict))
    await hub.deliver(make_message_new(message_dict))


async def _handle_operator_mark_read(
    websocket: WebSocket,
    operator: AdminAccount,
    payload: dict[str, Any],
) -> None:
    """Reset the acting operator's unread for a conversation.

    Degrades to a ``NOT_IMPLEMENTED`` error when ``mark_read`` is not yet
    available (task 2.9).
    """
    conversation_id = _coerce_uuid(payload.get("conversationId"))
    if conversation_id is None:
        await _send_event(
            websocket, make_error("INVALID_CONVERSATION", "Missing or invalid conversationId.")
        )
        return

    mark_read = _service_fn("mark_read")
    if mark_read is None:
        await _send_event(
            websocket,
            make_error("NOT_IMPLEMENTED", "Marking conversations read is not available yet."),
        )
        return

    try:
        async with SessionLocal() as db:
            await mark_read(db, operator, conversation_id)
            await db.commit()
    except (ConversationNotFoundError, ConversationForbiddenError) as exc:
        await _send_event(websocket, make_error("CONVERSATION_NOT_FOUND", str(exc)))
        return
    except Exception:
        logger.exception("Failed to mark support conversation read")
        await _send_event(websocket, make_error("INTERNAL_ERROR", "Failed to mark read."))
        return

    await _send_event(websocket, make_unread_update(str(conversation_id), 0))


async def _handle_operator_assign(
    websocket: WebSocket,
    hub: ConnectionHub,
    operator: AdminAccount,
    payload: dict[str, Any],
) -> None:
    """Self-assign or self-release a conversation and broadcast the change.

    Degrades to a ``NOT_IMPLEMENTED`` error when ``assign`` is not yet available
    (task 2.14).
    """
    conversation_id = _coerce_uuid(payload.get("conversationId"))
    if conversation_id is None:
        await _send_event(
            websocket, make_error("INVALID_CONVERSATION", "Missing or invalid conversationId.")
        )
        return

    assign_flag = payload.get("assign")
    if not isinstance(assign_flag, bool):
        await _send_event(
            websocket, make_error("INVALID_ASSIGN", "`assign` must be a boolean.")
        )
        return

    assign = _service_fn("assign")
    if assign is None:
        await _send_event(
            websocket,
            make_error("NOT_IMPLEMENTED", "Conversation assignment is not available yet."),
        )
        return

    try:
        async with SessionLocal() as db:
            await assign(db, operator, conversation_id, assign_flag)
            await db.commit()
    except (ConversationNotFoundError, ConversationForbiddenError) as exc:
        await _send_event(websocket, make_error("CONVERSATION_NOT_FOUND", str(exc)))
        return
    except Exception:
        logger.exception("Failed to change support conversation assignment")
        await _send_event(websocket, make_error("INTERNAL_ERROR", "Failed to change assignment."))
        return

    assigned_operator = (
        {"id": str(operator.id), "name": operator.name} if assign_flag else None
    )
    await hub.deliver(make_assignment_changed(str(conversation_id), assigned_operator))


async def _handle_operator_set_status(
    websocket: WebSocket,
    hub: ConnectionHub,
    operator: AdminAccount,
    payload: dict[str, Any],
) -> None:
    """Change a conversation's status and broadcast the change.

    Degrades to a ``NOT_IMPLEMENTED`` error when ``set_status`` is not yet
    available (task 2.14).
    """
    conversation_id = _coerce_uuid(payload.get("conversationId"))
    if conversation_id is None:
        await _send_event(
            websocket, make_error("INVALID_CONVERSATION", "Missing or invalid conversationId.")
        )
        return

    raw_status = payload.get("status")
    try:
        status = ConversationStatus(raw_status)
    except ValueError:
        await _send_event(
            websocket,
            make_error("INVALID_STATUS", f"Unknown conversation status: {raw_status}"),
        )
        return

    set_status = _service_fn("set_status")
    if set_status is None:
        await _send_event(
            websocket,
            make_error("NOT_IMPLEMENTED", "Changing conversation status is not available yet."),
        )
        return

    try:
        async with SessionLocal() as db:
            await set_status(db, operator, conversation_id, status)
            await db.commit()
    except (ConversationNotFoundError, ConversationForbiddenError) as exc:
        await _send_event(websocket, make_error("CONVERSATION_NOT_FOUND", str(exc)))
        return
    except Exception:
        logger.exception("Failed to change support conversation status")
        await _send_event(websocket, make_error("INTERNAL_ERROR", "Failed to change status."))
        return

    await hub.deliver(make_status_changed(str(conversation_id), status))
