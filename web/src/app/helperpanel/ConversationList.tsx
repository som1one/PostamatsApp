"use client";

// Список переписок оператор-панели (`Operator_Panel` → conversation list).
//
// Реализует левую колонку панели: фильтр по статусу, строки переписок
// (новейшие по активности сверху), бейджи непрочитанных и подсветку выбранной
// переписки. Дизайн: `.kiro/specs/support-chat/design.md`
// (раздел *Component responsibilities* → Operator_Panel).
//
// Требования: 9.1 (список со статусом/назначением/превью/unread), 9.2
// (порядок — новейшие сверху), 9.3 (живые `unread.update`/`conversation.updated`
// без полного рефетча), 12.6 (фильтр по статусу).
//
// ---------------------------------------------------------------------------
// ВЫБРАННЫЙ КОНТРАКТ (важно для композиции с ConversationView из задачи 8.4)
// ---------------------------------------------------------------------------
// Модуль намеренно разделён на ДВА экспорта, чтобы родитель
// (`HelperPanelClient`) владел ОДНИМ общим сокетом и одной выборкой:
//
//   1. `ConversationList` — ЧИСТО презентационный компонент. Не грузит данные,
//      не знает про сокет: получает `conversations`, `loading`, `error`,
//      `activeStatus`, `onStatusChange`, `selectedConversationId`, `onSelect`
//      и только рендерит. Это делает его тривиально тестируемым и переиспользуемым.
//
//   2. `useConversationList(socket?)` — хук данных + живого слияния. Грузит
//      `listConversations(status)` на маунте и при смене фильтра, держит
//      состояние списка и отдаёт стабильные `eventHandlers`
//      (`onUnreadUpdate` / `onConversationUpdated` / `onAssignmentChange` /
//      `onStatusChange` / `onReconnect`), которые РОДИТЕЛЬ вмешивает в свой
//      единственный мультиплексирующий вызов `socket.setHandlers(...)`.
//
// ПОЧЕМУ хук НЕ вызывает `socket.setHandlers` сам: у `OperatorChatSocket`
// `setHandlers` ПОЛНОСТЬЮ ЗАМЕНЯЕТ набор колбэков. Окно диалога
// (`ConversationView`, задача 8.4) живёт на ТОМ ЖЕ общем сокете и тоже хочет
// колбэки. Поэтому единственный владелец `setHandlers` — родитель
// (`HelperPanelClient`): он мультиплексирует события и в `eventHandlers`
// этого хука, и в обработчики окна диалога. Так список и окно делят одно
// соединение без затирания колбэков друг друга.

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { SupportConversationStatus } from "@/features/support-chat/api";
import {
  listConversations,
  type ConversationSummary,
} from "./operator-api";
import type {
  OperatorAssignmentChange,
  OperatorChatSocket,
  OperatorStatusChange,
  OperatorUnreadUpdate,
} from "./operator-socket";
import "./conversation-list.css";

// ---------------------------------------------------------------------------
// Фильтр по статусу (Requirement 12.6)
// ---------------------------------------------------------------------------

/** Значение фильтра: либо конкретный статус, либо «все» (без фильтра). */
export type StatusFilter = "all" | SupportConversationStatus;

/** Порядок и русские подписи кнопок фильтра. */
const STATUS_FILTERS: { value: StatusFilter; label: string }[] = [
  { value: "all", label: "Все" },
  { value: "open", label: "Открыт" },
  { value: "in_progress", label: "В работе" },
  { value: "closed", label: "Закрыт" },
];

/** Русская подпись статуса переписки для бейджа в строке. */
const STATUS_LABELS: Record<SupportConversationStatus, string> = {
  open: "Открыт",
  in_progress: "В работе",
  closed: "Закрыт",
};

// ---------------------------------------------------------------------------
// Утилиты
// ---------------------------------------------------------------------------

/**
 * Короткое относительное время последней активности для строки списка.
 * Возвращает «только что» / «N мин» / «N ч» / «N дн», а для дат старше недели —
 * короткую дату `дд.мм`. Пустая строка для отсутствующего/невалидного времени.
 */
