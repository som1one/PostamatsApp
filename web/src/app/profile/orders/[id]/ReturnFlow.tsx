"use client";

import {
  useCallback,
  useEffect,
  useId,
  useRef,
  useState,
  type ChangeEvent,
  type ReactNode,
  type RefObject,
} from "react";
import {
  Camera,
  CameraOff,
  Check,
  ChevronDown,
  Clock3,
  Copy,
  DoorClosed,
  DoorOpen,
  ImageIcon,
  ImageUp,
  KeyRound,
  LoaderCircle,
  MessageSquarePlus,
  PackageCheck,
  Plus,
  RefreshCcw,
  Trash2,
  TriangleAlert,
  X,
} from "lucide-react";
import {
  RETURN_PHOTO_UPLOAD_KIND,
  confirmRentalReturn,
  fetchRental,
  presignUpload,
} from "@/shared/api/endpoints";
import type {
  ActiveReturnRequest,
  RentalDetail,
  RentalListItem,
  ReturnReport,
} from "@/shared/api/types";
import { formatCountRu, formatDateTime, formatMoney } from "@/shared/format";
import {
  FILE_TOO_LARGE_MESSAGE,
  MAX_UPLOAD_BYTES,
  PHOTO_UNREADABLE_MESSAGE,
  isUploadAborted,
  needsImageConversion,
  preparePhotoForUpload,
  putPresignedFileWithProgress,
  withUploadDeadline,
} from "@/shared/imageUpload";
import { resolvePublicAssetUrl } from "@/shared/media";
import {
  RETURN_NOTE_MAX,
  RETURN_POLL_INTERVAL_MS,
  RETURN_PREPARE_TIMEOUT_MS,
  RETURN_PRESIGN_TIMEOUT_MS,
  clearReturnDraft,
  deriveReturnFlowMode,
  deriveReturnSteps,
  describeNoPhotoFallback,
  describeReturnClosed,
  describeReturnError,
  formatTimeLeft,
  getReturnCompletedBy,
  getReturnSubmitState,
  getSessionDraftStorage,
  isPast,
  pickReturnRequest,
  readReturnDraft,
  resolveMaxPhotos,
  shouldOfferNoPhotoFallback,
  splitPin,
  writeReturnDraft,
  type ConfirmReturnResult,
  type ReturnClosedNotice,
  type ReturnShotStatus,
  type ReturnStepState,
} from "./returnFlowState";

// Миниатюра для черновика: хватает, чтобы после перезагрузки кадр не выглядел
// пустым, и не забивает sessionStorage (4 × ~30 КБ).
const THUMBNAIL_SIZE = 480;

type Shot = {
  key: string;
  fileId: string | null;
  status: ReturnShotStatus;
  progress: number;
  /** object URL снимка — только в этой вкладке. */
  previewUrl: string | null;
  /** data URL миниатюры — переживает перезагрузку. */
  thumb: string | null;
  error: string | null;
};

type LocalRequest = Partial<ActiveReturnRequest> | null;

/** Куда вернуть фокус, когда элемент под ним исчез после действия. */
type FocusTarget = "title" | "shoot" | "frame";

export type ReturnFlowProps = {
  rental: RentalListItem;
  detail?: RentalDetail;
  /** Ответ return-request из этой вкладки — запасной источник PIN, пока список не обновился. */
  localRequest?: LocalRequest;
  /** Свежий detail из опроса: статус мог смениться, пока клиент у постамата. */
  onDetail: (detail: RentalDetail) => void;
  /** Возврат подтверждён (или фото досланы) — заказ нужно обновить. */
  onConfirmed: (result: ConfirmReturnResult) => void;
  /** Сервер ответил, что состояние уже другое — перечитать заказ. */
  onRefresh: () => void;
};

const clockFormatter = new Intl.DateTimeFormat("ru-RU", { hour: "2-digit", minute: "2-digit" });

function formatClock(value?: string | null) {
  if (!value) return null;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : clockFormatter.format(date);
}

function prefersReducedMotion() {
  return typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
}

function isPendingShot(shot: Pick<Shot, "status">) {
  return shot.status === "preparing" || shot.status === "uploading";
}

