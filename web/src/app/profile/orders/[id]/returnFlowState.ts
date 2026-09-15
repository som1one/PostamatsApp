// Чистая логика экрана возврата с фото: какой режим показать, какие шаги
// пройдены, как объяснить ошибку и как пережить перезагрузку страницы после
// камеры (iOS Safari выгружает вкладку, пока открыта камера). Без JSX и DOM —
// всё покрыто vitest-тестами в node.

import { ApiError } from "@/shared/api/client";
import type {
  ActiveReturnRequest,
  RentalDetail,
  RentalListItem,
  ReturnReport,
} from "@/shared/api/types";
import { FILE_TOO_LARGE_MESSAGE, UPLOAD_NETWORK_MESSAGE } from "@/shared/imageUpload";

/** Столько ракурсов принимает бэкенд (`RETURN_PHOTOS_MAX`), если отчёт не сказал иначе. */
export const RETURN_PHOTOS_DEFAULT_MAX = 4;
/** Лимит комментария на бэкенде (`RETURN_PHOTO_NOTE_MAX`). */
export const RETURN_NOTE_MAX = 500;
/** Пока идёт возврат, опрашиваем аренду: дверца может завершить его раньше кнопки. */
export const RETURN_POLL_INTERVAL_MS = 8_000;
/**
 * Часы телефона бывают впереди сервера: окно досылки прячем чуть позже
 * attachPhotosUntil, а последнее слово всё равно за сервером (WINDOW_CLOSED).
 */
export const RETURN_ATTACH_GRACE_MS = 60_000;
/** Столько ждём presign: fetch сам по себе не сдаётся на зависшем соединении. */
export const RETURN_PRESIGN_TIMEOUT_MS = 30_000;
/** Декодирование и сжатие снимка: если браузер завис на HEIC — это ошибка, а не вечное «Готовим…». */
export const RETURN_PREPARE_TIMEOUT_MS = 45_000;
/** Камера так и не дала снимок (запрет доступа, WebView) — через минуту предлагаем запасной выход. */
export const RETURN_CAMERA_STUCK_MS = 60_000;

// ── Режим экрана ─────────────────────────────────────────────────────────────

/**
 * - `in_progress` — возврат начат: PIN → фото → закрыть дверцу;
 * - `late` — возврат уже принят (дверцей или без фото), но фото ещё можно дослать;
 * - `receipt` — отчёт с фото отправлен или окно досылки закрылось — квитанция;
 * - `none` — блок возврата не нужен.
 */
export type ReturnFlowMode = "none" | "in_progress" | "late" | "receipt";

type ReturnSnapshot = Pick<RentalListItem, "status" | "returnReport">;

function parseTime(value?: string | null) {
  if (!value) return Number.NaN;
  return new Date(value).getTime();
}

export function deriveReturnFlowMode(
  rental: ReturnSnapshot,
  nowMs: number,
  options: {
    /** Фото в пути или идёт отправка — не прячем блок по часам клиента, пусть ответит сервер. */
    holdLate?: boolean;
  } = {},
): ReturnFlowMode {
  if (rental.status === "return_in_progress") {
    return "in_progress";
  }
  const report = rental.returnReport;
  if (!report) {
    return "none";
  }
  // Отчёт без фото (подтвердили без снимка или только с комментарием) не
  // закрывает досылку: пока сервер разрешает, предлагаем «Дослать фото».
  const hasPhotos = (report.photos?.length ?? 0) > 0;
  if (rental.status === "completed" && report.canAttachPhotos && !hasPhotos) {
    const untilMs = parseTime(report.attachPhotosUntil);
    const expired = !Number.isNaN(untilMs) && untilMs + RETURN_ATTACH_GRACE_MS <= nowMs;
    if (!expired || options.holdLate) {
      return "late";
    }
  }
  if (report.submittedAt) {
    return "receipt";
  }
  return "none";
}

/** Почему блок возврата пропал — объясняем, а не молча убираем степпер. */
export type ReturnClosedNotice = { tone: "neutral" | "ok" | "warn"; title: string; text: string };

