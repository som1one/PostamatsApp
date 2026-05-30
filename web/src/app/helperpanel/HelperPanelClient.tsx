"use client";

import { useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import { Headphones, LogOut } from "lucide-react";
import { ApiError } from "@/shared/api/client";
import { useOperatorAuth } from "./operator-auth-context";
import {
  ConversationList,
  useConversationList,
} from "./ConversationList";
import {
  ConversationView,
  useConversationView,
} from "./ConversationView";
import {
  connectOperatorChatSocket,
  type OperatorChatSocket,
} from "./operator-socket";

function OperatorLoginScreen() {
  const { login } = useOperatorAuth();
  const [loginValue, setLoginValue] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (isSubmitting) {
      return;
    }
    setError(null);
    setIsSubmitting(true);
    try {
      await login(loginValue.trim(), password);
      setPassword("");
    } catch (err) {
      // Неверный логин/пароль (Requirement 7.3) или нет роли оператора
      // (Requirement 7.6) — показываем ошибку аутентификации.
      const message =
        err instanceof ApiError
          ? err.message
          : "Не удалось войти. Попробуйте ещё раз.";
      setError(message);
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <div className="helperpanel-login">
      <form className="helperpanel-login-card" onSubmit={handleSubmit}>
        <div className="helperpanel-login-head">
          <span className="helperpanel-login-icon">
            <Headphones size={22} />
          </span>
          <div>
            <strong>Панель оператора</strong>
            <small>Вход для сотрудников поддержки</small>
          </div>
        </div>

        <label className="helperpanel-field">
          <span>Логин</span>
          <input
            type="text"
            name="login"
            autoComplete="username"
            value={loginValue}
            onChange={(event) => setLoginValue(event.target.value)}
            disabled={isSubmitting}
            required
          />
        </label>

        <label className="helperpanel-field">
          <span>Пароль</span>
          <input
            type="password"
            name="password"
            autoComplete="current-password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            disabled={isSubmitting}
            required
          />
        </label>

        {error ? (
          <p className="helperpanel-login-error" role="alert">
            {error}
          </p>
        ) : null}

        <button
          type="submit"
          className="helperpanel-login-submit"
          disabled={isSubmitting}
        >
          {isSubmitting ? "Входим…" : "Войти"}
        </button>
      </form>
    </div>
  );
}

function OperatorShell() {
  const { session, logout } = useOperatorAuth();
  const [isLoggingOut, setIsLoggingOut] = useState(false);

  async function handleLogout() {
    if (isLoggingOut) {
      return;
    }
    setIsLoggingOut(true);
    try {
      await logout();
    } finally {
      setIsLoggingOut(false);
    }
  }

  const admin = session?.admin;

  return (
    <div className="helperpanel-shell">
      <header className="helperpanel-topbar">
        <div className="helperpanel-brand">
          <span className="helperpanel-brand-icon">
            <Headphones size={18} />
          </span>
          <span className="helperpanel-brand-copy">
            <strong>Панель оператора</strong>
            <small>naprokatberu</small>
          </span>
        </div>
        <div className="helperpanel-topbar-actions">
          {admin ? (
            <span className="helperpanel-operator-id">
              {admin.name} · {admin.role}
            </span>
          ) : null}
          <button
            type="button"
            className="helperpanel-logout"
            onClick={handleLogout}
            disabled={isLoggingOut}
          >
            <LogOut size={16} />
            <span>{isLoggingOut ? "Выходим…" : "Выйти"}</span>
          </button>
        </div>
      </header>

      <main className="helperpanel-body">
        <OperatorWorkspace />
      </main>
    </div>
  );
}

/**
 * Owns the single shared operator WebSocket and composes the conversation list
 * (task 8.3) with the conversation view (task 8.4). Because
 * OperatorChatSocket.setHandlers REPLACES all handlers, this parent is the sole
 * caller of setHandlers and multiplexes every event into BOTH the list hook's
 * eventHandlers and the open conversation view's event applicators.
 */
function OperatorWorkspace() {
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [socket, setSocket] = useState<OperatorChatSocket | null>(null);
  const socketRef = useRef<OperatorChatSocket | null>(null);

  const list = useConversationList(socket);
  // The view hook always runs (hooks can't be conditional); it no-ops with an
  // empty conversation id until a conversation is selected.
  const view = useConversationView({
    conversationId: selectedId ?? "",
    socket,
    onConversationChanged: (summary) =>
      list.eventHandlers.onConversationUpdated(summary),
  });

  // Keep stable refs to the latest event applicators so the single
  // setHandlers registration always dispatches to current state closures.
  const listEventsRef = useRef(list.eventHandlers);
  const viewEventsRef = useRef(view.events);
  const selectedIdRef = useRef(selectedId);
  useEffect(() => {
    listEventsRef.current = list.eventHandlers;
  }, [list.eventHandlers]);
  useEffect(() => {
    viewEventsRef.current = view.events;
  }, [view.events]);
  useEffect(() => {
    selectedIdRef.current = selectedId;
  }, [selectedId]);

  // Open exactly one shared socket for the workspace lifetime, multiplexing
  // every inbound event into both the list and the open conversation view.
  useEffect(() => {
    const client = connectOperatorChatSocket({
      onMessage: (cid, message) => {
        viewEventsRef.current.onMessage(cid, message);
      },
      onAck: (clientMsgId, message) => {
        viewEventsRef.current.onAck(clientMsgId, message);
      },
      onUnreadUpdate: (update) => listEventsRef.current.onUnreadUpdate(update),
      onConversationUpdated: (conversation) =>
        listEventsRef.current.onConversationUpdated(conversation),
      onAssignmentChange: (change) => {
        listEventsRef.current.onAssignmentChange(change);
        viewEventsRef.current.onAssignmentChange(change);
      },
      onStatusChange: (change) => {
        listEventsRef.current.onStatusChange(change);
        viewEventsRef.current.onStatusChange(change);
      },
      onReconnect: () => {
        listEventsRef.current.onReconnect();
        viewEventsRef.current.onReconnect();
      },
    });
    socketRef.current = client;
    setSocket(client);
    return () => {
      client.close();
      socketRef.current = null;
    };
  }, []);

  return (
    <div className="helperpanel-workspace">
      <div className="helperpanel-list-pane">
        <ConversationList
          conversations={list.conversations}
          loading={list.loading}
          error={list.error}
          activeStatus={list.activeStatus}
          onStatusChange={list.setActiveStatus}
          selectedConversationId={selectedId ?? undefined}
          onSelect={setSelectedId}
        />
      </div>
      <div className="helperpanel-view-pane">
        {selectedId ? (
          <ConversationView view={view} />
        ) : (
          <div className="helperpanel-placeholder">
            <p>Выберите обращение слева.</p>
            <p className="helperpanel-placeholder-hint">
              Здесь откроется переписка с клиентом.
            </p>
          </div>
        )}
      </div>
    </div>
  );
}

export function HelperPanelClient() {
  const { isReady, isAuthed } = useOperatorAuth();

  if (!isReady) {
    return (
      <div className="helperpanel-loading" role="status">
        Загрузка…
      </div>
    );
  }

  return isAuthed ? <OperatorShell /> : <OperatorLoginScreen />;
}
