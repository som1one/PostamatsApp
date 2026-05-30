# Requirements Document

## Introduction

This feature replaces the current placeholder support widget (a floating panel that
only links to Telegram, WhatsApp, phone and email in `web/src/components/SupportWidget.tsx`)
with a real in-app support chat for the naprokatberu web application. The system has
two sides:

1. **Client side** — an in-app chat available to authenticated clients of the Next.js
   web app (`web/`). Clients can start a conversation with support, send messages, see
   operator replies in real time, and review their conversation history.
2. **Operator side** — a separate, dedicated operator interface served at the route
   `/helperpanel`. Support staff log in with a login and password, see a list of client
   conversations, open a conversation, and reply in real time. Operators can assign a
   conversation to themselves, move it through a status lifecycle, see a client info
   card, and see unread-message indicators.

The operator account is **not** a new authentication system. It reuses the existing
admin account infrastructure in the FastAPI backend (`backend/`): `AdminAccount`
(`backend/models/admin_account.py`), the `AdminRole` enum (`backend/models/enums.py`),
`AdminAuthSession`, PBKDF2 password hashing and admin access/refresh JWTs
(`backend/utils/admin_auth_utils.py`), and the admin auth router
(`backend/routers/admin/auth.py`). The `AdminRole` enum already declares an `OPERATOR`
value; this feature wires that role to operator chat access. Super-admins also have
operator access.

Client authentication reuses the existing user JWT auth (`backend/utils/auth_utils.py`,
`backend/routers/auth.py`) and the web auth context (`web/src/shared/auth/auth-context.tsx`).

Real-time delivery uses WebSocket connections, with Redis pub/sub
(`backend/core/redis.py`) used to fan messages out across backend workers so delivery
works regardless of which worker holds a given socket. Messages are persisted in the
database and delivered in a stable order.

Search and full conversation history search are explicitly **out of scope** for launch.

## Glossary

- **Client**: An authenticated end user of the naprokatberu web app, represented by a
  `User` row (`backend/models/user.py`) and authenticated with the existing user JWT.
- **Operator**: A support staff member authenticated through the existing admin account
  system whose `AdminAccount.role` is `OPERATOR` or `SUPER_ADMIN`.
- **Operator_Role**: The `AdminRole.OPERATOR` value in `backend/models/enums.py` that
  grants access to operator chat features.
- **Conversation**: A persisted support thread that belongs to exactly one Client and
  contains an ordered set of Messages.
- **Message**: A persisted unit of chat text with an author (Client or Operator), a
  creation timestamp, and a stable ordering key, belonging to one Conversation.
- **Conversation_Status**: The lifecycle state of a Conversation, one of `open`,
  `in_progress`, or `closed`.
- **Support_Chat_Service**: The backend component that creates Conversations, persists
  Messages, enforces authorization, and publishes real-time events.
- **Chat_Gateway**: The backend WebSocket endpoint component that authenticates socket
  connections and relays Messages and events between Clients, Operators, and the
  Support_Chat_Service.
- **Redis_Bus**: The Redis pub/sub channel set (`backend/core/redis.py`) used to
  broadcast chat events across backend workers.
- **Client_Chat_Widget**: The client-facing chat UI in the web app that replaces the
  current `SupportWidget`.
- **Operator_Panel**: The dedicated operator UI served at the `/helperpanel` route.
- **Client_Info_Card**: A panel in the Operator_Panel showing the Client's profile
  summary (phone) and recent orders/rentals.
- **Unread_Count**: The number of Messages in a Conversation that an Operator has not
  yet viewed.

## Requirements

### Requirement 1: Authenticated client starts or resumes a conversation

**User Story:** As an authenticated client, I want to open the support chat and have a
conversation ready, so that I can ask support for help without setup steps.

#### Acceptance Criteria

1. WHEN an authenticated Client opens the Client_Chat_Widget and has no existing
   Conversation, THE Support_Chat_Service SHALL create one Conversation owned by that
   Client with Conversation_Status `open`.
2. WHEN an authenticated Client opens the Client_Chat_Widget and already has a
   Conversation, THE Support_Chat_Service SHALL return that existing Conversation rather
   than creating a new one.
