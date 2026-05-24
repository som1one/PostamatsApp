"use client";

import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { ArrowLeft } from "lucide-react";
import { PageChrome } from "@/components/PageChrome";
import { ApiError } from "@/shared/api/client";
import { confirmCode, requestCode } from "@/shared/api/endpoints";
import { useAuth } from "@/shared/auth/auth-context";
import {
  normalizePhoneForApi,
  normalizePhoneInput,
} from "@/shared/format";

type Step = "phone" | "code";

const AUTH_ERROR_MESSAGES: Record<string, string> = {
  AUTH_PHONE_REQUIRED: "Введите номер телефона.",
  AUTH_PHONE_INVALID: "Введите корректный номер РФ или РБ.",
  AUTH_SMS_SEND_FAILED: "Не удалось отправить SMS. Попробуйте еще раз чуть позже.",
  AUTH_SMS_PROVIDER_ERROR: "Сервис SMS сейчас недоступен. Попробуйте еще раз чуть позже.",
  AUTH_RESEND_TOO_SOON: "Подождите немного перед повторной отправкой кода.",
  AUTH_SESSION_NOT_FOUND: "Сессия входа не найдена. Запросите код заново.",
  AUTH_SESSION_INACTIVE: "Этот код уже недействителен. Запросите новый.",
  AUTH_SESSION_EXPIRED: "Срок действия кода истек. Запросите новый.",
  AUTH_TOO_MANY_ATTEMPTS: "Слишком много попыток. Запросите новый код.",
  AUTH_CODE_INVALID: "Неверный код. Попробуйте еще раз.",
  AUTH_ACCOUNT_BLOCKED: "Аккаунт заблокирован. Обратитесь в поддержку.",
  AUTH_UNAUTHORIZED: "Сессия входа недействительна. Попробуйте войти заново.",
};


function resolveAuthErrorMessage(error: unknown, fallback: string): string {
  if (error instanceof ApiError) {
    return AUTH_ERROR_MESSAGES[error.code || ""] || fallback;
  }
  return fallback;
}

