"use client";

import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { ArrowLeft, KeyRound, Phone, ShieldCheck } from "lucide-react";
import { PageChrome } from "@/components/PageChrome";
import { confirmCode, requestCode } from "@/shared/api/endpoints";
import { useAuth } from "@/shared/auth/auth-context";
import {
  isPhoneReady,
  normalizePhoneForApi,
  normalizePhoneInput,
} from "@/shared/format";

type Step = "phone" | "code";

export function AuthClient() {
  const router = useRouter();
  const { setSessionFromLogin, isAuthed } = useAuth();
  const [step, setStep] = useState<Step>("phone");
  const [phone, setPhone] = useState("");
  const [code, setCode] = useState("");
  const [sessionId, setSessionId] = useState("");
  const [devCode, setDevCode] = useState("");
  const [ttl, setTtl] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
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
    if (!isPhoneReady(phone)) {
      setError("Введите номер РФ или РБ.");
      return;
    }

    setLoading(true);
    setError("");
    try {
      const result = await requestCode(normalizedPhone);
      setSessionId(result.verificationSessionId);
      setDevCode(result.code || "");
      setTtl(result.ttlSeconds || 0);
      setCode("");
      setStep("code");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось отправить код.");
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
    } catch (err) {
      setError(err instanceof Error ? err.message : "Код не подошёл.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <PageChrome compact>
      <div className="auth-layout">
        <section className="surface auth-copy">
          <p className="eyebrow">Postamats ID</p>
          <h1 className="page-title">Вход по телефону</h1>
          <p className="page-subtitle">
            Один аккаунт открывает каталог, проверку документов, брони, оплату и
            историю аренд.
          </p>
          <div className="step-list">
            <div className="step-item">
              <span className="step-dot">
                <Phone size={18} />
              </span>
              <div>
                <strong>Номер РФ или РБ</strong>
                <p className="small">Поддерживаются номера России и Беларуси.</p>
              </div>
            </div>
            <div className="step-item">
              <span className="step-dot">
                <KeyRound size={18} />
              </span>
              <div>
                <strong>Короткий код</strong>
                <p className="small">В dev-режиме код показывается после отправки.</p>
              </div>
            </div>
          </div>
        </section>

        <section className="surface auth-panel">
          {step === "phone" ? (
            <>
              <p className="eyebrow">Вход</p>
              <h1>Введите телефон</h1>
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
                  disabled={loading || !isPhoneReady(phone)}
                >
                  {loading ? "Отправляем" : "Далее"}
                </button>
              </form>
            </>
          ) : (
            <>
              <button
                className="button button-ghost button-inline"
                type="button"
                onClick={() => {
                  setStep("phone");
                  setError("");
                  setCode("");
                }}
              >
                <ArrowLeft size={18} />
                Назад
              </button>
              <p className="eyebrow">SMS-код</p>
              <h1>{normalizedPhone}</h1>
              <form className="form-stack" onSubmit={handleCodeSubmit}>
                <label className="field">
                  <span>Код</span>
                  <input
                    ref={codeInputRef}
                    className="input"
                    value={code}
                    inputMode="numeric"
                    maxLength={4}
                    placeholder="1234"
                    onChange={(event) =>
                      setCode(event.target.value.replace(/\D/g, "").slice(0, 4))
                    }
                  />
                </label>
                <div className="otp-row" aria-hidden="true">
                  {Array.from({ length: 4 }, (_, index) => (
                    <div className="otp-box" key={index}>
                      {code[index] || ""}
                    </div>
                  ))}
                </div>
                {devCode ? (
                  <div className="alert">
                    <ShieldCheck size={20} />
                    <div>
                      <strong>Тестовый код: {devCode}</strong>
                      <span>Для локального входа.</span>
                    </div>
                  </div>
                ) : null}
                {ttl ? <p className="muted">Код действует ещё {ttl} сек.</p> : null}
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
        </section>
      </div>
    </PageChrome>
  );
}
