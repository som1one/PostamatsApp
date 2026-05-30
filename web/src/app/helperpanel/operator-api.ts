// REST-клиент оператор-панели (`/api/admin/support/*`).
//
// Прямое отображение операторских REST-эндпоинтов из
// `.kiro/specs/support-chat/design.md` (раздел *REST endpoints* → операторская
// таблица) на типизированные функции. Это durable-путь оператора: список
// переписок, открытие переписки (сообщения + карточка клиента + сброс unread),
// постраничная подгрузка истории, ответ, назначение/снятие, смена статуса и
// отметка о прочтении.
//
// КЛЮЧЕВОЕ ОТЛИЧИЕ от клиентского REST-клиента
// (`web/src/features/support-chat/api.ts`): все запросы идут с ОПЕРАТОРСКИМ
// access-токеном из ОТДЕЛЬНОЙ операторской сессии (`operator-auth.ts`,
// localStorage-ключ `helperpanel-operator-auth`), а НЕ из `readStoredSession()`
// клиентской пользовательской сессии. На 401 токен обновляется через
// операторский refresh-flow (`refreshOperatorSession`), зеркаля логику
// `requestWithAuth`, но против операторского хранилища токенов.
//
// Требования: 9.1 (список переписок), 9.3 (unread на оператора),
// 10.3 (ответ оператора), 11.2 (назначение), 12.3 (смена статуса).

import { ApiError, requestJson } from "@/shared/api/client";
import type { SupportChatMessage } from "@/features/support-chat/messageList";
import type { SupportConversationStatus } from "@/features/support-chat/api";
import {
  clearOperatorSession,
  readOperatorSession,
  refreshOperatorSession,
  writeOperatorSession,
} from "./operator-auth";

// ---------------------------------------------------------------------------
// Типы данных (отображение Pydantic-моделей бэкенда на camelCase wire-shapes)
// ---------------------------------------------------------------------------

/**
 * Лёгкая ссылка на оператора, на которого назначена переписка
 * (`AssignedOperator` на бэкенде). `null`, когда переписка не назначена.
 */
export type AssignedOperator = {
  id: string;
  name: string;
};

/**
 * Строка переписки в операторском списке (`ConversationSummary`,
 * Requirement 9.1). Несёт статус, назначенного оператора (или `null`), превью
 * последнего сообщения, время последней активности и unread, посчитанный для
 * ЗАПРАШИВАЮЩЕГО оператора (Requirement 9.3).
 */
export type ConversationSummary = {
  id: string;
  status: SupportConversationStatus;
  assignedOperator: AssignedOperator | null;
  lastMessagePreview: string | null;
  lastMessageAt: string | null;
  unreadCount: number;
};

/**
 * Недавняя бронь в карточке клиента (`ReservationSummary`, Requirement 13).
 */
export type OperatorReservationSummary = {
  id: string;
  productName: string | null;
  status: string;
  pickupAt: string | null;
  createdAt: string;
};

/**
 * Недавняя аренда в карточке клиента (`RentalSummary`, Requirement 13).
 */
export type OperatorRentalSummary = {
  id: string;
  productName: string | null;
  status: string;
  startsAt: string | null;
  plannedEndAt: string | null;
};

/**
 * Операторская карточка клиента (`ClientInfoCard`, Requirement 13): телефон
 * владельца переписки плюс ≤10 последних броней и аренд (newest→oldest).
 * Списки пустые (никогда не `null`), когда у клиента ничего нет.
 */
export type ClientInfoCard = {
  phone: string;
  recentReservations: OperatorReservationSummary[];
  recentRentals: OperatorRentalSummary[];
};

// ---------------------------------------------------------------------------
// Типы ответов эндпоинтов
// ---------------------------------------------------------------------------

/** Ответ `GET /api/admin/support/conversations`. */
export type ListConversationsResponse = {
  conversations: ConversationSummary[];
};

/**
 * Ответ открытия переписки `GET /api/admin/support/conversations/{id}`:
 * сводка переписки (с уже сброшенным unread), первая страница сообщений
 * (oldest→newest), карточка клиента и курсоры пагинации.
 */
export type OpenConversationResponse = {
  conversation: ConversationSummary;
  messages: SupportChatMessage[];
  clientInfoCard: ClientInfoCard;
  hasMore: boolean;
  oldestSeq: number | null;
};

/**
 * Страница истории для keyset-пагинации старых сообщений
 * (`GET /api/admin/support/conversations/{id}/messages`).
 */
export type OperatorMessagesPage = {
  messages: SupportChatMessage[];
  hasMore: boolean;
  oldestSeq: number | null;
};

/** Ответ на ответ оператора `POST .../messages`. */
export type OperatorReplyResponse = {
  message: SupportChatMessage;
};

/**
 * Ответ мутаций, возвращающих обновлённую сводку переписки
 * (`POST .../assign`, `POST .../status`).
 */
export type ConversationResponse = {
  conversation: ConversationSummary;
};

/** Ответ `POST .../read` — unread после сброса (всегда 0). */
export type MarkReadResponse = {
  unreadCount: number;
};

/**
 * Размер страницы истории по умолчанию. Совпадает с серверным
 * `DEFAULT_PAGE_LIMIT`; передавать `limit` не обязательно.
 */
export const DEFAULT_PAGE_LIMIT = 50;

// ---------------------------------------------------------------------------
// Авторизованный транспорт против операторского хранилища токенов
// ---------------------------------------------------------------------------