function formatActivityTime(iso: string | null): string {
  if (!iso) {
    return "";
  }
  const date = new Date(iso);
  const ms = date.getTime();
  if (Number.isNaN(ms)) {
    return "";
  }
  const diff = Date.now() - ms;
  if (diff < 60_000) {
    return "только что";
  }
  const minutes = Math.floor(diff / 60_000);
  if (minutes < 60) {
    return `${minutes} мин`;
  }
  const hours = Math.floor(diff / 3_600_000);
  if (hours < 24) {
    return `${hours} ч`;
  }
  const days = Math.floor(diff / 86_400_000);
  if (days < 7) {
    return `${days} дн`;
  }
  return new Intl.DateTimeFormat("ru-RU", {
    day: "2-digit",
    month: "2-digit",
  }).format(date);
}

/** Короткая метка-идентификатор строки (клиентского имени в сводке нет). */
function conversationLabel(id: string): string {
  const short = id.replace(/-/g, "").slice(0, 8);
  return `Клиент · ${short}`;
}

/**
 * Детерминированная сортировка сводок: по `lastMessageAt` убыванием
 * (новейшие сверху, Requirement 9.2), `null`-время — в конец, tiebreak по `id`
 * для стабильности.
 */
function sortSummaries(items: ConversationSummary[]): ConversationSummary[] {
  return [...items].sort((a, b) => {
    const aMs = a.lastMessageAt ? new Date(a.lastMessageAt).getTime() : null;
    const bMs = b.lastMessageAt ? new Date(b.lastMessageAt).getTime() : null;
    const aVal = aMs !== null && !Number.isNaN(aMs) ? aMs : null;
    const bVal = bMs !== null && !Number.isNaN(bMs) ? bMs : null;
    if (aVal !== bVal) {
      if (aVal === null) return 1;
      if (bVal === null) return -1;
      return bVal - aVal;
    }
    return a.id < b.id ? -1 : a.id > b.id ? 1 : 0;
  });
}

/** Подходит ли статус сводки под активный фильтр. */
function matchesFilter(
  status: SupportConversationStatus,
  filter: StatusFilter,
): boolean {
  return filter === "all" || status === filter;
}

// ---------------------------------------------------------------------------
// Хук данных + живого слияния
// ---------------------------------------------------------------------------

/**
 * Стабильный набор колбэков живого обновления, который РОДИТЕЛЬ вмешивает в
 * свой единственный `socket.setHandlers(...)` (см. контракт в шапке файла).
 * Каждый колбэк сливает событие в состояние списка без полного рефетча
 * (Requirement 9.3).
 */
export type ConversationListEventHandlers = {
  onUnreadUpdate: (update: OperatorUnreadUpdate) => void;
  onConversationUpdated: (conversation: ConversationSummary) => void;
  onAssignmentChange: (change: OperatorAssignmentChange) => void;
  onStatusChange: (change: OperatorStatusChange) => void;
  /** Переподключение сокета — перезагрузить список из durable-хранилища. */
  onReconnect: () => void;
};

export type UseConversationListResult = {
  conversations: ConversationSummary[];
  loading: boolean;
  error: string | null;
  activeStatus: StatusFilter;
  setActiveStatus: (status: StatusFilter) => void;
  /** Принудительный рефетч текущего фильтра. */
  refresh: () => void;
  /** Колбэки для мультиплексирования родителем в общий сокет (Req 9.3). */
  eventHandlers: ConversationListEventHandlers;
};

/**
 * Загружает и держит состояние списка переписок и отдаёт живые merge-колбэки.
 *
 * @param socket Общий операторский сокет, которым владеет родитель. Хук НЕ
 *   регистрирует на нём обработчики (это затёрло бы колбэки окна диалога) —
 *   родитель сам мультиплексирует события в `eventHandlers`. Когда ссылка на
 *   сокет появляется/меняется (например, после входа оператора), хук
 *   перезагружает список, чтобы подтянуть свежие данные.
 */
