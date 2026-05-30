# Implementation Plan: Support Chat

## Overview

Convert the support-chat design into incremental coding steps. The build proceeds
durable-storage-first: data models, enums, the Alembic migration, Pydantic schemas,
and pure validators come first; then the `Support_Chat_Service` domain logic with its
property tests; then the realtime layer (events, connection hub, WS gateway); then the
REST routers and `backend/main.py` wiring; then the client chat widget; then the
`/helperpanel` operator panel; and finally an integration/wiring pass with full test
and build verification.

Backend is Python/FastAPI tested with **pytest + Hypothesis**. Frontend is
TypeScript/Next.js tested with **vitest + fast-check**. Each property-based test runs a
minimum of 100 iterations (`max_examples=100+` / `numRuns: 100+`) and carries a comment
tag in the form `Feature: support-chat, Property {number}: {property_text}`. Each
property test lives in its own test module so independent tests can run in parallel.

## Tasks

- [x] 1. Foundation: data models, enums, migration, schemas, and pure helpers
  - [x] 1.1 Add chat enums to `backend/models/enums.py`
    - Add `ConversationStatus` (`open`, `in_progress`, `closed`) and `MessageAuthorType` (`client`, `operator`) string enums
    - _Requirements: 12.1, 14.2_

  - [x] 1.2 Create ORM models and register them with `init_db`
    - Create `backend/models/support_conversation.py` (`SupportConversation`: UUID pk, unique `user_id` FK→`users.id`, `status` enum default `open`, nullable `assigned_operator_id` FK→`admin_accounts.id`, indexed nullable `last_message_at`, nullable `last_message_seq` bigint, timestamps)
    - Create `backend/models/support_message.py` (`SupportMessage`: UUID pk, `conversation_id` FK, not-null `seq` bigint, `author_type` enum, nullable `author_user_id`/`author_admin_id`, not-null `body`, `created_at`; composite index `(conversation_id, seq)`)
    - Create `backend/models/support_conversation_read.py` (`SupportConversationRead`: UUID pk, `conversation_id` FK, `operator_id` FK, not-null `last_read_seq` bigint default 0, `updated_at`; unique `(conversation_id, operator_id)`)
    - Add the three modules to the `init_db()` import list so dev/test DBs get the tables
    - _Requirements: 1.2, 1.3, 9.1, 11.1, 12.1, 14.1, 14.2_

  - [x] 1.3 Create the Alembic migration
    - New revision in `alembic/versions/` with `down_revision = "d9e2b4f5c601"`
    - `upgrade`: `CREATE SEQUENCE support_message_seq`; create the `conversation_status` and `message_author_type` enum types via `postgresql.ENUM(...).create(bind, checkfirst=True)`; create the three tables with the unique `user_id` index, the `(conversation_id, seq)` index, the `last_message_at` index, and the `(conversation_id, operator_id)` unique constraint
    - `downgrade`: drop tables (reverse order), then the two enums, then the sequence
    - _Requirements: 14.1, 14.2_

  - [x] 1.4 Create Pydantic schemas in `backend/schemas/support_schemas.py`
    - Request/response models: serialized `Message` (`id, conversationId, seq, authorType, authorName, body, createdAt`), `ConversationSummary` (status, assignee, last preview, unread), conversation + messages page payloads, `ClientInfoCard` (`phone`, `recentReservations[≤10]`, `recentRentals[≤10]`), and message-send request bodies
    - _Requirements: 9.1, 10.1, 13.1, 13.2_

  - [x] 1.5 Implement pure message-body validators in `backend/services/support_chat_service.py`
    - Add `MAX_MESSAGE_LENGTH = 4000`, `normalize_message_body(raw)`, `validate_message_body(raw)`, and `EmptyMessageError` / `MessageTooLongError`
    - Add `hypothesis` to `backend/requirements.txt` for the property tests that follow
    - _Requirements: 2.3, 2.4, 10.5_

  - [ ]* 1.6 Write property test for body validation
    - **Property 3: Message body validation accepts iff trimmed length is in [1, 4000]**
    - Own test module (e.g. `backend/tests/test_support_prop03_validation.py`); assert accept/reject is independent of author kind
    - **Validates: Requirements 2.3, 2.4, 10.5**

  - [x] 1.7 Implement WS auth helpers and operator-role guard in `backend/utils/support_auth.py`
    - `operator_has_access(role)` pure predicate (true iff `OPERATOR` or `SUPER_ADMIN`), `get_current_operator` dependency (calls `get_current_admin` then asserts role, else 403), and WS token verifiers reusing `verify_access_token` / `verify_admin_access_token` for `?token=` handshakes
    - _Requirements: 3.3, 7.6, 8.2, 8.4, 8.5_

  - [ ]* 1.8 Write property test for operator-access predicate
    - **Property 7: Operator access is granted exactly to operator and super-admin roles**
    - Own test module; iterate over every `AdminRole` value
    - **Validates: Requirements 7.6, 8.2**

