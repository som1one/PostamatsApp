"""Operator-facing support-chat REST router (``/api/admin/support``).

This router exposes the durable persistence + read path for the operator side of
the support chat (see ``.kiro/specs/support-chat/design.md`` → *REST endpoints*
→ operator table). Real-time delivery to other connected operators/clients is
handled by the WebSocket gateway; these endpoints guarantee that conversations
can be triaged, replied to, assigned, and have their status changed regardless of
socket liveness.

Every endpoint is gated by :func:`backend.utils.support_auth.get_current_operator`,
so a client (user) token or a non-operator admin can never reach operator logic
(Requirements 8.1, 8.2). The guard resolves the admin from the bearer access
token and asserts the operator role, returning ``(AdminAccount, AdminAuthSession)``.

For REST-initiated mutations (reply / assign / status) the router also fans the
change out to other connected operators/clients via the per-worker connection
hub *after* the database commit, so operators using REST stay consistent with
operators on the WebSocket path (design → *persist-before-publish*). Broadcasts
are best-effort: a delivery hiccup never fails an already-persisted mutation.

Responses follow the project convention of wrapping payloads in a ``{"data": …}``
envelope; payload shapes reuse the Pydantic models in
:mod:`backend.schemas.support_schemas`.
"""

from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.database import get_db
from backend.models.admin_account import AdminAccount
from backend.models.admin_auth_session import AdminAuthSession
from backend.models.enums import ConversationStatus
from backend.models.support_conversation import SupportConversation
from backend.models.support_message import SupportMessage
from backend.realtime.connection_hub import get_connection_hub
from backend.realtime.events import (
    make_assignment_changed,
    make_message_new,
    make_status_changed,
    serialize_message,
)
from backend.schemas.support_schemas import (
    AssignedOperator,
    AssignRequest,
    ClientInfoCard,
    ConversationSummary,
    Message,
    MessagesPage,
    OperatorSendMessageRequest,
    RentalSummary,
    ReservationSummary,
    StatusChangeRequest,
)
from backend.services import support_chat_service
from backend.services.support_chat_service import (
    DEFAULT_PAGE_LIMIT,
    ClientInfoCardData,
    ConversationForbiddenError,
    ConversationNotFoundError,
    ConversationSummaryData,
    EmptyMessageError,
    MessagePage,
    MessageTooLongError,
)
from backend.utils.support_auth import get_current_operator

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin/support", tags=["admin-support"])


# ---------------------------------------------------------------------------
# Mapping helpers (service value objects -> wire Pydantic models)
# ---------------------------------------------------------------------------


def _serialize_message(message, author_name: str | None = None) -> Message:
    """Render a ``SupportMessage`` ORM row into the wire :class:`Message` model.

    Reuses the canonical realtime serializer so the REST and WebSocket contracts
    stay identical. ``author_name`` is only resolved for the operator reply being
    posted (the gateway does the same); history messages are returned with
    ``authorName=None`` and the operator panel distinguishes authors by
    ``authorType``.
    """
    return Message.model_validate(serialize_message(message, author_name))


def _map_summary(summary: ConversationSummaryData) -> ConversationSummary:
    """Map a service :class:`ConversationSummaryData` to :class:`ConversationSummary`.

    Collapses the flat ``assigned_operator_id`` + ``assigned_operator_name`` pair
    into the nested ``assignedOperator`` reference (``None`` when unassigned); the
    remaining fields map by name into camelCase.
    """
    assigned = None
    if summary.assigned_operator_id is not None:
        assigned = AssignedOperator(
            id=summary.assigned_operator_id,
            name=summary.assigned_operator_name or "",
        )
    return ConversationSummary(
        id=summary.id,
        status=summary.status,
        assignedOperator=assigned,
        lastMessagePreview=summary.last_message_preview,
        lastMessageAt=summary.last_message_at,
        unreadCount=summary.unread_count,
    )


