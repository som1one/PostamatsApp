"use client";

import { useCallback, useEffect, useId, useRef, useState } from "react";
import { RefreshCw } from "lucide-react";
import { fetchCaptcha } from "@/shared/api/endpoints";
import {
  CAPTCHA_LENGTH,
  cleanCaptchaAnswer,
  solvedCaptcha as solvedCaptchaState,
  type CaptchaState,
} from "@/shared/captcha";

export type CaptchaControl = ReturnType<typeof useCaptcha>;

/**
 * Картинка-капча формы обратной связи. Токен одноразовый, поэтому после
 * каждой отправки формы — удачной или нет — нужен `reload()`.
 * `enabled` нужен модалке в подвале: подвал есть на каждой странице, а
 * картинку стоит тянуть, только когда форму открыли.
 */
export function useCaptcha(enabled = true) {
  const [state, setState] = useState<CaptchaState>({ kind: "loading" });
  const [answer, setAnswer] = useState("");
  const latestRequest = useRef(0);

  const reload = useCallback(async () => {
    const request = ++latestRequest.current;
    setState({ kind: "loading" });
    setAnswer("");
    try {
      const challenge = await fetchCaptcha();
      if (request === latestRequest.current) {
        setState({ kind: "ready", challenge });
      }
    } catch {
      if (request === latestRequest.current) {
        setState({ kind: "error" });
      }
    }
  }, []);

  useEffect(() => {
    if (enabled) {
      void reload();
    }
  }, [enabled, reload]);

  return { state, answer, setAnswer, reload };
}

/** Поля капчи для `submitFeedback` или текст, почему форму пока не отправить. */
export function solvedCaptcha({ state, answer }: CaptchaControl) {
  return solvedCaptchaState(state, answer);
}

export function CaptchaField({ captcha }: { captcha: CaptchaControl }) {
  const inputId = useId();
  const { state, answer, setAnswer, reload } = captcha;
  const loading = state.kind === "loading";

  return (
    <div className="field">
      <label className="field-label" htmlFor={inputId}>
        Код с картинки
      </label>
      <div className="captcha-row">
        <div className="captcha-image" aria-busy={loading}>
          {state.kind === "ready" ? (
            <img
              src={state.challenge.image}
              alt="Код из пяти цифр"
              width={150}
              height={50}
              draggable={false}
            />
          ) : (
            <p className="captcha-placeholder">{loading ? "Загружаем…" : "Не загрузилась"}</p>
          )}
        </div>
        <button
          type="button"
          className="button button-secondary icon-button captcha-refresh"
          onClick={() => void reload()}
          disabled={loading}
          aria-label="Показать другой код"
          title="Показать другой код"
        >
          <RefreshCw size={18} aria-hidden="true" />
        </button>
        <input
          id={inputId}
          className="input captcha-input"
          type="text"
          inputMode="numeric"
          pattern="[0-9]*"
          autoComplete="off"
          // Без maxLength: браузер обрезал бы вставку «5 8 3 3 4» до пробелов
          // раньше, чем мы выкинем лишнее, — длину держит cleanCaptchaAnswer.
          value={answer}
          onChange={(event) => setAnswer(cleanCaptchaAnswer(event.target.value))}
          placeholder={`${CAPTCHA_LENGTH} цифр`}
          required
        />
      </div>
    </div>
  );
}
