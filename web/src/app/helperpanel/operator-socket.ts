// WebSocket-клиент оператор-панели (`/ws/helperpanel`) — UI-агностичный.
//
// Этот модуль НЕ зависит от React. Он зеркалит клиентский
// `SupportChatSocket` (`web/src/features/support-chat/socket.ts`), но:
//   - читает ОПЕРАТОРСКИЙ access-токен из отдельной операторской сессии
//     (`operator-auth.ts`, localStorage-ключ `helperpanel-operator-auth`), а
//     НЕ из клиентской `readStoredSession()`;
//   - подключается к `/ws/helperpanel` (через общий `buildSupportSocketUrl`);
//   - отправляет операторский набор действий (open / message.send с
//     conversationId / markRead / assign / setStatus / ping);
//   - разбирает операторский набор событий (message.new, unread.update,
//     conversation.updated, assignment.changed, status.changed, message.ack,
//     error, pong).
//
// Протокол: `.kiro/specs/support-chat/design.md` (раздел *WebSocket protocol*).
// Браузер не может выставлять заголовки на WS-рукопожатии, поэтому access-токен
// передаётся в query-параметре `?token=`.
//
// Требования: 9.1/9.3 (list-level unread/обновления), 10.3 (ответ оператора в
// реальном времени), 11.2 (назначение), 12.3 (смена статуса).

import { buildSupportSocketUrl } from "@/features/support-chat/socket";
import type { SupportChatMessage } from "@/features/support-chat/messageList";
import type { SupportConversationStatus } from "@/features/support-chat/api";
import type {
  AssignedOperator,
  ConversationSummary,
} from "./operator-api";
import { readOperatorSession } from "./operator-auth";

/**
 * Состояние WS-соединения, пригодное для индикатора в UI.
 */
export type OperatorSocketState = "connecting" | "connected" | "disconnected";

/**
 * Серверное событие `error` (`{ code, message, clientMsgId? }`). `clientMsgId`
 * присутствует, когда ошибка относится к конкретной отправке `message.send`.
 */
export type OperatorSocketError = {
  code: string;
  message: string;
  clientMsgId?: string;
};

/** Payload события `unread.update` (Requirement 9.3). */
export type OperatorUnreadUpdate = {
  conversationId: string;
  unreadCount: number;
};

/** Payload события `assignment.changed` (Requirement 11.2). */
export type OperatorAssignmentChange = {
  conversationId: string;
  assignedOperator: AssignedOperator | null;
};

/** Payload события `status.changed` (Requirement 12.3). */
export type OperatorStatusChange = {
  conversationId: string;
  status: SupportConversationStatus;
};

/**
 * Набор колбэков, на которые подписывается обёртка-панель. Все необязательны —
 * клиент остаётся полезным и при частичной подписке.
 */
export type OperatorSocketHandlers = {
  /** Соединение открыто и аутентифицировано. */
  onOpen?: () => void;
  /** Соединение закрыто (в т.ч. перед попыткой переподключения). */
  onClose?: (event: CloseEvent) => void;
  /** Изменилось состояние соединения (connecting | connected | disconnected). */
  onStateChange?: (state: OperatorSocketState) => void;
  /** Подтверждение персистентности отправленного ответа (`message.ack`). */
  onAck?: (clientMsgId: string | null, message: SupportChatMessage) => void;
  /** Новое сообщение в переписке (`message.new`). */
  onMessage?: (conversationId: string, message: SupportChatMessage) => void;
  /** Обновление unread по переписке для оператора (`unread.update`). */
  onUnreadUpdate?: (update: OperatorUnreadUpdate) => void;
  /** Обновление сводки переписки в списке (`conversation.updated`). */
  onConversationUpdated?: (conversation: ConversationSummary) => void;
  /** Изменение назначения переписки (`assignment.changed`). */
  onAssignmentChange?: (change: OperatorAssignmentChange) => void;
  /** Изменение статуса переписки (`status.changed`). */
  onStatusChange?: (change: OperatorStatusChange) => void;
  /** Серверная ошибка (`error`). */
  onError?: (error: OperatorSocketError) => void;
  /** Ответ на keepalive (`pong`). */
  onPong?: () => void;
  /**
   * Успешное ПЕРЕподключение после разрыва (не первое подключение). Сигнал
   * панели заново открыть текущую переписку и/или обновить список, чтобы
   * подтянуть пропуски из durable-хранилища.
   */
  onReconnect?: () => void;
};