export function AuthClient() {
  const router = useRouter();
  const { setSessionFromLogin, isAuthed } = useAuth();
  const [step, setStep] = useState<Step>("phone");
  const [phone, setPhone] = useState("");
  const [code, setCode] = useState("");
  const [sessionId, setSessionId] = useState("");
  const [ttl, setTtl] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [isCodeFocused, setIsCodeFocused] = useState(false);
  const codeInputRef = useRef<HTMLInputElement | null>(null);
  const normalizedPhone = useMemo(() => normalizePhoneForApi(phone), [phone]);

  useEffect(() => {
    if (isAuthed) {
      router.replace("/profile");
    }
  }, [isAuthed, router]);

  useEffect(() => {
    if (step !== "code" || ttl <= 0) {
      return;
    }
    const timer = window.setInterval(() => {
      setTtl((current) => Math.max(0, current - 1));
    }, 1000);
    return () => window.clearInterval(timer);
  }, [step, ttl]);

  useEffect(() => {
    if (step === "code") {
      codeInputRef.current?.focus();
    }
  }, [step]);

  async function handlePhoneSubmit(event: FormEvent) {
    event.preventDefault();
    if (!normalizedPhone) {
      setError(AUTH_ERROR_MESSAGES.AUTH_PHONE_INVALID);
      return;
    }

    setLoading(true);
    setError("");
    try {
      const result = await requestCode(normalizedPhone);
      setSessionId(result.verificationSessionId);
      setTtl(result.ttlSeconds ?? 0);
      setCode("");
      setStep("code");
    } catch (submitError) {
      setError(
        resolveAuthErrorMessage(
          submitError,
          "Не удалось отправить SMS. Попробуйте еще раз.",
        ),
      );
    } finally {
      setLoading(false);
    }
  }

  async function handleCodeSubmit(event: FormEvent) {
    event.preventDefault();
    if (!sessionId || code.trim().length < 4) {
      setError("Введите SMS-код.");
      return;
    }

    setLoading(true);
    setError("");
    try {
      const result = await confirmCode(sessionId, code.trim());
      setSessionFromLogin(result);
      router.replace("/");
    } catch (submitError) {
      setError(
        resolveAuthErrorMessage(
          submitError,
          "Не удалось выполнить вход. Попробуйте еще раз.",
        ),
      );
    } finally {
      setLoading(false);
    }
  }

  function resetToPhoneStep() {
    setStep("phone");
    setSessionId("");
    setTtl(0);
    setError("");
    setCode("");
    setIsCodeFocused(false);
  }

  return (
    <PageChrome compact>
      <div className="auth-layout">
        <section className="surface auth-panel">
          <div className="auth-panel-card">
            {step === "phone" ? (
              <>
                <p className="eyebrow">Вход / Регистрация</p>
                <h1>Введите телефон</h1>
                <p className="auth-hint">
                  Если у вас ещё нет аккаунта, он будет создан автоматически.
                </p>
                <form className="form-stack" onSubmit={handlePhoneSubmit}>
                  <label className="field">
                    <span>Телефон</span>
                    <input
                      className="input"
                      value={phone}
                      placeholder="+79991234567"
                      onChange={(event) => setPhone(normalizePhoneInput(event.target.value))}
                      autoComplete="tel"
                    />
                  </label>
                  {error ? <div className="alert alert-danger">{error}</div> : null}
                  <button
                    className="button button-primary"
                    type="submit"
                    disabled={loading}
                  >
                    {loading ? "Отправляем" : "Получить код"}
                  </button>
                </form>
                <p className="auth-terms">
                  Нажимая «Получить код», вы соглашаетесь с условиями использования сервиса.
                </p>
              </>
            ) : (
              <>
                <button
                  className="button button-ghost button-inline"
                  type="button"
                  onClick={resetToPhoneStep}
                >
                  <ArrowLeft size={18} />
                  Назад
                </button>
                <p className="eyebrow">SMS-код</p>
                <h1>{normalizedPhone}</h1>
                <form className="form-stack" onSubmit={handleCodeSubmit}>
                  <div className="field">
                    <span>Код</span>
                    <div
                      className={`otp-input-shell ${isCodeFocused ? "is-focused" : ""}`}
                      role="button"
                      tabIndex={0}
                      aria-label="Введите код из SMS"
                      onClick={() => codeInputRef.current?.focus()}
                      onKeyDown={(event) => {
                        if (event.key === "Enter" || event.key === " ") {
                          event.preventDefault();
                          codeInputRef.current?.focus();
                        }
                      }}
                    >
                      <input
                        ref={codeInputRef}
                        className="otp-hidden-input"
                        value={code}
                        inputMode="numeric"
                        autoComplete="one-time-code"
                        maxLength={4}
                        onFocus={() => setIsCodeFocused(true)}
                        onBlur={() => setIsCodeFocused(false)}
                        onChange={(event) =>
                          setCode(event.target.value.replace(/\D/g, "").slice(0, 4))
                        }
                      />
                      <div className="otp-row" aria-hidden="true">
                        {Array.from({ length: 4 }, (_, index) => {
                          const isActive =
                            isCodeFocused &&
                            (index === Math.min(code.length, 3) ||
                              (code.length === 4 && index === 3));

                          return (
                            <div
                              className={`otp-box ${code[index] ? "is-filled" : ""} ${isActive ? "is-active" : ""}`}
                              key={index}
                            >
                              {code[index] || ""}
                            </div>
                          );
                        })}
                      </div>
                    </div>
                  </div>
                  {ttl ? <p className="muted">Код действует еще {ttl} сек.</p> : null}
                  {error ? <div className="alert alert-danger">{error}</div> : null}
                  <button
                    className="button button-primary"
                    type="submit"
                    disabled={loading || code.length < 4}
                  >
                    {loading ? "Проверяем" : "Войти"}
                  </button>
                </form>
              </>
            )}
          </div>
        </section>
      </div>
    </PageChrome>
  );
}
