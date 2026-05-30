// WebSocket-клиент поддержки (клиентская сторона) — UI-агностичный.
//
// Этот модуль НЕ зависит от React: он инкапсулирует подключение к
// `/ws/support`, отправку действий, разбор входящих событий, индикацию
// состояния соединения и авто-переподключение с backoff. Виджет (задача 7.5)
// оборачивает этот клиент и связывает его колбэки с UI/редьюсерами из
// `messageList.ts`.
//
// Протокол: `.kiro/specs/support-chat/design.md` (раздел *WebSocket protocol*).
// Браузер не может выставлять заголовки на WS-рукопожатии, поэтому access-токен
// передаётся в query-параметре `?token=` (совпадает с дизайном гейтвея).
//
// Требования: 4.1 (доставка в реальном времени), 6.2 (авто-переподключение),
// 6.3 (реконсиляция пропусков после переподключения — через `onReconnect`).

import { apiBaseUrl } from "@/shared/api/client";
import { readStoredSession } from "@/shared/auth/session";
import type { SupportChatMessage } from "./messageList";

/**
 * Состояние WS-соединения, пригодное для индикатора в UI (Requirement 6.1).
 */
export type SupportSocketState = "connecting" | "connected" | "disconnected";

/**
 * Серверное событие `error` (`{ code, message, clientMsgId? }`). `clientMsgId`
 * присутствует, когда ошибка относится к конкретной отправке `message.send`,
 * чтобы отправитель мог сопоставить её со своим оптимистичным сообщением.
 */
export type SupportSocketError = {
  code: string;
  message: string;
  clientMsgId?: string;
};

/**
 * Payload события `status.changed` для переписки клиента.
 */
export type SupportStatusChange = {
  conversationId: string;
  status: "open" | "in_progress" | "closed";
};

/**
 * Набор колбэков, на которые подписывается обёртка-виджет. Все необязательны —
 * клиент остаётся полезным и при частичной подписке.
 */
export type SupportSocketHandlers = {
  /** Соединение открыто и аутентифицировано. */
  onOpen?: () => void;
  /** Соединение закрыто (в т.ч. перед попыткой переподключения). */
  onClose?: (event: CloseEvent) => void;
  /** Изменилось состояние соединения (connecting | connected | disconnected). */
  onStateChange?: (state: SupportSocketState) => void;
  /** Подтверждение персистентности отправленного сообщения (`message.ack`). */
  onAck?: (clientMsgId: string | null, message: SupportChatMessage) => void;
  /** Новое сообщение в переписке (`message.new`). */
  onMessage?: (conversationId: string, message: SupportChatMessage) => void;
  /** Серверная ошибка (`error`). */
  onError?: (error: SupportSocketError) => void;
  /** Изменение статуса переписки (`status.changed`). */
  onStatusChange?: (change: SupportStatusChange) => void;
  /** Ответ на keepalive (`pong`). */
  onPong?: () => void;
  /**
   * Успешное ПЕРЕподключение после разрыва (не первое подключение). Сигнал для
   * виджета запустить реконсиляцию пропусков: подтянуть по REST сообщения с
   * `seq` выше локального максимума и вмержить через `reconcileMessages`
   * (Requirement 6.3).
   */
  onReconnect?: () => void;
};

/**
 * Настройки авто-переподключения с экспоненциальным backoff.
 */