/**
 * Настройки авто-переподключения с экспоненциальным backoff.
 */
export type OperatorSocketOptions = {
  /** Базовая задержка переподключения, мс (по умолчанию 1000). */
  baseReconnectDelayMs?: number;
  /** Верхняя граница задержки, мс (по умолчанию 30000). */
  maxReconnectDelayMs?: number;
  /**
   * Фабрика WebSocket — переопределяется в тестах. По умолчанию глобальный
   * `WebSocket`.
   */
  socketFactory?: (url: string) => WebSocket;
};

const DEFAULT_BASE_DELAY_MS = 1000;
const DEFAULT_MAX_DELAY_MS = 30000;

/** WS-путь оператор-панели (см. дизайн гейтвея). */
const HELPERPANEL_WS_PATH = "/ws/helperpanel";

function isStatus(value: unknown): value is SupportConversationStatus {
  return value === "open" || value === "in_progress" || value === "closed";
}

/**
 * Клиент WebSocket-канала оператор-панели.
 *
 * Жизненный цикл: `connect()` открывает сокет (или планирует повтор, если нет
 * операторского токена), `close()`/`dispose()` закрывает его и запрещает
 * дальнейшие переподключения. Авто-переподключение с backoff срабатывает только
 * на НЕожиданное закрытие — не после явного `close()`.
 */
export class OperatorChatSocket {
  private handlers: OperatorSocketHandlers;
  private readonly baseDelayMs: number;
  private readonly maxDelayMs: number;
  private readonly socketFactory: (url: string) => WebSocket;

  private socket: WebSocket | null = null;
  private state: OperatorSocketState = "disconnected";
  private reconnectAttempts = 0;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  /** Запрет переподключения после явного `close()`/`dispose()`. */
  private disposed = false;
  /** Было ли хотя бы одно успешное соединение — чтобы отличить reconnect. */
  private hasConnectedOnce = false;

  constructor(
    handlers: OperatorSocketHandlers = {},
    options: OperatorSocketOptions = {},
  ) {
    this.handlers = handlers;
    this.baseDelayMs = options.baseReconnectDelayMs ?? DEFAULT_BASE_DELAY_MS;
    this.maxDelayMs = options.maxReconnectDelayMs ?? DEFAULT_MAX_DELAY_MS;
    this.socketFactory =
      options.socketFactory ?? ((url: string) => new WebSocket(url));
  }

  /** Текущее состояние соединения. */
  getState(): OperatorSocketState {
    return this.state;
  }

  /** Заменить/дополнить набор колбэков после создания клиента. */
  setHandlers(handlers: OperatorSocketHandlers): void {
    this.handlers = handlers;
  }

