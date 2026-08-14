"use client";

import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ArrowLeft } from "lucide-react";
import { PageChrome } from "@/components/PageChrome";
import { confirmCode, requestCode } from "@/shared/api/endpoints";
import { useAuth } from "@/shared/auth/auth-context";
import {
  AUTH_ERROR_MESSAGES,
  resolveAuthErrorMessage,
} from "@/shared/authMessages";
import {
  normalizePhoneForApi,
  normalizePhoneInput,
} from "@/shared/format";

type Step = "phone" | "code";
type Channel = "sms" | "call";

export function AuthClient() {
  const router = useRouter();
  const { setSessionFromLogin, isAuthed } = useAuth();
  const [step, setStep] = useState<Step>("phone");
  const [phone, setPhone] = useState("");
  const [code, setCode] = useState("");
  const [sessionId, setSessionId] = useState("");
  const [ttl, setTtl] = useState(0);
  const [channel, setChannel] = useState<Channel>("sms");
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
      setChannel(result.channel === "call" ? "call" : "sms");
      setCode("");
      setStep("code");
    } catch (submitError) {
      setError(
        resolveAuthErrorMessage(
          submitError,
          "Не удалось отправить код. Попробуйте еще раз.",
        ),
      );
    } finally {
      setLoading(false);
    }
  }

  async function handleCodeSubmit(event: FormEvent) {
    event.preventDefault();
    if (!sessionId || code.trim().length < 4) {
      setError(channel === "call" ? "Введите код из звонка." : "Введите SMS-код.");
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
    setChannel("sms");
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
                  Нажимая «Получить код», вы соглашаетесь с{" "}
                  <Link className="legal-link" href="/terms-rental">
                    условиями аренды
                  </Link>{" "}
                  и{" "}
                  <Link className="legal-link" href="/privacy">
                    политикой конфиденциальности
                  </Link>
                  .
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
                <p className="eyebrow">{channel === "call" ? "Код из звонка" : "SMS-код"}</p>
                <h1>{normalizedPhone}</h1>
                {channel === "call" ? (
                  <p className="auth-hint">
                    Сейчас на ваш номер поступит входящий звонок.
                    Брать трубку не нужно — последние 4 цифры
                    номера, с которого звонят, и есть ваш код.
                  </p>
                ) : null}
                <form className="form-stack" onSubmit={handleCodeSubmit}>
                  <div className="field">
                    <span>Код</span>
                    <div
                      className={`otp-input-shell ${isCodeFocused ? "is-focused" : ""}`}
                      role="button"
                      tabIndex={0}
                      aria-label={
                        channel === "call"
                          ? "Введите 4 цифры с экрана звонка"
                          : "Введите код из SMS"
                      }
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