def _map_client_info_card(card: ClientInfoCardData) -> ClientInfoCard:
    """Map a service :class:`ClientInfoCardData` to the wire :class:`ClientInfoCard`.

    Field names map snake_case -> camelCase; the two lists preserve the service's
    newest→oldest order and ≤10 cap (Requirements 13.1–13.4).
    """
    return ClientInfoCard(
        phone=card.phone,
        recentReservations=[
            ReservationSummary(
                id=reservation.id,
                productName=reservation.product_name,
                status=reservation.status,
                pickupAt=reservation.pickup_at,
                createdAt=reservation.created_at,
            )
            for reservation in card.recent_reservations
        ],
        recentRentals=[
            RentalSummary(
                id=rental.id,
                productName=rental.product_name,
                status=rental.status,
                startsAt=rental.starts_at,
                plannedEndAt=rental.planned_end_at,
            )
            for rental in card.recent_rentals
        ],
    )


async def _build_conversation_summary(
    db: AsyncSession,
    conversation: SupportConversation,
    operator: AdminAccount,
) -> ConversationSummary:
    """Build a full :class:`ConversationSummary` for a single conversation.

    Resolves the assignee display name (one lookup when assigned), the most
    recent message body as the preview (looked up by the conversation's
    denormalized ``last_message_seq``), and the requesting operator's unread
    count, so the conversation object returned by the open / assign / status
    endpoints is consistent with the rows in the conversation list.
    """
    assigned = None
    if conversation.assigned_operator_id is not None:
        admin = await db.get(AdminAccount, conversation.assigned_operator_id)
        assigned = AssignedOperator(
            id=conversation.assigned_operator_id,
            name=admin.name if admin is not None else "",
        )

    preview: str | None = None
    if conversation.last_message_seq is not None:
        preview = (
            await db.execute(
                select(SupportMessage.body).where(
                    SupportMessage.seq == conversation.last_message_seq
                )
            )
        ).scalar_one_or_none()

    unread = await support_chat_service.compute_unread(db, conversation.id, operator.id)

    return ConversationSummary(
        id=conversation.id,
        status=conversation.status,
        assignedOperator=assigned,
        lastMessagePreview=preview,
        lastMessageAt=conversation.last_message_at,
        unreadCount=unread,
    )


def _serialize_page(page: MessagePage) -> tuple[list[Message], bool, int | None]:
    """Map a service :class:`MessagePage` to wire models + pagination metadata."""
    messages = [_serialize_message(row) for row in page.messages]
    return messages, page.has_more, page.oldest_seq


# ---------------------------------------------------------------------------
# Shared error / commit helpers
# ---------------------------------------------------------------------------


def _too_long_http_error(exc: MessageTooLongError) -> HTTPException:
    """Build the ``422`` for an over-length body, naming the limit (Req 10.5)."""
    return HTTPException(
        status_code=422,
        detail={"code": "MESSAGE_TOO_LONG", "limit": exc.limit, "message": str(exc)},
    )


async def _commit(db: AsyncSession, error_detail: str) -> None:
    """Commit the session, mapping failures to a ``500`` after a rollback."""
    try:
        await db.commit()
    except Exception as exc:  # pragma: no cover - defensive: surface as 500
        await db.rollback()
        raise HTTPException(status_code=500, detail=error_detail) from exc


async def _safe_deliver(event) -> None:
    """Fan an event out via the connection hub without ever raising.

    The mutation is already persisted before this is called, so a broadcast
    failure must not turn a successful REST mutation into an error. The hub's
    own dispatch/publish are already best-effort, but this guard makes the
    REST path's intent explicit and tolerant of any unexpected error.
    """
    try:
        await get_connection_hub().deliver(event)
    except Exception:  # pragma: no cover - best-effort live fan-out
        logger.warning(
            "Failed to broadcast support chat event from REST mutation",
            exc_info=True,
        )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/conversations")
async def list_conversations(
    operator_session: tuple[AdminAccount, AdminAuthSession] = Depends(get_current_operator),
    db: AsyncSession = Depends(get_db),
    status: ConversationStatus | None = Query(
        default=None,
        description="Optional status filter: open | in_progress | closed",
    ),
):
    """List conversations for the operator, newest activity first (Req 9.1, 12.6).

    Each summary carries the conversation's status, assignee, latest-message
    preview, activity timestamp, and the unread count computed for the requesting
    operator. ``status`` filters to a single :class:`ConversationStatus`; an
    unrecognised value is rejected by FastAPI with ``422``.
    """
    operator, _ = operator_session

    summaries = await support_chat_service.list_conversations(db, operator, status=status)
    conversations = [_map_summary(summary) for summary in summaries]
    return {"data": {"conversations": conversations}}