export type SupportSocketOptions = {
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

/**
 * Преобразует HTTP(S)-базу API в WS(S) и строит URL `/ws/support?token=…`.
 *
 * Экспортируется для переиспользования операторским сокетом (`/ws/helperpanel`)
 * и для модульных тестов.
 */
export function buildSupportSocketUrl(token: string, path = "/ws/support"): string {
  const httpBase = apiBaseUrl();
  const wsBase = httpBase.replace(/^http(s?):\/\//i, (_match, secure) =>
    secure ? "wss://" : "ws://",
  );
  const normalizedPath = path.startsWith("/") ? path : `/${path}`;
  return `${wsBase}${normalizedPath}?token=${encodeURIComponent(token)}`;
}

/**
 * Клиент WebSocket-канала поддержки.
 *
 * Жизненный цикл: `connect()` открывает сокет (или планирует повтор, если нет
 * токена), `close()`/`dispose()` закрывает его и запрещает дальнейшие
 * переподключения. Авто-переподключение с backoff срабатывает только на
 * НЕожиданное закрытие — не после явного `close()`.
 */
export class SupportChatSocket {
  private handlers: SupportSocketHandlers;
  private readonly baseDelayMs: number;
  private readonly maxDelayMs: number;
  private readonly socketFactory: (url: string) => WebSocket;

  private socket: WebSocket | null = null;
  private state: SupportSocketState = "disconnected";
  private reconnectAttempts = 0;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  /** Запрет переподключения после явного `close()`/`dispose()`. */
  private disposed = false;
  /** Было ли хотя бы одно успешное соединение — чтобы отличить reconnect. */
  private hasConnectedOnce = false;

  constructor(handlers: SupportSocketHandlers = {}, options: SupportSocketOptions = {}) {
    this.handlers = handlers;
    this.baseDelayMs = options.baseReconnectDelayMs ?? DEFAULT_BASE_DELAY_MS;
    this.maxDelayMs = options.maxReconnectDelayMs ?? DEFAULT_MAX_DELAY_MS;
    this.socketFactory =
      options.socketFactory ?? ((url: string) => new WebSocket(url));
  }

  /** Текущее состояние соединения. */
  getState(): SupportSocketState {
    return this.state;
  }

  /** Заменить/дополнить набор колбэков после создания клиента. */
  setHandlers(handlers: SupportSocketHandlers): void {
    this.handlers = handlers;
  }

  /**
   * Открыть соединение. Читает access-токен из хранимой сессии; при его
   * отсутствии планирует повтор (токен может появиться после входа). Повторный
   * вызов при уже открытом/открывающемся сокете игнорируется.
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

    const token = readStoredSession()?.accessToken;
    if (!token) {
      // Без токена подключиться нельзя — мягко повторим позже.
      this.setState("disconnected");
      this.scheduleReconnect();
      return;
    }

    this.setState("connecting");
    let ws: WebSocket;
    try {
      ws = this.socketFactory(buildSupportSocketUrl(token));
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
        // Сигнал виджету: подтянуть пропуски из durable-хранилища (Req 6.3).
        this.handlers.onReconnect?.();
      }
    };

    ws.onmessage = (event: MessageEvent) => {
      this.handleFrame(event.data);
    };

    ws.onerror = () => {
      // Ошибку транспорта обрабатываем через последующий onclose; здесь только
      // фиксируем, что соединение нездорово.
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
   * безопасно вызывать из cleanup-хука виджета.
   */
  close(code?: number, reason?: string): void {
    this.disposed = true;
    this.clearReconnectTimer();
    const ws = this.socket;
    this.socket = null;
    if (ws) {
      // Снимаем onclose, чтобы явное закрытие не запускало переподключение.
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

  /**
   * Отправить сообщение клиента (`message.send`). Возвращает `true`, если кадр
   * ушёл в открытый сокет; `false`, если соединение неактивно — в этом случае
   * виджет должен показать «не отправлено» и/или применить REST-fallback
   * (Requirement 6.4).
   */
  sendMessage(clientMsgId: string, body: string): boolean {
    return this.sendAction({ type: "message.send", clientMsgId, body });
  }

  /** Отправить keepalive `ping`. Возвращает `true`, если кадр ушёл. */
  ping(): boolean {
    return this.sendAction({ type: "ping" });
  }

  /** Открыт ли сокет (готов принимать кадры). */
  isConnected(): boolean {
    return this.socket?.readyState === WebSocket.OPEN;
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
      case "status.changed": {
        const conversationId = data.conversationId;
        const status = data.status;
        if (
          typeof conversationId === "string" &&
          (status === "open" || status === "in_progress" || status === "closed")
        ) {
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
        // Неизвестные/операторские события на клиентском сокете игнорируем.
        return;
    }
  }

  private setState(state: SupportSocketState): void {
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
 * Удобная фабрика: создаёт и сразу подключает клиент. Возвращает экземпляр для
 * отправки действий и закрытия.
 */
export function connectSupportChatSocket(
  handlers: SupportSocketHandlers = {},
  options: SupportSocketOptions = {},
): SupportChatSocket {
  const client = new SupportChatSocket(handlers, options);
  client.connect();
  return client;
}
