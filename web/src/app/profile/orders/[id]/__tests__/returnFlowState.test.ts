import { describe, expect, it } from "vitest";
import { ApiError } from "@/shared/api/client";
import type { RentalDetail, RentalListItem, ReturnReport } from "@/shared/api/types";
import { FILE_TOO_LARGE_MESSAGE, UPLOAD_NETWORK_MESSAGE } from "@/shared/imageUpload";
import {
  RETURN_ATTACH_GRACE_MS,
  RETURN_CAMERA_STUCK_MS,
  RETURN_DRAFT_MAX_AGE_MS,
  RETURN_NOTE_MAX,
  applyConfirmReturnResult,
  clearReturnDraft,
  deriveReturnFlowMode,
  deriveReturnSteps,
  describeNoPhotoFallback,
  describeReturnClosed,
  describeReturnError,
  formatTimeLeft,
  getReturnCompletedBy,
  getReturnSubmitState,
  mergeRentalDetailIntoListItem,
  parseReturnDraft,
  pickReturnRequest,
  readReturnDraft,
  resolveMaxPhotos,
  returnDraftKey,
  serializeReturnDraft,
  shouldOfferNoPhotoFallback,
  splitPin,
  writeReturnDraft,
  type DraftStorage,
  type ReturnDraft,
} from "../returnFlowState";

const NOW = Date.parse("2026-09-15T12:00:00Z");

function report(overrides: Partial<ReturnReport> = {}): ReturnReport {
  return {
    photos: [],
    note: null,
    submittedAt: null,
    canAttachPhotos: false,
    attachPhotosUntil: null,
    maxPhotos: 4,
    ...overrides,
  };
}

const listItem: RentalListItem = {
  id: "rental-1",
  status: "return_in_progress",
  pickupPin: null,
  returnRequest: {
    id: "rr-1",
    rentalId: "rental-1",
    status: "created",
    lockerId: "locker-1",
    lockerName: "ТЦ Галерея",
    cellId: "cell-1",
    cellLabel: "12",
    pin: "4821",
    expiresAt: "2026-09-15T12:30:00Z",
  },
  returnReport: report({ canAttachPhotos: true }),
  actualEndAt: null,
  product: { id: "p-1", name: "Палатка" },
  locker: { id: "locker-1", name: "ТЦ Галерея" },
};

function detail(overrides: Partial<RentalDetail> = {}): RentalDetail {
  return {
    id: "rental-1",
    status: "completed",
    product: { id: "p-1", name: "Палатка" },
    pickupLocker: { id: "locker-1", name: "ТЦ Галерея" },
    paymentSummary: { preauthAmount: 0, capturedAmount: 0, bonusSpent: 0, bonusAccrued: 0, currency: "RUB" },
    events: [],
    ...overrides,
  };
}

class MemoryStorage implements DraftStorage {
  data = new Map<string, string>();
  failNextWrites = 0;

  getItem(key: string) {
    return this.data.get(key) ?? null;
  }

  setItem(key: string, value: string) {
    if (this.failNextWrites > 0) {
      this.failNextWrites -= 1;
      throw new DOMException("quota", "QuotaExceededError");
    }
    this.data.set(key, value);
  }

  removeItem(key: string) {
    this.data.delete(key);
  }
}

