import { ApiError } from "@/shared/api/client";

/**
 * Тексты ошибок авторизации по кодам бэкенда. Вынесено из AuthClient.tsx,
 * чтобы мобильное приложение показывало ровно те же сообщения (файл
 * копируется в mobile/src/shared байт-идентично; ApiError резолвится на
 * платформенный клиент через alias @/*).
 */
export const AUTH_ERROR_MESSAGES: Record<string, string> = {
  AUTH_PHONE_REQUIRED: "Введите номер телефона.",
  AUTH_PHONE_INVALID: "Введите корректный номер РФ или РБ.",
  AUTH_SMS_SEND_FAILED: "Не удалось отправить код. Попробуйте еще раз чуть позже.",
  AUTH_SMS_PROVIDER_ERROR: "Сервис подтверждения сейчас недоступен. Попробуйте еще раз чуть позже.",
  AUTH_RESEND_TOO_SOON: "Подождите немного перед повторной отправкой кода.",
  AUTH_SESSION_NOT_FOUND: "Сессия входа не найдена. Запросите код заново.",
  AUTH_SESSION_INACTIVE: "Этот код уже недействителен. Запросите новый.",
  AUTH_SESSION_EXPIRED: "Срок действия кода истек. Запросите новый.",
  AUTH_TOO_MANY_ATTEMPTS: "Слишком много попыток. Запросите новый код.",
  AUTH_CODE_INVALID: "Неверный код. Попробуйте еще раз.",
  AUTH_ACCOUNT_BLOCKED: "Аккаунт заблокирован. Обратитесь в поддержку.",
  AUTH_UNAUTHORIZED: "Сессия входа недействительна. Попробуйте войти заново.",
};

export function resolveAuthErrorMessage(error: unknown, fallback: string): string {
  if (error instanceof ApiError) {
    return AUTH_ERROR_MESSAGES[error.code || ""] || fallback;
  }
  return fallback;
}
