import { afterEach, describe, expect, it, vi } from "vitest";
import {
  FILE_TOO_LARGE_MESSAGE,
  PHOTO_UNREADABLE_MESSAGE,
  UPLOAD_ATTEMPT_TIMEOUT_MS,
  UPLOAD_NETWORK_MESSAGE,
  UPLOAD_STALL_TIMEOUT_MS,
  UploadAbortedError,
  compressImageForUpload,
  isUploadAborted,
  needsImageConversion,
  preparePhotoForUpload,
  putPresignedFile,
  putPresignedFileWithProgress,
  resolveUploadUrl,
  uploadErrorMessage,
  withUploadDeadline,
} from "../imageUpload";
import type { PresignUploadResponse } from "../api/types";

const presign: PresignUploadResponse = {
  fileId: "file-1",
  fileKey: "verification/2026/09/07/file-1.jpg",
  uploadUrl: "/uploads/files/file-1",
  method: "PUT",
  headers: { "Content-Type": "image/jpeg", "X-Upload-Token": "token" },
  expiresIn: 900,
};

const file = new File([new Uint8Array(16)], "doc.jpg", { type: "image/jpeg" });

function jsonResponse(status: number, body: unknown) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe("putPresignedFile", () => {
  it("uploads to the API base when the presign url is relative", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(200, { data: { stored: true } }));
    vi.stubGlobal("fetch", fetchMock);

    await putPresignedFile(presign, file);

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0][0]).toBe(resolveUploadUrl(presign.uploadUrl));
    expect(fetchMock.mock.calls[0][1]).toMatchObject({ method: "PUT", headers: presign.headers });
  });

  // Ровно тот сценарий из прода: мобильная сеть рвёт длинный PUT, fetch падает
  // с TypeError «Failed to fetch». Повтор безопасен — токен живёт 15 минут.
  it("retries a dropped connection and succeeds", async () => {
    vi.useFakeTimers();
    const fetchMock = vi
      .fn()
      .mockRejectedValueOnce(new TypeError("Failed to fetch"))
      .mockResolvedValueOnce(jsonResponse(200, { data: { stored: true } }));
    vi.stubGlobal("fetch", fetchMock);

    const pending = putPresignedFile(presign, file);
    await vi.runAllTimersAsync();

    await expect(pending).resolves.toBeUndefined();
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("reports a readable message when every attempt drops", async () => {
    vi.useFakeTimers();
    const fetchMock = vi.fn().mockRejectedValue(new TypeError("Failed to fetch"));
    vi.stubGlobal("fetch", fetchMock);

    const pending = putPresignedFile(presign, file);
    const assertion = expect(pending).rejects.toThrow(UPLOAD_NETWORK_MESSAGE);
    await vi.runAllTimersAsync();
    await assertion;

    expect(fetchMock).toHaveBeenCalledTimes(3);
  });

  it("retries server errors but not client errors", async () => {
    vi.useFakeTimers();
    const serverFetch = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(500, { detail: "STORAGE_PERSIST_FAILED" }))
      .mockResolvedValueOnce(jsonResponse(200, { data: { stored: true } }));
    vi.stubGlobal("fetch", serverFetch);

    const pending = putPresignedFile(presign, file);
    await vi.runAllTimersAsync();
    await expect(pending).resolves.toBeUndefined();
    expect(serverFetch).toHaveBeenCalledTimes(2);

    const clientFetch = vi.fn().mockResolvedValue(jsonResponse(400, { detail: "INVALID_MIME_TYPE" }));
    vi.stubGlobal("fetch", clientFetch);

    await expect(putPresignedFile(presign, file)).rejects.toThrow(
      "Такой формат не подходит. Загрузите фото в JPG, PNG или WEBP.",
    );
    expect(clientFetch).toHaveBeenCalledTimes(1);
  });

  it("explains an expired upload token instead of showing the code", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(jsonResponse(401, { detail: "INVALID_UPLOAD_TOKEN" })),
    );

    await expect(putPresignedFile(presign, file)).rejects.toThrow(
      "Ссылка на загрузку устарела. Отправьте документы ещё раз.",
    );
  });
});

describe("compressImageForUpload", () => {
  it("keeps small files untouched", async () => {
    await expect(compressImageForUpload(file)).resolves.toBe(file);
  });

  it("falls back to the original file when the browser cannot decode it", async () => {
    // В node нет createImageBitmap — та же ветка, что для HEIC в Chrome.
    const heavy = new File([new Uint8Array(3 * 1024 * 1024)], "photo.heic", {
      type: "image/heic",
    });

    await expect(compressImageForUpload(heavy)).resolves.toBe(heavy);
  });
});

