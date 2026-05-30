"use client";

// Окно диалога оператор-панели (Operator_Panel → conversation view).
//
// Реализует ленту сообщений, окно ответа, карточку клиента, контрол назначения
// и контрол статуса. Требования: 10.1, 10.2, 10.4, 11.1, 11.3, 11.4, 12.3,
// 12.5, 13.1, 13.2.
//
// --------------------------------------------------------------------------
// АРХИТЕКТУРНЫЙ КОНТРАКТ (важно прочитать перед интеграцией)
// --------------------------------------------------------------------------
// Родитель (HelperPanelClient) владеет ОДНИМ общим сокетом `OperatorChatSocket`
// и обслуживает список диалогов одновременно с открытым диалогом. Проблема:
// `OperatorChatSocket.setHandlers` ЗАМЕЩАЕТ набор колбэков целиком — если бы
// этот вид сам вызывал `setHandlers`, он затёр бы обработчики списка диалогов
// родителя (unread.update / conversation.updated и т.п.).
//
// Поэтому вид НЕ подписывается на сокет сам. Вместо этого:
//   1. Логика и состояние инкапсулированы в хуке `useConversationView`. Хук
//      использует сокет ТОЛЬКО для ОТПРАВКИ (sendMessage / openConversation),
//      что не трогает обработчики, и для durable-мутаций ходит в REST.
//   2. Хук возвращает поле `events` — набор чистых аппликаторов входящих
//      событий (onMessage / onAck / onAssignmentChange / onStatusChange /
//      onReconnect). РОДИТЕЛЬ мультиплексирует события сокета и, когда событие
//      относится к открытому диалогу, вызывает соответствующий аппликатор.
//   3. Презентационный компонент `ConversationView` ПОТРЕБЛЯЕТ результат хука
//      (проп `view`) и только рендерит — без собственного состояния и I/O.
//
// Типичная проводка в родителе (будет сделана оркестратором отдельно):
//
//   const view = useConversationView({ conversationId, socket, onConversationChanged });
//   // в общем setHandlers родителя:
//   //   onMessage: (cid, msg) => { view.events.onMessage(cid, msg); ...список }
//   //   onAck: view.events.onAck,
//   //   onAssignmentChange: view.events.onAssignmentChange,
//   //   onStatusChange: view.events.onStatusChange,
//   //   onReconnect: () => { view.events.onReconnect(); ...список }
//   return <ConversationView view={view} />;
//
// Так список диалогов (8.3) и окно диалога (8.4) делят один сокет без гонки за
// обработчиками.

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AlertCircle,
  Phone,
  RotateCcw,
  Send,
  UserCheck,
  UserPlus,
  UserX,
} from "lucide-react";
import {
  mergeMessages,
  reconcileMessages,
  type SupportChatMessage,
} from "@/features/support-chat/messageList";
import type { SupportConversationStatus } from "@/features/support-chat/api";
import {
  assign as apiAssign,
  fetchOlderMessages as apiFetchOlderMessages,
  openConversation as apiOpenConversation,
  reply as apiReply,
  setStatus as apiSetStatus,
  type AssignedOperator,
  type ClientInfoCard,
  type ConversationSummary,
} from "./operator-api";
import type {
  OperatorAssignmentChange,
  OperatorChatSocket,
  OperatorStatusChange,
} from "./operator-socket";
import { useOperatorAuth } from "./operator-auth-context";
import "./conversation-view.css";

/** Лимит длины сообщения — совпадает с серверным `MAX_MESSAGE_LENGTH` (Req 10.5). */
const MAX_MESSAGE_LENGTH = 4000;

/** Задержка фонового повтора сохранения статуса при ошибке (Req 12.5). */
const STATUS_RETRY_MS = 5000;

/** Человекочитаемые подписи статусов для контрола (Req 12.3). */
const STATUS_OPTIONS: { value: SupportConversationStatus; label: string }[] = [
  { value: "open", label: "Открыт" },
  { value: "in_progress", label: "В работе" },
  { value: "closed", label: "Закрыт" },
];