@router.get("/conversations/{conversation_id}")
async def open_conversation(
    conversation_id: UUID,
    operator_session: tuple[AdminAccount, AdminAuthSession] = Depends(get_current_operator),
    db: AsyncSession = Depends(get_db),
):
    """Open a conversation: newest message page + client info card + mark read.

    Resets the requesting operator's unread for this conversation to zero
    (per-operator; other operators are unaffected) and returns the first page of
    messages oldest→newest together with the operator-facing client info card
    (Requirements 9.4, 10.1, 13). The conversation summary reflects the
    just-reset unread of zero.
    """
    operator, _ = operator_session

    try:
        await support_chat_service.mark_read(db, operator, conversation_id)
        page = await support_chat_service.list_messages(
            db, conversation_id, limit=DEFAULT_PAGE_LIMIT
        )
        card_data = await support_chat_service.build_client_info_card(db, conversation_id)
    except ConversationNotFoundError as exc:
        raise HTTPException(status_code=404, detail="CONVERSATION_NOT_FOUND") from exc
    except ConversationForbiddenError as exc:
        raise HTTPException(status_code=403, detail="CONVERSATION_FORBIDDEN") from exc

    conversation = await db.get(SupportConversation, conversation_id)
    summary = await _build_conversation_summary(db, conversation, operator)

    await _commit(db, "SUPPORT_CONVERSATION_FAILED")

    messages, has_more, oldest_seq = _serialize_page(page)
    return {
        "data": {
            "conversation": summary,
            "messages": messages,
            "clientInfoCard": _map_client_info_card(card_data),
            "hasMore": has_more,
            "oldestSeq": oldest_seq,
        }
    }


@router.get("/conversations/{conversation_id}/messages")
async def get_conversation_messages(
    conversation_id: UUID,
    operator_session: tuple[AdminAccount, AdminAuthSession] = Depends(get_current_operator),
    db: AsyncSession = Depends(get_db),
    beforeSeq: int | None = Query(
        default=None, description="Keyset cursor: return messages older than this seq"
    ),
    limit: int = Query(default=DEFAULT_PAGE_LIMIT, ge=1, description="Max messages to return"),
):
    """Return an older page of a conversation's history (Requirement 10.1).

    ``beforeSeq`` is the keyset cursor (the previous page's ``oldestSeq``); omit
    it to fetch the newest page. A missing conversation yields ``404``.
    """
    conversation = await db.get(SupportConversation, conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="CONVERSATION_NOT_FOUND")

    page = await support_chat_service.list_messages(
        db, conversation_id, before_seq=beforeSeq, limit=limit
    )
    messages, has_more, oldest_seq = _serialize_page(page)
    return {"data": MessagesPage(messages=messages, hasMore=has_more, oldestSeq=oldest_seq)}


@router.post("/conversations/{conversation_id}/messages")
async def reply_to_conversation(
    conversation_id: UUID,
    operator_session: tuple[AdminAccount, AdminAuthSession] = Depends(get_current_operator),
    db: AsyncSession = Depends(get_db),
    payload: OperatorSendMessageRequest = Body(...),
):
    """Post an operator reply (durable persistence path) and fan it out.

    Validation failures map to ``422`` (the over-length error names the 4000
    character limit); a missing conversation maps to ``404`` (Requirements 10.2,
    10.5). After commit the new message is broadcast as ``message.new`` so other
    connected operators and the conversation's client receive it live.
    """
    operator, _ = operator_session

    try:
        message = await support_chat_service.post_operator_message(
            db, operator, conversation_id, payload.body
        )
    except EmptyMessageError as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": "MESSAGE_EMPTY", "message": str(exc)},
        ) from exc
    except MessageTooLongError as exc:
        raise _too_long_http_error(exc) from exc
    except ConversationNotFoundError as exc:
        raise HTTPException(status_code=404, detail="CONVERSATION_NOT_FOUND") from exc

    message_dict = serialize_message(message, author_name=operator.name)
    await _commit(db, "SUPPORT_MESSAGE_FAILED")

    await _safe_deliver(make_message_new(message_dict))

    return {"data": {"message": Message.model_validate(message_dict)}}