export function useConversationList(
  socket?: OperatorChatSocket | null,
): UseConversationListResult {
  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeStatus, setActiveStatusState] = useState<StatusFilter>("all");

  // Ref на активный фильтр — чтобы merge-колбэки оставались стабильными и при
  // этом видели актуальный фильтр без пересоздания. Пишем в ref из эффекта
  // (правило react-hooks/refs запрещает писать в ref во время рендера).
  const activeStatusRef = useRef<StatusFilter>(activeStatus);
  useEffect(() => {
    activeStatusRef.current = activeStatus;
  }, [activeStatus]);

  // Токен загрузки — отбрасываем результаты устаревших запросов (смена фильтра
  // на лету), чтобы не показать список не от того фильтра.
  const loadTokenRef = useRef(0);

  const load = useCallback((status: StatusFilter) => {
    const token = ++loadTokenRef.current;
    setLoading(true);
    setError(null);
    const apiStatus = status === "all" ? undefined : status;
    listConversations(apiStatus)
      .then((response) => {
        if (loadTokenRef.current !== token) {
          return;
        }
        // Бэкенд уже отдаёт новейшие сверху; сортируем повторно для инварианта.
        setConversations(sortSummaries(response.conversations));
        setLoading(false);
      })
      .catch((err: unknown) => {
        if (loadTokenRef.current !== token) {
          return;
        }
        setError(
          err instanceof Error
            ? err.message
            : "Не удалось загрузить список обращений",
        );
        setLoading(false);
      });
  }, []);

  // Загрузка на маунте и при смене фильтра (Requirement 12.6).
  useEffect(() => {
    load(activeStatus);
  }, [activeStatus, load]);

  // Когда родитель подключает/пересоздаёт общий сокет, освежаем список из
  // durable-хранилища (Requirement 9.3 / реконсиляция 15.4). Пропускаем самый
  // первый рендер, чтобы не дублировать начальную загрузку выше.
  const socketSeenRef = useRef(false);
  useEffect(() => {
    if (!socketSeenRef.current) {
      socketSeenRef.current = true;
      return;
    }
    if (socket) {
      load(activeStatusRef.current);
    }
  }, [socket, load]);

  const setActiveStatus = useCallback((status: StatusFilter) => {
    setActiveStatusState(status);
  }, []);

  const refresh = useCallback(() => {
    load(activeStatusRef.current);
  }, [load]);

  // --- живое слияние (стабильные колбэки) ---

  const onUnreadUpdate = useCallback((update: OperatorUnreadUpdate) => {
    setConversations((prev) =>
      prev.map((item) =>
        item.id === update.conversationId
          ? { ...item, unreadCount: update.unreadCount }
          : item,
      ),
    );
  }, []);

  const onConversationUpdated = useCallback(
    (conversation: ConversationSummary) => {
      setConversations((prev) => {
        const filter = activeStatusRef.current;
        const exists = prev.some((item) => item.id === conversation.id);
        // Под активным фильтром: если обновлённый статус больше не подходит —
        // убрать строку; иначе — вставить/слить и пересортировать.
        if (!matchesFilter(conversation.status, filter)) {
          return exists
            ? prev.filter((item) => item.id !== conversation.id)
            : prev;
        }
        const next = exists
          ? prev.map((item) =>
              item.id === conversation.id ? { ...item, ...conversation } : item,
            )
          : [...prev, conversation];
        return sortSummaries(next);
      });
    },
    [],
  );

  const onAssignmentChange = useCallback((change: OperatorAssignmentChange) => {
    setConversations((prev) =>
      prev.map((item) =>
        item.id === change.conversationId
          ? { ...item, assignedOperator: change.assignedOperator }
          : item,
      ),
    );
  }, []);

  const onStatusChange = useCallback((change: OperatorStatusChange) => {
    setConversations((prev) => {
      const filter = activeStatusRef.current;
      if (!matchesFilter(change.status, filter)) {
        return prev.filter((item) => item.id !== change.conversationId);
      }
      return prev.map((item) =>
        item.id === change.conversationId
          ? { ...item, status: change.status }
          : item,
      );
    });
  }, []);

  const onReconnect = useCallback(() => {
    load(activeStatusRef.current);
  }, [load]);

  // Колбэки стабильны по ссылке, поэтому объект собираем через useMemo —
  // его ссылка меняется только если изменится какой-то из колбэков (т.е.
  // практически никогда), что и нужно для безопасного мультиплексирования.
  const eventHandlers = useMemo<ConversationListEventHandlers>(
    () => ({
      onUnreadUpdate,
      onConversationUpdated,
      onAssignmentChange,
      onStatusChange,
      onReconnect,
    }),
    [
      onUnreadUpdate,
      onConversationUpdated,
      onAssignmentChange,
      onStatusChange,
      onReconnect,
    ],
  );

  return {
    conversations,
    loading,
    error,
    activeStatus,
    setActiveStatus,
    refresh,
    eventHandlers,
  };
}

// ---------------------------------------------------------------------------
// Презентационный компонент
// ---------------------------------------------------------------------------

