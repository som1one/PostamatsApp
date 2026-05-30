"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import {
  AlertCircle,
  Headphones,
  LogIn,
  RotateCcw,
  Send,
  X,
} from "lucide-react";
import { useAuth } from "@/shared/auth/auth-context";
import {
  fetchOlderMessages,
  getConversation,
  sendMessageRest,
  type SupportConversationStatus,
} from "@/features/support-chat/api";
import {
  localMaxSeq,
  mergeMessages,
  reconcileMessages,
  type SupportChatMessage,
} from "@/features/support-chat/messageList";
import {
  connectSupportChatSocket,
  type SupportChatSocket,
  type SupportSocketState,
} from "@/features/support-chat/socket";

/** Лимит длины сообщения — совпадает с серверным `MAX_MESSAGE_LENGTH` (Req 2.4). */
const MAX_MESSAGE_LENGTH = 4000;

/**
 * Локальное «оптимистичное» сообщение клиента, ещё не подтверждённое сервером.
 *
 * `sending` — кадр ушёл в сокет, ждём `message.ack`; `failed` — отправить не
 * удалось (соединение разорвано или ошибка), показываем «не отправлено» с
 * возможностью повтора (Req 6.4).
 */
type PendingMessage = {
  clientMsgId: string;
  body: string;
  status: "sending" | "failed";
  createdAt: string;
};

const CONNECTION_LABELS: Record<SupportSocketState, string> = {
  connecting: "Подключение…",
  connected: "На связи",
  disconnected: "Нет соединения",
};