export function describeReturnClosed(
  previousMode: ReturnFlowMode,
  status: string,
): ReturnClosedNotice | null {
  if (previousMode === "late") {
    return {
      tone: "neutral",
      title: "Время, чтобы дослать фото, вышло",
      text: "Сам возврат принят — ничего делать не нужно.",
    };
  }
  if (previousMode !== "in_progress") {
    return null;
  }
  if (status === "completed") {
    return {
      tone: "ok",
      title: "Возврат завершён",
      text: "Постамат принял вещь. Ничего делать не нужно.",
    };
  }
  if (status === "incident") {
    return {
      tone: "warn",
      title: "Возврат не подтвердился",
      text:
        "Постамат не сообщил, что вещь в ячейке. Мы проверим ячейку и свяжемся с вами. Если вещь ещё у вас — напишите в поддержку.",
    };
  }
  if (status === "active" || status === "overdue") {
    return {
      tone: "warn",
      title: "Код возврата больше не действует",
      text: "Оформите возврат заново — кнопка ниже в карточке заказа.",
    };
  }
  return {
    tone: "warn",
    title: "Возврат прерван",
    text: "Статус заказа изменился. Если что-то выглядит не так, напишите в поддержку.",
  };
}

export function resolveMaxPhotos(report?: ReturnReport | null) {
  const value = report?.maxPhotos;
  return typeof value === "number" && Number.isFinite(value) && value >= 1
    ? Math.floor(value)
    : RETURN_PHOTOS_DEFAULT_MAX;
}

/** Кто завершил возврат — от этого зависит текст «поздней» досылки фото. */
export type ReturnCompletedBy = "locker" | "user" | "unknown";

export function getReturnCompletedBy(events?: RentalDetail["events"] | null): ReturnCompletedBy {
  if (!events?.length) {
    return "unknown";
  }
  for (let index = events.length - 1; index >= 0; index -= 1) {
    const event = events[index];
    if (event.eventType === "return_completed") {
      return event.source === "user" ? "user" : "locker";
    }
  }
  return "unknown";
}

/**
 * PIN и ячейка живут на бэке: сначала list-элемент, потом detail, и только
 * потом локальный ответ return-request (он теряется при перезагрузке).
 */
export function pickReturnRequest(
  ...candidates: Array<Partial<ActiveReturnRequest> | null | undefined>
): { pin: string | null; cellLabel: string | null; lockerName: string | null; expiresAt: string | null } {
  const pick = (key: "pin" | "cellLabel" | "lockerName" | "expiresAt") => {
    for (const candidate of candidates) {
      const value = candidate?.[key];
      if (typeof value === "string" && value.trim()) {
        return value.trim();
      }
    }
    return null;
  };
  return {
    pin: pick("pin"),
    cellLabel: pick("cellLabel"),
    lockerName: pick("lockerName"),
    expiresAt: pick("expiresAt"),
  };
}

/** Свежий detail (опрос) поверх list-элемента: поля, которых старый бэкенд не прислал, не затираем. */
export function mergeRentalDetailIntoListItem(
  item: RentalListItem,
  detail: RentalDetail,
): RentalListItem {
  return {
    ...item,
    status: detail.status,
    pickupPin: detail.pickupPin ?? item.pickupPin,
    startsAt: detail.startsAt ?? item.startsAt,
    pickupExpiresAt: detail.pickupExpiresAt ?? item.pickupExpiresAt,
    plannedEndAt: detail.plannedEndAt ?? item.plannedEndAt,
    actualEndAt: detail.actualEndAt ?? item.actualEndAt,
    returnRequest: detail.returnRequest === undefined ? item.returnRequest : detail.returnRequest,
    returnReport: detail.returnReport === undefined ? item.returnReport : detail.returnReport,
  };
}

export type ConfirmReturnResult = {
  rental: { id: string; status: string };
  returnReport?: ReturnReport | null;
};