/**
 * Локальный «оптимистичный» ответ оператора, ещё не подтверждённый сервером.
 * `sending` — отправка идёт (ждём `message.ack` или REST-ответ); `failed` —
 * отправить не удалось, показываем «не отправлено» с возможностью повтора.
 */
type PendingReply = {
  clientMsgId: string;
  body: string;
  status: "sending" | "failed";
  createdAt: string;
};

/** Набор аппликаторов входящих событий, которые вызывает РОДИТЕЛЬ. */
export type ConversationViewEvents = {
  /** Новое сообщение в переписке (`message.new`, Req 10.4). */
  onMessage: (conversationId: string, message: SupportChatMessage) => void;
  /** Подтверждение персистентности отправленного ответа (`message.ack`). */
  onAck: (clientMsgId: string | null, message: SupportChatMessage) => void;
  /** Изменение назначения (`assignment.changed`, Req 11.2/11.3). */
  onAssignmentChange: (change: OperatorAssignmentChange) => void;
  /** Изменение статуса (`status.changed`, Req 12.3). */
  onStatusChange: (change: OperatorStatusChange) => void;
  /** Успешное переподключение сокета — реконсилировать пропуски из durable. */
  onReconnect: () => void;
};

/** Опции хука `useConversationView`. */
export type UseConversationViewOptions = {
  /** Идентификатор открываемой переписки. */
  conversationId: string;
  /** Общий сокет панели (для отправки); `null`/`undefined` → только REST. */
  socket?: OperatorChatSocket | null;
  /** Колбэк об обновлении сводки переписки (для синхронизации списка). */
  onConversationChanged?: (summary: ConversationSummary) => void;
};

/** Результат хука — состояние + действия + аппликаторы событий. */
export type UseConversationViewResult = {
  // --- состояние ---
  status: SupportConversationStatus | null;
  messages: SupportChatMessage[];
  pending: PendingReply[];
  clientInfoCard: ClientInfoCard | null;
  assignedOperator: AssignedOperator | null;
  isSelfAssigned: boolean;
  loading: boolean;
  loadingOlder: boolean;
  hasMore: boolean;
  error: string | null;
  lengthError: string | null;
  statusSaveFailed: boolean;
  draft: string;
  setDraft: (value: string) => void;
  // --- действия ---
  sendReply: () => void;
  retryPending: (clientMsgId: string) => void;
  loadOlder: () => void;
  toggleAssignment: () => void;
  changeStatus: (next: SupportConversationStatus) => void;
  retryStatus: () => void;
  // --- аппликаторы событий (вызывает родитель) ---
  events: ConversationViewEvents;
};