type OperatorRequestOptions = {
  method?: "GET" | "POST" | "PATCH" | "DELETE";
  body?: unknown;
  headers?: Record<string, string>;
};

/**
 * Выполнить запрос с ОПЕРАТОРСКИМ access-токеном и refresh-on-401.
 *
 * Зеркалит `requestWithAuth` из `shared/api/client.ts`, но читает/пишет
 * операторскую сессию (`operator-auth.ts`), а не клиентскую. При 401 пытается
 * обновить сессию по операторскому refresh-токену; при неудаче обновления —
 * очищает операторскую сессию и пробрасывает ошибку (оператора отправит на
 * экран входа).
 */
async function requestWithOperatorAuth<T>(
  path: string,
  options: OperatorRequestOptions = {},
): Promise<T> {
  const session = readOperatorSession();
  if (!session?.accessToken) {
    throw new ApiError("Нужен вход оператора", 401, "UNAUTHORIZED");
  }

  try {
    return await requestJson<T>(path, { ...options, token: session.accessToken });
  } catch (error) {
    if (
      !(error instanceof ApiError) ||
      error.status !== 401 ||
      !session.refreshToken
    ) {
      throw error;
    }

    try {
      const refreshed = await refreshOperatorSession(session.refreshToken);
      writeOperatorSession({
        accessToken: refreshed.accessToken,
        refreshToken: refreshed.refreshToken,
        admin: refreshed.admin,
      });
      return await requestJson<T>(path, {
        ...options,
        token: refreshed.accessToken,
      });
    } catch (refreshError) {
      clearOperatorSession();
      throw refreshError;
    }
  }
}

const BASE_PATH = "/api/admin/support";

function conversationPath(conversationId: string, suffix = ""): string {
  return `${BASE_PATH}/conversations/${encodeURIComponent(conversationId)}${suffix}`;
}

// ---------------------------------------------------------------------------
// Эндпоинты
// ---------------------------------------------------------------------------

/**
 * Список переписок оператора, новейшие по активности сверху (Requirement 9.1).
 * Каждая сводка несёт unread, посчитанный для текущего оператора (Req 9.3).
 *
 * @param status Необязательный фильтр по статусу (Requirement 12.6).
 */
export function listConversations(
  status?: SupportConversationStatus,
): Promise<ListConversationsResponse> {
  const params = new URLSearchParams();
  if (status) {
    params.set("status", status);
  }
  const query = params.toString();
  return requestWithOperatorAuth<ListConversationsResponse>(
    query ? `${BASE_PATH}/conversations?${query}` : `${BASE_PATH}/conversations`,
  );
}

/**
 * Открыть переписку: первая страница сообщений (oldest→newest) + карточка
 * клиента, со сбросом unread текущего оператора в ноль (Requirements 9.4, 10.1,
 * 13).
 */
export function openConversation(
  conversationId: string,
): Promise<OpenConversationResponse> {
  return requestWithOperatorAuth<OpenConversationResponse>(
    conversationPath(conversationId),
  );
}

/**
 * Подгрузить более старую страницу истории по keyset-курсору (Requirement 10.1).
 *
 * @param beforeSeq Вернуть сообщения строго старше этого `seq` (обычно
 *   `oldestSeq` предыдущей страницы).
 * @param limit Максимум сообщений на странице; при `undefined` применяется
 *   серверное значение по умолчанию.
 */
export function fetchOlderMessages(
  conversationId: string,
  beforeSeq: number,
  limit?: number,
): Promise<OperatorMessagesPage> {
  const params = new URLSearchParams();
  params.set("beforeSeq", String(beforeSeq));
  if (limit !== undefined) {
    params.set("limit", String(limit));
  }
  return requestWithOperatorAuth<OperatorMessagesPage>(
    conversationPath(conversationId, `/messages?${params.toString()}`),
  );
}

/**
 * Отправить ответ оператора по durable REST-пути (Requirement 10.3).
 *
 * Тело валидируется и персистится на сервере независимо от живости WebSocket;
 * сервер затем разошлёт `message.new` другим операторам и клиенту переписки.
 * Пустое/из одних пробелов или превышающее лимит тело сервер отклонит
 * (`ApiError`).
 */
export function reply(
  conversationId: string,
  body: string,
): Promise<OperatorReplyResponse> {
  return requestWithOperatorAuth<OperatorReplyResponse>(
    conversationPath(conversationId, "/messages"),
    { method: "POST", body: { body } },
  );
}

/**
 * Назначить переписку на себя или снять назначение (Requirement 11.2).
 *
 * @param assign `true` — назначить текущего оператора, `false` — освободить.
 */
export function assign(
  conversationId: string,
  assign: boolean,
): Promise<ConversationResponse> {
  return requestWithOperatorAuth<ConversationResponse>(
    conversationPath(conversationId, "/assign"),
    { method: "POST", body: { assign } },
  );
}

/**
 * Сменить статус переписки (Requirement 12.3).
 */
export function setStatus(
  conversationId: string,
  status: SupportConversationStatus,
): Promise<ConversationResponse> {
  return requestWithOperatorAuth<ConversationResponse>(
    conversationPath(conversationId, "/status"),
    { method: "POST", body: { status } },
  );
}

/**
 * Сбросить unread текущего оператора по переписке в ноль (Requirement 9.4).
 * Влияет только на представление текущего оператора.
 */
export function markRead(conversationId: string): Promise<MarkReadResponse> {
  return requestWithOperatorAuth<MarkReadResponse>(
    conversationPath(conversationId, "/read"),
    { method: "POST" },
  );
}