function genClientMsgId(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  return `c-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

function formatTime(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) {
    return "";
  }
  return date.toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" });
}

export function SupportWidget() {
  const { isAuthed, isReady } = useAuth();
  const [open, setOpen] = useState(false);

  const [messages, setMessages] = useState<SupportChatMessage[]>([]);
  const [pending, setPending] = useState<PendingMessage[]>([]);
  const [connState, setConnState] = useState<SupportSocketState>("disconnected");
  const [convStatus, setConvStatus] = useState<SupportConversationStatus | null>(null);

  const [loading, setLoading] = useState(false);
  const [loadingOlder, setLoadingOlder] = useState(false);
  const [hasMore, setHasMore] = useState(false);
  const [oldestSeq, setOldestSeq] = useState<number | null>(null);
  const [draft, setDraft] = useState("");
  const [error, setError] = useState<string | null>(null);

  const rootRef = useRef<HTMLDivElement | null>(null);
  const socketRef = useRef<SupportChatSocket | null>(null);
  const bottomRef = useRef<HTMLDivElement | null>(null);
  const prevMaxSeqRef = useRef<number | null>(null);

  // Реконсиляция пропусков после переподключения (Req 6.3): подтягиваем по REST
  // персистентную переписку и вмерживаем сообщения с `seq` выше локального.
  const reconcile = useCallback(async () => {
    try {
      const resp = await getConversation();
      setMessages((prev) => reconcileMessages(prev, resp.messages));
      setConvStatus(resp.conversation.status);
    } catch {
      // Молча игнорируем — следующее переподключение повторит реконсиляцию.
    }
  }, []);

  // Загрузка переписки + открытие сокета при открытии панели авторизованным
  // клиентом. Сокет НЕ открывается для неавторизованных (Req 3.x).
  useEffect(() => {
    if (!open || !isReady || !isAuthed) {
      return;
    }

    let cancelled = false;
    setLoading(true);
    setError(null);

    void (async () => {
      try {
        const resp = await getConversation();
        if (cancelled) {
          return;
        }
        setMessages(mergeMessages([], resp.messages));
        setHasMore(resp.hasMore);
        setOldestSeq(resp.oldestSeq);
        setConvStatus(resp.conversation.status);
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

    const socket = connectSupportChatSocket({
      onStateChange: (state) => setConnState(state),
      onAck: (clientMsgId, message) => {
        setMessages((prev) => mergeMessages(prev, message));
        if (clientMsgId) {
          setPending((prev) => prev.filter((p) => p.clientMsgId !== clientMsgId));
        }
      },
      onMessage: (_conversationId, message) => {
        setMessages((prev) => mergeMessages(prev, message));
      },
      onError: (err) => {
        if (err.clientMsgId) {
          setPending((prev) =>
            prev.map((p) =>
              p.clientMsgId === err.clientMsgId ? { ...p, status: "failed" } : p,
            ),
          );
        } else {
          setError(err.message);
        }
      },
      onStatusChange: (change) => setConvStatus(change.status),
      onReconnect: () => {
        void reconcile();
      },
    });
    socketRef.current = socket;

    return () => {
      cancelled = true;
      socket.close();
      socketRef.current = null;
    };
  }, [open, isReady, isAuthed, reconcile]);

  // Автоскролл к низу при появлении новых сообщений/отправок (но не при
  // подгрузке более старой истории).
  useEffect(() => {
    const max = localMaxSeq(messages);
    const prev = prevMaxSeqRef.current;
    const grew = max !== null && (prev === null || max > prev);
    prevMaxSeqRef.current = max;
    if (grew || pending.length > 0) {
      bottomRef.current?.scrollIntoView({ block: "end" });
    }
  }, [messages, pending]);

  // Закрытие по Escape.
  useEffect(() => {
    if (!open) {
      return;
    }
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        setOpen(false);
      }
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [open]);

  const markFailed = useCallback((clientMsgId: string) => {
    setPending((prev) =>
      prev.map((p) => (p.clientMsgId === clientMsgId ? { ...p, status: "failed" } : p)),
    );
  }, []);

  const handleSend = useCallback(() => {
    const body = draft.trim();
    if (!body) {
      return;
    }
    if (body.length > MAX_MESSAGE_LENGTH) {
      setError(`Сообщение длиннее ${MAX_MESSAGE_LENGTH} символов.`);
      return;
    }

    const clientMsgId = genClientMsgId();
    const createdAt = new Date().toISOString();
    setDraft("");
    setError(null);

    const socket = socketRef.current;
    if (socket && socket.isConnected()) {
      setPending((prev) => [...prev, { clientMsgId, body, status: "sending", createdAt }]);
      const ok = socket.sendMessage(clientMsgId, body);
      if (!ok) {
        markFailed(clientMsgId);
      }
      return;
    }

    // Соединение разорвано — отмечаем «не отправлено» (Req 6.4); повтор
    // попробует сокет, а при его недоступности — REST-fallback для персистентности.
    setPending((prev) => [...prev, { clientMsgId, body, status: "failed", createdAt }]);
  }, [draft, markFailed]);

  const handleRetry = useCallback(
    (msg: PendingMessage) => {
      setPending((prev) =>
        prev.map((p) => (p.clientMsgId === msg.clientMsgId ? { ...p, status: "sending" } : p)),
      );

      const socket = socketRef.current;
      if (socket && socket.isConnected()) {
        const ok = socket.sendMessage(msg.clientMsgId, msg.body);
        if (!ok) {
          markFailed(msg.clientMsgId);
        }
        return;
      }

      // REST-fallback гарантирует персистентность даже при недоступном сокете (Req 6.4).
      void (async () => {
        try {
          const resp = await sendMessageRest(msg.body);
          setMessages((prev) => mergeMessages(prev, resp.message));
          setPending((prev) => prev.filter((p) => p.clientMsgId !== msg.clientMsgId));
        } catch {
          markFailed(msg.clientMsgId);
        }
      })();
    },
    [markFailed],
  );

  const handleLoadOlder = useCallback(() => {
    if (oldestSeq === null || loadingOlder || !hasMore) {
      return;
    }
    setLoadingOlder(true);
    void (async () => {
      try {
        const page = await fetchOlderMessages(oldestSeq);
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
  }, [oldestSeq, loadingOlder, hasMore]);

  const handleInputKeyDown = useCallback(
    (event: React.KeyboardEvent<HTMLTextAreaElement>) => {
      if (event.key === "Enter" && !event.shiftKey) {
        event.preventDefault();
        handleSend();
      }
    },
    [handleSend],
  );

  function renderPanelBody() {
    if (!isReady) {
      return <div className="support-chat-info">Загрузка…</div>;
    }

    if (!isAuthed) {
      return (
        <div className="support-chat-login">
          <p>Чтобы написать в поддержку, войдите в аккаунт.</p>
          <Link href="/login" className="support-chat-login-btn" onClick={() => setOpen(false)}>
            <LogIn size={16} />
            <span>Войти</span>
          </Link>
        </div>
      );
    }

    return (
      <>
        <div className="support-chat-body">
          {hasMore ? (
            <button
              type="button"
              className="support-chat-load-older"
              onClick={handleLoadOlder}
              disabled={loadingOlder}
            >
              {loadingOlder ? "Загрузка…" : "Показать ранние сообщения"}
            </button>
          ) : null}

          {loading && messages.length === 0 ? (
            <div className="support-chat-info">Загрузка переписки…</div>
          ) : null}

          {!loading && messages.length === 0 && pending.length === 0 ? (
            <div className="support-chat-info">
              Напишите нам — оператор ответит в ближайшее время.
            </div>
          ) : null}

          {messages.map((message) => (
            <div
              key={message.id}
              className={`support-chat-msg ${
                message.authorType === "client" ? "is-client" : "is-operator"
              }`}
            >
              <div className="support-chat-bubble">{message.body}</div>
              <div className="support-chat-meta">
                {message.authorType === "operator" && message.authorName
                  ? `${message.authorName} · `
                  : ""}
                {formatTime(message.createdAt)}
              </div>
            </div>
          ))}

          {pending.map((message) => (
            <div key={message.clientMsgId} className="support-chat-msg is-client is-pending">
              <div className="support-chat-bubble">{message.body}</div>
              <div className="support-chat-meta">
                {message.status === "failed" ? (
                  <button
                    type="button"
                    className="support-chat-retry"
                    onClick={() => handleRetry(message)}
                  >
                    <RotateCcw size={12} />
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

        {convStatus === "closed" ? (
          <div className="support-chat-status-note">
            Обращение закрыто. Новое сообщение откроет его снова.
          </div>
        ) : null}

        {error ? (
          <div className="support-chat-error">
            <AlertCircle size={14} />
            <span>{error}</span>
          </div>
        ) : null}

        <div className="support-chat-input-row">
          <textarea
            className="support-chat-input"
            placeholder="Введите сообщение…"
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={handleInputKeyDown}
            rows={1}
            maxLength={MAX_MESSAGE_LENGTH + 1}
          />
          <button
            type="button"
            className="support-chat-send"
            onClick={handleSend}
            disabled={draft.trim().length === 0}
            aria-label="Отправить сообщение"
          >
            <Send size={18} />
          </button>
        </div>
      </>
    );
  }

  const connLabel = CONNECTION_LABELS[connState];

  return (
    <div className="support-widget" ref={rootRef}>
      {open ? (
        <div
          className="support-widget-panel support-chat-panel"
          role="dialog"
          aria-label="Чат поддержки"
        >
          <div className="support-widget-head support-chat-head">
            <span className="support-widget-head-icon">
              <Headphones size={18} />
            </span>
            <span className="support-chat-head-copy">
              <strong>Поддержка naprokatberu</strong>
              {isReady && isAuthed ? (
                <small className="support-chat-conn">
                  <span className={`support-conn-dot is-${connState}`} aria-hidden="true" />
                  {connLabel}
                </small>
              ) : (
                <small>Мы на связи</small>
              )}
            </span>
            <button
              type="button"
              className="support-chat-close"
              onClick={() => setOpen(false)}
              aria-label="Свернуть чат"
            >
              <X size={18} />
            </button>
          </div>

          {renderPanelBody()}
        </div>
      ) : null}

      <button
        type="button"
        className={`support-widget-toggle${open ? " is-open" : ""}`}
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
        aria-label={open ? "Закрыть чат поддержки" : "Открыть чат поддержки"}
      >
        {open ? <X size={24} /> : <Headphones size={24} />}
      </button>
    </div>
  );
}
