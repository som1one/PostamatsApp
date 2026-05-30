// REST-клиент поддержки (клиентская сторона).
//
// Прямое отображение клиентских REST-эндпоинтов из
// `.kiro/specs/support-chat/design.md` (раздел *REST endpoints*) на
// типизированные функции. Это durable-путь: создание/получение переписки,
// постраничная подгрузка истории и отправка сообщения как fallback, когда
// WebSocket недоступен (Requirement 6.4 — гарантия персистентности).
//
// Все запросы идут через `requestWithAuth`, который читает access-токен из
// `readStoredSession()` и при 401 пытается обновить сессию по refresh-токену
// (см. `web/src/shared/api/client.ts`). Так клиент отправляет пользовательский
// JWT и не дублирует логику авторизации.
//
// Требования: 4.1 (получение/отправка), 5.1 (история oldest→newest),
// 5.3 (keyset-пагинация), 6.2/6.3 (реконсиляция через REST после переподключения).

import { requestWithAuth } from "@/shared/api/client";
import type { SupportChatMessage } from "./messageList";

/**
 * Жизненный статус переписки (Conversation_Status). Совпадает с
 * `ConversationStatus` на бэкенде (`open` | `in_progress` | `closed`).
 */
export type SupportConversationStatus = "open" | "in_progress" | "closed";

/**
 * Заголовок переписки, который видит владелец-клиент. Клиенту нужны только
 * идентификатор и статус собственной переписки; назначенный оператор и unread
 * — это операторские поля и тут не отдаются (см. `ConversationInfo`).
 */
export type SupportConversation = {
  id: string;
  status: SupportConversationStatus;
};

/**
 * Ответ get-or-create эндпоинта `GET /api/support/conversation`:
 * заголовок переписки + первая страница сообщений (oldest→newest) с курсорами
 * пагинации.
 */
export type GetConversationResponse = {
  conversation: SupportConversation;
  messages: SupportChatMessage[];
  /** Есть ли ещё более старые сообщения за пределами этой страницы. */
  hasMore: boolean;
  /** `seq` самого старого сообщения страницы — курсор `beforeSeq` для следующей
   *  (более старой) страницы; `null`, если страница пуста. */
  oldestSeq: number | null;
};

/**
 * Страница истории для keyset-пагинации старых сообщений
 * (`GET /api/support/conversation/messages`).
 */
export type SupportMessagesPage = {
  messages: SupportChatMessage[];
  hasMore: boolean;
  oldestSeq: number | null;
};

/**
 * Ответ на отправку сообщения по REST
 * (`POST /api/support/conversation/messages`).
 */
export type SendMessageResponse = {
  message: SupportChatMessage;
};

/**
 * Размер страницы истории по умолчанию. Совпадает с серверным
 * `DEFAULT_PAGE_LIMIT`; передавать `limit` не обязательно — при отсутствии
 * параметра сервер применит своё значение по умолчанию.
 */
export const DEFAULT_PAGE_LIMIT = 50;

/**
 * Получить (или создать) переписку текущего клиента и первую страницу её
 * сообщений (Requirements 4.1, 5.1).
 *
 * Идемпотентно: при отсутствии переписки сервер создаёт её со статусом `open`,
 * иначе возвращает существующую. Переписка резолвится из авторизованного
 * вызывающего, а не из переданного клиентом id, поэтому запрос всегда
 * ограничен собственной перепиской (Requirements 5.2, 8.3).
 */
export function getConversation(): Promise<GetConversationResponse> {
  return requestWithAuth<GetConversationResponse>("/api/support/conversation");
}

/**
 * Подгрузить более старую страницу истории по keyset-курсору (Requirement 5.3).
 *
 * @param beforeSeq Вернуть сообщения строго старше этого `seq` (обычно
 *   `oldestSeq` предыдущей страницы).
 * @param limit Максимум сообщений на странице; при `undefined` применяется
 *   серверное значение по умолчанию.
 */
export function fetchOlderMessages(
  beforeSeq: number,
  limit?: number,
): Promise<SupportMessagesPage> {
  const params = new URLSearchParams();
  params.set("beforeSeq", String(beforeSeq));
  if (limit !== undefined) {
    params.set("limit", String(limit));
  }
  return requestWithAuth<SupportMessagesPage>(
    `/api/support/conversation/messages?${params.toString()}`,
  );
}

/**
 * Отправить сообщение клиента по durable REST-пути (Requirements 4.1, 6.4).
 *
 * Используется как fallback, когда сокет недоступен: сообщение валидируется и
 * персистится на сервере независимо от живости WebSocket. Закрытая переписка
 * при этом будет переоткрыта сервисом. Пустое/из одних пробелов или превышающее
 * лимит тело сервер отклонит ошибкой валидации (`ApiError`).
 */
export function sendMessageRest(body: string): Promise<SendMessageResponse> {
  return requestWithAuth<SendMessageResponse>(
    "/api/support/conversation/messages",
    {
      method: "POST",
      body: { body },
    },
  );
}
