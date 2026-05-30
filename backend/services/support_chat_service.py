"""Support chat domain service.

This module hosts the authoritative support-chat domain logic:

* pure, side-effect-free message-body validators and their error types
  (``normalize_message_body`` / ``validate_message_body``);
* the database-backed conversation lifecycle, ownership-scoped reads, and
  history pagination (``get_or_create_conversation``, ``get_owned_conversation``,
  ``list_messages``).

The remaining database-backed methods (message posting, conversation listing /
unread, assignment / status mutations, and the client info card) are added in
later tasks. The validators perform no I/O; importing this module performs no
database work.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.enums import ConversationStatus
from backend.models.support_conversation import SupportConversation
from backend.models.support_message import SupportMessage
from backend.models.user import User

# Maximum number of characters allowed in a (trimmed) message body.
MAX_MESSAGE_LENGTH = 4000

# Default and maximum number of messages returned by a single history page.
DEFAULT_PAGE_LIMIT = 50
MAX_PAGE_LIMIT = 100


class MessageValidationError(Exception):
    """Base class for message-body validation failures."""


class EmptyMessageError(MessageValidationError):
    """Raised when a message body is empty or whitespace-only after trimming."""

    def __init__(self, message: str = "Message body must not be empty.") -> None:
        super().__init__(message)


class MessageTooLongError(MessageValidationError):
    """Raised when a (trimmed) message body exceeds ``MAX_MESSAGE_LENGTH``.

    The enforced ``limit`` is exposed as an attribute so callers can build a
    validation error message that names the length limit (Requirement 2.4).
    """

    def __init__(self, limit: int = MAX_MESSAGE_LENGTH) -> None:
        self.limit = limit
        super().__init__(f"Message body must not exceed {limit} characters.")


def normalize_message_body(raw: str) -> str:
    """Normalize a raw message body per policy.

    The normalization policy is to strip leading and trailing whitespace. The
    interior of the message is left untouched.
    """
    return raw.strip()


def validate_message_body(raw: str) -> str:
    """Validate and normalize a message body.

    Returns the normalized body when it is acceptable. A body is acceptable if
    and only if its trimmed length is in the inclusive range [1, 4000]
    (design Property 3).

    Raises:
        EmptyMessageError: if the trimmed body is empty or whitespace-only.
        MessageTooLongError: if the trimmed body exceeds ``MAX_MESSAGE_LENGTH``.
    """
    normalized = normalize_message_body(raw)
    if not normalized:
        raise EmptyMessageError()
    if len(normalized) > MAX_MESSAGE_LENGTH:
        raise MessageTooLongError(MAX_MESSAGE_LENGTH)
    return normalized


class ConversationAccessError(Exception):
    """Base class for conversation access/authorization failures.

    These are framework-light domain errors (no FastAPI dependency) so the
    service stays reusable from both REST routers and the WebSocket gateway.
    Routers map them to HTTP responses (typically 403/404).
    """


class ConversationNotFoundError(ConversationAccessError):
    """Raised when the requested conversation does not exist."""

    def __init__(self, message: str = "Conversation not found.") -> None:
        super().__init__(message)


class ConversationForbiddenError(ConversationAccessError):
    """Raised when a client tries to access a conversation they do not own.

    Enforces Requirements 5.2 / 8.3: a client may only read its own
    conversation's messages.
    """

    def __init__(self, message: str = "Conversation access is forbidden.") -> None:
        super().__init__(message)


@dataclass(frozen=True)
class MessagePage:
    """A single page of conversation history for keyset pagination.

    Attributes:
        messages: the page's ``SupportMessage`` rows ordered oldest -> newest
            (ascending ``seq``), ready to render directly in a chat thread.
        has_more: ``True`` when older messages exist before this page (i.e. a
            further page can be fetched using ``oldest_seq`` as ``before_seq``).
        oldest_seq: the smallest ``seq`` in this page, or ``None`` when the page
            is empty. Callers pass this back as ``before_seq`` to fetch the next
            (older) page.
    """

    messages: list[SupportMessage]
    has_more: bool
    oldest_seq: int | None


async def get_or_create_conversation(db: AsyncSession, user: User) -> SupportConversation:
    """Return the caller's conversation, creating one on first access.

    Idempotent: repeated calls for the same client return the same row because
    ``SupportConversation.user_id`` is unique (one conversation per client). A
    freshly created conversation defaults to ``ConversationStatus.OPEN``.

    The unique constraint on ``user_id`` also makes this safe under a race: if a
    concurrent caller inserts the row between our lookup and flush, the flush
    raises ``IntegrityError`` and we re-read the now-existing row instead.

    Implements Requirements 1.1, 1.2, 1.3, 12.2.
    """
    existing = await _load_conversation_by_user(db, user.id)
    if existing is not None:
        return existing

    conversation = SupportConversation(
        user_id=user.id,
        status=ConversationStatus.OPEN,
    )
    db.add(conversation)
    try:
        # Wrap the INSERT in a SAVEPOINT so a unique-violation from a concurrent
        # creator rolls back only this INSERT, not the caller's surrounding
        # transaction. flush (not commit) assigns the PK and surfaces the
        # violation while leaving transaction control to the caller.
        async with db.begin_nested():
            await db.flush()
    except IntegrityError:
        # A concurrent caller already created the conversation; the savepoint
        # rolled back our failed INSERT. Re-read and return the winning row.
        conversation = await _load_conversation_by_user(db, user.id)
        if conversation is None:  # pragma: no cover - integrity error implies a row exists
            raise
        return conversation
    return conversation


async def get_owned_conversation(
    db: AsyncSession,
    user: User,
    conversation_id: UUID,
) -> SupportConversation:
    """Load a conversation and assert the client owns it.

    Used for ownership-scoped client reads. Raises:
        ConversationNotFoundError: if no conversation has ``conversation_id``.
        ConversationForbiddenError: if the conversation exists but is owned by a
            different client.

    Enforces Requirements 5.2, 8.3.
    """
    conversation = await db.get(SupportConversation, conversation_id)
    if conversation is None:
        raise ConversationNotFoundError()
    if conversation.user_id != user.id:
        raise ConversationForbiddenError()
    return conversation


async def list_messages(
    db: AsyncSession,
    conversation_id: UUID,
    *,
    before_seq: int | None = None,
    limit: int = DEFAULT_PAGE_LIMIT,
) -> MessagePage:
    """Return a keyset-paginated page of a conversation's messages.

    The query selects the newest ``limit`` messages strictly older than
    ``before_seq`` (or the newest overall when ``before_seq`` is ``None``),
    ordered by ``seq`` descending, then reverses them so the returned page reads
    oldest -> newest. ``has_more`` reports whether an older page exists and
    ``oldest_seq`` is the keyset cursor for fetching it.

    Pagination is by ``seq`` only (a globally monotonic key), giving a stable,
    gap/dup-free ordering even when messages share a ``created_at`` timestamp.

    Backs Requirements 5.1, 5.3, 10.1.
    """
    bounded_limit = _bound_limit(limit)

    stmt = select(SupportMessage).where(
        SupportMessage.conversation_id == conversation_id
    )
    if before_seq is not None:
        stmt = stmt.where(SupportMessage.seq < before_seq)
    # Fetch one extra row to determine `has_more` without a second COUNT query.
    stmt = stmt.order_by(SupportMessage.seq.desc()).limit(bounded_limit + 1)

    result = await db.execute(stmt)
    rows = list(result.scalars().all())

    has_more = len(rows) > bounded_limit
    if has_more:
        rows = rows[:bounded_limit]

    # rows are newest -> oldest; reverse to oldest -> newest for display.
    rows.reverse()
    oldest_seq = rows[0].seq if rows else None

    return MessagePage(messages=rows, has_more=has_more, oldest_seq=oldest_seq)


async def list_owned_messages(
    db: AsyncSession,
    user: User,
    conversation_id: UUID,
    *,
    before_seq: int | None = None,
    limit: int = DEFAULT_PAGE_LIMIT,
) -> MessagePage:
    """Ownership-scoped history page for client callers.

    Verifies the requesting client owns ``conversation_id`` (Requirements 5.2,
    8.3) before returning a page via :func:`list_messages`.
    """
    await get_owned_conversation(db, user, conversation_id)
    return await list_messages(
        db,
        conversation_id,
        before_seq=before_seq,
        limit=limit,
    )


def _bound_limit(limit: int) -> int:
    """Clamp a requested page size into ``[1, MAX_PAGE_LIMIT]``."""
    if limit < 1:
        return 1
    if limit > MAX_PAGE_LIMIT:
        return MAX_PAGE_LIMIT
    return limit


async def _load_conversation_by_user(
    db: AsyncSession,
    user_id: UUID,
) -> SupportConversation | None:
    """Look up the single conversation owned by ``user_id`` (or ``None``)."""
    result = await db.execute(
        select(SupportConversation).where(SupportConversation.user_id == user_id)
    )
    return result.scalar_one_or_none()