describe("deriveReturnFlowMode", () => {
  it("shows the stepper while the return is in progress", () => {
    expect(deriveReturnFlowMode({ status: "return_in_progress", returnReport: null }, NOW)).toBe(
      "in_progress",
    );
  });

  it("offers a late photo when the locker door completed the return", () => {
    const late = report({ canAttachPhotos: true, attachPhotosUntil: "2026-09-15T13:30:00Z" });
    expect(deriveReturnFlowMode({ status: "completed", returnReport: late }, NOW)).toBe("late");
  });

  it("hides the late state once the attach window and the clock grace have passed", () => {
    const expired = report({ canAttachPhotos: true, attachPhotosUntil: "2026-09-15T11:58:00Z" });
    expect(deriveReturnFlowMode({ status: "completed", returnReport: expired }, NOW)).toBe("none");
  });

  // Часы телефона чуть впереди сервера — блок не должен пропадать раньше срока.
  it("keeps the late state within the clock grace after attachPhotosUntil", () => {
    const until = new Date(NOW - RETURN_ATTACH_GRACE_MS + 1_000).toISOString();
    const late = report({ canAttachPhotos: true, attachPhotosUntil: until });
    expect(deriveReturnFlowMode({ status: "completed", returnReport: late }, NOW)).toBe("late");
  });

  // Фото в пути или идёт отправка — ответ сервера важнее часов клиента.
  it("holds the late state while an upload or submit is in flight", () => {
    const expired = report({ canAttachPhotos: true, attachPhotosUntil: "2026-09-15T11:00:00Z" });
    const snapshot = { status: "completed", returnReport: expired };
    expect(deriveReturnFlowMode(snapshot, NOW, { holdLate: true })).toBe("late");
    expect(deriveReturnFlowMode(snapshot, NOW, { holdLate: false })).toBe("none");
  });

  // Подтвердили без фото, но с комментарием: отчёт есть, а досылка ещё открыта.
  it("keeps offering late photos for a photo-less report while the server allows it", () => {
    const noteOnly = report({
      note: "чехол порван",
      submittedAt: "2026-09-15T11:50:00Z",
      canAttachPhotos: true,
      attachPhotosUntil: "2026-09-15T13:50:00Z",
    });
    expect(deriveReturnFlowMode({ status: "completed", returnReport: noteOnly }, NOW)).toBe("late");
    // Окно закрылось — показываем квитанцию «Без фото», а не пустоту.
    const closed = { ...noteOnly, canAttachPhotos: false, attachPhotosUntil: null };
    expect(deriveReturnFlowMode({ status: "completed", returnReport: closed }, NOW)).toBe("receipt");
    const expiredOnClient = { ...noteOnly, attachPhotosUntil: "2026-09-15T11:00:00Z" };
    expect(deriveReturnFlowMode({ status: "completed", returnReport: expiredOnClient }, NOW)).toBe(
      "receipt",
    );
  });

  it("shows the receipt once a report was submitted", () => {
    const sent = report({
      photos: [{ id: "m-1", url: "/assets/runtime-uploads/condition/m-1.jpg" }],
      submittedAt: "2026-09-15T11:40:00Z",
    });
    expect(deriveReturnFlowMode({ status: "completed", returnReport: sent }, NOW)).toBe("receipt");
    // Отчёт с фото закрывает досылку, даже если сервер по старой памяти прислал canAttachPhotos.
    expect(
      deriveReturnFlowMode({ status: "completed", returnReport: { ...sent, canAttachPhotos: true } }, NOW),
    ).toBe("receipt");
  });

  it("stays out of the way for rentals without a locker return", () => {
    expect(deriveReturnFlowMode({ status: "active", returnReport: null }, NOW)).toBe("none");
    expect(deriveReturnFlowMode({ status: "completed", returnReport: null }, NOW)).toBe("none");
    expect(deriveReturnFlowMode({ status: "completed", returnReport: report() }, NOW)).toBe("none");
    expect(
      deriveReturnFlowMode({ status: "incident", returnReport: report({ canAttachPhotos: true }) }, NOW),
    ).toBe("none");
  });
});

describe("resolveMaxPhotos", () => {
  it("falls back to four when the report is missing or broken", () => {
    expect(resolveMaxPhotos(null)).toBe(4);
    expect(resolveMaxPhotos(report({ maxPhotos: 0 }))).toBe(4);
    expect(resolveMaxPhotos(report({ maxPhotos: 3 }))).toBe(3);
  });
});

