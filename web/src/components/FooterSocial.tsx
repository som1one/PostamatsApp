"use client";

import { useEffect, useState } from "react";
import Image from "next/image";
import { Mail, X } from "lucide-react";
import { submitFeedback } from "@/shared/api/endpoints";

type FormStatus =
  | { kind: "idle" }
  | { kind: "submitting" }
  | { kind: "success" }
  | { kind: "error"; message: string };

/** Соцсети в подвале одним рядом + форма обратной связи по клику на почту. */
export function FooterSocial() {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [city, setCity] = useState("");
  const [email, setEmail] = useState("");
  const [question, setQuestion] = useState("");
  const [status, setStatus] = useState<FormStatus>({ kind: "idle" });

  useEffect(() => {
    if (!open) {
      return;
    }
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        setOpen(false);
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [open]);

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (status.kind === "submitting") {
      return;
    }
    const trimmedName = name.trim();
    const trimmedCity = city.trim();
    const trimmedEmail = email.trim();
    const trimmedQuestion = question.trim();
    if (!trimmedName || !trimmedCity || !trimmedEmail || !trimmedQuestion) {
      setStatus({ kind: "error", message: "Заполните все поля формы." });
      return;
    }
    setStatus({ kind: "submitting" });
    try {
      await submitFeedback({
        name: trimmedName,
        email: trimmedEmail,
        // Города нет отдельным полем в обращении, поэтому кладём его первой
        // строкой сообщения — так он виден и в админке, и в уведомлении.
        message: `Город: ${trimmedCity}\n\n${trimmedQuestion}`,
      });
      setStatus({ kind: "success" });
      setName("");
      setCity("");
      setEmail("");
      setQuestion("");
    } catch (error) {
      const message =
        error instanceof Error && error.message
          ? error.message
          : "Не удалось отправить вопрос. Попробуйте ещё раз.";
      setStatus({ kind: "error", message });
    }
  }

  const submitting = status.kind === "submitting";

  return (
    <>
      <div className="footer-social-row" aria-label="Мы на связи">
        <a
          className="footer-social-btn"
          href="https://vk.ru/naprokatberu"
          target="_blank"
          rel="noreferrer"
          aria-label="ВКонтакте"
          title="ВКонтакте"
        >
          <Image
            className="footer-social-img footer-social-img-vk"
            src="/vk-icon.svg"
            alt=""
            width={28}
            height={28}
          />
        </a>
        <a
          className="footer-social-btn"
          href="https://t.me/Naprokatberu"
          target="_blank"
          rel="noreferrer"
          aria-label="Telegram"
          title="Telegram"
        >
          <Image
            className="footer-social-img"
            src="/telegram-icon.svg"
            alt=""
            width={28}
            height={28}
          />
        </a>
        <span className="footer-social-btn" aria-label="Макс" title="Макс">
          <Image
            className="footer-social-img"
            src="/max-icon.png"
            alt=""
            width={28}
            height={28}
          />
        </span>
        <button
          type="button"
          className="footer-social-btn footer-social-btn-mail"
          onClick={() => {
            setStatus({ kind: "idle" });
            setOpen(true);
          }}
          aria-label="Написать нам"
          title="Написать нам"
        >
          <Mail size={20} />
        </button>
      </div>

      {open ? (
        <div
          className="modal-overlay"
          role="presentation"
          onClick={() => setOpen(false)}
        >
          <div
            className="modal-box footer-contact-modal"
            role="dialog"
            aria-modal="true"
            aria-label="Обратная связь"
            onClick={(event) => event.stopPropagation()}
          >
            <div className="footer-contact-head">
              <h2 className="modal-title">Написать нам</h2>
              <button
                type="button"
                className="button button-ghost icon-button"
                onClick={() => setOpen(false)}
                aria-label="Закрыть"
              >
                <X size={18} />
              </button>
            </div>
            <form className="footer-contact-form" onSubmit={handleSubmit} noValidate>
              <label className="field">
                <span>Имя</span>
                <input
                  className="input"
                  type="text"
                  value={name}
                  onChange={(event) => setName(event.target.value)}
                  placeholder="Ваше имя"
                  autoComplete="name"
                  maxLength={120}
                  required
                />
              </label>
              <label className="field">
                <span>Город</span>
                <input
                  className="input"
                  type="text"
                  value={city}
                  onChange={(event) => setCity(event.target.value)}
                  placeholder="Например, Великий Новгород"
                  maxLength={120}
                  required
                />
              </label>
              <label className="field">
                <span>Email для ответа</span>
                <input
                  className="input"
                  type="email"
                  value={email}
                  onChange={(event) => setEmail(event.target.value)}
                  placeholder="ваш@email"
                  autoComplete="email"
                  maxLength={255}
                  required
                />
              </label>
              <label className="field">
                <span>Вопрос</span>
                <textarea
                  className="textarea"
                  value={question}
                  onChange={(event) => setQuestion(event.target.value)}
                  placeholder="О чём хотите спросить?"
                  maxLength={4000}
                  rows={5}
                  required
                />
              </label>

              {status.kind === "error" ? (
                <p className="form-error" role="alert">
                  {status.message}
                </p>
              ) : null}
              {status.kind === "success" ? (
                <p className="form-success" role="status">
                  Спасибо! Вопрос отправлен — ответим вам на почту.
                </p>
              ) : null}

              <button
                type="submit"
                className="button button-primary"
                disabled={submitting}
              >
                {submitting ? "Отправляем..." : "Отправить"}
              </button>
            </form>
          </div>
        </div>
      ) : null}
    </>
  );
}