export function ReturnFlow({
  rental,
  detail,
  localRequest,
  onDetail,
  onConfirmed,
  onRefresh,
}: ReturnFlowProps) {
  const rentalId = rental.id;
  const [nowMs, setNowMs] = useState(() => Date.now());
  const maxPhotos = resolveMaxPhotos(rental.returnReport ?? detail?.returnReport);
  const request = pickReturnRequest(rental.returnRequest, detail?.returnRequest, localRequest);

  // Черновик читаем один раз при монтировании: после камеры iOS Safari может
  // перезагрузить вкладку, а уже отправленные фото терять нельзя.
  const [initialDraft] = useState(() => {
    const initialMode = deriveReturnFlowMode(rental, Date.now());
    return initialMode === "in_progress" || initialMode === "late"
      ? readReturnDraft(getSessionDraftStorage(), rentalId, Date.now(), maxPhotos)
      : null;
  });
  const [shots, setShots] = useState<Shot[]>(() =>
    (initialDraft?.photos ?? []).map((photo) => ({
      key: `restored-${photo.fileId}`,
      fileId: photo.fileId,
      status: "uploaded" as const,
      progress: 1,
      previewUrl: null,
      thumb: photo.thumb,
      error: null,
    })),
  );
  // Комментарий, уже отправленный с отчётом без фото, показываем в поле: его
  // можно дополнить, когда досылаете снимок.
  const [note, setNote] = useState(() => initialDraft?.note || rental.returnReport?.note || "");
  const [noteOpen, setNoteOpen] = useState(() =>
    Boolean(initialDraft?.note || rental.returnReport?.note),
  );
  const [cellOpened, setCellOpened] = useState(() => initialDraft?.cellOpened ?? false);
  const [showOpenStep, setShowOpenStep] = useState(false);
  const [activeKey, setActiveKey] = useState<string | null>(null);
  const [flash, setFlash] = useState(0);
  const [photoTrouble, setPhotoTrouble] = useState(false);
  // Когда впервые открыли камеру: если за минуту ни одного фото — камера не работает.
  const [firstCaptureAt, setFirstCaptureAt] = useState<number | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState("");
  const [showNoPhotoDialog, setShowNoPhotoDialog] = useState(false);
  const [finishedHere, setFinishedHere] = useState<"photos" | "without_photos" | null>(null);
  const [pinCopied, setPinCopied] = useState(false);
  const [announcement, setAnnouncement] = useState("");
  const [closedNotice, setClosedNotice] = useState<ReturnClosedNotice | null>(null);
  const [focusRequest, setFocusRequest] = useState<{ target: FocusTarget; seq: number } | null>(null);
  const [remembered, setRemembered] = useState(() => ({
    cellLabel: request.cellLabel,
    lockerName: request.lockerName,
  }));

  // Пока фото в пути или идёт отправка, окно досылки не закрываем по часам
  // телефона — дождёмся ответа сервера.
  const hasPendingShots = shots.some(isPendingShot);
  const mode = deriveReturnFlowMode(rental, nowMs, { holdLate: submitting || hasPendingShots });

  const sectionRef = useRef<HTMLElement>(null);
  const titleRef = useRef<HTMLHeadingElement>(null);
  const shootHeadingRef = useRef<HTMLHeadingElement>(null);
  const frameRef = useRef<HTMLDivElement>(null);
  const dialogRef = useRef<HTMLDivElement>(null);
  const noPhotoTriggerRef = useRef<HTMLButtonElement>(null);
  const restoreDialogFocusRef = useRef(false);
  const receiptRef = useRef<HTMLElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const captureTargetRef = useRef<string | null>(null);
  const filesRef = useRef(new Map<string, File>());
  const controllersRef = useRef(new Map<string, AbortController>());
  const objectUrlsRef = useRef(new Set<string>());
  const keySeqRef = useRef(0);
  const progressRef = useRef(new Map<string, number>());
  const submittingRef = useRef(false);
  const generationRef = useRef(0);
  const copyTimerRef = useRef<number | undefined>(undefined);
  const previousModeRef = useRef(mode);

  const ids = useId();
  const titleId = `${ids}-title`;
  const noteId = `${ids}-note`;
  const hintId = `${ids}-hint`;
  const dialogTitleId = `${ids}-dialog-title`;
  const dialogTextId = `${ids}-dialog-text`;

  // Часы для срока PIN и окна досылки.
  useEffect(() => {
    const timer = window.setInterval(() => setNowMs(Date.now()), 15_000);
    return () => window.clearInterval(timer);
  }, []);

  // Ячейку и постамат запоминаем, пока заявка активна: после завершения бэкенд
  // её уже не отдаёт, а квитанции они нужны.
  useEffect(() => {
    if (request.cellLabel || request.lockerName) {
      setRemembered((current) => ({
        cellLabel: request.cellLabel ?? current.cellLabel,
        lockerName: request.lockerName ?? current.lockerName,
      }));
    }
  }, [request.cellLabel, request.lockerName]);

  // Черновик: только загруженные фото (fileId + миниатюра), комментарий и шаг.
  // Прогресс отправки меняет shots десятки раз — в storage пишем, только когда
  // меняется набор загруженных файлов.
  const latestShotsRef = useRef(shots);
  useEffect(() => {
    latestShotsRef.current = shots;
  }, [shots]);
  const uploadedSignature = shots
    .filter((shot) => shot.status === "uploaded" && shot.fileId)
    .map((shot) => `${shot.fileId}:${shot.thumb ? 1 : 0}`)
    .join("|");
  useEffect(() => {
    if (mode !== "in_progress" && mode !== "late") {
      return;
    }
    const photos = latestShotsRef.current
      .filter((shot) => shot.status === "uploaded" && shot.fileId)
      .map((shot) => ({ fileId: shot.fileId as string, thumb: shot.thumb }));
    writeReturnDraft(getSessionDraftStorage(), {
      rentalId,
      photos,
      note,
      cellOpened,
      savedAt: Date.now(),
    });
  }, [mode, rentalId, uploadedSignature, note, cellOpened]);

  useEffect(() => {
    if (mode === "receipt" || mode === "none") {
      clearReturnDraft(getSessionDraftStorage(), rentalId);
      // Возврат закрыт — недоотправленные кадры уже никуда не приложить.
      controllersRef.current.forEach((controller) => controller.abort());
      controllersRef.current.clear();
    }
  }, [mode, rentalId]);

  useEffect(() => {
    const urls = objectUrlsRef.current;
    const controllers = controllersRef.current;
    return () => {
      urls.forEach((url) => URL.revokeObjectURL(url));
      urls.clear();
      controllers.forEach((controller) => controller.abort());
      controllers.clear();
      window.clearTimeout(copyTimerRef.current);
    };
  }, []);

  // Страница открылась посреди возврата ниже степпера — подтягиваем его в экран.
  useEffect(() => {
    const node = sectionRef.current;
    if (node && node.getBoundingClientRect().top < 0) {
      node.scrollIntoView({ block: "start", behavior: prefersReducedMotion() ? "auto" : "smooth" });
    }
  }, []);

  // Смена режима без перезагрузки: степпер появился, дверца закрыла возврат,
  // окно досылки вышло. Проговариваем, подтягиваем в экран и не теряем фокус.
  useEffect(() => {
    const previous = previousModeRef.current;
    previousModeRef.current = mode;
    if (previous === mode) {
      return;
    }
    const focusLost = !document.activeElement || document.activeElement === document.body;
    restoreDialogFocusRef.current = false;
    setShowNoPhotoDialog(false);

    if (mode === "none") {
      // Степпер пропадает не молча: объясняем почему. Недоотправленные кадры
      // сбрасываем — к этому возврату их уже не приложить.
      setClosedNotice(describeReturnClosed(previous, rental.status));
      objectUrlsRef.current.forEach((url) => URL.revokeObjectURL(url));
      objectUrlsRef.current.clear();
      filesRef.current.clear();
      progressRef.current.clear();
      setShots([]);
      setActiveKey(null);
      setCellOpened(false);
      setPhotoTrouble(false);
      setFirstCaptureAt(null);
      if (focusLost) {
        setFocusRequest((current) => ({ target: "title", seq: (current?.seq ?? 0) + 1 }));
      }
      return;
    }

    setClosedNotice(null);
    if (previous === "none" && mode === "in_progress") {
      // «Оформить возврат» нажали внизу карточки, а PIN появился наверху —
      // уводим экран к степперу и ставим фокус на его заголовок.
      sectionRef.current?.scrollIntoView({
        block: "start",
        behavior: prefersReducedMotion() ? "auto" : "smooth",
      });
      titleRef.current?.focus({ preventScroll: true });
      return;
    }
    if (previous === "in_progress" && mode === "late" && !finishedHere) {
      setAnnouncement("Возврат принят дверцей постамата. Отправьте фото вещи.");
    }
    if (mode === "late" && focusLost) {
      titleRef.current?.focus({ preventScroll: true });
    }
  }, [mode, rental.status, finishedHere]);

  useEffect(() => {
    if (!focusRequest) {
      return;
    }
    const node =
      focusRequest.target === "shoot"
        ? shootHeadingRef.current
        : focusRequest.target === "frame"
          ? frameRef.current
          : titleRef.current;
    node?.focus({ preventScroll: focusRequest.target === "title" });
  }, [focusRequest]);

  // Квитанция, появившаяся после нажатия, забирает фокус и попадает в экран.
  useEffect(() => {
    if (mode !== "receipt" || !finishedHere) {
      return;
    }
    const node = receiptRef.current;
    if (!node) return;
    node.focus({ preventScroll: true });
    node.scrollIntoView({ block: "nearest", behavior: prefersReducedMotion() ? "auto" : "smooth" });
  }, [mode, finishedHere]);

  // Пока возврат идёт — раз в ~8 с перечитываем аренду (только в видимой
  // вкладке). Ответ, начатый до подтверждения, выбрасываем: он старше.
  useEffect(() => {
    if (mode !== "in_progress") {
      return;
    }
    let cancelled = false;
    let inFlight = false;
    let timer: number | undefined;

    const schedule = (delay: number) => {
      window.clearTimeout(timer);
      timer = window.setTimeout(() => void tick(), delay);
    };

    const tick = async () => {
      if (cancelled || inFlight) return;
      if (document.visibilityState === "visible" && !submittingRef.current) {
        inFlight = true;
        const generation = generationRef.current;
        try {
          const fresh = await fetchRental(rentalId);
          if (!cancelled && generation === generationRef.current && !submittingRef.current) {
            onDetail(fresh);
          }
        } catch {
          // Сеть у постамата бывает слабой — просто попробуем в следующий раз.
        } finally {
          inFlight = false;
        }
      }
      if (!cancelled) schedule(RETURN_POLL_INTERVAL_MS);
    };

    const handleVisibility = () => {
      if (document.visibilityState === "visible" && !inFlight) {
        schedule(0);
      }
    };

    schedule(RETURN_POLL_INTERVAL_MS);
    document.addEventListener("visibilitychange", handleVisibility);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
      document.removeEventListener("visibilitychange", handleVisibility);
    };
  }, [mode, rentalId, onDetail]);

  // Диалог без фото: Escape закрывает, Tab не уходит на страницу под
  // затемнением, после закрытия фокус возвращается на ссылку-триггер.
  useEffect(() => {
    if (!showNoPhotoDialog) {
      if (restoreDialogFocusRef.current) {
        restoreDialogFocusRef.current = false;
        const trigger = noPhotoTriggerRef.current;
        if (trigger?.isConnected) trigger.focus();
      }
      return;
    }
    restoreDialogFocusRef.current = true;
    const handleKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        setShowNoPhotoDialog(false);
        return;
      }
      if (event.key !== "Tab") {
        return;
      }
      const box = dialogRef.current;
      if (!box) return;
      const focusable = Array.from(
        box.querySelectorAll<HTMLElement>("button:not([disabled]), a[href]"),
      );
      if (focusable.length === 0) {
        event.preventDefault();
        return;
      }
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      const active = document.activeElement;
      const inside = active instanceof Node && box.contains(active);
      if (event.shiftKey ? !inside || active === first : !inside || active === last) {
        event.preventDefault();
        (event.shiftKey ? last : first).focus();
      }
    };
    document.addEventListener("keydown", handleKey);
    return () => document.removeEventListener("keydown", handleKey);
  }, [showNoPhotoDialog]);

  const updateShot = useCallback((key: string, patch: Partial<Shot>) => {
    setShots((current) => current.map((shot) => (shot.key === key ? { ...shot, ...patch } : shot)));
  }, []);

  function requestFocus(target: FocusTarget) {
    setFocusRequest((current) => ({ target, seq: (current?.seq ?? 0) + 1 }));
  }

  function createObjectUrl(file: File) {
    try {
      const url = URL.createObjectURL(file);
      objectUrlsRef.current.add(url);
      return url;
    } catch {
      return null;
    }
  }

  function revokeObjectUrl(url: string | null) {
    if (url && objectUrlsRef.current.has(url)) {
      URL.revokeObjectURL(url);
      objectUrlsRef.current.delete(url);
    }
  }

  function nextKey() {
    keySeqRef.current += 1;
    return `shot-${Date.now()}-${keySeqRef.current}`;
  }

  function cancelUpload(key: string) {
    controllersRef.current.get(key)?.abort();
    controllersRef.current.delete(key);
  }

  async function uploadShot(key: string, original: File) {
    // Один кадр — одна отправка: повтор или пересъёмка гасят предыдущую.
    cancelUpload(key);
    const controller = new AbortController();
    controllersRef.current.set(key, controller);
    const { signal } = controller;

    updateShot(key, { status: "preparing", progress: 0, error: null });
    try {
      const prepared = await withUploadDeadline(
        preparePhotoForUpload(original, { thumbnailSize: THUMBNAIL_SIZE }),
        { timeoutMs: RETURN_PREPARE_TIMEOUT_MS, signal, timeoutMessage: PHOTO_UNREADABLE_MESSAGE },
      );
      if (prepared.file.size > MAX_UPLOAD_BYTES) {
        throw new Error(FILE_TOO_LARGE_MESSAGE);
      }
      const patch: Partial<Shot> = { status: "uploading", thumb: prepared.thumbnail };
      if (needsImageConversion(original)) {
        // HEIC браузер мог не показать — превью берём из перегнанного JPEG.
        patch.previewUrl = createObjectUrl(prepared.file);
      }
      updateShot(key, patch);

      // fetch presign сам не сдаётся на зависшей сети — ограничиваем по времени.
      const presign = await withUploadDeadline(
        presignUpload({
          fileName: prepared.file.name || "return-photo.jpg",
          mimeType: prepared.file.type || "image/jpeg",
          fileSize: prepared.file.size,
          kind: RETURN_PHOTO_UPLOAD_KIND,
        }),
        { timeoutMs: RETURN_PRESIGN_TIMEOUT_MS, signal },
      );
      await putPresignedFileWithProgress(presign, prepared.file, {
        context: "photo",
        signal,
        onProgress: (fraction) => {
          const percent = Math.round(fraction * 100);
          if (progressRef.current.get(key) === percent) return;
          progressRef.current.set(key, percent);
          updateShot(key, { progress: fraction });
        },
      });
      if (signal.aborted) return;
      updateShot(key, { status: "uploaded", progress: 1, fileId: presign.fileId, error: null });
      filesRef.current.delete(key);
      progressRef.current.delete(key);
      setAnnouncement("Фото получено.");
    } catch (err) {
      // Кадр удалили или пересняли — его ошибка уже никому не нужна.
      if (signal.aborted || isUploadAborted(err)) return;
      const view = describeReturnError(err, { stage: "upload", maxPhotos });
      updateShot(key, { status: "failed", error: view.message });
      progressRef.current.delete(key);
      setPhotoTrouble(true);
      setAnnouncement(`Фото не отправилось. ${view.message}`);
    } finally {
      if (controllersRef.current.get(key) === controller) {
        controllersRef.current.delete(key);
      }
    }
  }

  function openPicker(targetKey: string | null) {
    captureTargetRef.current = targetKey;
    setFirstCaptureAt((current) => current ?? Date.now());
    inputRef.current?.click();
  }

  function handleFiles(event: ChangeEvent<HTMLInputElement>) {
    const input = event.currentTarget;
    const picked = Array.from(input.files ?? []);
    // Сбрасываем value, чтобы тот же файл можно было выбрать ещё раз.
    input.value = "";
    const target = captureTargetRef.current;
    captureTargetRef.current = null;
    if (picked.length === 0) {
      return;
    }
    const files = picked.filter((file) => file.size > 0);
    if (files.length === 0) {
      setSubmitError("Снимок оказался пустым. Сделайте фото ещё раз.");
      // Некоторые камеры Android раз за разом отдают пустой файл — без
      // запасного выхода клиент застрял бы у открытой дверцы.
      setPhotoTrouble(true);
      return;
    }

    setSubmitError("");
    setCellOpened(true);
    setFlash((value) => value + 1);

    if (target && shots.some((shot) => shot.key === target)) {
      const file = files[0];
      const key = nextKey();
      const previous = shots.find((shot) => shot.key === target);
      revokeObjectUrl(previous?.previewUrl ?? null);
      cancelUpload(target);
      filesRef.current.delete(target);
      progressRef.current.delete(target);
      filesRef.current.set(key, file);
      const replacement: Shot = {
        key,
        fileId: null,
        status: "preparing",
        progress: 0,
        previewUrl: needsImageConversion(file) ? null : createObjectUrl(file),
        thumb: null,
        error: null,
      };
      setShots((current) => current.map((shot) => (shot.key === target ? replacement : shot)));
      setActiveKey(key);
      void uploadShot(key, file);
      return;
    }

    const room = Math.max(0, maxPhotos - shots.length);
    const accepted = files.slice(0, room);
    if (accepted.length === 0) {
      setSubmitError(`Можно приложить не больше ${maxPhotos} фото.`);
      return;
    }
    const created: Shot[] = accepted.map((file) => {
      const key = nextKey();
      filesRef.current.set(key, file);
      return {
        key,
        fileId: null,
        status: "preparing",
        progress: 0,
        previewUrl: needsImageConversion(file) ? null : createObjectUrl(file),
        thumb: null,
        error: null,
      };
    });
    setShots((current) => [...current, ...created].slice(0, maxPhotos));
    setActiveKey(created[created.length - 1].key);
    if (shots.length === 0) {
      // Кнопка «Сделать фото» исчезла вместе с пустым кадром — фокус на сам кадр.
      requestFocus("frame");
    }
    created.forEach((shot, index) => {
      void uploadShot(shot.key, accepted[index]);
    });
  }

  function removeShot(key: string) {
    const index = shots.findIndex((shot) => shot.key === key);
    if (index < 0) return;
    const removed = shots[index];
    cancelUpload(key);
    revokeObjectUrl(removed.previewUrl);
    filesRef.current.delete(key);
    progressRef.current.delete(key);
    // Только функциональное обновление: другой кадр мог догрузиться между
    // рендером и нажатием, и его «Фото получено» затирать нельзя.
    setShots((current) => current.filter((shot) => shot.key !== key));
    const neighbour = shots[index - 1] ?? shots[index + 1] ?? null;
    setActiveKey(neighbour?.key ?? null);
    if (!neighbour) {
      requestFocus("frame");
    }
    setAnnouncement(isPendingShot(removed) ? "Отправка фото отменена." : "Фото удалено.");
  }

  function retryShot(key: string) {
    const file = filesRef.current.get(key);
    if (file) {
      void uploadShot(key, file);
    } else {
      openPicker(key);
    }
  }

  async function copyPin(pin: string) {
    try {
      await navigator.clipboard.writeText(pin);
      setPinCopied(true);
      window.clearTimeout(copyTimerRef.current);
      copyTimerRef.current = window.setTimeout(() => setPinCopied(false), 2000);
    } catch {
      // Буфер обмена недоступен (http, webview) — PIN и так крупно на экране.
    }
  }

  /**
   * Подтверждение возврата. Всегда уходят уже загруженные фото и комментарий —
   * и из основной кнопки, и из запасного выхода (там кнопка не ждёт остальные
   * кадры). Отчёт без фото сервер оставляет открытым для досылки.
   */
  async function submit(options: { fromDialog?: boolean } = {}) {
    const photoFileIds = shots
      .filter((shot) => shot.status === "uploaded" && shot.fileId)
      .map((shot) => shot.fileId as string);
    const trimmedNote = note.trim().slice(0, RETURN_NOTE_MAX);

    setSubmitError("");
    setSubmitting(true);
    submittingRef.current = true;
    generationRef.current += 1;
    let succeeded = false;
    try {
      const result = await confirmRentalReturn(rentalId, {
        photoFileIds,
        note: trimmedNote || undefined,
      });
      succeeded = true;
      clearReturnDraft(getSessionDraftStorage(), rentalId);
      setFinishedHere(photoFileIds.length > 0 ? "photos" : "without_photos");
      setAnnouncement(photoFileIds.length > 0 ? "Возврат принят, фото получены." : "Возврат принят без фото.");
      onConfirmed(result);
    } catch (err) {
      const view = describeReturnError(err, { stage: "confirm", maxPhotos });
      setSubmitError(view.message);
      if (view.photoProblem) setPhotoTrouble(true);
      if (view.refresh) onRefresh();
    } finally {
      submittingRef.current = false;
      setSubmitting(false);
      if (options.fromDialog) {
        // Не вышло — фокус обратно на ссылку, рядом с текстом ошибки.
        restoreDialogFocusRef.current = !succeeded;
        setShowNoPhotoDialog(false);
      }
    }
  }

  const liveRegion = (
    <p className="return-sr-only" aria-live="polite">
      {announcement}
    </p>
  );

  if (mode === "none") {
    if (!closedNotice) {
      return null;
    }
    const NoticeIcon =
      closedNotice.tone === "ok" ? PackageCheck : closedNotice.tone === "warn" ? TriangleAlert : Clock3;
    return (
      <section ref={sectionRef} className="return-flow is-closed" aria-labelledby={titleId}>
        <header className="return-late-head">
          <span className={`return-late-badge is-${closedNotice.tone}`} aria-hidden="true">
            <NoticeIcon size={22} />
          </span>
          <div className="return-flow-head">
            <h2 id={titleId} ref={titleRef} tabIndex={-1} className="return-flow-title">
              {closedNotice.title}
            </h2>
            <p className="return-flow-lead" role="status">
              {closedNotice.text}
            </p>
          </div>
        </header>
        <button type="button" className="return-link" onClick={() => setClosedNotice(null)}>
          <Check size={16} aria-hidden="true" />
          Понятно
        </button>
      </section>
    );
  }

  if (mode === "receipt" && rental.returnReport) {
    const report = rental.returnReport;
    const localPreviews = new Map<string, string>();
    for (const shot of shots) {
      const local = shot.previewUrl ?? shot.thumb;
      if (shot.fileId && local) localPreviews.set(shot.fileId, local);
    }
    return (
      <ReturnReceipt
        receiptRef={receiptRef}
        report={report}
        returnedAt={report.returnedAt ?? rental.actualEndAt ?? detail?.actualEndAt ?? report.submittedAt}
        lockerName={report.lockerName ?? remembered.lockerName ?? rental.locker.name ?? null}
        cellLabel={report.cellLabel ?? remembered.cellLabel}
        bonusAccrued={detail?.paymentSummary?.bonusAccrued ?? 0}
        currency={detail?.paymentSummary?.currency}
        localPreviews={localPreviews}
        fresh={Boolean(finishedHere)}
      />
    );
  }

  const isLate = mode === "late";
  const submitState = getReturnSubmitState(shots);
  const activeShot = shots.find((shot) => shot.key === activeKey) ?? shots[0] ?? null;
  const activeIndex = activeShot ? shots.indexOf(activeShot) : -1;
  const canAddMore = shots.length < maxPhotos;
  const steps = deriveReturnSteps({ cellOpened, shots });

  const submitHint =
    submitState.blockedBy === "uploading"
      ? "Дождитесь, пока фото отправится, или отмените его."
      : submitState.blockedBy === "no_photo"
        ? isLate
          ? "Кнопка заработает, когда фото отправится."
          : "Кнопка заработает, когда фото вещи в ячейке отправится."
        : submitState.failed > 0
          ? "Фото с ошибкой не уйдут — повторите отправку или удалите их."
          : null;

  const capture = (
    <PhotoCapture
      frameRef={frameRef}
      late={isLate}
      shots={shots}
      activeShot={activeShot}
      activeIndex={activeIndex}
      maxPhotos={maxPhotos}
      canAddMore={canAddMore}
      flash={flash}
      onFlashEnd={() => setFlash(0)}
      disabled={submitting}
      onCapture={() => openPicker(null)}
      onRetake={(key) => openPicker(key)}
      onRetry={retryShot}
      onRemove={removeShot}
      onSelect={setActiveKey}
    />
  );

  const noteField = (
    <NoteField
      id={noteId}
      open={noteOpen}
      value={note}
      disabled={submitting}
      onOpen={() => setNoteOpen(true)}
      onChange={(value) => setNote(value.slice(0, RETURN_NOTE_MAX))}
    />
  );

  const errorBlock = submitError ? (
    <p className="return-error" role="alert">
      <TriangleAlert size={16} aria-hidden="true" />
      <span>{submitError}</span>
    </p>
  ) : null;

  const fileInput = (
    <input
      ref={inputRef}
      className="return-file-input"
      type="file"
      accept="image/*"
      capture={isLate ? undefined : "environment"}
      multiple={isLate}
      tabIndex={-1}
      aria-hidden="true"
      onChange={handleFiles}
    />
  );

  if (isLate) {
    // Возврат приняли без снимка (запасной выход или отчёт только с
    // комментарием) — предлагаем именно «дослать».
    const acceptedWithoutPhoto =
      finishedHere === "without_photos" ||
      Boolean(rental.returnReport?.submittedAt) ||
      getReturnCompletedBy(detail?.events) === "user";
    const until = formatClock(rental.returnReport?.attachPhotosUntil);
    return (
      <section ref={sectionRef} className="return-flow is-late" aria-labelledby={titleId}>
        <header className="return-late-head">
          <span className="return-late-badge" aria-hidden="true">
            <PackageCheck size={22} />
          </span>
          <div className="return-flow-head">
            <p className="return-flow-eyebrow is-green">Осталось фото</p>
            <h2 id={titleId} ref={titleRef} tabIndex={-1} className="return-flow-title">
              {acceptedWithoutPhoto ? "Возврат принят без фото" : "Возврат принят дверцей постамата"}
            </h2>
            <p className="return-flow-lead">
              {acceptedWithoutPhoto
                ? "Если снимок всё-таки получился — дошлите его, так мы быстрее проверим вещь."
                : "Отправьте фото вещи в ячейке — так мы увидим, в каком виде она вернулась."}
              {until ? ` Можно до ${until}.` : ""}
            </p>
          </div>
        </header>
        {capture}
        {noteField}
        {errorBlock}
        <div className="return-submit-block">
          <button
            type="button"
            className="button button-primary return-submit"
            disabled={!submitState.canSubmit || submitting}
            aria-describedby={submitHint ? hintId : undefined}
            onClick={() => void submit()}
          >
            {submitting ? (
              <>
                <LoaderCircle size={18} className="return-spin" aria-hidden="true" />
                Отправляем фото…
              </>
            ) : (
              <>
                <ImageUp size={18} aria-hidden="true" />
                {acceptedWithoutPhoto ? "Дослать фото" : "Отправить фото"}
              </>
            )}
          </button>
          {submitHint ? (
            <p id={hintId} className="return-submit-hint">
              {submitHint}
            </p>
          ) : null}
        </div>
        {fileInput}
        {liveRegion}
      </section>
    );
  }

  const pinDigits = splitPin(request.pin);
  const expired = isPast(request.expiresAt, nowMs);
  const expiresClock = formatClock(request.expiresAt);
  const timeLeft = formatTimeLeft(request.expiresAt, nowMs);
  const openSummary = [
    request.pin ? `PIN ${request.pin}` : null,
    request.cellLabel ? `ячейка ${request.cellLabel}` : null,
  ]
    .filter(Boolean)
    .join(" · ");
  const openExpanded = steps.open.expanded || showOpenStep;
  // Основная кнопка и так отправит всё, что дошло, — ссылка нужна, только
  // когда она заблокирована.
  const offerFallback =
    !submitState.canSubmit &&
    shouldOfferNoPhotoFallback({
      photoTrouble,
      firstCaptureAt,
      uploaded: submitState.uploaded,
      nowMs,
    });
  const fallback = describeNoPhotoFallback(submitState.uploaded);

  return (
    <section ref={sectionRef} className="return-flow" aria-labelledby={titleId}>
      <header className="return-flow-head">
        <p className="return-flow-eyebrow">Возврат</p>
        <h2 id={titleId} ref={titleRef} tabIndex={-1} className="return-flow-title">
          Сдайте вещь в постамат
        </h2>
        <p className="return-flow-lead">
          Сфотографируйте вещь в открытой ячейке — так мы убедимся, что всё на месте.
        </p>
      </header>

      <ol className="return-steps">
        <ReturnStep
          index={1}
          state={steps.open.state}
          title="Откройте ячейку"
          summary={steps.open.state === "done" ? openSummary || "Ячейка открыта" : null}
          expanded={openExpanded}
          contentId={`${ids}-step-open`}
          onToggle={steps.open.state === "done" ? () => setShowOpenStep((value) => !value) : undefined}
        >
          {request.pin ? (
            <div className="return-pin">
              <div className="return-pin-top">
                <span className="return-pin-label">
                  <KeyRound size={14} aria-hidden="true" />
                  PIN-код
                </span>
                <button
                  type="button"
                  className={`return-pin-copy${pinCopied ? " is-copied" : ""}`}
                  onClick={() => void copyPin(request.pin as string)}
                >
                  {pinCopied ? <Check size={14} aria-hidden="true" /> : <Copy size={14} aria-hidden="true" />}
                  {pinCopied ? "Скопировано" : "Копировать"}
                </button>
              </div>
              <p className="return-pin-keys">
                <span className="return-sr-only">{pinDigits.join(" ")}</span>
                {pinDigits.map((digit, index) => (
                  <span key={`${digit}-${index}`} className="return-pin-key" aria-hidden="true">
                    {digit}
                  </span>
                ))}
              </p>
              {request.cellLabel || expiresClock ? (
                <div className="return-pin-meta">
                  {request.cellLabel ? (
                    <span className="return-chip">
                      <CellGlyph />
                      Ячейка {request.cellLabel}
                    </span>
                  ) : null}
                  {expiresClock ? (
                    <span className={`return-chip${expired ? " is-danger" : ""}`}>
                      <Clock3 size={14} aria-hidden="true" />
                      {expired
                        ? "Срок кода истёк"
                        : `до ${expiresClock}${timeLeft ? ` · ${timeLeft}` : ""}`}
                    </span>
                  ) : null}
                </div>
              ) : null}
            </div>
          ) : (
            <p className="return-step-text">
              PIN-код ещё не пришёл. Обновите страницу через пару секунд.
            </p>
          )}
          <p className="return-step-text">
            Наберите код на клавиатуре постамата — дверца ячейки откроется.
          </p>
          {steps.open.state !== "done" ? (
            <button
              type="button"
              className="button button-primary return-step-action"
              onClick={() => {
                setCellOpened(true);
                setShowOpenStep(false);
                // Кнопка исчезает вместе с шагом — фокус на следующий шаг.
                requestFocus("shoot");
              }}
            >
              <DoorOpen size={18} aria-hidden="true" />
              Ячейка открылась
            </button>
          ) : null}
        </ReturnStep>

        <ReturnStep
          index={2}
          state={steps.shoot.state}
          title="Сфотографируйте вещь в ячейке"
          summary={steps.shoot.expanded ? null : "Не закрывайте дверцу до фото"}
          expanded={steps.shoot.expanded}
          contentId={`${ids}-step-shoot`}
          headingRef={shootHeadingRef}
        >
          <p className="return-warn">
            <DoorOpen size={16} aria-hidden="true" />
            <span>
              <strong>Не закрывайте дверцу.</strong> Закрытая ячейка сразу принимает возврат —
              сначала фото.
            </span>
          </p>
          {capture}
          {noteField}
        </ReturnStep>

        <ReturnStep
          index={3}
          state={steps.close.state}
          title="Закройте дверцу и подтвердите"
          summary={steps.close.expanded ? null : "Фото уйдёт вместе с возвратом"}
          expanded={steps.close.expanded}
          contentId={`${ids}-step-close`}
        >
          <p className="return-step-text">
            Проверьте, что вещь внутри, и захлопните дверцу до щелчка. Потом нажмите кнопку —
            фото уйдут вместе с возвратом.
          </p>
          {errorBlock}
          <div className="return-submit-block">
            <button
              type="button"
              className="button button-primary return-submit"
              disabled={!submitState.canSubmit || submitting}
              aria-describedby={submitHint ? hintId : undefined}
              onClick={() => void submit()}
            >
              {submitting ? (
                <>
                  <LoaderCircle size={18} className="return-spin" aria-hidden="true" />
                  Завершаем возврат…
                </>
              ) : (
                <>
                  <DoorClosed size={18} aria-hidden="true" />
                  Дверца закрыта — вернуть
                </>
              )}
            </button>
            {submitHint ? (
              <p id={hintId} className="return-submit-hint">
                {submitHint}
              </p>
            ) : null}
            {offerFallback ? (
              <button
                ref={noPhotoTriggerRef}
                type="button"
                className="return-link is-quiet"
                disabled={submitting}
                aria-haspopup="dialog"
                onClick={() => setShowNoPhotoDialog(true)}
              >
                Не получается отправить фото
              </button>
            ) : null}
          </div>
        </ReturnStep>
      </ol>

      {fileInput}
      {liveRegion}

      {showNoPhotoDialog ? (
        <div
          className="modal-overlay"
          role="dialog"
          aria-modal="true"
          aria-labelledby={dialogTitleId}
          aria-describedby={dialogTextId}
          onClick={(event) => {
            if (event.target === event.currentTarget && !submitting) setShowNoPhotoDialog(false);
          }}
        >
          <div ref={dialogRef} className="modal-box">
            <div className="modal-icon">
              <CameraOff size={28} aria-hidden="true" />
            </div>
            <h2 id={dialogTitleId} className="modal-title">
              {fallback.title}
            </h2>
            <p id={dialogTextId} className="modal-text">
              {fallback.text}
            </p>
            <div className="modal-actions">
              <div className="modal-actions-row">
                <button
                  className="button button-primary"
                  type="button"
                  disabled={submitting}
                  onClick={() => void submit({ fromDialog: true })}
                >
                  {submitting ? "Завершаем…" : fallback.action}
                </button>
              </div>
              <div className="modal-back">
                {/* Фокус по умолчанию — на безопасном действии: Enter не завершит возврат без фото. */}
                <button
                  type="button"
                  autoFocus
                  disabled={submitting}
                  onClick={() => setShowNoPhotoDialog(false)}
                >
                  Попробовать отправить фото ещё раз
                </button>
              </div>
            </div>
          </div>
        </div>
      ) : null}
    </section>
  );
}