3. THE Support_Chat_Service SHALL associate each Conversation with exactly one Client
   identified by the Client's user identifier.

### Requirement 2: Authenticated client sends messages

**User Story:** As an authenticated client, I want to type and send messages to support,
so that I can describe my problem.

#### Acceptance Criteria

1. WHEN an authenticated Client submits a non-empty message in the Client_Chat_Widget,
   THE Support_Chat_Service SHALL persist the message as a Message authored by that
   Client in that Client's Conversation.
2. WHEN the Support_Chat_Service persists a Client Message, THE Support_Chat_Service
   SHALL record the author identity, the message text, and a creation timestamp.
3. IF a Client submits a message containing only whitespace or no text, THEN THE
   Support_Chat_Service SHALL reject the message and SHALL NOT persist a Message.
4. IF a message exceeds 4000 characters, THEN THE Support_Chat_Service SHALL reject the
   message and SHALL return a validation error describing the length limit.
5. IF a request to send a message carries no valid user access token, THEN THE
   Support_Chat_Service SHALL reject the request with an unauthorized error and SHALL
   NOT persist a Message.

### Requirement 3: Unauthenticated visitor is prompted to log in

**User Story:** As a visitor who is not logged in, I want to be told that I need to log
in to use support chat, so that I understand how to get help.

#### Acceptance Criteria

1. WHILE a visitor is not authenticated, THE Client_Chat_Widget SHALL display a prompt
   to log in instead of a message input on every page where the Client_Chat_Widget is
   present, regardless of page context.
2. WHILE a visitor is not authenticated, THE Client_Chat_Widget SHALL provide a control
   that navigates to the existing login flow.
3. IF a visitor who is not authenticated attempts to open a WebSocket connection to the
   Chat_Gateway as a Client, THEN THE Chat_Gateway SHALL reject the connection with an
   unauthorized result.

### Requirement 4: Client receives operator replies in real time

**User Story:** As an authenticated client, I want to see operator replies as soon as
they are sent, so that the conversation feels live.

#### Acceptance Criteria

1. WHEN an Operator sends a Message in a Client's Conversation, THE Chat_Gateway SHALL
   deliver that Message to the connected Client within 2 seconds under normal operation.
2. WHILE a Client has the Client_Chat_Widget open with an active connection, THE
   Client_Chat_Widget SHALL append newly received Messages to the visible message list
   in creation order.
3. WHEN a Client sends a Message, THE Client_Chat_Widget SHALL display that Message in
   the visible message list after the Support_Chat_Service confirms persistence.

### Requirement 5: Client views conversation history

**User Story:** As an authenticated client, I want to see previous messages when I open
the chat, so that I can continue where I left off.

#### Acceptance Criteria

1. WHEN an authenticated Client opens the Client_Chat_Widget, THE Support_Chat_Service
   SHALL return the existing Messages of that Client's Conversation ordered from oldest
   to newest.
2. THE Support_Chat_Service SHALL return only Messages that belong to the requesting
   Client's own Conversation.
3. WHERE a Conversation has more Messages than one page, THE Support_Chat_Service SHALL
   support retrieving older Messages in pages ordered by the stable ordering key.

### Requirement 6: Client connection state and reconnection

**User Story:** As an authenticated client, I want to know whether the chat is connected,
so that I can tell whether my messages will be delivered.

#### Acceptance Criteria

1. THE Client_Chat_Widget SHALL display a connection state indicator reflecting whether
   the chat connection is connected, connecting, or disconnected.
2. WHEN the chat connection is lost, THE Client_Chat_Widget SHALL attempt to reconnect
   automatically.
3. WHEN the chat connection is re-established after a disconnection, THE
   Client_Chat_Widget SHALL retrieve any Messages created during the disconnection so
   that the visible message list matches the persisted Conversation.
4. IF the Client submits a message WHILE the chat connection is disconnected, THEN THE
   Client_Chat_Widget SHALL indicate that the message was not sent.

### Requirement 7: Operator role and authentication at /helperpanel

**User Story:** As a support staff member, I want to log in at /helperpanel with my login
and password, so that I can access the operator chat tools.

#### Acceptance Criteria

1. THE Operator_Panel SHALL be served at the `/helperpanel` route as a dedicated
   operator interface separate from the client web pages.