function genClientMsgId(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  return `op-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

function formatTime(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) {
    return "";
  }
  return date.toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" });
}

function formatDate(iso: string | null): string {
  if (!iso) {
    return "—";
  }
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) {
    return "—";
  }
  return date.toLocaleDateString("ru-RU", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
  });
}

/**
 * Хук окна диалога: загрузка переписки + карточки клиента, оптимистичная
 * отправка ответа (сокет → REST-fallback), подгрузка истории, назначение и
 * смена статуса с оптимистичным применением. Подписку на сокет НЕ делает —
 * родитель маршрутизирует события в `result.events` (см. контракт сверху).
 */
export function useConversationView({
  conversationId,
  socket,
  onConversationChanged,
}: UseConversationViewOptions): UseConversationViewResult {
  const { session } = useOperatorAuth();
  const currentOperatorId = session?.admin.id ?? null;

  const [messages, setMessages] = useState<SupportChatMessage[]>([]);
  const [pending, setPending] = useState<PendingReply[]>([]);
  const [status, setConvStatus] = useState<SupportConversationStatus | null>(null);
  const [assignedOperator, setAssignedOperator] = useState<AssignedOperator | null>(
    null,
  );
  const [clientInfoCard, setClientInfoCard] = useState<ClientInfoCard | null>(null);
  const [loading, setLoading] = useState(false);
  const [loadingOlder, setLoadingOlder] = useState(false);
  const [hasMore, setHasMore] = useState(false);
  const [oldestSeq, setOldestSeq] = useState<number | null>(null);
  const [draft, setDraft] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [lengthError, setLengthError] = useState<string | null>(null);
  const [statusSaveFailed, setStatusSaveFailed] = useState(false);

  // Стабильная ссылка на колбэк родителя — чтобы не пересоздавать эффекты.
  const onConversationChangedRef = useRef(onConversationChanged);
  useEffect(() => {
    onConversationChangedRef.current = onConversationChanged;
  }, [onConversationChanged]);

  // Желаемый (оптимистично применённый) статус и таймер фонового повтора.
  const desiredStatusRef = useRef<SupportConversationStatus | null>(null);
  const statusRetryTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const persistStatusRef = useRef<(target: SupportConversationStatus) => void>(
    () => {},
  );

  const clearStatusRetry = useCallback(() => {
    if (statusRetryTimer.current !== null) {
      clearTimeout(statusRetryTimer.current);
      statusRetryTimer.current = null;
    }
  }, []);

  // --- Загрузка переписки при смене conversationId -------------------------
  // openConversation сбрасывает unread текущего оператора на сервере (Req 9.4)
  // и возвращает сообщения oldest→newest (Req 10.1), карточку клиента (Req 13)
  // и сводку (статус + назначение).
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    setLengthError(null);
    setMessages([]);
    setPending([]);
    setClientInfoCard(null);
    setHasMore(false);
    setOldestSeq(null);
    setStatusSaveFailed(false);
    desiredStatusRef.current = null;
    clearStatusRetry();

    void (async () => {
      try {
        const resp = await apiOpenConversation(conversationId);
        if (cancelled) {
          return;
        }
        setMessages(mergeMessages([], resp.messages));
        setHasMore(resp.hasMore);
        setOldestSeq(resp.oldestSeq);
        setConvStatus(resp.conversation.status);
        setAssignedOperator(resp.conversation.assignedOperator);
        setClientInfoCard(resp.clientInfoCard);
        onConversationChangedRef.current?.(resp.conversation);
      } catch {
        if (!cancelled) {
          setError("Не удалось загрузить переписку. Попробуйте позже.");
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    })();

    // Подписать сокет на conversation-scoped `message.new` (Req 10.4). Если
    // сокет ещё не подключён — родитель повторит после переподключения через
    // events.onReconnect.
    socket?.openConversation(conversationId);

    return () => {
      cancelled = true;
      clearStatusRetry();
    };
  }, [conversationId, socket, clearStatusRetry]);

  // --- Отправка ответа -----------------------------------------------------
  const sendViaRest = useCallback(
    async (clientMsgId: string, body: string) => {
      try {
        const resp = await apiReply(conversationId, body);
        setMessages((prev) => mergeMessages(prev, resp.message));
        setPending((prev) => prev.filter((p) => p.clientMsgId !== clientMsgId));
      } catch {
        setPending((prev) =>
          prev.map((p) =>
            p.clientMsgId === clientMsgId ? { ...p, status: "failed" } : p,
          ),
        );
      }
    },
    [conversationId],
  );

  const sendReply = useCallback(() => {
    const body = draft.trim();
    if (!body) {
      return;
    }
    if (body.length > MAX_MESSAGE_LENGTH) {
      setLengthError(`Сообщение длиннее ${MAX_MESSAGE_LENGTH} символов.`);
      return;
    }

    const clientMsgId = genClientMsgId();
    const createdAt = new Date().toISOString();
    setDraft("");
    setLengthError(null);
    setError(null);
    setPending((prev) => [
      ...prev,
      { clientMsgId, body, status: "sending", createdAt },
    ]);

    // Оптимистичная отправка через сокет с подтверждением `message.ack`
    // (Req 10.2). Если кадр не ушёл или сокет неактивен — durable REST-fallback.
    if (socket && socket.isConnected()) {
      const ok = socket.sendMessage(conversationId, clientMsgId, body);
      if (!ok) {
        void sendViaRest(clientMsgId, body);
      }
      return;
    }
    void sendViaRest(clientMsgId, body);
  }, [draft, socket, conversationId, sendViaRest]);

  const retryPending = useCallback(
    (clientMsgId: string) => {
      const target = pending.find((p) => p.clientMsgId === clientMsgId);
      if (!target) {
        return;
      }
      setPending((prev) =>
        prev.map((p) =>
          p.clientMsgId === clientMsgId ? { ...p, status: "sending" } : p,
        ),
      );
      if (socket && socket.isConnected()) {
        const ok = socket.sendMessage(conversationId, clientMsgId, target.body);
        if (!ok) {
          void sendViaRest(clientMsgId, target.body);
        }
        return;
      }
      void sendViaRest(clientMsgId, target.body);
    },
    [pending, socket, conversationId, sendViaRest],
  );

  // --- Подгрузка истории (Req 10.1) ----------------------------------------
  const loadOlder = useCallback(() => {
    if (oldestSeq === null || loadingOlder || !hasMore) {
      return;
    }
    setLoadingOlder(true);
    void (async () => {
      try {
        const page = await apiFetchOlderMessages(conversationId, oldestSeq);
        setMessages((prev) => mergeMessages(prev, page.messages));
        setHasMore(page.hasMore);
        if (page.oldestSeq !== null) {
          setOldestSeq(page.oldestSeq);
        }
      } catch {
        setError("Не удалось загрузить историю.");
      } finally {
        setLoadingOlder(false);
      }
    })();
  }, [conversationId, oldestSeq, loadingOlder, hasMore]);

  // --- Назначение на себя / снятие (Req 11.1, 11.3, 11.4) ------------------
  const isSelfAssigned =
    assignedOperator !== null &&
    currentOperatorId !== null &&
    assignedOperator.id === currentOperatorId;

  const toggleAssignment = useCallback(() => {
    const nextAssign = !isSelfAssigned;
    // Оптимистично отражаем назначение; assignment.changed подтвердит.
    const previous = assignedOperator;
    setAssignedOperator(
      nextAssign && currentOperatorId
        ? { id: currentOperatorId, name: session?.admin.name ?? "Вы" }
        : null,
    );
    void (async () => {
      try {
        const resp = await apiAssign(conversationId, nextAssign);
        setAssignedOperator(resp.conversation.assignedOperator);
        onConversationChangedRef.current?.(resp.conversation);
      } catch {
        // Откат к прежнему значению + сообщение об ошибке.
        setAssignedOperator(previous);
        setError("Не удалось изменить назначение.");
      }
    })();
  }, [
    isSelfAssigned,
    assignedOperator,
    currentOperatorId,
    session,
    conversationId,
  ]);

  // --- Смена статуса с оптимистичным применением (Req 12.3, 12.5) ----------
  const persistStatus = useCallback(
    (target: SupportConversationStatus) => {
      desiredStatusRef.current = target;
      apiSetStatus(conversationId, target)
        .then((resp) => {
          if (desiredStatusRef.current !== target) {
            return;
          }
          clearStatusRetry();
          setStatusSaveFailed(false);
          setConvStatus(resp.conversation.status);
          onConversationChangedRef.current?.(resp.conversation);
        })
        .catch(() => {
          if (desiredStatusRef.current !== target) {
            return;
          }
          // Неблокирующий бейдж «не сохранено» + фоновый повтор (Req 12.5).
          setStatusSaveFailed(true);
          clearStatusRetry();
          statusRetryTimer.current = setTimeout(() => {
            statusRetryTimer.current = null;
            if (desiredStatusRef.current === target) {
              persistStatusRef.current(target);
            }
          }, STATUS_RETRY_MS);
        });
    },
    [conversationId, clearStatusRetry],
  );

  useEffect(() => {
    persistStatusRef.current = persistStatus;
  }, [persistStatus]);

  const changeStatus = useCallback(
    (next: SupportConversationStatus) => {
      if (next === status && !statusSaveFailed) {
        return;
      }
      // Оптимистично применяем сразу, чтобы не блокировать оператора (Req 12.5).
      setConvStatus(next);
      persistStatus(next);
    },
    [status, statusSaveFailed, persistStatus],
  );

  const retryStatus = useCallback(() => {
    const target = desiredStatusRef.current;
    if (target) {
      clearStatusRetry();
      persistStatus(target);
    }
  }, [persistStatus, clearStatusRetry]);

  // --- Аппликаторы входящих событий (вызывает родитель) --------------------
  const reconcile = useCallback(() => {
    socket?.openConversation(conversationId);
    void (async () => {
      try {
        const resp = await apiOpenConversation(conversationId);
        setMessages((prev) => reconcileMessages(prev, resp.messages));
        setConvStatus(resp.conversation.status);
        setAssignedOperator(resp.conversation.assignedOperator);
        setClientInfoCard(resp.clientInfoCard);
        onConversationChangedRef.current?.(resp.conversation);
      } catch {
        // Игнорируем — следующее событие/переподключение повторит.
      }
    })();
  }, [socket, conversationId]);

  const events = useMemo<ConversationViewEvents>(
    () => ({
      onMessage: (cid, message) => {
        if (cid !== conversationId) {
          return;
        }
        setMessages((prev) => mergeMessages(prev, message));
      },
      onAck: (clientMsgId, message) => {
        if (message.conversationId !== conversationId) {
          return;
        }
        setMessages((prev) => mergeMessages(prev, message));
        if (clientMsgId) {
          setPending((prev) => prev.filter((p) => p.clientMsgId !== clientMsgId));
        }
      },
      onAssignmentChange: (change) => {
        if (change.conversationId !== conversationId) {
          return;
        }
        setAssignedOperator(change.assignedOperator);
      },
      onStatusChange: (change) => {
        if (change.conversationId !== conversationId) {
          return;
        }
        // Подтверждение извне: совпало с желаемым — снимаем бейдж/повтор.
        if (desiredStatusRef.current === change.status) {
          desiredStatusRef.current = null;
          clearStatusRetry();
          setStatusSaveFailed(false);
        }
        setConvStatus(change.status);
      },
      onReconnect: () => {
        reconcile();
      },
    }),
    [conversationId, reconcile, clearStatusRetry],
  );

  return {
    status,
    messages,
    pending,
    clientInfoCard,
    assignedOperator,
    isSelfAssigned,
    loading,
    loadingOlder,
    hasMore,
    error,
    lengthError,
    statusSaveFailed,
    draft,
    setDraft,
    sendReply,
    retryPending,
    loadOlder,
    toggleAssignment,
    changeStatus,
    retryStatus,
    events,
  };
}

// --------------------------------------------------------------------------
// Презентационный компонент
// --------------------------------------------------------------------------

/** Подкомпонент: контрол назначения (Req 11.1, 11.3, 11.4). */
function AssignControl({ view }: { view: UseConversationViewResult }) {
  const { assignedOperator, isSelfAssigned, toggleAssignment } = view;
  return (
    <div className="cv-assign">
      <span className="cv-assign-info">
        {assignedOperator ? (
          <>
            <UserCheck size={15} aria-hidden="true" />
            <span>
              Назначен: <strong>{assignedOperator.name || "оператор"}</strong>
            </span>
          </>
        ) : (
          <>
            <UserX size={15} aria-hidden="true" />
            <span>Не назначен</span>
          </>
        )}
      </span>
      <button
        type="button"
        className="cv-assign-btn"
        onClick={toggleAssignment}
        title={isSelfAssigned ? "Снять назначение" : "Назначить на себя"}
      >
        {isSelfAssigned ? (
          <>
            <UserX size={15} aria-hidden="true" />
            <span>Снять</span>
          </>
        ) : (
          <>
            <UserPlus size={15} aria-hidden="true" />
            <span>Взять себе</span>
          </>
        )}
      </button>
    </div>
  );
}

/** Подкомпонент: контрол статуса с бейджем «не сохранено» (Req 12.3, 12.5). */
function StatusControl({ view }: { view: UseConversationViewResult }) {
  const { status, statusSaveFailed, changeStatus, retryStatus } = view;
  return (
    <div className="cv-status">
      <span className="cv-status-label">Статус</span>
      <div className="cv-status-group" role="group" aria-label="Статус переписки">
        {STATUS_OPTIONS.map((option) => (
          <button
            key={option.value}
            type="button"
            className={`cv-status-btn${status === option.value ? " is-active" : ""}`}
            aria-pressed={status === option.value}
            onClick={() => changeStatus(option.value)}
          >
            {option.label}
          </button>
        ))}
      </div>
      {statusSaveFailed ? (
        <button
          type="button"
          className="cv-status-unsaved"
          onClick={retryStatus}
          title="Изменение статуса ещё не сохранено. Нажмите, чтобы повторить."
        >
          <AlertCircle size={13} aria-hidden="true" />
          не сохранено
        </button>
      ) : null}
    </div>
  );
}

/** Подкомпонент: карточка клиента (Req 13.1, 13.2). */
function ClientInfoPanel({ card }: { card: ClientInfoCard | null }) {
  if (!card) {
    return (
      <aside className="cv-aside">
        <p className="cv-empty">Карточка клиента загружается…</p>
      </aside>
    );
  }
  return (
    <aside className="cv-aside">
      <section className="cv-card-section">
        <h3>Клиент</h3>
        <span className="cv-phone">
          <Phone size={15} aria-hidden="true" />
          {card.phone || "Телефон не указан"}
        </span>
      </section>

      <section className="cv-card-section">
        <h3>Недавние брони</h3>
        {card.recentReservations.length === 0 ? (
          <p className="cv-empty">Броней нет.</p>
        ) : (
          <div className="cv-activity-list">
            {card.recentReservations.map((item) => (
              <div className="cv-activity-item" key={item.id}>
                <div className="cv-activity-name">
                  {item.productName ?? "Без названия"}
                </div>
                <div className="cv-activity-meta">
                  <span className="cv-activity-status">{item.status}</span>
                  <span>{formatDate(item.pickupAt ?? item.createdAt)}</span>
                </div>
              </div>
            ))}
          </div>
        )}
      </section>

      <section className="cv-card-section">
        <h3>Недавние аренды</h3>
        {card.recentRentals.length === 0 ? (
          <p className="cv-empty">Аренд нет.</p>
        ) : (
          <div className="cv-activity-list">
            {card.recentRentals.map((item) => (
              <div className="cv-activity-item" key={item.id}>
                <div className="cv-activity-name">
                  {item.productName ?? "Без названия"}
                </div>
                <div className="cv-activity-meta">
                  <span className="cv-activity-status">{item.status}</span>
                  <span>
                    {formatDate(item.startsAt)} — {formatDate(item.plannedEndAt)}
                  </span>
                </div>
              </div>
            ))}
          </div>
        )}
      </section>
    </aside>
  );
}

/**
 * Презентационное окно диалога. Не имеет собственного состояния и I/O —
 * принимает готовый результат хука `useConversationView` через проп `view`.
 *
 * Родитель отвечает за маршрутизацию событий сокета в `view.events`
 * (см. контракт в начале файла).
 */
export function ConversationView({ view }: { view: UseConversationViewResult }) {
  const {
    messages,
    pending,
    clientInfoCard,
    status,
    loading,
    loadingOlder,
    hasMore,
    error,
    lengthError,
    draft,
    setDraft,
    sendReply,
    retryPending,
    loadOlder,
  } = view;

  const bottomRef = useRef<HTMLDivElement | null>(null);
  const prevCountRef = useRef(0);

  // Автоскролл вниз при появлении новых сообщений/отправок (не при подгрузке
  // более старой истории, когда счётчик тоже растёт, но сверху — поэтому
  // ориентируемся на pending и на рост общего числа лишь когда не грузим старое).
  useEffect(() => {
    const total = messages.length + pending.length;
    if (total > prevCountRef.current && !loadingOlder) {
      bottomRef.current?.scrollIntoView({ block: "end" });
    }
    prevCountRef.current = total;
  }, [messages, pending, loadingOlder]);

  const handleInputKeyDown = useCallback(
    (event: React.KeyboardEvent<HTMLTextAreaElement>) => {
      if (event.key === "Enter" && !event.shiftKey) {
        event.preventDefault();
        sendReply();
      }
    },
    [sendReply],
  );

  return (
    <div className="cv-root">
      <div className="cv-main">
        <div className="cv-header">
          <AssignControl view={view} />
          <div className="cv-header-controls">
            <StatusControl view={view} />
          </div>
        </div>

        <div className="cv-thread">
          {hasMore ? (
            <button
              type="button"
              className="cv-load-older"
              onClick={loadOlder}
              disabled={loadingOlder}
            >
              {loadingOlder ? "Загрузка…" : "Показать ранние сообщения"}
            </button>
          ) : null}

          {loading && messages.length === 0 ? (
            <div className="cv-info">Загрузка переписки…</div>
          ) : null}

          {!loading && messages.length === 0 && pending.length === 0 ? (
            <div className="cv-info">В этой переписке пока нет сообщений.</div>
          ) : null}

          {messages.map((message) => (
            <div
              key={message.id}
              className={`cv-msg ${
                message.authorType === "operator" ? "is-operator" : "is-client"
              }`}
            >
              <div className="cv-bubble">{message.body}</div>
              <div className="cv-meta">
                {message.authorType === "operator" && message.authorName
                  ? `${message.authorName} · `
                  : ""}
                {formatTime(message.createdAt)}
              </div>
            </div>
          ))}

          {pending.map((message) => (
            <div key={message.clientMsgId} className="cv-msg is-operator is-pending">
              <div className="cv-bubble">{message.body}</div>
              <div className="cv-meta">
                {message.status === "failed" ? (
                  <button
                    type="button"
                    className="cv-retry"
                    onClick={() => retryPending(message.clientMsgId)}
                  >
                    <RotateCcw size={12} aria-hidden="true" />
                    не отправлено · повторить
                  </button>
                ) : (
                  "отправка…"
                )}
              </div>
            </div>
          ))}

          <div ref={bottomRef} />
        </div>

        {status === "closed" ? (
          <div className="cv-closed-note">
            Обращение закрыто. Сообщение клиента откроет его снова.
          </div>
        ) : null}

        {error ? (
          <div className="cv-error">
            <AlertCircle size={14} aria-hidden="true" />
            <span>{error}</span>
          </div>
        ) : null}

        {lengthError ? <div className="cv-reply-len-error">{lengthError}</div> : null}

        <div className="cv-reply">
          <textarea
            className="cv-reply-input"
            placeholder="Ответ оператора…"
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={handleInputKeyDown}
            rows={1}
            maxLength={MAX_MESSAGE_LENGTH + 1}
          />
          <button
            type="button"
            className="cv-reply-send"
            onClick={sendReply}
            disabled={draft.trim().length === 0}
            aria-label="Отправить ответ"
          >
            <Send size={18} aria-hidden="true" />
          </button>
        </div>
      </div>

      <ClientInfoPanel card={clientInfoCard} />
    </div>
  );
}