// ── Шаг степпера ────────────────────────────────────────────────────────────

function ReturnStep({
  index,
  state,
  title,
  summary,
  expanded,
  contentId,
  onToggle,
  headingRef,
  children,
}: {
  index: number;
  state: ReturnStepState;
  title: string;
  summary?: string | null;
  expanded: boolean;
  contentId: string;
  onToggle?: () => void;
  /** Заголовок, на который можно перевести фокус, когда шаг становится текущим. */
  headingRef?: RefObject<HTMLHeadingElement | null>;
  children: ReactNode;
}) {
  const stateLabel = state === "done" ? "выполнен" : state === "current" ? "текущий" : "впереди";
  const titleContent = (
    <span className="return-step-titles">
      <span className="return-step-title">
        <span className="return-sr-only">
          Шаг {index}, {stateLabel}:{" "}
        </span>
        {title}
      </span>
      {summary ? <span className="return-step-summary">{summary}</span> : null}
    </span>
  );
  return (
    <li
      className={`return-step is-${state}${expanded ? " is-expanded" : ""}`}
      aria-current={state === "current" ? "step" : undefined}
    >
      <span className="return-step-marker" aria-hidden="true">
        {state === "done" ? <Check size={16} strokeWidth={3} /> : index}
      </span>
      <div className="return-step-main">
        <h3
          ref={headingRef}
          className="return-step-heading"
          tabIndex={headingRef && !onToggle ? -1 : undefined}
        >
          {onToggle ? (
            <button
              type="button"
              className="return-step-toggle"
              aria-expanded={expanded}
              aria-controls={expanded ? contentId : undefined}
              onClick={onToggle}
            >
              {titleContent}
              <ChevronDown size={18} className="return-step-chevron" aria-hidden="true" />
            </button>
          ) : (
            titleContent
          )}
        </h3>
        {expanded ? (
          <div id={contentId} className="return-step-body">
            {children}
          </div>
        ) : null}
      </div>
    </li>
  );
}