describe("uploadErrorMessage", () => {
  it("keeps the documents wording for verification by default", () => {
    expect(uploadErrorMessage(401, "INVALID_UPLOAD_TOKEN")).toContain("документы");
    expect(uploadErrorMessage(404, "MEDIA_FILE_NOT_FOUND")).toContain("документы");
  });

  it("never mentions documents in the photo context", () => {
    for (const code of [
      "INVALID_UPLOAD_TOKEN",
      "INVALID_MIME_TYPE",
      "EMPTY_UPLOAD",
      "MEDIA_FILE_NOT_FOUND",
      "INVALID_FILE_CONTENT",
      "MEDIA_FILE_LOCKED",
      "FILE_TOO_LARGE",
      null,
    ]) {
      for (const status of [400, 401, 404, 413, 500]) {
        expect(uploadErrorMessage(status, code, "photo")).not.toMatch(/документ/i);
      }
    }
  });

  // Коды жёсткой проверки PUT на бэкенде: пользователю — текст, не код.
  it("explains the upload hardening codes without leaking them", () => {
    expect(uploadErrorMessage(400, "INVALID_FILE_CONTENT", "photo")).toContain("JPG");
    expect(uploadErrorMessage(413, "FILE_TOO_LARGE", "photo")).toBe(FILE_TOO_LARGE_MESSAGE);
    expect(uploadErrorMessage(409, "MEDIA_FILE_LOCKED", "photo")).toContain("уже отправлен");
    for (const code of ["INVALID_FILE_CONTENT", "FILE_TOO_LARGE", "MEDIA_FILE_LOCKED"]) {
      expect(uploadErrorMessage(400, code, "photo")).not.toContain(code);
    }
  });
});

describe("preparePhotoForUpload", () => {
  it("passes a small jpeg through untouched", async () => {
    await expect(preparePhotoForUpload(file)).resolves.toEqual({ file, thumbnail: null });
  });

  // В node нет canvas — ровно та ветка, когда браузер не смог перегнать HEIC.
  // Отправлять такой файл нельзя: бэкенд ответит INVALID_MIME_TYPE.
  it("refuses a HEIC or an empty-type file it cannot convert", async () => {
    const heic = new File([new Uint8Array(32)], "IMG_0001.HEIC", { type: "image/heic" });
    const untyped = new File([new Uint8Array(32)], "photo", { type: "" });

    await expect(preparePhotoForUpload(heic)).rejects.toThrow(PHOTO_UNREADABLE_MESSAGE);
    await expect(preparePhotoForUpload(untyped)).rejects.toThrow(PHOTO_UNREADABLE_MESSAGE);
  });

  it("knows which types the backend accepts as is", () => {
    expect(needsImageConversion(file)).toBe(false);
    expect(needsImageConversion(new File([], "a.webp", { type: "image/webp" }))).toBe(false);
    expect(needsImageConversion(new File([], "a.heic", { type: "image/heic" }))).toBe(true);
    expect(needsImageConversion(new File([], "a", { type: "" }))).toBe(true);
  });
});

type FakeXhrScript =
  | { kind: "network" }
  // Соединение молча зависло: пара событий прогресса — и тишина, без ответа.
  | { kind: "hang"; progress?: number[] }
  | { kind: "response"; status: number; body?: string; progress?: number[] };

type SentRequest = {
  method: string;
  url: string;
  headers: Record<string, string>;
  body: unknown;
  timeout: number;
  aborted: boolean;
};

function installFakeXhr(script: FakeXhrScript[]) {
  const sent: SentRequest[] = [];
  class FakeXhr {
    status = 0;
    responseText = "";
    timeout = 0;
    upload: {
      onprogress: ((event: { lengthComputable: boolean; loaded: number; total: number }) => void) | null;
      onload: (() => void) | null;
    } = {
      onprogress: null,
      onload: null,
    };
    onload: (() => void) | null = null;
    onerror: (() => void) | null = null;
    ontimeout: (() => void) | null = null;
    onabort: (() => void) | null = null;
    private method = "";
    private url = "";
    private headers: Record<string, string> = {};
    private record: SentRequest | null = null;

    open(method: string, url: string) {
      this.method = method;
      this.url = url;
    }

    setRequestHeader(name: string, value: string) {
      this.headers[name] = value;
    }

    abort() {
      if (this.record) this.record.aborted = true;
      this.onabort?.();
    }

    send(body: unknown) {
      this.record = {
        method: this.method,
        url: this.url,
        headers: this.headers,
        body,
        timeout: this.timeout,
        aborted: false,
      };
      sent.push(this.record);
      const step = script.shift() ?? { kind: "network" };
      queueMicrotask(() => {
        if (step.kind === "network") {
          this.onerror?.();
          return;
        }
        if (step.kind === "hang") {
          for (const loaded of step.progress ?? []) {
            this.upload.onprogress?.({ lengthComputable: true, loaded, total: 100 });
          }
          return;
        }
        for (const loaded of step.progress ?? []) {
          this.upload.onprogress?.({ lengthComputable: true, loaded, total: 100 });
        }
        this.status = step.status;
        this.responseText = step.body ?? "";
        this.onload?.();
      });
    }
  }
  vi.stubGlobal("XMLHttpRequest", FakeXhr);
  return sent;
}

