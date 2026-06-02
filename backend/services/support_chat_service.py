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
  (``mark_read``);
* assignment self-assign/self-release and status mutations (``assign``,
  ``set_status``);
* the operator-facing client info card (``build_client_info_card``) reporting the
  owning client's phone plus their most recent reservations and rentals.

The validators perform no I/O; importing this module performs no database work.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.admin_account import AdminAccount
from backend.models.enums import ConversationStatus, MessageAuthorType, RentalStatus, ReservationStatus
from backend.models.inventory_unit import InventoryUnit
from backend.models.product import Product
from backend.models.rental import Rental
from backend.models.reservation import Reservation
from backend.models.support_conversation import SupportConversation
from backend.models.support_conversation_read import SupportConversationRead
from backend.models.support_message import SupportMessage
from backend.models.user import User

# Maximum number of characters allowed in a (trimmed) message body.
MAX_MESSAGE_LENGTH = 4000

# Default and maximum number of messages returned by a single history page.
DEFAULT_PAGE_LIMIT = 50
MAX_PAGE_LIMIT = 100

# Maximum number of recent reservations/rentals included in the client info card
# (Requirement 13.3).
CLIENT_INFO_CARD_LIMIT = 10


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


@dataclass(frozen=True)
class ReservationSummaryData:
    """A computed recent-reservation entry for the client info card.

    Transport-agnostic value object: ``build_client_info_card`` returns these and
    the operator router maps each onto
    :class:`backend.schemas.support_schemas.ReservationSummary` (fields map by
    name in camelCase: ``product_name`` -> ``productName``, ``pickup_at`` ->
    ``pickupAt``, ``created_at`` -> ``createdAt``).

    Attributes:
        id: the reservation id.
        product_name: the reserved product's display name, or ``None`` when it
            cannot be resolved.
        status: the reservation's :class:`ReservationStatus`.
        pickup_at: the scheduled pickup time, or ``None`` when unset.
        created_at: when the reservation was created.
    """

    id: UUID
    product_name: str | None
    status: ReservationStatus
    pickup_at: datetime | None
    created_at: datetime


@dataclass(frozen=True)
class RentalSummaryData:
    """A computed recent-rental entry for the client info card.

    Transport-agnostic value object mapped by the operator router onto
    :class:`backend.schemas.support_schemas.RentalSummary` (``product_name`` ->
    ``productName``, ``starts_at`` -> ``startsAt``, ``planned_end_at`` ->
    ``plannedEndAt``).

    Attributes:
        id: the rental id.
        product_name: the rented product's display name (resolved via the
            rental's inventory unit), or ``None`` when it cannot be resolved.
        status: the rental's :class:`RentalStatus`.
        starts_at: the rental start time, or ``None`` when unset.
        planned_end_at: the planned rental end time.
        created_at: when the rental was created (used only for ordering).
    """

    id: UUID
    product_name: str | None
    status: RentalStatus
    starts_at: datetime | None
    planned_end_at: datetime
    created_at: datetime


@dataclass(frozen=True)
class ClientInfoCardData:
    """The operator-facing profile summary for a conversation's owning client.

    Transport-agnostic value object: ``build_client_info_card`` returns this and
    the operator router maps it onto
    :class:`backend.schemas.support_schemas.ClientInfoCard`. The two lists are
    capped at the 10 most recent of each, ordered newest -> oldest, and are empty
    (never ``None``) when the client has none (Requirements 13.2, 13.3, 13.4).

    Attributes:
        phone: the owning client's phone number (Requirement 13.1).
        recent_reservations: up to 10 most recent reservations, newest -> oldest.
        recent_rentals: up to 10 most recent rentals, newest -> oldest.
    """

    phone: str
    recent_reservations: list[ReservationSummaryData]
    recent_rentals: list[RentalSummaryData]


async def get_or_create_conversation_with_meta(
    db: AsyncSession, user: User
) -> tuple[SupportConversation, bool]:
    """Return the caller's conversation plus a ``was_just_created`` flag.

    Same semantics as :func:`get_or_create_conversation`; additionally reports
    whether the conversation row was inserted by this call (``True``) or was
    pre-existing (``False``). The flag is intended for one-shot side effects
    (e.g. Telegram notifications on first contact) and is computed locally —
    a concurrent insert that loses the race returns ``False``.
    """
    existing = await _load_conversation_by_user(db, user.id)
    if existing is not None:
        return existing, False

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
        return conversation, False
    return conversation, True


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
    conversation, _ = await get_or_create_conversation_with_meta(db, user)
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


