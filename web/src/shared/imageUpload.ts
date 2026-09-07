import { apiBaseUrl } from "@/shared/api/client";
import type { PresignUploadResponse } from "@/shared/api/types";

/** Столько же принимает бэкенд (`MAX_FILE_SIZE_IMAGE` в uploads_utils.py). */
export const MAX_UPLOAD_BYTES = 10 * 1024 * 1024;

// Снимок с телефона весит 5–12 МБ. Отдать его одним PUT на мобильном интернете
// — это минуты в одном запросе: любое переключение сети или блокировка экрана
// рвут соединение, fetch падает с TypeError «Failed to fetch», и заявка на
// верификацию не уходит. Поэтому кадр ужимаем в браузере (обычно до ~0.3–0.7 МБ)
// и повторяем PUT, если сеть моргнула.
const COMPRESS_ABOVE_BYTES = 1.5 * 1024 * 1024;
const MAX_IMAGE_DIMENSION = 2000;
const JPEG_QUALITY = 0.82;
const UPLOAD_ATTEMPTS = 3;
const RETRY_DELAY_MS = 800;

export const UPLOAD_NETWORK_MESSAGE =
  "Не удалось загрузить фото: соединение прервалось. Проверьте интернет и попробуйте ещё раз.";
export const FILE_TOO_LARGE_MESSAGE =
  "Фото больше 10 МБ. Сделайте снимок меньшего размера или уменьшите качество.";

function delay(ms: number) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function canCompressInBrowser() {
  return (
    typeof document !== "undefined" &&
    typeof createImageBitmap === "function" &&
    typeof File === "function"
  );
}

function toJpegName(name: string) {
  const base = name.replace(/\.[^.]+$/, "").trim();
  return `${base || "photo"}.jpg`;
}

/**
 * Уменьшает снимок до 2000 px по длинной стороне и пережимает в JPEG.
 * Любая осечка (HEIC, который браузер не декодирует; отсутствие canvas) — это не
 * ошибка: возвращаем исходный файл, дальше решает бэкенд.
 */
export async function compressImageForUpload(file: File): Promise<File> {
  if (file.size <= COMPRESS_ABOVE_BYTES || !file.type.startsWith("image/")) {
    return file;
  }
  if (!canCompressInBrowser()) {
    return file;
  }

  try {
    const bitmap = await createImageBitmap(file, { imageOrientation: "from-image" });
    const longestSide = Math.max(bitmap.width, bitmap.height);
    const scale = longestSide > MAX_IMAGE_DIMENSION ? MAX_IMAGE_DIMENSION / longestSide : 1;
    const width = Math.max(1, Math.round(bitmap.width * scale));
    const height = Math.max(1, Math.round(bitmap.height * scale));

    const canvas = document.createElement("canvas");
    canvas.width = width;
    canvas.height = height;
    const context = canvas.getContext("2d");
    if (!context) {
      bitmap.close();
      return file;
    }
    context.drawImage(bitmap, 0, 0, width, height);
    bitmap.close();

    const blob = await new Promise<Blob | null>((resolve) => {
      canvas.toBlob((result) => resolve(result), "image/jpeg", JPEG_QUALITY);
    });
    if (!blob || blob.size >= file.size) {
      return file;
    }

    return new File([blob], toJpegName(file.name), {
      type: "image/jpeg",
      lastModified: file.lastModified,
    });
  } catch {
    return file;
  }
}

/** Бэкенд отдаёт относительный uploadUrl, чтобы reverse-proxy не срезал префикс. */
export function resolveUploadUrl(uploadUrl: string) {
  if (/^https?:\/\//i.test(uploadUrl)) {
    return uploadUrl;
  }
  return `${apiBaseUrl()}${uploadUrl.startsWith("/") ? "" : "/"}${uploadUrl}`;
}

async function readDetailCode(response: Response) {
  try {
    const payload = await response.json();
    const detail = (payload as { detail?: unknown } | null)?.detail;
    return typeof detail === "string" ? detail : null;
  } catch {
    return null;
  }
}

export function uploadErrorMessage(status: number, code: string | null) {
  switch (code) {
    case "INVALID_UPLOAD_TOKEN":
      return "Ссылка на загрузку устарела. Отправьте документы ещё раз.";
    case "INVALID_MIME_TYPE":
      return "Такой формат не подходит. Загрузите фото в JPG, PNG или WEBP.";
    case "EMPTY_UPLOAD":
      return "Файл оказался пустым. Выберите снимок ещё раз.";
    case "MEDIA_FILE_NOT_FOUND":
      return "Загрузка не найдена на сервере. Отправьте документы ещё раз.";
    default:
      break;
  }
  if (status === 413) {
    return FILE_TOO_LARGE_MESSAGE;
  }
  if (status >= 500) {
    return "Сервер не смог сохранить фото. Попробуйте ещё раз через минуту.";
  }
  return `Не удалось загрузить фото (ошибка ${status}). Попробуйте ещё раз.`;
}

/**
 * PUT по подписанной ссылке с повторами. Повтор безопасен: токен presign живёт
 * 15 минут, а запись идёт в тот же file_key — сервер просто перезаписывает файл.
 */
export async function putPresignedFile(presign: PresignUploadResponse, file: File) {
  const targetUrl = resolveUploadUrl(presign.uploadUrl);

  for (let attempt = 1; attempt <= UPLOAD_ATTEMPTS; attempt += 1) {
    const isLastAttempt = attempt === UPLOAD_ATTEMPTS;
    let response: Response;
    try {
      response = await fetch(targetUrl, {
        method: presign.method || "PUT",
        headers: presign.headers,
        body: file,
      });
    } catch {
      // Сюда прилетает то самое «Failed to fetch»: обрыв соединения, а не ответ
      // сервера. Пользователю такое показывать нельзя — либо повтор, либо текст.
      if (isLastAttempt) {
        throw new Error(UPLOAD_NETWORK_MESSAGE);
      }
      await delay(RETRY_DELAY_MS * attempt);
      continue;
    }

    if (response.ok) {
      return;
    }

    const code = await readDetailCode(response);
    if (response.status >= 500 && !isLastAttempt) {
      await delay(RETRY_DELAY_MS * attempt);
      continue;
    }
    throw new Error(uploadErrorMessage(response.status, code));
  }

  throw new Error(UPLOAD_NETWORK_MESSAGE);
}