/** Ответ confirm-return сразу применяем к заказу — квитанция появляется без перезагрузки. */
export function applyConfirmReturnResult(
  item: RentalListItem,
  result: ConfirmReturnResult,
): RentalListItem {
  const status = result.rental?.status || item.status;
  return {
    ...item,
    status,
    returnRequest: status === "return_in_progress" ? item.returnRequest : null,
    returnReport: result.returnReport === undefined ? item.returnReport : result.returnReport,
  };
}

// ── Шаги ─────────────────────────────────────────────────────────────────────

export type ReturnStepState = "done" | "current" | "upcoming";
export type ReturnStepView = { state: ReturnStepState; expanded: boolean };
export type ReturnStepsView = {
  open: ReturnStepView;
  shoot: ReturnStepView;
  close: ReturnStepView;
};

export type ReturnShotStatus = "preparing" | "uploading" | "uploaded" | "failed";

export function countShots(shots: ReadonlyArray<{ status: ReturnShotStatus }>) {
  let uploaded = 0;
  let pending = 0;
  let failed = 0;
  for (const shot of shots) {
    if (shot.status === "uploaded") uploaded += 1;
    else if (shot.status === "failed") failed += 1;
    else pending += 1;
  }
  return { uploaded, pending, failed, total: shots.length };
}

/**
 * ① открыть ячейку → ② сфотографировать → ③ закрыть и подтвердить.
 * Пройденный первый шаг сворачивается в строку; шаг с фото остаётся раскрытым,
 * чтобы можно было доснять ракурс; третий раскрыт сразу после открытия ячейки,
 * но «текущим» становится только с загруженным фото.
 */
export function deriveReturnSteps(input: {
  cellOpened: boolean;
  shots: ReadonlyArray<{ status: ReturnShotStatus }>;
}): ReturnStepsView {
  const counts = countShots(input.shots);
  const opened = input.cellOpened || counts.total > 0;
  if (!opened) {
    return {
      open: { state: "current", expanded: true },
      shoot: { state: "upcoming", expanded: false },
      close: { state: "upcoming", expanded: false },
    };
  }
  const hasPhoto = counts.uploaded > 0;
  return {
    open: { state: "done", expanded: false },
    shoot: { state: hasPhoto ? "done" : "current", expanded: true },
    close: { state: hasPhoto ? "current" : "upcoming", expanded: true },
  };
}

export type ReturnSubmitBlock = "no_photo" | "uploading" | null;

/** Кнопка подтверждения: нужна хотя бы одна загруженная фотография и ни одной в пути. */
export function getReturnSubmitState(shots: ReadonlyArray<{ status: ReturnShotStatus }>) {
  const counts = countShots(shots);
  let blockedBy: ReturnSubmitBlock = null;
  if (counts.pending > 0) {
    blockedBy = "uploading";
  } else if (counts.uploaded === 0) {
    blockedBy = "no_photo";
  }
  return { canSubmit: blockedBy === null, blockedBy, ...counts };
}

/**
 * Запасной выход «Не получается отправить фото»: после ошибки загрузки, после
 * пустого снимка или если камера за минуту так и не дала ни одного фото
 * (запрет доступа в Safari или WebView — change-события может не быть вовсе).
 */
export function shouldOfferNoPhotoFallback(input: {
  photoTrouble: boolean;
  firstCaptureAt: number | null;
  uploaded: number;
  nowMs: number;
}) {
  if (input.photoTrouble) {
    return true;
  }
  return (
    input.firstCaptureAt !== null &&
    input.uploaded === 0 &&
    input.nowMs - input.firstCaptureAt >= RETURN_CAMERA_STUCK_MS
  );
}

/**
 * Текст диалога запасного выхода. Уже дошедшие фото уходят вместе с возвратом:
 * тогда отчёт с фото закрыт, и обещать досылку нельзя. Без фото сервер держит
 * досылку открытой, пока не выйдет окно.
 */