// ── Кадр возврата ───────────────────────────────────────────────────────────

function PhotoCapture({
  frameRef,
  late,
  shots,
  activeShot,
  activeIndex,
  maxPhotos,
  canAddMore,
  flash,
  onFlashEnd,
  disabled,
  onCapture,
  onRetake,
  onRetry,
  onRemove,
  onSelect,
}: {
  frameRef: RefObject<HTMLDivElement | null>;
  late: boolean;
  shots: Shot[];
  activeShot: Shot | null;
  activeIndex: number;
  maxPhotos: number;
  canAddMore: boolean;
  flash: number;
  onFlashEnd: () => void;
  disabled: boolean;
  onCapture: () => void;
  onRetake: (key: string) => void;
  onRetry: (key: string) => void;
  onRemove: (key: string) => void;
  onSelect: (key: string) => void;
}) {
  const status = activeShot?.status ?? "empty";
  const pending = status === "preparing" || status === "uploading";
  const src = activeShot ? activeShot.previewUrl ?? activeShot.thumb : null;
  const percent = activeShot ? Math.round(activeShot.progress * 100) : 0;

  return (
    <div className="return-capture">
      <div
        ref={frameRef}
        className={`return-shot is-${status}`}
        role="group"
        aria-label={late ? "Фото вещи" : "Кадр возврата"}
        tabIndex={-1}
      >
        <span className="return-shot-corner is-tl" aria-hidden="true" />
        <span className="return-shot-corner is-tr" aria-hidden="true" />
        <span className="return-shot-corner is-bl" aria-hidden="true" />
        <span className="return-shot-corner is-br" aria-hidden="true" />

        {activeShot ? (
          <>
            {src ? (
              <img
                key={src}
                className="return-shot-img"
                src={src}
                alt={`Фото ${activeIndex + 1} из ${shots.length}: вещь в ячейке`}
              />
            ) : (
              <span className="return-shot-developing" aria-hidden="true" />
            )}
            <span className="return-shot-scrim" aria-hidden="true" />
            {pending ? <span className="return-shot-scan" aria-hidden="true" /> : null}

            {pending ? (
              <div className="return-shot-hud">
                <span className="return-shot-status">
                  <span>{status === "preparing" ? "Готовим снимок…" : "Отправляем…"}</span>
                  {status === "uploading" ? <span className="return-shot-percent">{percent}%</span> : null}
                </span>
                <span
                  className={`return-shot-progress${status === "preparing" ? " is-indeterminate" : ""}`}
                  role="progressbar"
                  aria-label="Отправка фото"
                  aria-valuemin={0}
                  aria-valuemax={100}
                  aria-valuenow={status === "uploading" ? percent : undefined}
                >
                  <span style={status === "uploading" ? { transform: `scaleX(${activeShot.progress})` } : undefined} />
                </span>
              </div>
            ) : null}

            {status === "uploaded" ? (
              <span className="return-shot-stamp">
                <Check size={14} strokeWidth={3} aria-hidden="true" />
                Фото получено
              </span>
            ) : null}

            {status === "failed" ? (
              <div className="return-shot-fail">
                <span className="return-shot-fail-title">
                  <TriangleAlert size={16} aria-hidden="true" />
                  Не отправилось
                </span>
                <button
                  type="button"
                  className="button button-sm return-shot-retry"
                  disabled={disabled}
                  onClick={() => onRetry(activeShot.key)}
                >
                  <RefreshCcw size={15} aria-hidden="true" />
                  Повторить
                </button>
              </div>
            ) : null}
          </>
        ) : (
          <div className="return-shot-empty">
            <LockerCellArt />
            <p className="return-shot-caption">
              {late ? "Фото вещи в ячейке" : "Вещь в открытой ячейке"}
            </p>
            <button
              type="button"
              className="button button-primary return-shot-cta"
              disabled={disabled}
              onClick={onCapture}
            >
              {late ? <ImageUp size={18} aria-hidden="true" /> : <Camera size={18} aria-hidden="true" />}
              {late ? "Выбрать фото" : "Сделать фото"}
            </button>
          </div>
        )}

        {flash > 0 ? (
          <span
            key={flash}
            className="return-shot-flash"
            aria-hidden="true"
            onAnimationEnd={onFlashEnd}
          />
        ) : null}
      </div>

      {activeShot && status === "failed" && activeShot.error ? (
        <p className="return-error" role="alert">
          <TriangleAlert size={16} aria-hidden="true" />
          <span>{activeShot.error}</span>
        </p>
      ) : null}

      {/* Панель видна и во время отправки: зависший кадр можно отменить или переснять. */}
      {activeShot ? (
        <div className="return-shot-toolbar">
          <button
            type="button"
            className="button button-secondary button-sm"
            disabled={disabled}
            onClick={() => onRetake(activeShot.key)}
          >
            <Camera size={15} aria-hidden="true" />
            Переснять
          </button>
          <button
            type="button"
            className="button button-ghost button-sm"
            disabled={disabled}
            onClick={() => onRemove(activeShot.key)}
          >
            {pending ? <X size={15} aria-hidden="true" /> : <Trash2 size={15} aria-hidden="true" />}
            {pending ? "Отменить" : "Удалить"}
          </button>
        </div>
      ) : null}

      {shots.length > 0 ? (
        <div className="return-strip-wrap">
          <ul className="return-strip" aria-label={`Ракурсы: ${shots.length} из ${maxPhotos}`}>
            {shots.map((shot, index) => {
              const thumb = shot.previewUrl ?? shot.thumb;
              const isActive = activeShot?.key === shot.key;
              const label =
                shot.status === "uploaded"
                  ? "отправлено"
                  : shot.status === "failed"
                    ? "ошибка отправки"
                    : "отправляется";
              return (
                <li key={shot.key}>
                  <button
                    type="button"
                    className={`return-strip-tile is-${shot.status}${isActive ? " is-active" : ""}`}
                    aria-pressed={isActive}
                    aria-label={`Фото ${index + 1}, ${label}`}
                    onClick={() => onSelect(shot.key)}
                  >
                    {thumb ? <img src={thumb} alt="" /> : <Camera size={18} aria-hidden="true" />}
                    <span className="return-strip-badge" aria-hidden="true">
                      {shot.status === "uploaded" ? (
                        <Check size={11} strokeWidth={3.5} />
                      ) : shot.status === "failed" ? (
                        <TriangleAlert size={10} strokeWidth={3} />
                      ) : (
                        <LoaderCircle size={11} strokeWidth={3} className="return-spin" />
                      )}
                    </span>
                  </button>
                </li>
              );
            })}
            {canAddMore ? (
              <li>
                <button
                  type="button"
                  className="return-strip-add"
                  disabled={disabled}
                  onClick={onCapture}
                >
                  <Plus size={18} aria-hidden="true" />
                  <span>ещё ракурс</span>
                </button>
              </li>
            ) : null}
          </ul>
        </div>
      ) : null}
    </div>
  );
}

