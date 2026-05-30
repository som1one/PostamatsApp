// Pure message-list reducers for the support chat client.
//
// Эти функции НЕ зависят от React, сети или любого I/O — это чистые
// преобразования над упорядоченными списками сообщений. Благодаря этому их
// можно покрыть property-тестами (fast-check) в задачах 7.2 / 7.3.
//
// Дизайн: .kiro/specs/support-chat/design.md
//   - Property 8: merge-редьюсер выдаёт дедуплицированный список, строго
//     возрастающий по `seq`.
//   - Property 9: реконсиляция после переподключения совпадает с персистентной
//     (persisted) перепиской без пропусков и дубликатов.

/**
 * Сериализованное сообщение поддержки в том виде, в котором его отдаёт
 * бэкенд (см. `message` в design.md: WebSocket protocol / REST endpoints).
 *
 * `seq` — глобальный монотонный ключ упорядочивания (на сервере это bigint из
 * последовательности `support_message_seq`). В сериализованном виде он
 * приходит как `number` и используется как единственный ключ сортировки.
 */
export type SupportChatMessage = {
  id: string;
  conversationId: string;
  seq: number;
  authorType: "client" | "operator";
  authorName?: string;
  body: string;
  createdAt: string;
};

/**
 * Сравнение по `seq` для строгой сортировки по возрастанию.
 *
 * Используем сравнение, а не вычитание (`a.seq - b.seq`), чтобы не терять
 * точность на больших значениях `seq` (последовательность на сервере —
 * bigint). `seq` уникален в рамках одной переписки, поэтому дополнительного
 * tiebreak не требуется; при равенстве сохраняем стабильный порядок.
 */
function compareBySeq(a: SupportChatMessage, b: SupportChatMessage): number {
  if (a.seq < b.seq) return -1;
  if (a.seq > b.seq) return 1;
  return 0;
}

/**
 * MERGE-редьюсер списка сообщений (Property 8).
 *
 * Принимает текущий упорядоченный список и одно или несколько входящих
 * сообщений (в любом порядке, возможно с дубликатами по `id`), и возвращает
 * НОВЫЙ список, который:
 *   - содержит каждый `id` ровно один раз (дедупликация по `id`);
 *   - строго упорядочен по возрастанию `seq`.
 *
 * При совпадении `id` побеждает входящее сообщение (последняя версия), что
 * корректно для возможных переотправок одной и той же записи. Исходные
 * массивы не мутируются.
 */
export function mergeMessages(
  existing: readonly SupportChatMessage[],
  incoming: SupportChatMessage | readonly SupportChatMessage[],
): SupportChatMessage[] {
  const incomingList = Array.isArray(incoming)
    ? incoming
    : [incoming as SupportChatMessage];

  const byId = new Map<string, SupportChatMessage>();
  for (const message of existing) {
    byId.set(message.id, message);
  }
  for (const message of incomingList) {
    byId.set(message.id, message);
  }

  return Array.from(byId.values()).sort(compareBySeq);
}

/**
 * Максимальный известный `seq` в локальном списке, либо `null` для пустого
 * списка. Используется, чтобы запросить у сервера только сообщения, созданные
 * во время разрыва соединения (`seq` строго больше локального максимума).
 */
export function localMaxSeq(
  messages: readonly SupportChatMessage[],
): number | null {
  let max: number | null = null;
  for (const message of messages) {
    if (max === null || message.seq > max) {
      max = message.seq;
    }
  }
  return max;
}

/**
 * Хелпер реконсиляции пропусков после переподключения (Property 9).
 *
 * Берёт локально известный (упорядоченный) список и персистентные (persisted)
 * сообщения, после чего вмерживает в локальный список те персистентные
 * сообщения, чей `seq` строго больше локального максимума. Если локальный
 * список — префикс полной переписки (типичный случай: клиент получил
 * непрерывное начало переписки, затем разорвал соединение), результат равен
 * полному персистентному упорядоченному списку без пропусков и дубликатов.
 *
 * Фильтрация по «выше локального максимума» делает хелпер идемпотентным и
 * корректным как при передаче уже отфильтрованного «хвоста» (сообщения после
 * `localMaxSeq`), так и при передаче полной персистентной переписки.
 */
export function reconcileMessages(
  local: readonly SupportChatMessage[],
  persisted: readonly SupportChatMessage[],
): SupportChatMessage[] {
  const maxSeq = localMaxSeq(local);
  const gapFill =
    maxSeq === null
      ? persisted
      : persisted.filter((message) => message.seq > maxSeq);

  return mergeMessages(local, gapFill);
}