2. WHEN an Operator submits a valid login and password at the Operator_Panel, THE
   Support_Chat_Service SHALL authenticate the Operator using the existing admin account
   credentials and SHALL issue an admin access token and refresh token.
3. IF a login attempt presents an unknown login or an incorrect password, THEN THE
   Support_Chat_Service SHALL reject the attempt with an authentication error and SHALL
   NOT issue tokens.
4. WHEN an admin access token expires and a valid admin refresh token is presented, THE
   Support_Chat_Service SHALL issue a new admin access token.
5. WHEN an Operator logs out, THE Support_Chat_Service SHALL revoke the corresponding
   admin auth session.
6. THE Support_Chat_Service SHALL grant operator chat access to admin accounts whose role
   is Operator_Role or `SUPER_ADMIN`.

### Requirement 8: Authorization boundaries between client and operator scopes

**User Story:** As the platform owner, I want client and operator capabilities strictly
separated, so that clients cannot access operator tools and operators act only within
their role.

#### Acceptance Criteria

1. IF a request authenticated only with a Client user token targets an operator chat
   endpoint, THEN THE Support_Chat_Service SHALL reject the request with a forbidden
   result.
2. IF a request authenticated with an admin account whose role is neither Operator_Role
   nor `SUPER_ADMIN` targets an operator chat endpoint, THEN THE Support_Chat_Service
   SHALL reject the request with a forbidden result.
3. IF a Client requests Messages or a Conversation that the Client does not own, THEN THE
   Support_Chat_Service SHALL reject the request with a forbidden or not-found result.
4. THE Chat_Gateway SHALL authenticate every WebSocket connection as either a Client or
   an Operator before relaying any Message.
5. IF a WebSocket connection presents no valid Client or Operator credentials, THEN THE
   Chat_Gateway SHALL reject the connection immediately without granting any guest or
   limited access.
6. IF an Operator attempts to send a Message to a Conversation through the Chat_Gateway
   without a valid operator authorization, THEN THE Chat_Gateway SHALL reject the send
   and SHALL NOT persist a Message.

### Requirement 9: Operator conversation list with unread indicators

**User Story:** As an operator, I want a list of client conversations with unread
indicators, so that I can see who needs a response.

#### Acceptance Criteria

1. WHEN an authenticated Operator opens the Operator_Panel, THE Support_Chat_Service
   SHALL return the list of Conversations with, for each Conversation, its
   Conversation_Status, its assigned Operator if any, the most recent Message preview,
   and the Unread_Count.
2. THE Operator_Panel SHALL order the Conversation list by most recent Message activity
   from newest to oldest.
3. WHEN a Client sends a Message in a Conversation, THE Support_Chat_Service SHALL
   increase that Conversation's Unread_Count and SHALL deliver an updated Unread_Count to
   connected Operators within 2 seconds under normal operation.
4. WHEN an Operator opens a Conversation, THE Support_Chat_Service SHALL reset that
   Conversation's Unread_Count to zero for that Operator's view.

### Requirement 10: Operator opens a conversation and replies in real time

**User Story:** As an operator, I want to open a conversation and reply, with replies
delivered to the client immediately, so that I can support clients live.

#### Acceptance Criteria

1. WHEN an Operator opens a Conversation in the Operator_Panel, THE Support_Chat_Service
   SHALL return that Conversation's Messages ordered from oldest to newest.
2. WHEN an Operator submits a non-empty reply in an opened Conversation, THE
   Support_Chat_Service SHALL persist the reply as a Message authored by that Operator in
   that Conversation.
3. WHEN the Support_Chat_Service persists an Operator Message, THE Chat_Gateway SHALL
   deliver that Message to the connected Client of that Conversation within 2 seconds
   under normal operation.
4. WHILE an Operator has a Conversation open with an active connection, THE
   Operator_Panel SHALL append newly received Client Messages to the visible message list
   in creation order.
5. IF an Operator submits a reply that is empty, whitespace only, or longer than 4000
   characters, THEN THE Support_Chat_Service SHALL reject the reply and SHALL NOT persist
   a Message.

### Requirement 11: Conversation assignment to self

**User Story:** As an operator, I want to assign a conversation to myself, so that other
operators know I am handling it.

