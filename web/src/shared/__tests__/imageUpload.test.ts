import { afterEach, describe, expect, it, vi } from "vitest";
import {
  UPLOAD_NETWORK_MESSAGE,
  compressImageForUpload,
  putPresignedFile,
  resolveUploadUrl,
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