function NoteField({
  id,
  open,
  value,
  disabled,
  onOpen,
  onChange,
}: {
  id: string;
  open: boolean;
  value: string;
  disabled: boolean;
  onOpen: () => void;
  onChange: (value: string) => void;
}) {
  if (!open) {
    return (
      <button type="button" className="return-link" aria-expanded={false} onClick={onOpen}>
        <MessageSquarePlus size={16} aria-hidden="true" />
        Добавить комментарий
      </button>
    );
  }
  return (
    <div className="return-note">
      <label htmlFor={id} className="return-note-label">
        Комментарий <span>по желанию</span>
      </label>
      <textarea
        id={id}
        className="textarea return-note-input"
        rows={3}
        maxLength={RETURN_NOTE_MAX}
        value={value}
        disabled={disabled}
        autoFocus={!value}
        placeholder="Например: в комплекте не хватает чехла"
        onChange={(event) => onChange(event.target.value)}
      />
      <span className="return-note-count">
        {value.length}/{RETURN_NOTE_MAX}
      </span>
    </div>
  );
}

// ── Квитанция возврата ──────────────────────────────────────────────────────

function ReturnReceipt({
  receiptRef,
  report,
  returnedAt,
  lockerName,
  cellLabel,
  bonusAccrued,
  currency,
  localPreviews,
  fresh,
}: {
  receiptRef: RefObject<HTMLElement | null>;
  report: ReturnReport;
  returnedAt?: string | null;
  lockerName: string | null;
  cellLabel: string | null;
  bonusAccrued: number;
  currency?: string;
  localPreviews: Map<string, string>;
  fresh: boolean;
}) {
  const titleId = useId();
  const photos = report.photos;
  const [main, ...rest] = photos;

  return (
    <div className={`return-receipt-wrap${fresh ? " is-fresh" : ""}`}>
      <section ref={receiptRef} className="return-receipt" aria-labelledby={titleId} tabIndex={-1}>
        <div className="return-receipt-grid">
          <div className="return-receipt-media">
            <div className="return-receipt-main">
              {main ? (
                <ReceiptPhoto
                  local={localPreviews.get(main.id) ?? null}
                  remote={resolvePublicAssetUrl(main.url)}
                  alt={photos.length > 1 ? `Фото 1 из ${photos.length}: вещь в ячейке` : "Фото вещи в ячейке"}
                />
              ) : (
                <span className="return-receipt-photo is-empty">
                  <CameraOff size={22} aria-hidden="true" />
                  <span>Без фото</span>
                </span>
              )}
              <span className="return-receipt-stamp" aria-hidden="true">
                <Check size={11} strokeWidth={3.5} />
                Принято
              </span>
            </div>
            {rest.length > 0 ? (
              <div className="return-receipt-thumbs">
                {rest.slice(0, 3).map((photo, index) => (
                  <ReceiptPhoto
                    key={photo.id}
                    small
                    local={localPreviews.get(photo.id) ?? null}
                    remote={resolvePublicAssetUrl(photo.url)}
                    alt={`Фото ${index + 2} из ${photos.length}`}
                  />
                ))}
              </div>
            ) : null}
          </div>

          <div className="return-receipt-info">
            <p className="return-receipt-kicker">Квитанция возврата</p>
            <h2 id={titleId} className="return-receipt-title">
              Возврат принят
            </h2>
            <dl className="return-receipt-rows">
              {lockerName ? (
                <div>
                  <dt>Постамат</dt>
                  <dd>{lockerName}</dd>
                </div>
              ) : null}
              {cellLabel ? (
                <div>
                  <dt>Ячейка</dt>
                  <dd>{cellLabel}</dd>
                </div>
              ) : null}
              <div>
                <dt>Время</dt>
                <dd>{formatDateTime(returnedAt)}</dd>
              </div>
              <div>
                <dt>Фото</dt>
                <dd>
                  {photos.length
                    ? formatCountRu(photos.length, ["снимок", "снимка", "снимков"])
                    : "не приложено"}
                </dd>
              </div>
              {bonusAccrued > 0 ? (
                <div className="is-bonus">
                  <dt>Бонусы</dt>
                  <dd>+{formatMoney(bonusAccrued, currency)}</dd>
                </div>
              ) : null}
            </dl>
          </div>
        </div>
        {report.note ? (
          <div className="return-receipt-note">
            <span>Ваш комментарий</span>
            <p>{report.note}</p>
          </div>
        ) : null}
      </section>
    </div>
  );
}

