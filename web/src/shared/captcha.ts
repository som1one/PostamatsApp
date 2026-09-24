import type { CaptchaChallenge } from "@/shared/api/types";

/**
 * Картинка-капча формы обратной связи — общая часть сайта и приложения:
 * состояние картинки и тексты «почему пока нельзя отправить». Файл
 * копируется в mobile/src/shared байт-идентично.
 *
 * Картинку и одноразовый токен отдаёт `GET /api/captcha` (fetchCaptcha);
 * после каждой отправки формы, удачной или нет, нужна новая картинка.
 */
export type CaptchaState =
  | { kind: "loading" }
  | { kind: "ready"; challenge: CaptchaChallenge }
  | { kind: "error" };

/** Сколько цифр на картинке — `CAPTCHA_LENGTH` в backend/utils/captcha.py. */
export const CAPTCHA_LENGTH = 5;

/** На картинке только цифры: всё остальное из ввода выкидываем сразу. */
export function cleanCaptchaAnswer(raw: string) {
  return raw.replace(/\D/g, "").slice(0, CAPTCHA_LENGTH);
}

/** Поля капчи для `submitFeedback` или текст, почему форму пока не отправить. */
export function solvedCaptcha(
  state: CaptchaState,
  answer: string,
): { captchaToken: string; captchaAnswer: string } | { error: string } {
  if (state.kind === "loading") {
    return { error: "Картинка с кодом ещё загружается — подождите секунду." };
  }
  if (state.kind === "error") {
    return { error: "Картинка с кодом не загрузилась. Обновите её кнопкой рядом с полем." };
  }
  if (!answer) {
    return { error: "Введите код с картинки." };
  }
  return { captchaToken: state.challenge.token, captchaAnswer: answer };
}