describe("getReturnCompletedBy", () => {
  it("reads the latest return_completed event", () => {
    const events: RentalDetail["events"] = [
      { id: "1", eventType: "return_requested", source: "user", createdAt: "2026-09-15T11:00:00Z" },
      { id: "2", eventType: "return_completed", source: "locker_webhook", createdAt: "2026-09-15T11:10:00Z" },
    ];
    expect(getReturnCompletedBy(events)).toBe("locker");
    expect(
      getReturnCompletedBy([
        ...events,
        { id: "3", eventType: "return_completed", source: "user", createdAt: "2026-09-15T11:11:00Z" },
      ]),
    ).toBe("user");
    expect(getReturnCompletedBy([])).toBe("unknown");
    expect(getReturnCompletedBy(undefined)).toBe("unknown");
  });
});

describe("pickReturnRequest", () => {
  it("prefers the server request and falls back to the local return-request answer", () => {
    expect(pickReturnRequest(null, undefined, { pin: "7777", cellLabel: "3" })).toEqual({
      pin: "7777",
      cellLabel: "3",
      lockerName: null,
      expiresAt: null,
    });
    expect(pickReturnRequest(listItem.returnRequest, { pin: "0000" }).pin).toBe("4821");
    expect(pickReturnRequest({ pin: "  " }, { pin: "1234" }).pin).toBe("1234");
  });
});

describe("mergeRentalDetailIntoListItem", () => {
  it("takes the fresh status and report from a poll", () => {
    const fresh = detail({
      actualEndAt: "2026-09-15T11:10:00Z",
      returnRequest: null,
      returnReport: report({ canAttachPhotos: true, attachPhotosUntil: "2026-09-15T13:10:00Z" }),
    });
    const merged = mergeRentalDetailIntoListItem(listItem, fresh);
    expect(merged.status).toBe("completed");
    expect(merged.returnRequest).toBeNull();
    expect(merged.returnReport?.attachPhotosUntil).toBe("2026-09-15T13:10:00Z");
    expect(merged.actualEndAt).toBe("2026-09-15T11:10:00Z");
    expect(merged.product).toBe(listItem.product);
  });

  it("keeps list fields an older backend did not send in the detail", () => {
    const merged = mergeRentalDetailIntoListItem(listItem, detail({ status: "return_in_progress" }));
    expect(merged.returnRequest).toBe(listItem.returnRequest);
    expect(merged.returnReport).toBe(listItem.returnReport);
  });
});

describe("applyConfirmReturnResult", () => {
  it("switches to the submitted report right away", () => {
    const sent = report({ photos: [{ id: "m-1", url: null }], submittedAt: "2026-09-15T12:00:00Z" });
    const next = applyConfirmReturnResult(listItem, {
      rental: { id: "rental-1", status: "completed" },
      returnReport: sent,
    });
    expect(next.status).toBe("completed");
    expect(next.returnRequest).toBeNull();
    expect(deriveReturnFlowMode(next, NOW)).toBe("receipt");
  });

  it("keeps the current report when an old backend answers without one", () => {
    const next = applyConfirmReturnResult(listItem, { rental: { id: "rental-1", status: "completed" } });
    expect(next.returnReport).toBe(listItem.returnReport);
  });
});

describe("deriveReturnSteps and getReturnSubmitState", () => {
  it("starts on the cell step", () => {
    const steps = deriveReturnSteps({ cellOpened: false, shots: [] });
    expect(steps.open).toEqual({ state: "current", expanded: true });
    expect(steps.shoot.state).toBe("upcoming");
    expect(steps.close.expanded).toBe(false);
  });

  it("collapses the opened cell and waits for a photo", () => {
    const steps = deriveReturnSteps({ cellOpened: true, shots: [{ status: "uploading" }] });
    expect(steps.open).toEqual({ state: "done", expanded: false });
    expect(steps.shoot).toEqual({ state: "current", expanded: true });
    expect(steps.close).toEqual({ state: "upcoming", expanded: true });
  });

  it("marks the photo step done and the close step current after an upload", () => {
    const steps = deriveReturnSteps({ cellOpened: false, shots: [{ status: "uploaded" }] });
    expect(steps.open.state).toBe("done");
    expect(steps.shoot.state).toBe("done");
    expect(steps.close.state).toBe("current");
  });

  it("enables confirm only with an uploaded photo and nothing in flight", () => {
    expect(getReturnSubmitState([])).toMatchObject({ canSubmit: false, blockedBy: "no_photo" });
    expect(getReturnSubmitState([{ status: "failed" }])).toMatchObject({
      canSubmit: false,
      blockedBy: "no_photo",
    });
    expect(getReturnSubmitState([{ status: "uploaded" }, { status: "preparing" }])).toMatchObject({
      canSubmit: false,
      blockedBy: "uploading",
    });
    expect(getReturnSubmitState([{ status: "uploaded" }, { status: "failed" }])).toMatchObject({
      canSubmit: true,
      blockedBy: null,
      uploaded: 1,
      failed: 1,
    });
  });
});