function ReceiptPhoto({
  local,
  remote,
  alt,
  small = false,
}: {
  local: string | null;
  remote: string | null;
  alt: string;
  small?: boolean;
}) {
  // Сразу после отправки показываем локальный снимок (не ждём сеть), потом —
  // серверный. Если картинка не загрузилась, пробуем следующий источник.
  const sources = [local, remote].filter((value): value is string => Boolean(value));
  const [failedCount, setFailedCount] = useState(0);
  const src = sources[failedCount] ?? null;
  const className = `return-receipt-photo${small ? " is-small" : ""}`;

  if (!src) {
    return (
      <span className={`${className} is-missing`} role="img" aria-label={alt}>
        <ImageIcon size={small ? 14 : 22} aria-hidden="true" />
      </span>
    );
  }
  const image = (
    <img src={src} alt={alt} loading="lazy" onError={() => setFailedCount((value) => value + 1)} />
  );
  return remote ? (
    <a className={className} href={remote} target="_blank" rel="noreferrer">
      {image}
    </a>
  ) : (
    <span className={className}>{image}</span>
  );
}

// ── Иллюстрации ─────────────────────────────────────────────────────────────

/** Контур открытой ячейки постамата с вещью внутри — пустое состояние кадра. */
function LockerCellArt() {
  return (
    <svg
      className="return-shot-art"
      viewBox="0 0 160 120"
      fill="none"
      stroke="currentColor"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {/* рама ячейки */}
      <rect x="14" y="8" width="96" height="104" rx="8" strokeWidth="2" />
      {/* проём и глубина */}
      <rect x="24" y="18" width="76" height="84" rx="4" strokeWidth="1.5" opacity="0.55" />
      <rect x="36" y="30" width="52" height="60" rx="2" strokeWidth="1.2" opacity="0.28" />
      <path d="M24 18 36 30M100 18 88 30M24 102 36 90M100 102 88 90" strokeWidth="1.2" opacity="0.28" />
      {/* вещь внутри */}
      <path d="M44 90V66a3 3 0 0 1 3-3h30a3 3 0 0 1 3 3v24" strokeWidth="2" />
      <path d="M44 72h36M58 63v9" strokeWidth="1.5" opacity="0.7" />
      {/* открытая дверца */}
      <path d="M110 10 146 22v76l-36 12" strokeWidth="2" />
      <path d="M137 52v14" strokeWidth="3" />
    </svg>
  );
}

function CellGlyph() {
  return (
    <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" aria-hidden="true">
      <rect x="2" y="2" width="12" height="12" rx="2.5" strokeWidth="1.6" />
      <path d="M10.5 7v2.5" strokeWidth="1.8" strokeLinecap="round" />
    </svg>
  );
}