@dataclass(frozen=True)
class PostedClientMessage:
    """Result of :func:`post_client_message_with_meta`.

    Carries the persisted ``message`` and the owning ``conversation`` (so callers
    can build notifications without an extra query), plus two one-shot flags:

    * ``conversation_was_created`` — ``True`` iff this call inserted the
      conversation row (i.e. the client's first ever support message).
    * ``conversation_was_reopened`` — ``True`` iff the conversation existed in
      ``CLOSED`` status before this message and was reopened to ``OPEN`` by it.
    """

    message: SupportMessage
    conversation: SupportConversation
    conversation_was_created: bool
    conversation_was_reopened: bool


async def post_client_message_with_meta(
    db: AsyncSession,
    user: User,
    body: str,
) -> PostedClientMessage:
    """Like :func:`post_client_message` but also reports lifecycle transitions.

    The returned :class:`PostedClientMessage` exposes whether this call created
    the conversation and/or reopened a previously closed one, so callers can
    fire side effects (e.g. admin Telegram notifications) without re-querying.
    """
    validated = validate_message_body(body)
    conversation, was_created = await get_or_create_conversation_with_meta(db, user)
    was_reopened = (
        not was_created and conversation.status == ConversationStatus.CLOSED
    )

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

    return PostedClientMessage(
        message=message,
        conversation=conversation,
        conversation_was_created=was_created,
        conversation_was_reopened=was_reopened,
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
    posted = await post_client_message_with_meta(db, user, body)
    return posted.message


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


async def assign(
    db: AsyncSession,
    operator: AdminAccount,
    conversation_id: UUID,
    assign: bool,
) -> SupportConversation:
    """Self-assign or self-release a conversation for ``operator``.

    Loads the conversation by id (raising :class:`ConversationNotFoundError`
    when it does not exist) and then either records or clears the assignee:

    * ``assign=True``  -> ``assigned_operator_id = operator.id`` (self-assign,
      Requirement 11.1);
    * ``assign=False`` -> ``assigned_operator_id = None`` (self-release,
      Requirement 11.4).

    Operator authorization is enforced upstream (``get_current_operator`` at the
    router/gateway layer); this function only verifies existence and applies the
    mutation. The updated conversation is flushed and returned.

    Implements Requirements 11.1, 11.4.
    """
    conversation = await db.get(SupportConversation, conversation_id)
    if conversation is None:
        raise ConversationNotFoundError()

    conversation.assigned_operator_id = operator.id if assign else None
    await db.flush()

    return conversation


async def set_status(
    db: AsyncSession,
    operator: AdminAccount,
    conversation_id: UUID,
    status: ConversationStatus,
) -> SupportConversation:
    """Set a conversation's status to ``status``.

    Loads the conversation by id (raising :class:`ConversationNotFoundError`
    when it does not exist) and persists the target :class:`ConversationStatus`.
    Operator authorization is enforced upstream (``get_current_operator``); this
    function only verifies existence and applies the mutation. The updated
    conversation is flushed and returned, so a subsequent reload reports the
    exact status that was set (Requirement 12.3).

    Implements Requirement 12.3.
    """
    conversation = await db.get(SupportConversation, conversation_id)
    if conversation is None:
        raise ConversationNotFoundError()

    conversation.status = status
    await db.flush()

    return conversation


async def build_client_info_card(
    db: AsyncSession,
    conversation_id: UUID,
) -> ClientInfoCardData:
    """Build the operator-facing client info card for a conversation.

    Resolves the conversation by id (raising :class:`ConversationNotFoundError`
    when it does not exist), then loads the owning :class:`User` to report their
    phone (Requirement 13.1) alongside their most recent reservations and rentals
    (Requirement 13.2). Each list is capped at the 10 most recent rows ordered
    newest -> oldest by ``created_at`` (Requirement 13.3) and is empty (never
    ``None``) when the client has none (Requirement 13.4).

    Product names are resolved in batch to avoid N+1 queries: reservations carry
    ``product_id`` directly, while rentals reach a product through their
    ``inventory_unit_id`` -> :class:`InventoryUnit` -> ``product_id``. All
    referenced product ids are collected and resolved with a single ``IN`` query.

    Implements Requirements 13.1, 13.2, 13.3, 13.4.
    """
    conversation = await db.get(SupportConversation, conversation_id)
    if conversation is None:
        raise ConversationNotFoundError()

    user = await db.get(User, conversation.user_id)
    if user is None:  # pragma: no cover - FK guarantees the owning user exists
        raise ConversationNotFoundError()

    reservations = list(
        (
            await db.execute(
                select(Reservation)
                .where(Reservation.user_id == user.id)
                .order_by(Reservation.created_at.desc())
                .limit(CLIENT_INFO_CARD_LIMIT)
            )
        )
        .scalars()
        .all()
    )

    rentals = list(
        (
            await db.execute(
                select(Rental)
                .where(Rental.user_id == user.id)
                .order_by(Rental.created_at.desc())
                .limit(CLIENT_INFO_CARD_LIMIT)
            )
        )
        .scalars()
        .all()
    )

    (
        product_name_by_product_id,
        product_id_by_inventory_unit_id,
    ) = await _resolve_product_names(db, reservations, rentals)

    recent_reservations = [
        ReservationSummaryData(
            id=reservation.id,
            product_name=product_name_by_product_id.get(reservation.product_id),
            status=reservation.status,
            pickup_at=reservation.pickup_at,
            created_at=reservation.created_at,
        )
        for reservation in reservations
    ]

    recent_rentals = []
    for rental in rentals:
        product_id = product_id_by_inventory_unit_id.get(rental.inventory_unit_id)
        product_name = (
            product_name_by_product_id.get(product_id) if product_id is not None else None
        )
        recent_rentals.append(
            RentalSummaryData(
                id=rental.id,
                product_name=product_name,
                status=rental.status,
                starts_at=rental.starts_at,
                planned_end_at=rental.planned_end_at,
                created_at=rental.created_at,
            )
        )

    return ClientInfoCardData(
        phone=user.phone,
        recent_reservations=recent_reservations,
        recent_rentals=recent_rentals,
    )


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


async def _resolve_product_names(
    db: AsyncSession,
    reservations: list[Reservation],
    rentals: list[Rental],
) -> tuple[dict[UUID, str], dict[UUID, UUID]]:
    """Batch-resolve product names for the client info card (no N+1).

    Reservations reference a product directly via ``product_id``; rentals reach a
    product indirectly via ``inventory_unit_id`` -> :class:`InventoryUnit` ->
    ``product_id``. This helper resolves both with at most two ``IN`` queries:

    1. one over :class:`InventoryUnit` to map each rental's inventory-unit id to
       its product id;
    2. one over :class:`Product` to map every referenced product id (from
       reservations and from the resolved inventory units) to its name.

    Returns a tuple ``(product_name_by_product_id, product_id_by_inventory_unit_id)``.
    Both maps omit ids that cannot be resolved, so callers treat a missing entry
    as an unresolved (``None``) product name.
    """
    inventory_unit_ids = {
        rental.inventory_unit_id for rental in rentals if rental.inventory_unit_id is not None
    }
    product_id_by_inventory_unit_id: dict[UUID, UUID] = {}
    if inventory_unit_ids:
        unit_rows = await db.execute(
            select(InventoryUnit.id, InventoryUnit.product_id).where(
                InventoryUnit.id.in_(inventory_unit_ids)
            )
        )
        product_id_by_inventory_unit_id = {row[0]: row[1] for row in unit_rows.all()}

    product_ids: set[UUID] = {
        reservation.product_id for reservation in reservations if reservation.product_id is not None
    }
    product_ids.update(product_id_by_inventory_unit_id.values())

    product_name_by_product_id: dict[UUID, str] = {}
    if product_ids:
        product_rows = await db.execute(
            select(Product.id, Product.name).where(Product.id.in_(product_ids))
        )
        product_name_by_product_id = {row[0]: row[1] for row in product_rows.all()}

    return product_name_by_product_id, product_id_by_inventory_unit_id


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
