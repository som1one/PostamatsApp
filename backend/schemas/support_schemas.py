"""Pydantic request/response models for the support chat feature.

These models describe the JSON shapes exchanged over the support-chat REST and
WebSocket contracts (see ``.kiro/specs/support-chat/design.md``). They follow the
project convention of plain :class:`pydantic.BaseModel` subclasses with
camelCase field names; response payloads are assembled into the ``{"data": ...}``
envelope by the routers.

Importing this module performs no database or I/O work and must stay free of
imports from :mod:`backend.services.support_chat_service` to avoid a circular
import (the service imports the response models defined here).
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from backend.models.enums import (
    ConversationStatus,
    MessageAuthorType,
    RentalStatus,
    ReservationStatus,
)

# Mirrors ``support_chat_service.MAX_MESSAGE_LENGTH``. Duplicated here as a plain
# constant (rather than imported) so this module stays decoupled from the
# service module. The authoritative validation gate lives in the service's
# ``validate_message_body``; the ``max_length`` below is only a schema-level hint.
MAX_MESSAGE_LENGTH = 4000


# ---------------------------------------------------------------------------
# Core serialized entities
# ---------------------------------------------------------------------------


class Message(BaseModel):
    """A serialized support message (the canonical wire shape).

    Mirrors the WebSocket ``message`` payload
    ``{ id, conversationId, seq, authorType, authorName, body, createdAt }``.
    ``seq`` is the stable monotonic ordering key used for display order and gap
    detection on the client.
    """

    id: UUID = Field(..., description="Message id")
    conversationId: UUID = Field(..., description="Owning conversation id")
    seq: int = Field(..., description="Stable monotonic ordering key")
    authorType: MessageAuthorType = Field(..., description="client | operator")
    authorName: str | None = Field(default=None, description="Display name of the author, if known")
    body: str = Field(..., description="Message text")
    createdAt: datetime = Field(..., description="Creation timestamp")


class AssignedOperator(BaseModel):
    """Lightweight reference to the operator a conversation is assigned to."""

    id: UUID = Field(..., description="Admin account id of the assigned operator")
    name: str = Field(..., description="Display name / login of the assigned operator")


class ConversationSummary(BaseModel):
    """A conversation row in the operator conversation list (Requirement 9.1)."""

    id: UUID = Field(..., description="Conversation id")
    status: ConversationStatus = Field(..., description="open | in_progress | closed")
    assignedOperator: AssignedOperator | None = Field(
        default=None, description="Current assignee, or null when unassigned"
    )
    lastMessagePreview: str | None = Field(
        default=None, description="Preview of the most recent message, if any"
    )
    lastMessageAt: datetime | None = Field(
        default=None, description="Timestamp of the most recent message activity"
    )
    unreadCount: int = Field(
        default=0,
        ge=0,
        description="Unread client messages for the requesting operator",
    )


class ConversationInfo(BaseModel):
    """Conversation header returned to the owning client.

    Clients only need the identity and lifecycle status of their own
    conversation; assignee and unread are operator-only concerns.
    """

    id: UUID = Field(..., description="Conversation id")
    status: ConversationStatus = Field(..., description="open | in_progress | closed")


# ---------------------------------------------------------------------------
# Paged history payloads
# ---------------------------------------------------------------------------


class MessagesPage(BaseModel):
    """A page of messages for older-history (keyset) pagination.

    ``oldestSeq`` is the ``seq`` of the oldest message in this page and is used
    as the ``beforeSeq`` cursor for fetching the next older page; it is null when
    the page is empty. ``hasMore`` indicates whether older messages remain.
    """

    messages: list[Message] = Field(default_factory=list, description="Messages, oldest→newest")
    hasMore: bool = Field(default=False, description="Whether older messages remain")
    oldestSeq: int | None = Field(
        default=None, description="seq of the oldest message in this page (next cursor)"
    )


class ClientConversationPayload(BaseModel):
    """Response for the client get-or-create endpoint.

    Bundles the conversation header with the first page of messages
    (``GET /api/support/conversation`` → ``{ conversation, messages, hasMore, oldestSeq }``).
    """

    conversation: ConversationInfo = Field(..., description="The caller's conversation")
    messages: list[Message] = Field(default_factory=list, description="First page, oldest→newest")
    hasMore: bool = Field(default=False, description="Whether older messages remain")
    oldestSeq: int | None = Field(
        default=None, description="seq of the oldest message in this page (next cursor)"
    )


# ---------------------------------------------------------------------------
# Client info card (Requirement 13)
# ---------------------------------------------------------------------------


class ReservationSummary(BaseModel):
    """Lightweight recent-reservation entry for the client info card."""

    id: UUID = Field(..., description="Reservation id")
    productName: str | None = Field(default=None, description="Reserved product name")
    status: ReservationStatus = Field(..., description="Reservation status")
    pickupAt: datetime | None = Field(default=None, description="Scheduled pickup time, if set")
    createdAt: datetime = Field(..., description="When the reservation was created")


class RentalSummary(BaseModel):
    """Lightweight recent-rental entry for the client info card."""

    id: UUID = Field(..., description="Rental id")
    productName: str | None = Field(default=None, description="Rented product name")
    status: RentalStatus = Field(..., description="Rental status")
    startsAt: datetime | None = Field(default=None, description="Rental start time, if set")
    plannedEndAt: datetime | None = Field(default=None, description="Planned rental end time")


class ClientInfoCard(BaseModel):
    """Operator-facing profile summary for the conversation's owning client.

    Lists are capped at the 10 most recent of each, ordered newest→oldest, and
    are empty (never null) when the client has none (Requirements 13.3, 13.4).
    """

    phone: str = Field(..., description="Owning client's phone number")
    recentReservations: list[ReservationSummary] = Field(
        default_factory=list,
        max_length=10,
        description="Up to 10 most recent reservations, newest→oldest",
    )
    recentRentals: list[RentalSummary] = Field(
        default_factory=list,
        max_length=10,
        description="Up to 10 most recent rentals, newest→oldest",
    )


# ---------------------------------------------------------------------------
# Request bodies
# ---------------------------------------------------------------------------


class ClientSendMessageRequest(BaseModel):
    """Body for a client sending a message (``POST /api/support/conversation/messages``).

    The conversation is resolved from the authenticated caller. ``max_length`` is
    a schema-level hint; emptiness/whitespace and the authoritative length gate
    are enforced by the service validators.
    """

    body: str = Field(..., max_length=MAX_MESSAGE_LENGTH, description="Message text")


class OperatorSendMessageRequest(BaseModel):
    """Body for an operator reply.

    The target ``conversationId`` is taken from the REST path, so only the body
    is carried here. ``max_length`` is a schema-level hint; the service performs
    the authoritative validation.
    """

    body: str = Field(..., max_length=MAX_MESSAGE_LENGTH, description="Reply text")


class StatusChangeRequest(BaseModel):
    """Body for changing a conversation's status (``POST .../status``)."""

    status: ConversationStatus = Field(..., description="Target status: open | in_progress | closed")


class AssignRequest(BaseModel):
    """Body for self-assign / self-release (``POST .../assign``)."""

    assign: bool = Field(..., description="True to assign to self, false to release")