describe("describeReturnClosed", () => {
  it("explains an expired late window instead of silently removing the block", () => {
    const notice = describeReturnClosed("late", "completed");
    expect(notice?.title).toContain("дослать фото");
    expect(notice?.text).toContain("возврат принят");
  });

  it("explains why an in-progress return disappeared, by the new rental status", () => {
    expect(describeReturnClosed("in_progress", "incident")?.tone).toBe("warn");
    expect(describeReturnClosed("in_progress", "incident")?.text).toMatch(/поддержку/);
    expect(describeReturnClosed("in_progress", "active")?.text).toMatch(/Оформите возврат заново/);
    expect(describeReturnClosed("in_progress", "overdue")?.title).toMatch(/Код возврата/);
    expect(describeReturnClosed("in_progress", "completed")?.tone).toBe("ok");
    expect(describeReturnClosed("in_progress", "cancelled")?.title).toBeTruthy();
  });

  it("stays silent when nothing was on screen before", () => {
    expect(describeReturnClosed("none", "active")).toBeNull();
    expect(describeReturnClosed("receipt", "completed")).toBeNull();
  });
});

describe("no-photo fallback", () => {
  const base = { photoTrouble: false, firstCaptureAt: null, uploaded: 0, nowMs: NOW };

  it("appears after an upload problem or an empty capture", () => {
    expect(shouldOfferNoPhotoFallback(base)).toBe(false);
    expect(shouldOfferNoPhotoFallback({ ...base, photoTrouble: true })).toBe(true);
  });

  // Камера молчит (запрет доступа в Safari, WebView): change-события нет вовсе.
  it("appears when the camera gave no photo for a minute after the first attempt", () => {
    const opened = { ...base, firstCaptureAt: NOW - RETURN_CAMERA_STUCK_MS + 1 };
    expect(shouldOfferNoPhotoFallback(opened)).toBe(false);
    expect(shouldOfferNoPhotoFallback({ ...opened, nowMs: NOW + 1 })).toBe(true);
    expect(shouldOfferNoPhotoFallback({ ...opened, nowMs: NOW + 1, uploaded: 1 })).toBe(false);
  });

  it("finishes with the photos that already arrived and never promises what it cannot do", () => {
    const none = describeNoPhotoFallback(0);
    expect(none.action).toBe("Завершить без фото");
    expect(none.text).toContain("дослать");

    const one = describeNoPhotoFallback(1);
    expect(one.action).toBe("Завершить с тем, что есть");
    expect(one.text).toContain("фото, которое уже дошло");
    // Отчёт с фото закрывает досылку — «можно будет дослать» здесь было бы неправдой.
    expect(one.text).toContain("дослать их потом не получится");
    expect(describeNoPhotoFallback(3).text).toContain("3 фото, которые уже дошли");

    for (const view of [none, one]) {
      expect(view.text).toContain("закройте дверцу");
    }
  });
});

