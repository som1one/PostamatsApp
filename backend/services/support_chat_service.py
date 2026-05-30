"""Support chat domain service.

This module hosts the authoritative support-chat domain logic. For now it only
contains the pure, side-effect-free message-body validators and their error
types; the database-backed service methods (get_or_create_conversation,
post_client_message, list_conversations, ...) are added in later tasks.

Importing this module performs no database or I/O work.
"""

from __future__ import annotations

# Maximum number of characters allowed in a (trimmed) message body.
MAX_MESSAGE_LENGTH = 4000


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