  /**
   * Открыть соединение. Читает ОПЕРАТОРСКИЙ access-токен из операторской
   * сессии; при его отсутствии планирует повтор (токен может появиться после
   * входа оператора). Повторный вызов при уже открытом/открывающемся сокете
   * игнорируется.
   */
  connect(): void {
    this.disposed = false;
    if (
      this.socket &&
      (this.socket.readyState === WebSocket.OPEN ||
        this.socket.readyState === WebSocket.CONNECTING)
    ) {
      return;
    }

    const token = readOperatorSession()?.accessToken;
    if (!token) {
      // Без токена подключиться нельзя — мягко повторим позже.
      this.setState("disconnected");
      this.scheduleReconnect();
      return;
    }

    this.setState("connecting");
    let ws: WebSocket;
    try {
      ws = this.socketFactory(buildSupportSocketUrl(token, HELPERPANEL_WS_PATH));
    } catch {
      this.setState("disconnected");
      this.scheduleReconnect();
      return;
    }
    this.socket = ws;

    ws.onopen = () => {
      this.reconnectAttempts = 0;
      this.setState("connected");
      const isReconnect = this.hasConnectedOnce;
      this.hasConnectedOnce = true;
      this.handlers.onOpen?.();
      if (isReconnect) {
        this.handlers.onReconnect?.();
      }
    };

    ws.onmessage = (event: MessageEvent) => {
      this.handleFrame(event.data);
    };

    ws.onerror = () => {
      // Ошибку транспорта обрабатываем через последующий onclose.
    };

    ws.onclose = (event: CloseEvent) => {
      this.socket = null;
      this.setState("disconnected");
      this.handlers.onClose?.(event);
      if (!this.disposed) {
        this.scheduleReconnect();
      }
    };
  }

  /**
   * Закрыть соединение и запретить авто-переподключение. Идемпотентно;
   * безопасно вызывать из cleanup-хука панели.
   */
  close(code?: number, reason?: string): void {
    this.disposed = true;
    this.clearReconnectTimer();
    const ws = this.socket;
    this.socket = null;
    if (ws) {
      ws.onclose = null;
      ws.onopen = null;
      ws.onmessage = null;
      ws.onerror = null;
      try {
        ws.close(code, reason);
      } catch {
        // Сокет уже закрыт/закрывается — игнорируем.
      }
    }
    this.setState("disconnected");
  }

  /** Псевдоним `close()` для интеграции с lifecycle-хелперами. */
  dispose(): void {
    this.close();
  }

  /** Открыт ли сокет (готов принимать кадры). */
  isConnected(): boolean {
    return this.socket?.readyState === WebSocket.OPEN;
  }

  // ---- операторские действия ----

  /**
   * Подписаться на конкретную переписку (`conversation.open`). После этого
   * сокет получает `message.new` для этой переписки.
   */
  openConversation(conversationId: string): boolean {
    return this.sendAction({ type: "conversation.open", conversationId });
  }

  /**
   * Отправить ответ оператора (`message.send`) в указанную переписку.
   * Возвращает `true`, если кадр ушёл в открытый сокет; `false`, если
   * соединение неактивно — тогда панель должна показать «не отправлено» и/или
   * применить REST-fallback (`reply` из `operator-api.ts`).
   */
  sendMessage(conversationId: string, clientMsgId: string, body: string): boolean {
    return this.sendAction({
      type: "message.send",
      conversationId,
      clientMsgId,
      body,
    });
  }

  /** Отметить переписку прочитанной (`conversation.markRead`). */
  markRead(conversationId: string): boolean {
    return this.sendAction({ type: "conversation.markRead", conversationId });
  }

  /** Назначить/снять назначение (`conversation.assign`, Requirement 11.2). */
  assign(conversationId: string, assign: boolean): boolean {
    return this.sendAction({ type: "conversation.assign", conversationId, assign });
  }

  /** Сменить статус переписки (`conversation.setStatus`, Requirement 12.3). */
  setStatus(conversationId: string, status: SupportConversationStatus): boolean {
    return this.sendAction({
      type: "conversation.setStatus",
      conversationId,
      status,
    });
  }

  /** Отправить keepalive `ping`. Возвращает `true`, если кадр ушёл. */
  ping(): boolean {
    return this.sendAction({ type: "ping" });
  }

  // ---- внутреннее ----

  private sendAction(action: Record<string, unknown>): boolean {
    const ws = this.socket;
    if (!ws || ws.readyState !== WebSocket.OPEN) {
      return false;
    }
    try {
      ws.send(JSON.stringify(action));
      return true;
    } catch {
      return false;
    }
  }