describe("putPresignedFileWithProgress", () => {
  it("reports real progress and sends the presign headers", async () => {
    const sent = installFakeXhr([{ kind: "response", status: 200, progress: [25, 80, 100] }]);
    const progress: number[] = [];

    await putPresignedFileWithProgress(presign, file, { onProgress: (value) => progress.push(value) });

    expect(sent).toHaveLength(1);
    expect(sent[0]).toMatchObject({
      method: "PUT",
      url: resolveUploadUrl(presign.uploadUrl),
      headers: presign.headers,
      body: file,
    });
    expect(progress).toEqual([0, 0.25, 0.8, 1, 1]);
  });

  it("retries a dropped connection and a server error, like putPresignedFile", async () => {
    vi.useFakeTimers();
    const sent = installFakeXhr([
      { kind: "network" },
      { kind: "response", status: 502, body: "" },
      { kind: "response", status: 200 },
    ]);

    const pending = putPresignedFileWithProgress(presign, file, { context: "photo" });
    await vi.runAllTimersAsync();

    await expect(pending).resolves.toBeUndefined();
    expect(sent).toHaveLength(3);
  });

  it("gives up after three dropped attempts with the network message", async () => {
    vi.useFakeTimers();
    const sent = installFakeXhr([{ kind: "network" }, { kind: "network" }, { kind: "network" }]);

    const pending = putPresignedFileWithProgress(presign, file, { context: "photo" });
    const assertion = expect(pending).rejects.toThrow(UPLOAD_NETWORK_MESSAGE);
    await vi.runAllTimersAsync();
    await assertion;
    expect(sent).toHaveLength(3);
  });

  it("does not retry client errors and speaks about the photo, not documents", async () => {
    const sent = installFakeXhr([
      { kind: "response", status: 401, body: JSON.stringify({ detail: "INVALID_UPLOAD_TOKEN" }) },
    ]);

    await expect(putPresignedFileWithProgress(presign, file, { context: "photo" })).rejects.toThrow(
      "Ссылка на загрузку устарела. Отправьте фото ещё раз.",
    );
    expect(sent).toHaveLength(1);
  });

  it("limits every attempt in time so a dead connection cannot hang forever", async () => {
    const sent = installFakeXhr([{ kind: "response", status: 200 }]);

    await putPresignedFileWithProgress(presign, file, { context: "photo" });

    expect(sent[0].timeout).toBe(UPLOAD_ATTEMPT_TIMEOUT_MS);
  });

  // Смена Wi-Fi → LTE: XHR не падает, прогресс просто замирает. Без сторожа
  // кадр висел бы в «Отправляем… 40%», а кнопка возврата — заблокированной.
  it("aborts a stalled attempt after the silence threshold and retries it", async () => {
    vi.useFakeTimers();
    const sent = installFakeXhr([{ kind: "hang", progress: [10, 40] }, { kind: "response", status: 200 }]);
    const progress: number[] = [];

    const pending = putPresignedFileWithProgress(presign, file, {
      context: "photo",
      onProgress: (value) => progress.push(value),
    });
    await vi.advanceTimersByTimeAsync(UPLOAD_STALL_TIMEOUT_MS - 1);
    expect(sent).toHaveLength(1);
    expect(sent[0].aborted).toBe(false);

    await vi.runAllTimersAsync();
    await expect(pending).resolves.toBeUndefined();
    expect(sent).toHaveLength(2);
    expect(sent[0].aborted).toBe(true);
    expect(progress.at(-1)).toBe(1);
  });

  it("turns a connection that keeps stalling into the network error", async () => {
    vi.useFakeTimers();
    const sent = installFakeXhr([{ kind: "hang" }, { kind: "hang" }, { kind: "hang" }]);

    const pending = putPresignedFileWithProgress(presign, file, { context: "photo" });
    const assertion = expect(pending).rejects.toThrow(UPLOAD_NETWORK_MESSAGE);
    await vi.runAllTimersAsync();
    await assertion;
    expect(sent).toHaveLength(3);
  });

  it("stops at once when the user cancels, without retries", async () => {
    vi.useFakeTimers();
    const sent = installFakeXhr([{ kind: "hang", progress: [20] }, { kind: "response", status: 200 }]);
    const controller = new AbortController();

    const pending = putPresignedFileWithProgress(presign, file, {
      context: "photo",
      signal: controller.signal,
    });
    const assertion = expect(pending).rejects.toBeInstanceOf(UploadAbortedError);
    await vi.advanceTimersByTimeAsync(1_000);
    controller.abort();
    await assertion;
    await vi.runAllTimersAsync();

    expect(sent).toHaveLength(1);
    expect(sent[0].aborted).toBe(true);
    await pending.catch((error: unknown) => expect(isUploadAborted(error)).toBe(true));
  });

  it("does not start when the signal is already aborted", async () => {
    const sent = installFakeXhr([{ kind: "response", status: 200 }]);
    const controller = new AbortController();
    controller.abort();

    await expect(
      putPresignedFileWithProgress(presign, file, { signal: controller.signal }),
    ).rejects.toBeInstanceOf(UploadAbortedError);
    expect(sent).toHaveLength(0);
  });

  it("falls back to fetch when XMLHttpRequest is unavailable", async () => {
    vi.stubGlobal("XMLHttpRequest", undefined);
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(200, { data: { stored: true } }));
    vi.stubGlobal("fetch", fetchMock);
    const progress: number[] = [];

    await putPresignedFileWithProgress(presign, file, { onProgress: (value) => progress.push(value) });

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(progress.at(-1)).toBe(1);
  });
});