@router.post("/conversations/{conversation_id}/assign")
async def assign_conversation(
    conversation_id: UUID,
    operator_session: tuple[AdminAccount, AdminAuthSession] = Depends(get_current_operator),
    db: AsyncSession = Depends(get_db),
    payload: AssignRequest = Body(...),
):
    """Self-assign or self-release a conversation and broadcast the change.

    ``assign=True`` records the requesting operator as the assignee;
    ``assign=False`` releases it to unassigned (Requirements 11.1, 11.4). After
    commit an ``assignment.changed`` event is fanned out to operators.
    """
    operator, _ = operator_session

    try:
        conversation = await support_chat_service.assign(
            db, operator, conversation_id, payload.assign
        )
    except ConversationNotFoundError as exc:
        raise HTTPException(status_code=404, detail="CONVERSATION_NOT_FOUND") from exc
    except ConversationForbiddenError as exc:
        raise HTTPException(status_code=403, detail="CONVERSATION_FORBIDDEN") from exc

    summary = await _build_conversation_summary(db, conversation, operator)
    await _commit(db, "SUPPORT_ASSIGN_FAILED")

    assigned_operator = (
        {"id": str(operator.id), "name": operator.name} if payload.assign else None
    )
    await _safe_deliver(make_assignment_changed(conversation_id, assigned_operator))

    return {"data": {"conversation": summary}}


@router.post("/conversations/{conversation_id}/status")
async def change_conversation_status(
    conversation_id: UUID,
    operator_session: tuple[AdminAccount, AdminAuthSession] = Depends(get_current_operator),
    db: AsyncSession = Depends(get_db),
    payload: StatusChangeRequest = Body(...),
):
    """Change a conversation's status and broadcast the change (Requirement 12.3).

    An unrecognised status value is rejected by FastAPI with ``422`` before this
    handler runs; a missing conversation maps to ``404``. After commit a
    ``status.changed`` event is fanned out to operators and the conversation's
    client.
    """
    operator, _ = operator_session

    try:
        conversation = await support_chat_service.set_status(
            db, operator, conversation_id, payload.status
        )
    except ConversationNotFoundError as exc:
        raise HTTPException(status_code=404, detail="CONVERSATION_NOT_FOUND") from exc
    except ConversationForbiddenError as exc:
        raise HTTPException(status_code=403, detail="CONVERSATION_FORBIDDEN") from exc

    summary = await _build_conversation_summary(db, conversation, operator)
    await _commit(db, "SUPPORT_STATUS_FAILED")

    await _safe_deliver(make_status_changed(conversation_id, payload.status))

    return {"data": {"conversation": summary}}


@router.post("/conversations/{conversation_id}/read")
async def mark_conversation_read(
    conversation_id: UUID,
    operator_session: tuple[AdminAccount, AdminAuthSession] = Depends(get_current_operator),
    db: AsyncSession = Depends(get_db),
):
    """Reset the requesting operator's unread for a conversation to zero (Req 9.4).

    Unread is per-operator, so this only affects the acting operator's view; no
    broadcast is needed (other operators' unread is unchanged). A missing
    conversation maps to ``404``.
    """
    operator, _ = operator_session

    try:
        await support_chat_service.mark_read(db, operator, conversation_id)
    except ConversationNotFoundError as exc:
        raise HTTPException(status_code=404, detail="CONVERSATION_NOT_FOUND") from exc
    except ConversationForbiddenError as exc:
        raise HTTPException(status_code=403, detail="CONVERSATION_FORBIDDEN") from exc

    await _commit(db, "SUPPORT_READ_FAILED")

    return {"data": {"unreadCount": 0}}