- [x] 2. Implement Support_Chat_Service domain logic
  - [x] 2.1 Implement conversation lifecycle, ownership-scoped reads, and history pagination
    - In `support_chat_service.py`: `get_or_create_conversation` (idempotent upsert on unique `user_id`, new conversations default `open`) and `list_messages` keyset pagination (`WHERE conversation_id=? AND seq<? ORDER BY seq DESC LIMIT n`), always scoped by `conversation.user_id` for client callers
    - _Requirements: 1.1, 1.2, 1.3, 5.1, 5.2, 5.3, 8.3, 10.1, 12.2_

  - [ ]* 2.2 Write property test for get-or-create idempotency
    - **Property 1: Conversation get-or-create is idempotent and yields one open conversation per client**
    - Own test module; transactional test DB with per-example rollback
    - **Validates: Requirements 1.1, 1.2, 1.3, 12.2**

  - [ ]* 2.3 Write property test for client read ownership
    - **Property 6: Clients can read only their own conversation's messages**
    - Own test module
    - **Validates: Requirements 5.2, 8.3**

  - [ ]* 2.4 Write property test for keyset pagination
    - **Property 5: Keyset pagination reproduces the full ordered history exactly**
    - Own test module; concatenate successive `beforeSeq` pages and assert no gaps/dupes/overlaps
    - **Validates: Requirements 5.3**

  - [x] 2.5 Implement message posting with monotonic ordering and reopen-on-message
    - In `support_chat_service.py`: `post_client_message` and `post_operator_message` — validate body, draw `seq` from `support_message_seq`, set `author_type`/author id columns, persist before returning, update `last_message_at`/`last_message_seq`, and flip `closed`→`open` on a client message
    - _Requirements: 2.1, 2.2, 10.2, 12.4, 14.1, 14.2_

  - [ ]* 2.6 Write property test for message persistence and author fields
    - **Property 2: Valid messages persist with correct author fields and round-trip**
    - Own test module
    - **Validates: Requirements 2.1, 2.2, 10.2**

  - [ ]* 2.7 Write property test for ordering keys
    - **Property 4: Ordering keys are strictly increasing and retrieval is deterministically ordered**
    - Own test module; include the identical-`created_at` tiebreak case
    - **Validates: Requirements 14.2, 14.3, 14.4, 5.1, 10.1**

  - [ ]* 2.8 Write property test for reopen-on-message
    - **Property 14: A client message reopens a closed conversation**
    - Own test module; non-closed statuses must be preserved
    - **Validates: Requirements 12.4**

  - [x] 2.9 Implement conversation listing, unread computation, and mark-read
    - In `support_chat_service.py`: `list_conversations` (summaries with status, assignee, latest preview, per-operator unread; ordered by `last_message_at` desc with `last_message_seq` tiebreak; optional status filter) and `mark_read` (upsert `last_read_seq` to the conversation max for that operator only); unread = count of client-authored messages with `seq > last_read_seq`
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 12.6_

  - [ ]* 2.10 Write property test for per-operator unread
    - **Property 10: Per-operator unread count is consistent and reset on open**
    - Own test module; assert reset affects only the acting operator
    - **Validates: Requirements 9.1, 9.3, 9.4**

  - [ ]* 2.11 Write property test for conversation summaries
    - **Property 11: Conversation summaries carry correct status, assignee, preview, and unread**
    - Own test module
    - **Validates: Requirements 9.1**

  - [ ]* 2.12 Write property test for list ordering
    - **Property 12: Conversation list is ordered by most recent activity, newest first**
    - Own test module
    - **Validates: Requirements 9.2**

  - [ ]* 2.13 Write property test for status filter
    - **Property 13: Status filter returns exactly the conversations with that status**
    - Own test module
    - **Validates: Requirements 12.6**

  - [x] 2.14 Implement assignment and status mutations
    - In `support_chat_service.py`: `assign` (record/clear `assigned_operator_id` for self-assign and self-release) and `set_status` (persist target status)
    - _Requirements: 11.1, 11.4, 12.3_

  - [ ]* 2.15 Write property test for assignment round trip
    - **Property 16: Assign-then-release returns a conversation to unassigned**
    - Own test module
    - **Validates: Requirements 11.1, 11.4**

  - [ ]* 2.16 Write property test for status round trip
    - **Property 15: Status changes round-trip through persistence**
    - Own test module; iterate all `{open, in_progress, closed}` targets
    - **Validates: Requirements 12.3**

  - [x] 2.17 Implement the client info card builder
    - In `support_chat_service.py`: `build_client_info_card` returning the owning client's phone plus their ≤10 most recent reservations and rentals (newest→oldest), empty lists when none
    - _Requirements: 13.1, 13.2, 13.3, 13.4_

  - [ ]* 2.18 Write property test for the client info card
    - **Property 17: Client info card reflects only the owning client's data within limits**
    - Own test module
    - **Validates: Requirements 13.1, 13.2, 13.3, 13.4**