  private handleFrame(raw: unknown): void {
    if (typeof raw !== "string") {
      return;
    }
    let frame: unknown;
    try {
      frame = JSON.parse(raw);
    } catch {
      return;
    }
    if (!frame || typeof frame !== "object") {
      return;
    }
    const data = frame as Record<string, unknown>;
    const type = data.type;
    if (typeof type !== "string") {
      return;
    }

    switch (type) {
      case "message.ack": {
        const message = data.message as SupportChatMessage | undefined;
        if (message) {
          const clientMsgId =
            typeof data.clientMsgId === "string" ? data.clientMsgId : null;
          this.handlers.onAck?.(clientMsgId, message);
        }
        return;
      }
      case "message.new": {
        const message = data.message as SupportChatMessage | undefined;
        const conversationId =
          typeof data.conversationId === "string"
            ? data.conversationId
            : message?.conversationId;
        if (message && conversationId) {
          this.handlers.onMessage?.(conversationId, message);
        }
        return;
      }
      case "unread.update": {
        const conversationId = data.conversationId;
        const unreadCount = data.unreadCount;
        if (typeof conversationId === "string" && typeof unreadCount === "number") {
          this.handlers.onUnreadUpdate?.({ conversationId, unreadCount });
        }
        return;
      }
      case "conversation.updated": {
        const conversation = data.conversation as ConversationSummary | undefined;
        if (conversation && typeof conversation.id === "string") {
          this.handlers.onConversationUpdated?.(conversation);
        }
        return;
      }
      case "assignment.changed": {
        const conversationId = data.conversationId;
        if (typeof conversationId === "string") {
          const raw = data.assignedOperator as AssignedOperator | null | undefined;
          const assignedOperator =
            raw && typeof raw.id === "string"
              ? { id: raw.id, name: typeof raw.name === "string" ? raw.name : "" }
              : null;
          this.handlers.onAssignmentChange?.({ conversationId, assignedOperator });
        }
        return;
      }
      case "status.changed": {
        const conversationId = data.conversationId;
        const status = data.status;
        if (typeof conversationId === "string" && isStatus(status)) {
          this.handlers.onStatusChange?.({ conversationId, status });
        }
        return;
      }
      case "error": {
        const code = typeof data.code === "string" ? data.code : "UNKNOWN";
        const message =
          typeof data.message === "string" ? data.message : "Unknown error";
        const clientMsgId =
          typeof data.clientMsgId === "string" ? data.clientMsgId : undefined;
        this.handlers.onError?.({ code, message, clientMsgId });
        return;
      }
      case "pong": {
        this.handlers.onPong?.();
        return;
      }
      default:
        // Неизвестные события игнорируем.
        return;
    }
  }

  private setState(state: OperatorSocketState): void {
    if (this.state === state) {
      return;
    }
    this.state = state;
    this.handlers.onStateChange?.(state);
  }

  private scheduleReconnect(): void {
    if (this.disposed || this.reconnectTimer !== null) {
      return;
    }
    const delay = Math.min(
      this.maxDelayMs,
      this.baseDelayMs * 2 ** this.reconnectAttempts,
    );
    this.reconnectAttempts += 1;
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      if (!this.disposed) {
        this.connect();
      }
    }, delay);
  }

  private clearReconnectTimer(): void {
    if (this.reconnectTimer !== null) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
  }
}

/**
 * Удобная фабрика: создаёт и сразу подключает операторский клиент. Возвращает
 * экземпляр для отправки действий и закрытия.
 */
export function connectOperatorChatSocket(
  handlers: OperatorSocketHandlers = {},
  options: OperatorSocketOptions = {},
): OperatorChatSocket {
  const client = new OperatorChatSocket(handlers, options);
  client.connect();
  return client;
}
