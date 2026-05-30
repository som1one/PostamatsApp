"""Support chat domain service.

This module hosts the authoritative support-chat domain logic:

* pure, side-effect-free message-body validators and their error types
  (``normalize_message_body`` / ``validate_message_body``);
* the database-backed conversation lifecycle, ownership-scoped reads, and
  history pagination (``get_or_create_conversation``, ``get_owned_conversation``,
  ``list_messages``);
* message posting with monotonic ordering and reopen-on-message
  (``post_client_message``, ``post_operator_message``);
* operator conversation listing with per-operator unread, latest-message
  preview, and assignee resolution (``list_conversations``), the per-operator
  unread computation (``compute_unread``), and the read-marker upsert
  (``mark_read``).

The remaining database-backed methods (assignment / status mutations and the
client info card) are added in later tasks. The validators perform no I/O;
importing this module performs no database work.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.admin_account import AdminAccount
from backend.models.enums import ConversationStatus, MessageAuthorType
from backend.models.support_conversation import SupportConversation
from backend.models.support_conversation_read import SupportConversationRead
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


@dataclass(frozen=True)
class ConversationSummaryData:
    """A computed conversation summary for the operator conversation list.

    This is a transport-agnostic value object: ``list_conversations`` returns
    these (ORM-derived id/status plus computed fields) and the operator router
    maps each one onto the :class:`backend.schemas.support_schemas.ConversationSummary`
    Pydantic model (``assigned_operator_id`` + ``assigned_operator_name`` ->
    ``assignedOperator``; the remaining fields map by name in camelCase).

    Attributes:
        id: the conversation's id.
        status: the conversation's current :class:`ConversationStatus`.
        assigned_operator_id: the assignee's admin-account id, or ``None`` when
            the conversation is unassigned.
        assigned_operator_name: the assignee's display name, resolved from
            ``AdminAccount.name``; ``None`` when unassigned.
        last_message_preview: the body of the conversation's most recent message,
            or ``None`` when the conversation has no messages yet.
        last_message_at: timestamp of the most recent message activity (the
            conversation's denormalized ``last_message_at``), or ``None``.
        unread_count: count of client-authored messages newer than the
            requesting operator's ``last_read_seq`` (Requirements 9.1, 9.3).
    """

    id: UUID
    status: ConversationStatus
    assigned_operator_id: UUID | None
    assigned_operator_name: str | None
    last_message_preview: str | None
    last_message_at: datetime | None
    unread_count: int


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


async def post_client_message(
    db: AsyncSession,
    user: User,
    body: str,
) -> SupportMessage:
    """Validate, persist, and order a client-authored message.

    The flow is durable-storage-first (Requirement 14.1): the body is validated,
    the caller's conversation is resolved (created on first contact), a globally
    monotonic ``seq`` is drawn, and the message is flushed so its ``seq`` and
    server-assigned ``created_at`` are populated before the row is returned.

    The conversation's denormalized activity markers
    (``last_message_at`` / ``last_message_seq``) are updated to this message, and
    a ``closed`` conversation is reopened (``closed`` -> ``open``); conversations
    in any other status keep their status (Requirement 12.4).

    Implements Requirements 2.1, 2.2, 12.4, 14.1, 14.2.
    """
    validated = validate_message_body(body)
    conversation = await get_or_create_conversation(db, user)

    seq = await _next_message_seq(db)
    message = SupportMessage(
        conversation_id=conversation.id,
        seq=seq,
        author_type=MessageAuthorType.CLIENT,
        author_user_id=user.id,
        body=validated,
    )
    db.add(message)
    # Flush + refresh so `seq` and the server-default `created_at` are populated
    # on the instance before we read them below and before returning.
    await db.flush()
    await db.refresh(message)

    conversation.last_message_at = message.created_at
    conversation.last_message_seq = message.seq
    # Reopen-on-message: only a client message reopens a closed conversation.
    if conversation.status == ConversationStatus.CLOSED:
        conversation.status = ConversationStatus.OPEN
    await db.flush()

    return message


async def post_operator_message(
    db: AsyncSession,
    operator: AdminAccount,
    conversation_id: UUID,
    body: str,
) -> SupportMessage:
    """Validate, persist, and order an operator-authored reply.

    The conversation must already exist (operators reply to existing client
    conversations); a missing conversation raises
    :class:`ConversationNotFoundError`. Operator authorization is enforced at the
    router/gateway layer (``get_current_operator``); this function only verifies
    existence.

    A monotonic ``seq`` is drawn from the same source as client messages and the
    row is flushed so ``seq`` / ``created_at`` are populated before returning.
    The conversation activity markers are updated, but an operator message never
    reopens a closed conversation (only client messages do; Requirement 12.4).

    Implements Requirements 2.1, 2.2, 10.2, 14.1, 14.2.
    """
    validated = validate_message_body(body)

    conversation = await db.get(SupportConversation, conversation_id)
    if conversation is None:
        raise ConversationNotFoundError()

    seq = await _next_message_seq(db)
    message = SupportMessage(
        conversation_id=conversation.id,
        seq=seq,
        author_type=MessageAuthorType.OPERATOR,
        author_admin_id=operator.id,
        body=validated,
    )
    db.add(message)
    await db.flush()
    await db.refresh(message)

    conversation.last_message_at = message.created_at
    conversation.last_message_seq = message.seq
    # Operator replies never reopen a conversation.
    await db.flush()

    return message


async def list_conversations(
    db: AsyncSession,
    operator: AdminAccount,
    *,
    status: ConversationStatus | None = None,
) -> list[ConversationSummaryData]:
    """Return operator-facing summaries for all conversations.

    Each :class:`ConversationSummaryData` carries the conversation's status, its
    resolved assignee (id + display name, or ``None`` when unassigned), the body
    of its most recent message as a preview (``None`` when empty), the activity
    timestamp, and the per-operator unread count for ``operator`` (count of
    client-authored messages newer than this operator's ``last_read_seq``;
    Requirements 9.1, 9.3).

    Results are ordered by ``last_message_at`` descending with ``last_message_seq``
    descending as a deterministic tiebreak (newest activity first); conversations
    with no activity yet sort last (Requirement 9.2). When ``status`` is provided,
    only conversations in that status are returned (Requirement 12.6).

    The query avoids per-conversation round trips: assignee names, last-message
    previews, and unread counts are each resolved in a single batched query.

    Implements Requirements 9.1, 9.2, 9.3, 12.6.
    """
    conv_stmt = select(SupportConversation)
    if status is not None:
        conv_stmt = conv_stmt.where(SupportConversation.status == status)
    conv_stmt = conv_stmt.order_by(
        SupportConversation.last_message_at.desc().nullslast(),
        SupportConversation.last_message_seq.desc().nullslast(),
    )
    conversations = list((await db.execute(conv_stmt)).scalars().all())
    if not conversations:
        return []

    # Resolve assignee display names in one query (avoid N+1).
    operator_ids = {
        c.assigned_operator_id
        for c in conversations
        if c.assigned_operator_id is not None
    }
    operator_names: dict[UUID, str] = {}
    if operator_ids:
        name_rows = await db.execute(
            select(AdminAccount.id, AdminAccount.name).where(
                AdminAccount.id.in_(operator_ids)
            )
        )
        operator_names = {row[0]: row[1] for row in name_rows.all()}

    # Resolve last-message previews in one query. `seq` is globally unique, so a
    # single `seq IN (...)` lookup maps each conversation's last_message_seq to
    # its body.
    last_seqs = {
        c.last_message_seq
        for c in conversations
        if c.last_message_seq is not None
    }
    preview_by_seq: dict[int, str] = {}
    if last_seqs:
        preview_rows = await db.execute(
            select(SupportMessage.seq, SupportMessage.body).where(
                SupportMessage.seq.in_(last_seqs)
            )
        )
        preview_by_seq = {int(row[0]): row[1] for row in preview_rows.all()}

    # Per-operator unread counts for every conversation in one grouped query.
    unread_by_conversation = await _unread_counts_for_operator(db, operator.id)

    summaries: list[ConversationSummaryData] = []
    for conversation in conversations:
        assigned_id = conversation.assigned_operator_id
        preview = (
            preview_by_seq.get(conversation.last_message_seq)
            if conversation.last_message_seq is not None
            else None
        )
        summaries.append(
            ConversationSummaryData(
                id=conversation.id,
                status=conversation.status,
                assigned_operator_id=assigned_id,
                assigned_operator_name=(
                    operator_names.get(assigned_id) if assigned_id is not None else None
                ),
                last_message_preview=preview,
                last_message_at=conversation.last_message_at,
                unread_count=unread_by_conversation.get(conversation.id, 0),
            )
        )
    return summaries


async def compute_unread(
    db: AsyncSession,
    conversation_id: UUID,
    operator_id: UUID,
) -> int:
    """Count unread client messages in a conversation for one operator.

    Unread is the number of **client-authored** messages whose ``seq`` is
    strictly greater than this operator's ``last_read_seq`` for the conversation
    (default ``0`` when the operator has never opened it). An operator's own
    replies are never counted as unread (Requirement 9.3).

    Implements Requirements 9.1, 9.3.
    """
    last_read_seq = await _operator_last_read_seq(db, conversation_id, operator_id)
    result = await db.execute(
        select(func.count())
        .select_from(SupportMessage)
        .where(SupportMessage.conversation_id == conversation_id)
        .where(SupportMessage.author_type == MessageAuthorType.CLIENT)
        .where(SupportMessage.seq > last_read_seq)
    )
    return int(result.scalar_one())


async def mark_read(
    db: AsyncSession,
    operator: AdminAccount,
    conversation_id: UUID,
) -> int:
    """Reset this operator's unread for a conversation to zero.

    Upserts the :class:`SupportConversationRead` row for
    ``(conversation_id, operator.id)``, setting ``last_read_seq`` to the
    conversation's current maximum message ``seq`` (``0`` when the conversation
    has no messages). Because unread counts only messages with ``seq`` greater
    than this marker, the requesting operator's unread becomes zero while every
    other operator's read marker — and therefore their unread — is untouched
    (Requirement 9.4).

    The upsert is done portably (works on SQLite and PostgreSQL): the existing
    read row is selected; if present it is updated, otherwise a new row is
    inserted. Returns the new ``last_read_seq``.

    Raises:
        ConversationNotFoundError: if no conversation has ``conversation_id``.

    Implements Requirement 9.4.
    """
    conversation = await db.get(SupportConversation, conversation_id)
    if conversation is None:
        raise ConversationNotFoundError()

    max_seq_result = await db.execute(
        select(func.coalesce(func.max(SupportMessage.seq), 0)).where(
            SupportMessage.conversation_id == conversation_id
        )
    )
    max_seq = int(max_seq_result.scalar_one())

    existing = await db.execute(
        select(SupportConversationRead)
        .where(SupportConversationRead.conversation_id == conversation_id)
        .where(SupportConversationRead.operator_id == operator.id)
    )
    read_row = existing.scalar_one_or_none()
    if read_row is None:
        read_row = SupportConversationRead(
            conversation_id=conversation_id,
            operator_id=operator.id,
            last_read_seq=max_seq,
        )
        db.add(read_row)
    else:
        read_row.last_read_seq = max_seq
    await db.flush()

    return max_seq


async def _next_message_seq(db: AsyncSession) -> int:
    """Draw the next globally monotonic message ordering key.

    On PostgreSQL the value comes from the dedicated ``support_message_seq``
    sequence (created by the Alembic migration), which is globally monotonic and
    gap-tolerant, giving a total order even across conversations and identical
    ``created_at`` timestamps (Requirement 14.2).

    Sequences do not exist on SQLite (used by the test/dev databases), so we fall
    back to ``max(seq) + 1`` across ``support_messages``. Because each posted
    message is flushed before the next ``seq`` is drawn, this stays unique and
    strictly increasing within a transaction.
    """
    if _dialect_name(db) == "postgresql":
        result = await db.execute(select(func.nextval("support_message_seq")))
        return int(result.scalar_one())

    result = await db.execute(select(func.coalesce(func.max(SupportMessage.seq), 0)))
    current_max = int(result.scalar_one())
    return current_max + 1


def _dialect_name(db: AsyncSession) -> str:
    """Return the bound dialect name (e.g. ``postgresql``/``sqlite``), or ``""``."""
    bind = db.bind
    if bind is None:
        return ""
    return bind.dialect.name


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


async def _operator_last_read_seq(
    db: AsyncSession,
    conversation_id: UUID,
    operator_id: UUID,
) -> int:
    """Return this operator's ``last_read_seq`` for a conversation.

    Defaults to ``0`` when no read marker exists yet, so every client message is
    unread until the operator first opens / marks the conversation read.
    """
    result = await db.execute(
        select(SupportConversationRead.last_read_seq)
        .where(SupportConversationRead.conversation_id == conversation_id)
        .where(SupportConversationRead.operator_id == operator_id)
    )
    last_read_seq = result.scalar_one_or_none()
    return int(last_read_seq) if last_read_seq is not None else 0


async def _unread_counts_for_operator(
    db: AsyncSession,
    operator_id: UUID,
) -> dict[UUID, int]:
    """Compute per-conversation unread counts for one operator in one query.

    Returns a mapping ``{conversation_id: unread_count}`` covering every
    conversation that has at least one unread client-authored message for this
    operator. Conversations absent from the mapping have an unread count of ``0``.

    The count for a conversation is the number of client-authored messages whose
    ``seq`` exceeds the operator's ``last_read_seq`` (``0`` when the operator has
    no read marker for that conversation). This is expressed as a single grouped
    query with a LEFT JOIN onto this operator's read markers so a missing marker
    is treated as ``last_read_seq = 0`` (Requirements 9.1, 9.3).
    """
    read_for_operator = (
        select(
            SupportConversationRead.conversation_id.label("conversation_id"),
            SupportConversationRead.last_read_seq.label("last_read_seq"),
        )
        .where(SupportConversationRead.operator_id == operator_id)
        .subquery()
    )

    effective_last_read = func.coalesce(read_for_operator.c.last_read_seq, 0)
    stmt = (
        select(
            SupportMessage.conversation_id,
            func.count().label("unread"),
        )
        .select_from(SupportMessage)
        .outerjoin(
            read_for_operator,
            read_for_operator.c.conversation_id == SupportMessage.conversation_id,
        )
        .where(SupportMessage.author_type == MessageAuthorType.CLIENT)
        .where(SupportMessage.seq > effective_last_read)
        .group_by(SupportMessage.conversation_id)
    )
    rows = await db.execute(stmt)
    return {row[0]: int(row[1]) for row in rows.all()}
