"""Client-facing support-chat REST router (``/api/support``).

This router exposes the durable persistence path for the client side of the
support chat (see ``.kiro/specs/support-chat/design.md`` → *REST endpoints*).
Real-time delivery is handled by the WebSocket gateway; these endpoints
guarantee that conversations are created and messages are persisted regardless
of socket liveness, and serve the history pages the widget reconciles against on
(re)connect.

All endpoints require an authenticated client (the existing user JWT, resolved
via :func:`get_current_client_user`) and are implicitly scoped to the caller's
own conversation: the conversation is always resolved from the authenticated
user, never from a client-supplied id, so a client can only ever read or write
its own thread (Requirements 5.2, 8.3).

Responses follow the project convention of wrapping payloads in a ``{"data": …}``
envelope; the payload shapes are the Pydantic models in
:mod:`backend.schemas.support_schemas`.
"""

from __future__ import annotations

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.database import get_db
from backend.realtime.events import serialize_message
from backend.schemas.support_schemas import (
    ClientConversationPayload,
    ClientSendMessageRequest,
    ConversationInfo,
    Message,
    MessagesPage,
)
from backend.services import support_chat_service
from backend.services.support_chat_service import (
    DEFAULT_PAGE_LIMIT,
    ConversationForbiddenError,
    ConversationNotFoundError,
    EmptyMessageError,
    MessagePage,
    MessageTooLongError,
)
from backend.utils.auth_utils import get_current_client_user
from backend.utils.support_notifications import (
    notify_support_client_message,
    notify_support_conversation_created,
)

router = APIRouter(prefix="/api/support", tags=["support"])


def _serialize_message(message) -> Message:
    """Render a ``SupportMessage`` ORM row into the wire :class:`Message` model.

    Reuses the canonical realtime serializer so the REST and WebSocket contracts
    stay identical. ``authorName`` is intentionally left unresolved here (the
    client distinguishes its own messages from operator replies by
    ``authorType``); resolving operator display names would require extra queries
    and is not needed by the client widget.
    """
    return Message.model_validate(serialize_message(message))


def _serialize_page(page: MessagePage) -> tuple[list[Message], bool, int | None]:
    """Map a service :class:`MessagePage` to wire models + pagination metadata."""
    messages = [_serialize_message(row) for row in page.messages]
    return messages, page.has_more, page.oldest_seq


@router.get("/conversation")
async def get_conversation(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Get-or-create the caller's conversation and return its first message page.

    Idempotent: a client without a conversation gets one created (status
    ``open``); an existing conversation is returned as-is. The first page is the
    newest messages ordered oldest→newest, with ``hasMore``/``oldestSeq`` cursors
    for loading older history (Requirements 1.1, 5.1).
    """
    user = await get_current_client_user(request, db)

    conversation, was_created = await support_chat_service.get_or_create_conversation_with_meta(
        db, user
    )
    page = await support_chat_service.list_messages(
        db,
        conversation.id,
        limit=DEFAULT_PAGE_LIMIT,
    )

    # Persist a freshly created conversation (get-or-create may have inserted it).
    try:
        await db.commit()
    except Exception as exc:  # pragma: no cover - defensive: surface as 500
        await db.rollback()
        raise HTTPException(status_code=500, detail="SUPPORT_CONVERSATION_FAILED") from exc

    if was_created:
        notify_support_conversation_created(user, conversation)

    messages, has_more, oldest_seq = _serialize_page(page)
    payload = ClientConversationPayload(
        conversation=ConversationInfo(id=conversation.id, status=conversation.status),
        messages=messages,
        hasMore=has_more,
        oldestSeq=oldest_seq,
    )
    return {"data": payload}


@router.get("/conversation/messages")
async def get_conversation_messages(
    request: Request,
    db: AsyncSession = Depends(get_db),
    beforeSeq: int | None = Query(default=None, description="Keyset cursor: return messages older than this seq"),
    limit: int = Query(default=DEFAULT_PAGE_LIMIT, ge=1, description="Max messages to return"),
):
    """Return an older page of the caller's conversation history (Requirement 5.3).

    The conversation is resolved from the authenticated caller (never supplied by
    the client), so the page is inherently ownership-scoped (Requirements 5.2,
    8.3). ``beforeSeq`` is the keyset cursor (the previous page's ``oldestSeq``);
    omit it to fetch the newest page.
    """
    user = await get_current_client_user(request, db)

    conversation = await support_chat_service.get_or_create_conversation(db, user)
    page = await support_chat_service.list_messages(
        db,
        conversation.id,
        before_seq=beforeSeq,
        limit=limit,
    )

    try:
        await db.commit()
    except Exception as exc:  # pragma: no cover - defensive: surface as 500
        await db.rollback()
        raise HTTPException(status_code=500, detail="SUPPORT_CONVERSATION_FAILED") from exc

    messages, has_more, oldest_seq = _serialize_page(page)
    return {"data": MessagesPage(messages=messages, hasMore=has_more, oldestSeq=oldest_seq)}


@router.post("/conversation/messages")
async def send_conversation_message(
    request: Request,
    db: AsyncSession = Depends(get_db),
    payload: ClientSendMessageRequest = Body(...),
):
    """Send (persist) a client message in the caller's conversation.

    This is the durable persistence path: the message is validated and written
    before being confirmed (the WebSocket gateway handles live fan-out). A
    ``closed`` conversation is reopened by the service when a client posts.

    Validation failures map to ``422``; the over-length error names the 4000
    character limit (Requirements 2.1, 2.4, 2.5, 8.3).
    """
    user = await get_current_client_user(request, db)

    try:
        posted = await support_chat_service.post_client_message_with_meta(
            db, user, payload.body
        )
    except EmptyMessageError as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": "MESSAGE_EMPTY", "message": str(exc)},
        ) from exc
    except MessageTooLongError as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "MESSAGE_TOO_LONG",
                "limit": exc.limit,
                "message": str(exc),
            },
        ) from exc
    except ConversationForbiddenError as exc:
        raise HTTPException(status_code=403, detail="CONVERSATION_FORBIDDEN") from exc
    except ConversationNotFoundError as exc:
        raise HTTPException(status_code=404, detail="CONVERSATION_NOT_FOUND") from exc

    try:
        await db.commit()
    except Exception as exc:
        await db.rollback()
        raise HTTPException(status_code=500, detail="SUPPORT_MESSAGE_FAILED") from exc

    notify_support_client_message(
        user,
        posted.conversation,
        posted.message,
        conversation_was_created=posted.conversation_was_created,
        conversation_was_reopened=posted.conversation_was_reopened,
    )

    return {"data": {"message": _serialize_message(posted.message)}}