#### Acceptance Criteria

1. WHEN an Operator assigns an unassigned Conversation to themselves, THE
   Support_Chat_Service SHALL record that Operator as the assigned Operator of the
   Conversation.
2. WHEN a Conversation's assignment changes, THE Support_Chat_Service SHALL deliver the
   updated assignment to connected Operators within 2 seconds under normal operation.
3. WHERE a Conversation is already assigned to a different Operator, THE Operator_Panel
   SHALL display the current assignee to other Operators.
4. WHEN an Operator releases a Conversation that is assigned to themselves, THE
   Support_Chat_Service SHALL record the Conversation as unassigned.

### Requirement 12: Conversation status lifecycle

**User Story:** As an operator, I want to move a conversation through open, in progress,
and closed, so that the team can track which conversations still need work.

#### Acceptance Criteria

1. THE Support_Chat_Service SHALL represent each Conversation's status as one of `open`,
   `in_progress`, or `closed`.
2. WHEN a Conversation is created, THE Support_Chat_Service SHALL set its
   Conversation_Status to `open`.
3. WHEN an Operator changes a Conversation_Status, THE Support_Chat_Service SHALL persist
   the new Conversation_Status and SHALL deliver the change to connected Operators within
   2 seconds under normal operation.
4. WHEN a Client sends a Message in a Conversation whose Conversation_Status is `closed`,
   THE Support_Chat_Service SHALL set that Conversation_Status to `open`.
5. IF persisting an Operator-initiated Conversation_Status change fails, THEN THE
   Operator_Panel SHALL show the status change as applied to preserve operator workflow
   continuity AND THE Operator_Panel SHALL surface a non-blocking indication that the
   change has not yet been saved.
6. THE Operator_Panel SHALL allow filtering the Conversation list by Conversation_Status.

### Requirement 13: Client info card

**User Story:** As an operator, I want to see who I am talking to and their recent
activity, so that I can help them with context.

#### Acceptance Criteria

1. WHEN an Operator opens a Conversation, THE Support_Chat_Service SHALL return the
   Client_Info_Card containing the Client's phone number.
2. WHEN an Operator opens a Conversation, THE Support_Chat_Service SHALL return the
   Client's recent reservations and rentals associated with the Client's user identifier.
3. THE Support_Chat_Service SHALL limit the returned recent reservations and rentals to
   at most the 10 most recent of each, ordered from newest to oldest.
4. IF the Client has no reservations or rentals, THEN THE Support_Chat_Service SHALL
   return an empty recent-activity list in the Client_Info_Card without error.

### Requirement 14: Message persistence and ordering

**User Story:** As a client and as an operator, I want messages stored reliably and shown
in a consistent order, so that the conversation is accurate after reloads.

#### Acceptance Criteria

1. THE Support_Chat_Service SHALL persist every accepted Message in durable storage
   before confirming the Message to its author.
2. THE Support_Chat_Service SHALL assign each Message a stable ordering key that
   determines a single consistent display order within a Conversation.
3. WHEN Messages of a Conversation are retrieved, THE Support_Chat_Service SHALL return
   them in the order defined by the stable ordering key.
4. WHEN two Messages in the same Conversation share an identical creation timestamp, THE
   Support_Chat_Service SHALL produce a deterministic order between them.

### Requirement 15: Real-time delivery across backend workers

**User Story:** As the platform owner, I want real-time delivery to work no matter which
backend worker holds a connection, so that messages are not lost in a multi-worker
deployment.

#### Acceptance Criteria

1. WHEN a Message or chat event is produced on one backend worker, THE
   Support_Chat_Service SHALL publish the event to the Redis_Bus so that other workers
   can deliver it to their connected sockets.
2. WHEN a backend worker receives a chat event from the Redis_Bus, THE Chat_Gateway SHALL
   deliver the event to the relevant connected Clients and Operators held by that worker.
3. IF the Redis connection is unavailable, THEN THE Support_Chat_Service SHALL still
   persist Messages durably so that no accepted Message is lost.
4. WHEN a connection is established or re-established, THE Support_Chat_Service SHALL
   allow the connecting party to retrieve persisted Messages so that real-time gaps are
   reconciled from durable storage.