export function describeNoPhotoFallback(uploaded: number) {
  if (uploaded > 0) {
    const count = uploaded === 1 ? "фото, которое уже дошло" : `${uploaded} фото, которые уже дошли`;
    return {
      title: "Завершить возврат с тем, что есть?",
      text: `Отправим ${count}. Снимки, которые не отправились, не уйдут, и дослать их потом не получится. Сначала закройте дверцу ячейки.`,
      action: "Завершить с тем, что есть",
    };
  }
  return {
    title: "Завершить возврат без фото?",
    text:
      "Возврат примем, но без снимка не сможем быстро убедиться, что с вещью всё в порядке. Если связь появится, фото можно будет дослать на этой странице. Сначала закройте дверцу ячейки.",
    action: "Завершить без фото",
  };
}

// ── Ошибки ───────────────────────────────────────────────────────────────────

export type ReturnErrorStage = "upload" | "confirm";

export type ReturnErrorView = {
  message: string;
  code: string | null;
  /** Проблема именно с фото — показываем запасной выход «Не получается отправить фото». */
  photoProblem: boolean;
  /** Статус аренды на сервере, скорее всего, уже другой — стоит перечитать заказ. */
  refresh: boolean;
};

const NETWORK_MESSAGE = "Нет связи с сервером. Проверьте интернет и попробуйте ещё раз.";

function tooManyMessage(maxPhotos: number) {
  return `Можно приложить не больше ${maxPhotos} фото. Уберите лишние и отправьте ещё раз.`;
}

const CONFIRM_MESSAGES: Record<string, { message: string; photoProblem?: boolean; refresh?: boolean }> = {
  RETURN_PHOTO_INVALID: {
    message: "Одно из фото не подошло. Удалите его, сделайте снимок заново и отправьте ещё раз.",
    photoProblem: true,
  },
  RETURN_PHOTO_NOT_UPLOADED: {
    message: "Сервер не получил одно из фото целиком. Переснимите его и отправьте ещё раз.",
    photoProblem: true,
  },
  RETURN_PHOTOS_WINDOW_CLOSED: {
    message: "Время, чтобы дослать фото, вышло. Сам возврат уже принят — ничего делать не нужно.",
    refresh: true,
  },
  RETURN_PHOTOS_ALREADY_SENT: {
    message: "Фото к этому возврату уже отправлены — показываем, что мы получили.",
    refresh: true,
  },
  RENTAL_NOT_RETURNING: {
    message: "Возврат уже завершён или отменён. Обновили данные заказа.",
    refresh: true,
  },
  RETURN_REQUEST_NOT_FOUND: {
    message: "Заявка на возврат не найдена или истекла. Оформите возврат заново.",
    refresh: true,
  },
  RETURN_REQUEST_NOT_ACTIVE: {
    message: "Срок кода возврата истёк. Оформите возврат заново.",
    refresh: true,
  },
  CONFIRM_RETURN_FAILED: {
    message: "Не удалось завершить возврат. Попробуйте ещё раз через минуту.",
  },
  RENTAL_FORBIDDEN: {
    message: "Этот заказ оформлен на другой аккаунт.",
  },
  RENTAL_NOT_FOUND: {
    message: "Заказ не найден. Обновите страницу.",
  },
};

const UPLOAD_MESSAGES: Record<string, string> = {
  INVALID_MIME_TYPE: "Такой формат не подходит. Сделайте фото ещё раз — подойдут JPG, PNG или WEBP.",
  FILE_TOO_LARGE: FILE_TOO_LARGE_MESSAGE,
  INVALID_FILE_KIND: "Не получилось подготовить загрузку фото. Обновите страницу и попробуйте ещё раз.",
  EMPTY_UPLOAD: "Снимок оказался пустым. Сделайте фото ещё раз.",
};

const RAW_CODE = /^[A-Z0-9_]+$/;