describe("describeReturnError", () => {
  const confirm = (code: string, status = 409) =>
    describeReturnError(new ApiError(code, status, code), { stage: "confirm", maxPhotos: 4 });

  it("translates every confirm-return code into Russian without leaking the code", () => {
    const codes = [
      "RETURN_PHOTOS_TOO_MANY",
      "RETURN_PHOTO_INVALID",
      "RETURN_PHOTO_NOT_UPLOADED",
      "RETURN_PHOTOS_WINDOW_CLOSED",
      "RETURN_PHOTOS_ALREADY_SENT",
      "RENTAL_NOT_RETURNING",
      "RETURN_REQUEST_NOT_FOUND",
      "RETURN_REQUEST_NOT_ACTIVE",
      "CONFIRM_RETURN_FAILED",
      "SOMETHING_NEW",
    ];
    for (const code of codes) {
      const view = confirm(code);
      expect(view.message).not.toMatch(/[A-Z]{3,}_/);
      expect(view.message).toMatch(/[а-яё]/i);
    }
    expect(confirm("RETURN_PHOTOS_TOO_MANY", 400).message).toContain("4 фото");
  });

  it("reveals the no-photo escape hatch only for photo problems", () => {
    expect(confirm("RETURN_PHOTO_INVALID", 400).photoProblem).toBe(true);
    expect(confirm("RETURN_PHOTO_NOT_UPLOADED").photoProblem).toBe(true);
    expect(confirm("RETURN_REQUEST_NOT_FOUND").photoProblem).toBe(false);
    expect(confirm("CONFIRM_RETURN_FAILED", 500).photoProblem).toBe(false);
  });

  it("asks to reload the order when the server state moved on", () => {
    expect(confirm("RETURN_PHOTOS_ALREADY_SENT").refresh).toBe(true);
    expect(confirm("RETURN_PHOTOS_WINDOW_CLOSED").refresh).toBe(true);
    expect(confirm("RENTAL_NOT_RETURNING").refresh).toBe(true);
    expect(confirm("CONFIRM_RETURN_FAILED").refresh).toBe(false);
  });

  it("maps presign codes and network failures for uploads", () => {
    const upload = (error: unknown) => describeReturnError(error, { stage: "upload" });
    expect(upload(new ApiError("FILE_TOO_LARGE", 400, "FILE_TOO_LARGE")).message).toBe(
      FILE_TOO_LARGE_MESSAGE,
    );
    expect(upload(new ApiError("INVALID_MIME_TYPE", 400, "INVALID_MIME_TYPE")).message).toContain("JPG");
    expect(upload(new ApiError("INVALID_FILE_KIND", 400, "INVALID_FILE_KIND")).message).toMatch(/[а-я]/);
    const offline = upload(
      new ApiError("Не удалось связаться с сервером. Проверьте, что backend запущен.", 0, "NETWORK_ERROR"),
    );
    expect(offline.message).not.toContain("backend");
    expect(offline.photoProblem).toBe(true);
    expect(upload(new Error(UPLOAD_NETWORK_MESSAGE)).message).toBe(UPLOAD_NETWORK_MESSAGE);
    expect(upload("boom").message).toBe(UPLOAD_NETWORK_MESSAGE);
  });

  it("never mentions documents in upload errors", () => {
    for (const code of ["FILE_TOO_LARGE", "INVALID_MIME_TYPE", "INVALID_FILE_KIND", "EMPTY_UPLOAD", "NETWORK_ERROR"]) {
      const view = describeReturnError(new ApiError(code, 400, code), { stage: "upload" });
      expect(view.message).not.toMatch(/документ/i);
    }
  });
});

