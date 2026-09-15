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
export const PHOTO_UNREADABLE_MESSAGE =
  "Не получилось прочитать снимок. Сделайте фото ещё раз — подойдут JPG, PNG или WEBP.";

/** Форматы фото, которые принимает бэкенд (`ALLOWED_IMAGE_TYPES` в uploads_utils.py). */
export const UPLOADABLE_IMAGE_TYPES: readonly string[] = ["image/jpeg", "image/png", "image/webp"];

/**
 * Для каких сценариев пишем текст ошибки: верификация просит «отправить документы»,
 * а в остальных местах (фото при возврате) речь только о снимке.
 */
export type UploadMessageContext = "documents" | "photo";

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

export function uploadErrorMessage(
  status: number,
  code: string | null,
  context: UploadMessageContext = "documents",
) {
  const retryHint =
    context === "documents" ? "Отправьте документы ещё раз." : "Отправьте фото ещё раз.";
  switch (code) {
    case "INVALID_UPLOAD_TOKEN":
      return `Ссылка на загрузку устарела. ${retryHint}`;
    case "INVALID_MIME_TYPE":
      return "Такой формат не подходит. Загрузите фото в JPG, PNG или WEBP.";
    case "EMPTY_UPLOAD":
      return "Файл оказался пустым. Выберите снимок ещё раз.";
    // Содержимое не похоже на JPG/PNG/WEBP, хотя тип заявлен как фото.
    case "INVALID_FILE_CONTENT":
      return "Файл не похож на фото. Выберите снимок в JPG, PNG или WEBP.";
    case "FILE_TOO_LARGE":
      return FILE_TOO_LARGE_MESSAGE;
    // Файл уже приложен к отчёту — перезаписывать его сервер не даёт.
    case "MEDIA_FILE_LOCKED":
      return `Этот снимок уже отправлен. ${retryHint}`;
    case "MEDIA_FILE_NOT_FOUND":
      return `Загрузка не найдена на сервере. ${retryHint}`;
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

// ── Фото с камеры: конвертация, миниатюра и PUT с прогрессом ─────────────────

export type PreparedPhoto = {
  /** Файл, который можно объявлять в presign и отправлять PUT-ом. */
  file: File;
  /** Маленькое JPEG-превью (data URL) — переживает перезагрузку страницы. */
  thumbnail: string | null;
};

type DecodedImage = {
  width: number;
  height: number;
  source: CanvasImageSource;
  close: () => void;
};

function canUseCanvas() {
  return typeof document !== "undefined" && typeof File === "function";
}

/** Бэкенд примет только jpeg/png/webp; пустой MIME (бывает у HEIC на Android) — тоже нет. */
export function needsImageConversion(file: File) {
  return !UPLOADABLE_IMAGE_TYPES.includes(file.type);
}

async function decodeWithBitmap(file: File): Promise<DecodedImage | null> {
  if (typeof createImageBitmap !== "function") {
    return null;
  }
  try {
    const bitmap = await createImageBitmap(file, { imageOrientation: "from-image" });
    return {
      width: bitmap.width,
      height: bitmap.height,
      source: bitmap,
      close: () => bitmap.close(),
    };
  } catch {
    return null;
  }
}

// Safari показывает HEIC в <img>, но не всегда отдаёт его в createImageBitmap —
// поэтому второй заход через обычный Image.
async function decodeWithImageElement(file: File): Promise<DecodedImage | null> {
  if (typeof Image !== "function" || typeof URL === "undefined" || !URL.createObjectURL) {
    return null;
  }
  const objectUrl = URL.createObjectURL(file);
  try {
    const image = new Image();
    image.decoding = "async";
    image.src = objectUrl;
    await image.decode();
    if (!image.naturalWidth || !image.naturalHeight) {
      URL.revokeObjectURL(objectUrl);
      return null;
    }
    return {
      width: image.naturalWidth,
      height: image.naturalHeight,
      source: image,
      close: () => URL.revokeObjectURL(objectUrl),
    };
  } catch {
    URL.revokeObjectURL(objectUrl);
    return null;
  }
}

function drawToCanvas(image: DecodedImage, maxDimension: number) {
  const longestSide = Math.max(image.width, image.height);
  const scale = longestSide > maxDimension ? maxDimension / longestSide : 1;
  const canvas = document.createElement("canvas");
  canvas.width = Math.max(1, Math.round(image.width * scale));
  canvas.height = Math.max(1, Math.round(image.height * scale));
  const context = canvas.getContext("2d");
  if (!context) {
    return null;
  }
  context.drawImage(image.source, 0, 0, canvas.width, canvas.height);
  return canvas;
}

function canvasToJpeg(canvas: HTMLCanvasElement, quality: number) {
  return new Promise<Blob | null>((resolve) => {
    canvas.toBlob((result) => resolve(result), "image/jpeg", quality);
  });
}

/**
 * Готовит снимок с камеры к загрузке за одно декодирование:
 * - HEIC, пустой или неизвестный MIME всегда перегоняем в JPEG — иначе бэкенд
 *   отклонит файл или сохранит картинку, которую операторы не откроют;
 * - тяжёлые кадры ужимаем до 2000 px (как `compressImageForUpload`);
 * - по желанию рисуем маленькую миниатюру для восстановления после перезагрузки.
 * Если перегнать неподходящий формат не вышло — бросаем понятную ошибку, а не
 * отправляем файл, который сервер всё равно не примет.
 */
export async function preparePhotoForUpload(
  file: File,
  options: { thumbnailSize?: number; maxDimension?: number } = {},
): Promise<PreparedPhoto> {
  const mustConvert = needsImageConversion(file);
  const shouldDownscale = file.size > COMPRESS_ABOVE_BYTES;
  const thumbnailSize = options.thumbnailSize ?? 0;

  if (!canUseCanvas()) {
    if (mustConvert) {
      throw new Error(PHOTO_UNREADABLE_MESSAGE);
    }
    return { file, thumbnail: null };
  }
  if (!mustConvert && !shouldDownscale && thumbnailSize <= 0) {
    return { file, thumbnail: null };
  }

  const image = (await decodeWithBitmap(file)) ?? (await decodeWithImageElement(file));
  if (!image) {
    if (mustConvert) {
      throw new Error(PHOTO_UNREADABLE_MESSAGE);
    }
    return { file, thumbnail: null };
  }

  try {
    let output = file;
    if (mustConvert || shouldDownscale) {
      const canvas = drawToCanvas(image, options.maxDimension ?? MAX_IMAGE_DIMENSION);
      const blob = canvas ? await canvasToJpeg(canvas, JPEG_QUALITY) : null;
      if (blob && (mustConvert || blob.size < file.size)) {
        output = new File([blob], toJpegName(file.name), {
          type: "image/jpeg",
          lastModified: file.lastModified,
        });
      } else if (mustConvert) {
        throw new Error(PHOTO_UNREADABLE_MESSAGE);
      }
    }

    let thumbnail: string | null = null;
    if (thumbnailSize > 0) {
      try {
        const thumbCanvas = drawToCanvas(image, thumbnailSize);
        thumbnail = thumbCanvas ? thumbCanvas.toDataURL("image/jpeg", 0.6) : null;
      } catch {
        thumbnail = null;
      }
    }

    return { file: output, thumbnail };
  } finally {
    image.close();
  }
}

/**
 * Одна попытка PUT дольше этого — соединение считаем мёртвым и повторяем.
 * Снимок до 1.5 МБ уходит без сжатия: даже на слабом 3G это меньше минуты,
 * а молчаливое зависание раньше ловит сторож прогресса.
 */
export const UPLOAD_ATTEMPT_TIMEOUT_MS = 120_000;
/**
 * Столько без единого события прогресса — соединение «зависло» молча
 * (переход Wi-Fi → LTE, обрыв NAT): XHR сам не упадёт, обрываем и повторяем.
 */
export const UPLOAD_STALL_TIMEOUT_MS = 25_000;

/** Отправку отменил сам пользователь (удалил или переснял кадр) — это не ошибка сети. */
export class UploadAbortedError extends Error {
  constructor() {
    super("Отправка фото отменена.");
    this.name = "AbortError";
  }
}

export function isUploadAborted(error: unknown) {
  return error instanceof Error && error.name === "AbortError";
}

/**
 * Ограничивает по времени шаг загрузки, который сам не умеет в AbortSignal
 * (presign через fetch, декодирование снимка). По таймауту — понятная ошибка,
 * по отмене — UploadAbortedError. Сам шаг может доработать в фоне: его
 * результат просто никто не ждёт.
 */
export function withUploadDeadline<T>(
  task: Promise<T>,
  options: { timeoutMs: number; signal?: AbortSignal; timeoutMessage?: string },
): Promise<T> {
  const { timeoutMs, signal } = options;
  if (signal?.aborted) {
    task.catch(() => undefined);
    return Promise.reject(new UploadAbortedError());
  }
  return new Promise<T>((resolve, reject) => {
    let settled = false;
    const finish = (callback: () => void) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      signal?.removeEventListener("abort", handleAbort);
      callback();
    };
    const handleAbort = () => finish(() => reject(new UploadAbortedError()));
    const timer = setTimeout(
      () => finish(() => reject(new Error(options.timeoutMessage ?? UPLOAD_NETWORK_MESSAGE))),
      timeoutMs,
    );
    signal?.addEventListener("abort", handleAbort, { once: true });
    task.then(
      (value) => finish(() => resolve(value)),
      (error: unknown) => finish(() => reject(error)),
    );
  });
}

/** Пауза перед повтором, которую можно прервать отменой. true — отменили. */
function waitBeforeRetry(ms: number, signal?: AbortSignal) {
  if (signal?.aborted) {
    return Promise.resolve(true);
  }
  return new Promise<boolean>((resolve) => {
    const handleAbort = () => {
      clearTimeout(timer);
      resolve(true);
    };
    const timer = setTimeout(() => {
      signal?.removeEventListener("abort", handleAbort);
      resolve(false);
    }, ms);
    signal?.addEventListener("abort", handleAbort, { once: true });
  });
}

type SendOutcome =
  | { kind: "network" }
  | { kind: "aborted" }
  | { kind: "response"; status: number; code: string | null };

type SendOptions = {
  onProgress?: (fraction: number) => void;
  signal?: AbortSignal;
  timeoutMs: number;
  stallMs: number;
};

function readDetailCodeFromText(text: string) {
  try {
    const detail = (JSON.parse(text) as { detail?: unknown } | null)?.detail;
    return typeof detail === "string" ? detail : null;
  } catch {
    return null;
  }
}

function sendWithXhr(
  targetUrl: string,
  presign: PresignUploadResponse,
  file: File,
  options: SendOptions,
) {
  const { onProgress, signal, timeoutMs, stallMs } = options;
  return new Promise<SendOutcome>((resolve) => {
    if (signal?.aborted) {
      resolve({ kind: "aborted" });
      return;
    }
    const xhr = new XMLHttpRequest();
    let settled = false;
    let stallTimer: ReturnType<typeof setTimeout> | undefined;

    const finish = (outcome: SendOutcome) => {
      if (settled) return;
      settled = true;
      clearTimeout(stallTimer);
      signal?.removeEventListener("abort", handleAbort);
      resolve(outcome);
    };
    const handleAbort = () => {
      finish({ kind: "aborted" });
      xhr.abort();
    };
    // Сторож «зависания»: каждое событие прогресса отодвигает его. Сработал —
    // обрываем запрос как сетевой сбой, дальше решают повторы.
    const armStall = () => {
      clearTimeout(stallTimer);
      if (stallMs > 0 && !settled) {
        stallTimer = setTimeout(() => {
          finish({ kind: "network" });
          xhr.abort();
        }, stallMs);
      }
    };

    xhr.open(presign.method || "PUT", targetUrl);
    xhr.timeout = timeoutMs;
    for (const [name, value] of Object.entries(presign.headers || {})) {
      xhr.setRequestHeader(name, value);
    }
    const upload = xhr.upload;
    if (upload) {
      upload.onprogress = (event) => {
        armStall();
        if (onProgress && event.lengthComputable && event.total > 0) {
          onProgress(Math.min(1, event.loaded / event.total));
        }
      };
      // Тело ушло целиком — дальше ждём ответ сервера, его стережёт xhr.timeout.
      upload.onload = () => clearTimeout(stallTimer);
    }
    xhr.onload = () => {
      // status 0 в onload — тоже обрыв, а не ответ сервера.
      if (!xhr.status) {
        finish({ kind: "network" });
        return;
      }
      const ok = xhr.status >= 200 && xhr.status < 300;
      finish({
        kind: "response",
        status: xhr.status,
        code: ok ? null : readDetailCodeFromText(xhr.responseText),
      });
    };
    xhr.onerror = () => finish({ kind: "network" });
    xhr.ontimeout = () => finish({ kind: "network" });
    xhr.onabort = () => finish(signal?.aborted ? { kind: "aborted" } : { kind: "network" });
    signal?.addEventListener("abort", handleAbort, { once: true });
    xhr.send(file);
    // Без xhr.upload событий прогресса не будет — не за чем и следить.
    if (upload) {
      armStall();
    }
  });
}

async function sendWithFetch(
  targetUrl: string,
  presign: PresignUploadResponse,
  file: File,
  options: SendOptions,
): Promise<SendOutcome> {
  const { signal, timeoutMs } = options;
  if (signal?.aborted) {
    return { kind: "aborted" };
  }
  const controller = typeof AbortController === "function" ? new AbortController() : null;
  const abort = () => controller?.abort();
  const timer = setTimeout(abort, timeoutMs);
  signal?.addEventListener("abort", abort, { once: true });
  let response: Response;
  try {
    response = await fetch(targetUrl, {
      method: presign.method || "PUT",
      headers: presign.headers,
      body: file,
      signal: controller?.signal,
    });
  } catch {
    return signal?.aborted ? { kind: "aborted" } : { kind: "network" };
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener("abort", abort);
  }
  return {
    kind: "response",
    status: response.status,
    code: response.ok ? null : await readDetailCode(response),
  };
}

/**
 * То же, что `putPresignedFile` (3 попытки, повтор обрывов и 5xx, без повтора
 * 4xx), но через XMLHttpRequest — fetch не умеет сообщать прогресс отправки.
 * Каждая попытка ограничена по времени и по «тишине» без прогресса, так что
 * зависшая сеть превращается в ошибку, а не в вечные «Отправляем… 40%».
 * `signal` отменяет отправку (UploadAbortedError, без повторов).
 * Без XHR (тесты, экзотические окружения) шлём fetch-ем и отдаём прогресс 1
 * по завершении.
 */
export async function putPresignedFileWithProgress(
  presign: PresignUploadResponse,
  file: File,
  options: {
    onProgress?: (fraction: number) => void;
    context?: UploadMessageContext;
    signal?: AbortSignal;
    attemptTimeoutMs?: number;
    stallTimeoutMs?: number;
  } = {},
) {
  const targetUrl = resolveUploadUrl(presign.uploadUrl);
  const context = options.context ?? "documents";
  const hasXhr = typeof XMLHttpRequest === "function";
  const { signal } = options;
  const sendOptions: SendOptions = {
    onProgress: options.onProgress,
    signal,
    timeoutMs: options.attemptTimeoutMs ?? UPLOAD_ATTEMPT_TIMEOUT_MS,
    stallMs: options.stallTimeoutMs ?? UPLOAD_STALL_TIMEOUT_MS,
  };

  for (let attempt = 1; attempt <= UPLOAD_ATTEMPTS; attempt += 1) {
    if (signal?.aborted) {
      throw new UploadAbortedError();
    }
    const isLastAttempt = attempt === UPLOAD_ATTEMPTS;
    options.onProgress?.(0);
    const outcome = hasXhr
      ? await sendWithXhr(targetUrl, presign, file, sendOptions)
      : await sendWithFetch(targetUrl, presign, file, sendOptions);

    if (outcome.kind === "aborted") {
      throw new UploadAbortedError();
    }
    if (outcome.kind === "network") {
      if (isLastAttempt) {
        throw new Error(UPLOAD_NETWORK_MESSAGE);
      }
      if (await waitBeforeRetry(RETRY_DELAY_MS * attempt, signal)) {
        throw new UploadAbortedError();
      }
      continue;
    }

    if (outcome.status >= 200 && outcome.status < 300) {
      options.onProgress?.(1);
      return;
    }
    if (outcome.status >= 500 && !isLastAttempt) {
      if (await waitBeforeRetry(RETRY_DELAY_MS * attempt, signal)) {
        throw new UploadAbortedError();
      }
      continue;
    }
    throw new Error(uploadErrorMessage(outcome.status, outcome.code, context));
  }

  throw new Error(UPLOAD_NETWORK_MESSAGE);
}