describe("withUploadDeadline", () => {
  it("passes the result through when the step finishes in time", async () => {
    await expect(withUploadDeadline(Promise.resolve("ok"), { timeoutMs: 1_000 })).resolves.toBe("ok");
    await expect(
      withUploadDeadline(Promise.reject(new Error("presign failed")), { timeoutMs: 1_000 }),
    ).rejects.toThrow("presign failed");
  });

  // presign идёт через fetch без таймаута — на зависшей сети он бы ждал вечно.
  it("rejects with a readable network message when the step hangs", async () => {
    vi.useFakeTimers();
    const pending = withUploadDeadline(new Promise(() => undefined), { timeoutMs: 30_000 });
    const assertion = expect(pending).rejects.toThrow(UPLOAD_NETWORK_MESSAGE);
    await vi.advanceTimersByTimeAsync(30_000);
    await assertion;

    const custom = withUploadDeadline(new Promise(() => undefined), {
      timeoutMs: 10,
      timeoutMessage: PHOTO_UNREADABLE_MESSAGE,
    });
    const customAssertion = expect(custom).rejects.toThrow(PHOTO_UNREADABLE_MESSAGE);
    await vi.advanceTimersByTimeAsync(10);
    await customAssertion;
  });

  it("rejects as aborted when the user removes the photo", async () => {
    const controller = new AbortController();
    const pending = withUploadDeadline(new Promise(() => undefined), {
      timeoutMs: 30_000,
      signal: controller.signal,
    });
    controller.abort();
    await expect(pending).rejects.toBeInstanceOf(UploadAbortedError);

    await expect(
      withUploadDeadline(Promise.resolve(1), { timeoutMs: 10, signal: controller.signal }),
    ).rejects.toBeInstanceOf(UploadAbortedError);
  });
});

describe("putPresignedFileWithProgress over fetch", () => {
  function hangingFetch() {
    return vi.fn((_url: string, init: RequestInit) => {
      return new Promise<Response>((_resolve, reject) => {
        init.signal?.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")));
      });
    });
  }

  it("reports a cancelled upload as aborted, not as a network failure", async () => {
    vi.stubGlobal("XMLHttpRequest", undefined);
    const controller = new AbortController();
    const fetchMock = hangingFetch();
    vi.stubGlobal("fetch", fetchMock);

    const pending = putPresignedFileWithProgress(presign, file, { signal: controller.signal });
    controller.abort();

    await expect(pending).rejects.toBeInstanceOf(UploadAbortedError);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("gives up on a hanging fetch after the attempt timeout", async () => {
    vi.useFakeTimers();
    vi.stubGlobal("XMLHttpRequest", undefined);
    const fetchMock = hangingFetch();
    vi.stubGlobal("fetch", fetchMock);

    const pending = putPresignedFileWithProgress(presign, file, { attemptTimeoutMs: 1_000 });
    const assertion = expect(pending).rejects.toThrow(UPLOAD_NETWORK_MESSAGE);
    await vi.runAllTimersAsync();
    await assertion;
    expect(fetchMock).toHaveBeenCalledTimes(3);
  });
});