- [ ] 3. Checkpoint - Ensure all backend service tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 4. Implement the realtime layer
  - [x] 4.1 Implement event/envelope schema in `backend/realtime/events.py`
    - Define inbound action types (`message.send`, `conversation.open`, `conversation.markRead`, `conversation.assign`, `conversation.setStatus`, `ping`) and outbound event types (`message.ack`, `message.new`, `unread.update`, `conversation.updated`, `assignment.changed`, `status.changed`, `error`, `pong`), plus the audience hint (`client`/`operators`/`both`) and message serializer
    - _Requirements: 4.1, 15.1, 15.2_

  - [x] 4.2 Implement the per-worker connection hub in `backend/realtime/connection_hub.py`
    - Socket registry (clients grouped by `conversation_id`, operator sockets with currently-open conversation), `dispatch_local` recipient selection, `publish` to the single `support:events` Redis channel after persistence, `run_subscriber` background task, and graceful local-only fallback when `get_redis_client()` is `None`
    - _Requirements: 15.1, 15.2, 15.3_

  - [ ]* 4.3 Write property test for dispatch recipient selection
    - **Property 18: Event dispatch selects the correct local recipients**
    - Own test module; test `dispatch_local`'s pure recipient-set computation in isolation from socket I/O
    - **Validates: Requirements 15.2**

  - [x] 4.4 Implement the WS gateway in `backend/realtime/chat_gateway.py`
    - `/ws/support` (client JWT) and `/ws/helperpanel` (admin JWT + operator role) endpoints: validate the `?token=` handshake, `close(4401)` on failure before any hub registration, parse action envelopes, re-check operator authorization on `message.send`, delegate to the service, register sockets with the hub, and emit `message.ack`/`message.new`
    - _Requirements: 3.3, 4.1, 8.4, 8.5, 8.6, 10.3, 10.4_

  - [ ]* 4.5 Write integration tests for the WS gateway
    - 1–3 representative examples: unauthenticated connection rejected with `4401`, and operator→client `message.new` delivery
    - _Requirements: 3.3, 4.1, 8.4, 8.5, 10.3_