export type ConversationListProps = {
  /** Сводки переписок (родитель получает их из `useConversationList`). */
  conversations: ConversationSummary[];
  /** Идёт ли загрузка списка. */
  loading: boolean;
  /** Текст ошибки загрузки, если есть. */
  error?: string | null;
  /** Активный фильтр по статусу (Requirement 12.6). */
  activeStatus: StatusFilter;
  /** Смена фильтра. */
  onStatusChange: (status: StatusFilter) => void;
  /** Id выбранной переписки для подсветки. */
  selectedConversationId?: string;
  /** Выбор переписки (родитель открывает её в окне диалога). */
  onSelect: (conversationId: string) => void;
};

/**
 * Презентационный список переписок: фильтр по статусу + строки. Данные и живые
 * обновления приходят сверху (см. контракт в шапке файла) — компонент только
 * рендерит, поэтому легко тестируется и переиспользуется.
 */
export function ConversationList({
  conversations,
  loading,
  error = null,
  activeStatus,
  onStatusChange,
  selectedConversationId,
  onSelect,
}: ConversationListProps) {
  return (
    <section className="hp-convlist" aria-label="Список обращений">
      <div
        className="hp-convlist-filter"
        role="group"
        aria-label="Фильтр по статусу"
      >
        {STATUS_FILTERS.map((filter) => {
          const active = filter.value === activeStatus;
          return (
            <button
              key={filter.value}
              type="button"
              className={
                active
                  ? "hp-convlist-filter-btn is-active"
                  : "hp-convlist-filter-btn"
              }
              aria-pressed={active}
              onClick={() => onStatusChange(filter.value)}
            >
              {filter.label}
            </button>
          );
        })}
      </div>

      <div className="hp-convlist-body">
        {error ? (
          <p className="hp-convlist-error" role="alert">
            {error}
          </p>
        ) : null}

        {loading ? (
          <p className="hp-convlist-empty" role="status">
            Загрузка…
          </p>
        ) : null}

        {!loading && !error && conversations.length === 0 ? (
          <p className="hp-convlist-empty">Нет обращений</p>
        ) : null}

        {!loading && conversations.length > 0 ? (
          <ul className="hp-convlist-items">
            {conversations.map((conversation) => (
              <ConversationRow
                key={conversation.id}
                conversation={conversation}
                selected={conversation.id === selectedConversationId}
                onSelect={onSelect}
              />
            ))}
          </ul>
        ) : null}
      </div>
    </section>
  );
}

type ConversationRowProps = {
  conversation: ConversationSummary;
  selected: boolean;
  onSelect: (conversationId: string) => void;
};

function ConversationRow({
  conversation,
  selected,
  onSelect,
}: ConversationRowProps) {
  const {
    id,
    status,
    assignedOperator,
    lastMessagePreview,
    lastMessageAt,
    unreadCount,
  } = conversation;

  const statusLabel = STATUS_LABELS[status];
  const preview = lastMessagePreview?.trim() || "Нет сообщений";
  const time = formatActivityTime(lastMessageAt);
  const hasUnread = unreadCount > 0;

  const ariaLabel = [
    conversationLabel(id),
    `статус: ${statusLabel}`,
    assignedOperator ? `оператор: ${assignedOperator.name}` : "не назначено",
    hasUnread ? `непрочитанных: ${unreadCount}` : null,
    preview,
  ]
    .filter(Boolean)
    .join(", ");

  return (
    <li className="hp-convlist-item">
      <button
        type="button"
        className={selected ? "hp-conv-row is-selected" : "hp-conv-row"}
        aria-pressed={selected}
        aria-label={ariaLabel}
        onClick={() => onSelect(id)}
      >
        <span className="hp-conv-row-top">
          <span className="hp-conv-row-label">{conversationLabel(id)}</span>
          {time ? <time className="hp-conv-row-time">{time}</time> : null}
        </span>

        <span className="hp-conv-row-preview">{preview}</span>

        <span className="hp-conv-row-meta">
          <span className={`hp-conv-status hp-conv-status-${status}`}>
            {statusLabel}
          </span>
          {assignedOperator ? (
            <span className="hp-conv-assignee">{assignedOperator.name}</span>
          ) : (
            <span className="hp-conv-assignee hp-conv-assignee-none">
              Не назначено
            </span>
          )}
          {hasUnread ? (
            <span
              className="hp-conv-unread"
              aria-label={`Непрочитанных: ${unreadCount}`}
            >
              {unreadCount}
            </span>
          ) : null}
        </span>
      </button>
    </li>
  );
}
