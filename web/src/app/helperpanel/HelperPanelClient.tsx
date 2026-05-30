"use client";

import { useState, type FormEvent } from "react";
import { Headphones, LogOut } from "lucide-react";
import { ApiError } from "@/shared/api/client";
import { useOperatorAuth } from "./operator-auth-context";

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
        {/* Список диалогов и просмотр диалога реализуются в задачах 8.3/8.4.
            Здесь только аутентифицированный контейнер-заглушка. */}
        <div className="helperpanel-placeholder">
          <p>Вы вошли в панель оператора.</p>
          <p className="helperpanel-placeholder-hint">
            Список обращений и окно диалога появятся здесь.
          </p>
        </div>
      </main>
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