export function describeReturnError(
  error: unknown,
  options: { stage: ReturnErrorStage; maxPhotos?: number },
): ReturnErrorView {
  const maxPhotos = options.maxPhotos ?? RETURN_PHOTOS_DEFAULT_MAX;
  const isUpload = options.stage === "upload";
  const fallback = isUpload
    ? "Не удалось отправить фото. Попробуйте ещё раз."
    : "Не удалось завершить возврат. Попробуйте ещё раз.";

  if (error instanceof ApiError) {
    const code = error.code ?? null;
    if (code === "RETURN_PHOTOS_TOO_MANY") {
      return { message: tooManyMessage(maxPhotos), code, photoProblem: false, refresh: false };
    }
    if (code && CONFIRM_MESSAGES[code]) {
      const entry = CONFIRM_MESSAGES[code];
      return {
        message: entry.message,
        code,
        photoProblem: isUpload || Boolean(entry.photoProblem),
        refresh: Boolean(entry.refresh),
      };
    }
    if (code && UPLOAD_MESSAGES[code]) {
      return { message: UPLOAD_MESSAGES[code], code, photoProblem: true, refresh: false };
    }
    if (code === "NETWORK_ERROR" || error.status === 0) {
      return { message: NETWORK_MESSAGE, code, photoProblem: isUpload, refresh: false };
    }
    if (code === "UNAUTHORIZED" || error.status === 401) {
      return {
        message: "Сессия истекла. Войдите в аккаунт ещё раз — снятые фото сохранятся.",
        code,
        photoProblem: false,
        refresh: false,
      };
    }
    if (error.status === 413) {
      return { message: FILE_TOO_LARGE_MESSAGE, code, photoProblem: true, refresh: false };
    }
    if (error.status >= 500) {
      return {
        message: "Сервер не ответил. Попробуйте ещё раз через минуту.",
        code,
        photoProblem: isUpload,
        refresh: false,
      };
    }
    const readable = error.message && !RAW_CODE.test(error.message) ? error.message : fallback;
    return { message: readable, code, photoProblem: isUpload, refresh: false };
  }

  if (error instanceof Error && error.message && !RAW_CODE.test(error.message)) {
    // Тексты из imageUpload уже человеческие: обрыв сети, размер, формат.
    return { message: error.message, code: null, photoProblem: isUpload, refresh: false };
  }
  return {
    message: isUpload ? UPLOAD_NETWORK_MESSAGE : fallback,
    code: null,
    photoProblem: isUpload,
    refresh: false,
  };
}

// ── Черновик в sessionStorage ────────────────────────────────────────────────

export type ReturnDraftPhoto = { fileId: string; thumb: string | null };

export type ReturnDraft = {
  rentalId: string;
  photos: ReturnDraftPhoto[];
  note: string;
  cellOpened: boolean;
  savedAt: number;
};

export type DraftStorage = Pick<Storage, "getItem" | "setItem" | "removeItem">;

const DRAFT_VERSION = 1;
/** Черновик дольше пары часов не нужен: PIN живёт 30 минут, окно досылки — 2 часа. */
export const RETURN_DRAFT_MAX_AGE_MS = 6 * 60 * 60 * 1000;
/** Миниатюра ~400 px в JPEG — это 20–40 КБ; всё, что сильно больше, не храним. */
export const RETURN_DRAFT_THUMB_MAX_CHARS = 200_000;

const FILE_ID = /^[A-Za-z0-9-]{1,64}$/;

export function returnDraftKey(rentalId: string) {
  return `postamats-return-draft:${rentalId}`;
}

export function isEmptyReturnDraft(draft: Pick<ReturnDraft, "photos" | "note" | "cellOpened">) {
  return draft.photos.length === 0 && !draft.note.trim() && !draft.cellOpened;
}

export function serializeReturnDraft(draft: ReturnDraft, options: { withThumbs?: boolean } = {}) {
  const withThumbs = options.withThumbs ?? true;
  return JSON.stringify({
    v: DRAFT_VERSION,
    rentalId: draft.rentalId,
    photos: draft.photos.map((photo) => ({
      fileId: photo.fileId,
      thumb: withThumbs ? photo.thumb : null,
    })),
    note: draft.note.slice(0, RETURN_NOTE_MAX),
    cellOpened: draft.cellOpened,
    savedAt: draft.savedAt,
  });
}