- [x] 5. Implement REST routers and wire everything into the app
  - [x] 5.1 Implement the client REST router `backend/routers/support.py`
    - Prefix `/api/support`: `GET /conversation` (get-or-create + first message page), `GET /conversation/messages` (older pages via `beforeSeq`/`limit`), `POST /conversation/messages` (send, persistence path); all guarded by `get_current_client_user` and scoped to the caller's own conversation
    - _Requirements: 1.1, 2.1, 2.4, 2.5, 5.1, 5.3, 8.3_

  - [x] 5.2 Implement the operator REST router `backend/routers/admin/support.py`
    - Prefix `/api/admin/support`, all guarded by `get_current_operator`: list conversations (with status filter), open conversation (messages + client info card + reset this operator's unread), older history page, reply, assign/release, change status, mark read
    - _Requirements: 8.1, 8.2, 9.1, 9.4, 10.1, 10.2, 10.5, 11.1, 11.3, 12.3, 12.6, 13.1, 13.2_

  - [x] 5.3 Wire routers, WS endpoints, and hub lifecycle into `backend/main.py`
    - `include_router` for both routers, register `/ws/support` and `/ws/helperpanel`, start the connection hub + Redis subscriber in `startup_event`, and cancel the subscriber task in `shutdown_event`
    - _Requirements: 7.2, 15.1, 15.2_

  - [ ]* 5.4 Write integration tests for REST auth boundaries
    - Client token rejected on operator routes; non-operator admin rejected; client cannot read another client's conversation
    - _Requirements: 8.1, 8.2, 8.3_

- [ ] 6. Checkpoint - Ensure backend tests and migration apply cleanly
  - Ensure all tests pass, ask the user if questions arise.

- [x] 7. Implement the client chat widget
  - [x] 7.1 Implement pure message-list reducers in `web/src/features/support-chat/`
    - Message-list merge reducer (dedupe by id, sort ascending by `seq`) and gap-reconciliation helper (merge persisted messages with `seq` above the local max)
    - Add `fast-check` to `web/` devDependencies for the property tests that follow
    - _Requirements: 4.2, 6.3, 10.4, 15.4_

  - [ ]* 7.2 Write property test for the message-list merge reducer
    - **Property 8: Message-list merge yields a deduplicated, seq-ascending list**
    - Own fast-check spec; feed permutations with duplicates
    - **Validates: Requirements 4.2, 10.4**

  - [ ]* 7.3 Write property test for gap reconciliation
    - **Property 9: Reconnection reconciliation matches the persisted conversation**
    - Own fast-check spec
    - **Validates: Requirements 6.3, 15.4**

  - [x] 7.4 Implement the support-chat WS and REST clients
    - WebSocket client (connect with `?token=`, send actions, dispatch events, auto-reconnect) and REST client (get-or-create conversation, fetch older pages, send fallback) under `web/src/features/support-chat/`
    - _Requirements: 4.1, 5.1, 5.3, 6.2, 6.3_

  - [x] 7.5 Implement the Client_Chat_Widget replacing `web/src/components/SupportWidget.tsx`
    - Auth-gated UI (login prompt + control to existing login flow when unauthenticated), connection-state indicator, message list using the merge reducer, send box, history load + keyset pagination, auto-reconnect with gap reconciliation on reconnect, and a "not sent" indicator for sends while disconnected
    - _Requirements: 1.1, 2.1, 3.1, 3.2, 4.2, 4.3, 5.1, 6.1, 6.2, 6.3, 6.4_

  - [ ]* 7.6 Write unit tests for widget UI states
    - Login prompt for unauthenticated visitors, connection-state indicator, and disconnected-send indicator
    - _Requirements: 3.1, 3.2, 6.1, 6.4_

- [x] 8. Implement the operator panel at /helperpanel
  - [x] 8.1 Create the `/helperpanel` route group, layout, and login screen
    - `web/src/app/helperpanel/layout.tsx` that does NOT wrap children in `PageShell` (no `AppHeader`/`Footer`/`SupportWidget`), plus a login screen reusing the existing admin auth endpoints (`/api/admin/auth/login`, `/refresh`, `/logout`, `/me`)
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5_

  - [x] 8.2 Implement the operator API and WS clients
    - REST client for `/api/admin/support/*` and an operator WebSocket client for `/ws/helperpanel` (list-level + conversation-scoped events) under `web/src/app/helperpanel/`
    - _Requirements: 9.1, 9.3, 10.3, 11.2, 12.3_

  - [x] 8.3 Implement the conversation list with status filter and unread badges
    - Conversation list ordered newest-first, status filter control, unread badges, and live `unread.update`/`conversation.updated` handling
    - _Requirements: 9.1, 9.2, 9.3, 12.6_

  - [x] 8.4 Implement the conversation view
    - Message thread (reusing the merge reducer), reply box, client info card, assign/release control with current-assignee display, and status control with optimistic apply + non-blocking "not yet saved" badge on failure
    - _Requirements: 10.1, 10.2, 10.4, 11.1, 11.3, 11.4, 12.3, 12.5, 13.1, 13.2_

  - [ ]* 8.5 Write unit tests for the operator panel
    - Smoke test that `/helperpanel` renders without `PageShell` chrome, optimistic status badge behavior, and current-assignee display
    - _Requirements: 7.1, 11.3, 12.5_

- [ ] 9. Checkpoint - Ensure frontend tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 10. Integration, wiring, and verification
  - [x] 10.1 Final wiring pass
    - Confirm the client widget and operator panel consume the live REST/WS contracts, the widget is mounted in the client `PageShell` while `/helperpanel` stays excluded, and there is no orphaned/unintegrated code
    - _Requirements: 3.1, 4.1, 7.1, 15.2_

  - [ ]* 10.2 Run the backend test suite
    - Run pytest including all Hypothesis property tests (`max_examples` ≥ 100) and the WS/REST integration tests
    - _Requirements: 2.3, 2.4, 5.3, 9.1, 11.1, 12.3, 13.1, 14.2, 15.2_

  - [ ]* 10.3 Run the frontend test suite
    - Run `vitest run` including the fast-check property specs (`numRuns` ≥ 100) and widget/panel unit tests
    - _Requirements: 4.2, 6.3, 10.4, 15.4_

  - [ ]* 10.4 Run build and migration verification
    - `next build`, `tsc --noEmit`, `eslint`, and apply the Alembic migration against a scratch database to confirm `upgrade`/`downgrade`
    - _Requirements: 7.1, 14.1_

## Notes

- Tasks marked with `*` are optional test/verification sub-tasks and can be skipped for a faster MVP; top-level tasks are never optional.
- Each task references the specific requirement sub-clauses it implements for traceability.
- Checkpoints (tasks 3, 6, 9) provide incremental validation gates.
- Property-based tests validate the 18 universal correctness properties from the design (backend via Hypothesis, frontend via fast-check), each as a single tagged test with ≥100 iterations in its own module.
- Service implementation sub-tasks (2.1, 2.5, 2.9, 2.14, 2.17) all edit `backend/services/support_chat_service.py` and are therefore sequenced into separate waves.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.5", "1.7", "7.1", "8.1"] },
    { "id": 1, "tasks": ["1.2", "1.4", "1.6", "1.8", "7.2", "7.3"] },
    { "id": 2, "tasks": ["1.3", "2.1", "4.1"] },
    { "id": 3, "tasks": ["2.5", "2.2", "2.3", "2.4", "4.2"] },
    { "id": 4, "tasks": ["2.9", "2.6", "2.7", "2.8", "4.3", "5.1"] },
    { "id": 5, "tasks": ["2.14", "2.10", "2.11", "2.12", "2.13"] },
    { "id": 6, "tasks": ["2.17", "2.15", "2.16", "4.4"] },
    { "id": 7, "tasks": ["2.18", "5.2", "4.5", "7.4"] },
    { "id": 8, "tasks": ["5.3", "7.5", "8.2"] },
    { "id": 9, "tasks": ["5.4", "7.6", "8.3", "8.4"] },
    { "id": 10, "tasks": ["8.5", "10.1"] },
    { "id": 11, "tasks": ["10.2", "10.3", "10.4"] }
  ]
}
```