describe("return draft in sessionStorage", () => {
  const draft: ReturnDraft = {
    rentalId: "rental-1",
    photos: [
      { fileId: "0b6f5c0e-1111-4c1a-9a55-5e5cc3a1a001", thumb: "data:image/jpeg;base64,AAAA" },
      { fileId: "0b6f5c0e-1111-4c1a-9a55-5e5cc3a1a002", thumb: null },
    ],
    note: "Царапина была до аренды",
    cellOpened: true,
    savedAt: NOW - 60_000,
  };

  it("round-trips uploaded photos, note and the opened cell", () => {
    expect(parseReturnDraft(serializeReturnDraft(draft), "rental-1", NOW)).toEqual(draft);
  });

  it("ignores another rental, expired, malformed or foreign drafts", () => {
    const raw = serializeReturnDraft(draft);
    expect(parseReturnDraft(raw, "rental-2", NOW)).toBeNull();
    expect(parseReturnDraft(raw, "rental-1", draft.savedAt + RETURN_DRAFT_MAX_AGE_MS + 1)).toBeNull();
    expect(parseReturnDraft("{not json", "rental-1", NOW)).toBeNull();
    expect(parseReturnDraft(JSON.stringify({ ...JSON.parse(raw), v: 99 }), "rental-1", NOW)).toBeNull();
    expect(parseReturnDraft(null, "rental-1", NOW)).toBeNull();
  });

  it("drops broken photos, duplicates, unsafe thumbs and extra angles", () => {
    const raw = JSON.stringify({
      v: 1,
      rentalId: "rental-1",
      savedAt: NOW,
      cellOpened: false,
      note: "x".repeat(RETURN_NOTE_MAX + 50),
      photos: [
        { fileId: "a-1", thumb: "javascript:alert(1)" },
        { fileId: "a-1", thumb: null },
        { fileId: "../../etc", thumb: null },
        { fileId: 42 },
        null,
        { fileId: "a-2", thumb: "data:image/jpeg;base64,BBBB" },
        { fileId: "a-3" },
        { fileId: "a-4" },
      ],
    });
    const parsed = parseReturnDraft(raw, "rental-1", NOW, 3);
    expect(parsed?.photos).toEqual([
      { fileId: "a-1", thumb: null },
      { fileId: "a-2", thumb: "data:image/jpeg;base64,BBBB" },
      { fileId: "a-3", thumb: null },
    ]);
    expect(parsed?.note).toHaveLength(RETURN_NOTE_MAX);
    // Есть фото — значит, ячейка точно была открыта.
    expect(parsed?.cellOpened).toBe(true);
  });

  it("writes, reads back and clears through storage", () => {
    const storage = new MemoryStorage();
    expect(writeReturnDraft(storage, draft)).toBe(true);
    expect(readReturnDraft(storage, "rental-1", NOW)).toEqual(draft);
    clearReturnDraft(storage, "rental-1");
    expect(storage.getItem(returnDraftKey("rental-1"))).toBeNull();
  });

  it("retries without thumbnails when the quota is exceeded", () => {
    const storage = new MemoryStorage();
    storage.failNextWrites = 1;
    expect(writeReturnDraft(storage, draft)).toBe(true);
    const restored = readReturnDraft(storage, "rental-1", NOW);
    expect(restored?.photos.map((photo) => photo.thumb)).toEqual([null, null]);
    expect(restored?.photos).toHaveLength(2);
  });

  it("removes the key instead of storing an empty draft and survives a missing storage", () => {
    const storage = new MemoryStorage();
    writeReturnDraft(storage, draft);
    writeReturnDraft(storage, { ...draft, photos: [], note: " ", cellOpened: false });
    expect(storage.getItem(returnDraftKey("rental-1"))).toBeNull();
    expect(writeReturnDraft(null, draft)).toBe(false);
    expect(readReturnDraft(null, "rental-1", NOW)).toBeNull();
  });
});

describe("formatting helpers", () => {
  it("formats the time left on the return code", () => {
    expect(formatTimeLeft("2026-09-15T12:24:30Z", NOW)).toBe("ещё 24 мин");
    expect(formatTimeLeft("2026-09-15T13:05:00Z", NOW)).toBe("ещё 1 ч 5 мин");
    expect(formatTimeLeft("2026-09-15T14:00:00Z", NOW)).toBe("ещё 2 ч");
    expect(formatTimeLeft("2026-09-15T12:00:20Z", NOW)).toBe("меньше минуты");
    expect(formatTimeLeft("2026-09-15T11:00:00Z", NOW)).toBeNull();
    expect(formatTimeLeft(null, NOW)).toBeNull();
  });

  it("splits the PIN into keypad cells", () => {
    expect(splitPin("48 21")).toEqual(["4", "8", "2", "1"]);
    expect(splitPin(null)).toEqual([]);
  });
});