export function parseReturnDraft(
  raw: string | null | undefined,
  rentalId: string,
  nowMs: number,
  maxPhotos: number = RETURN_PHOTOS_DEFAULT_MAX,
): ReturnDraft | null {
  if (!raw) {
    return null;
  }
  let payload: unknown;
  try {
    payload = JSON.parse(raw);
  } catch {
    return null;
  }
  if (!payload || typeof payload !== "object") {
    return null;
  }
  const data = payload as Record<string, unknown>;
  if (data.v !== DRAFT_VERSION || data.rentalId !== rentalId) {
    return null;
  }
  const savedAt = typeof data.savedAt === "number" ? data.savedAt : Number.NaN;
  if (!Number.isFinite(savedAt) || nowMs - savedAt > RETURN_DRAFT_MAX_AGE_MS || savedAt - nowMs > 60_000) {
    return null;
  }

  const seen = new Set<string>();
  const photos: ReturnDraftPhoto[] = [];
  for (const entry of Array.isArray(data.photos) ? data.photos : []) {
    if (!entry || typeof entry !== "object") continue;
    const { fileId, thumb } = entry as Record<string, unknown>;
    if (typeof fileId !== "string" || !FILE_ID.test(fileId) || seen.has(fileId)) continue;
    seen.add(fileId);
    const safeThumb =
      typeof thumb === "string" &&
      thumb.startsWith("data:image/") &&
      thumb.length <= RETURN_DRAFT_THUMB_MAX_CHARS
        ? thumb
        : null;
    photos.push({ fileId, thumb: safeThumb });
    if (photos.length >= maxPhotos) break;
  }

  return {
    rentalId,
    photos,
    note: typeof data.note === "string" ? data.note.slice(0, RETURN_NOTE_MAX) : "",
    cellOpened: data.cellOpened === true || photos.length > 0,
    savedAt,
  };
}

export function readReturnDraft(
  storage: DraftStorage | null,
  rentalId: string,
  nowMs: number,
  maxPhotos?: number,
) {
  if (!storage) return null;
  try {
    return parseReturnDraft(storage.getItem(returnDraftKey(rentalId)), rentalId, nowMs, maxPhotos);
  } catch {
    return null;
  }
}

/** Пишет черновик; если не влезло в квоту — пробует ещё раз без миниатюр. */
export function writeReturnDraft(storage: DraftStorage | null, draft: ReturnDraft) {
  if (!storage) return false;
  const key = returnDraftKey(draft.rentalId);
  if (isEmptyReturnDraft(draft)) {
    clearReturnDraft(storage, draft.rentalId);
    return true;
  }
  try {
    storage.setItem(key, serializeReturnDraft(draft));
    return true;
  } catch {
    try {
      storage.setItem(key, serializeReturnDraft(draft, { withThumbs: false }));
      return true;
    } catch {
      return false;
    }
  }
}

export function clearReturnDraft(storage: DraftStorage | null, rentalId: string) {
  if (!storage) return;
  try {
    storage.removeItem(returnDraftKey(rentalId));
  } catch {
    // Приватный режим Safari может запрещать storage — черновик просто не живёт.
  }
}

export function getSessionDraftStorage(): DraftStorage | null {
  try {
    return typeof window !== "undefined" ? window.sessionStorage : null;
  } catch {
    return null;
  }
}

// ── Форматирование ───────────────────────────────────────────────────────────

/** «ещё 24 мин», «ещё 1 ч 5 мин», «меньше минуты»; null — время уже вышло или неизвестно. */
export function formatTimeLeft(untilIso: string | null | undefined, nowMs: number) {
  const untilMs = parseTime(untilIso);
  if (Number.isNaN(untilMs)) return null;
  const diff = untilMs - nowMs;
  if (diff <= 0) return null;
  const minutes = Math.floor(diff / 60_000);
  if (minutes < 1) return "меньше минуты";
  if (minutes < 60) return `ещё ${minutes} мин`;
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  return rest ? `ещё ${hours} ч ${rest} мин` : `ещё ${hours} ч`;
}

export function isPast(iso: string | null | undefined, nowMs: number) {
  const value = parseTime(iso);
  return !Number.isNaN(value) && value <= nowMs;
}

/** PIN раскладываем по «клавишам»: только цифры и буквы, без пробелов. */
export function splitPin(pin: string | null | undefined) {
  return (pin ?? "").replace(/\s+/g, "").split("").slice(0, 12);
}
