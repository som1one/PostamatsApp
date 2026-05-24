"use client";

import { FormEvent, useEffect, useId, useState } from "react";
import Link from "next/link";
import { CheckCircle2, FileImage, ShieldCheck, Trash2, Upload } from "lucide-react";
import { PageChrome } from "@/components/PageChrome";
import { PageHeader } from "@/components/PageHeader";
import { RequireAuth } from "@/components/RequireAuth";
import { StatusPill } from "@/components/StatusPill";
import { Surface } from "@/components/Surface";
import {
  createVerification,
  deleteVerification,
  fetchMe,
  fetchVerification,
  presignUpload,
} from "@/shared/api/endpoints";
import { apiBaseUrl } from "@/shared/api/client";
import type { AppUser, VerificationState } from "@/shared/api/types";

type UploadKind = "verification_front" | "verification_back" | "verification_selfie";
type VerificationFileKind = "document_front" | "document_back" | "selfie";
type Notice = {
  title: string;
  detail: string;
};

const kindMap: Record<UploadKind, VerificationFileKind> = {
  verification_front: "document_front",
  verification_back: "document_back",
  verification_selfie: "selfie",
};

export function VerificationClient() {
  return (
    <PageChrome>
      <RequireAuth>
        <VerificationContent />
      </RequireAuth>
    </PageChrome>
  );
}

function VerificationContent() {
  const [user, setUser] = useState<AppUser | null>(null);
  const [verification, setVerification] = useState<VerificationState | null>(null);
  const [form, setForm] = useState({
    firstName: "",
    lastName: "",
    birthDate: "",
    documentType: "passport_rf",
    documentName: "",
    documentNumber: "",
    documentIssueDate: "",
    documentExpiryDate: "",
  });
  const [front, setFront] = useState<File | null>(null);
  const [back, setBack] = useState<File | null>(null);
  const [selfie, setSelfie] = useState<File | null>(null);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [message, setMessage] = useState<Notice | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    Promise.all([fetchMe(), fetchVerification()])
      .then(([me, kyc]) => {
        if (!active) {
          return;
        }
        setUser(me);
        setVerification(kyc);
        setForm((current) => ({
          ...current,
          firstName: me.firstName || "",
          lastName: me.lastName || "",
          birthDate: me.birthDate || "",
          documentType: kyc.documentType || "passport_rf",
          documentName: kyc.documentName || "",
          documentNumber: kyc.documentNumber || "",
          documentIssueDate: kyc.documentIssueDate || "",
          documentExpiryDate: kyc.documentExpiryDate || "",
        }));
      })
      .catch((err: unknown) => {
        if (active) {
          setError(err instanceof Error ? err.message : "Не удалось загрузить данные для проверки");
        }
      })
      .finally(() => {
        if (active) {
          setLoading(false);
        }
      });
    return () => {
      active = false;
    };
  }, []);

  async function uploadFile(file: File, kind: UploadKind) {
    const presign = await presignUpload({
      fileName: file.name,
      mimeType: file.type || "image/jpeg",
      fileSize: file.size,
      kind,
    });
    const targetUrl = /^https?:\/\//i.test(presign.uploadUrl)
      ? presign.uploadUrl
      : `${apiBaseUrl()}${presign.uploadUrl.startsWith("/") ? "" : "/"}${presign.uploadUrl}`;
    const uploadResponse = await fetch(targetUrl, {
      method: presign.method || "PUT",
      headers: presign.headers,
      body: file,
    });
    if (!uploadResponse.ok) {
      throw new Error("Не удалось загрузить файл");
    }
    return {
      fileKey: presign.fileKey,
      kind: kindMap[kind],
    };
  }

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    if (!front || !selfie) {
      setError("Нужны фото документа и селфи.");
      return;
    }

    if (form.documentType === "other" && !form.documentName.trim()) {
      setError("Укажите название документа.");
      return;
    }

    setSubmitting(true);
    setMessage(null);
    setError("");
    try {
      const files = [
        await uploadFile(front, "verification_front"),
        ...(back ? [await uploadFile(back, "verification_back")] : []),
        await uploadFile(selfie, "verification_selfie"),
      ];
      const next = await createVerification({
        ...form,
        documentName: form.documentType === "other" ? form.documentName.trim() : undefined,
        documentIssueDate: form.documentIssueDate || undefined,
        documentExpiryDate: form.documentExpiryDate || undefined,
        files,
      });
      setVerification(next);
      setFront(null);
      setBack(null);
      setSelfie(null);
      setMessage({
        title: "Документы отправлены",
        detail:
          "Мы получили фотографии и передали заявку на проверку. Дальше останется дождаться решения оператора.",
      });
    } catch (err) {
      if (err instanceof Error) {
        if (err.message === "DOCUMENT_NAME_REQUIRED") {
          setError("Укажите название документа.");
        } else if (err.message === "DOCUMENT_NUMBER_ALREADY_EXISTS") {
          setError("Документ с таким номером уже существует в системе.");
        } else {
          setError(err.message);
        }
      } else {
        setError("Не удалось отправить документы на проверку");
      }
    } finally {
      setSubmitting(false);
    }
  }

  async function handleDeleteVerification() {
    setDeleting(true);
    setError("");
    setMessage(null);
    try {
      const documentNumber = verification?.documentNumber || form.documentNumber;
      if (!documentNumber.trim()) {
        throw new Error("Не удалось определить номер документа для удаления заявки.");
      }
      const next = await deleteVerification(documentNumber);
      setVerification(next);
      setFront(null);
      setBack(null);
      setSelfie(null);
      setMessage({
        title: "Заявка удалена",
        detail: "Можно снова выбрать файлы и отправить новую заявку на проверку.",
      });
    } catch (err) {
      if (err instanceof Error) {
        if (err.message === "VERIFICATION_REQUEST_NOT_FOUND") {
          setError("Заявка по этому номеру документа не найдена.");
        } else {
          setError(err.message);
        }
      } else {
        setError("Не удалось удалить заявку");
      }
    } finally {
      setDeleting(false);
    }
  }

  const isPendingReview = verification?.status === "pending_review";
  const isApproved = verification?.status === "approved";
  const isRejected = verification?.status === "rejected";
  const isLocked = isPendingReview || isApproved;
  const requiresDocumentName = form.documentType === "other";

  const pendingReviewNotice =
    !message && isPendingReview
      ? {
          title: "Заявка уже на проверке",
          detail:
            "Документы получены. Статус обновится здесь, как только проверка завершится.",
        }
      : null;

  const rejectedNotice =
    !message && isRejected
      ? {
          title: "Заявка отклонена",
          detail:
            verification?.rejectReason?.trim() ||
            "Оператор отклонил предыдущую заявку. Проверьте данные и попробуйте отправить документы заново.",
        }
      : null;

  if (loading) {
    return <div className="loader">Загружаем данные для проверки</div>;
  }

  return (
    <>
      <PageHeader
        eyebrow="Проверка"
        title="Верификация"
        subtitle={user?.phone || "Документы нужны перед первой бронью."}
        actions={<StatusPill status={verification?.status || user?.verificationStatus} />}
      />

      {message ? (
        <div className="alert alert-success" role="status">
          <ShieldCheck size={22} />
          <div>
            <strong>{message.title}</strong>
            <span>{message.detail}</span>
          </div>
        </div>
      ) : null}
      {pendingReviewNotice ? (
        <div className="alert alert-success" role="status">
          <ShieldCheck size={22} />
          <div>
            <strong>{pendingReviewNotice.title}</strong>
            <span>{pendingReviewNotice.detail}</span>
          </div>
        </div>
      ) : null}
      {rejectedNotice ? (
        <div className="alert alert-danger" role="status">
          <ShieldCheck size={22} />
          <div>
            <strong>{rejectedNotice.title}</strong>
            <span>{rejectedNotice.detail}</span>
          </div>
        </div>
      ) : null}
      {error ? <div className="alert alert-danger">{error}</div> : null}

      {isApproved ? (
        <div className="alert alert-success">
          <ShieldCheck size={22} />
          <div>
            <strong>Документы одобрены</strong>
            <Link href="/catalog">Перейти в каталог</Link>
          </div>
        </div>
      ) : null}

      <form className="layout-split" onSubmit={handleSubmit}>
        <Surface className="detail-panel">
          <div>
            <p className="eyebrow">Документ</p>
            <h2 className="section-title">Основные данные</h2>
          </div>
          <div className="form-grid verification-form-grid">
            <label className="field">
              <span>Имя</span>
              <input
                className="input"
                required
                disabled={isLocked}
                value={form.firstName}
                onChange={(event) => setForm({ ...form, firstName: event.target.value })}
              />
            </label>
            <label className="field">
              <span>Фамилия</span>
              <input
                className="input"
                required
                disabled={isLocked}
                value={form.lastName}
                onChange={(event) => setForm({ ...form, lastName: event.target.value })}
              />
            </label>
            <label className="field">
              <span>Дата рождения</span>
              <input
                className="input"
                required
                disabled={isLocked}
                type="date"
                value={form.birthDate}
                onChange={(event) => setForm({ ...form, birthDate: event.target.value })}
              />
            </label>
            <label className="field">
              <span>Тип документа</span>
              <select
                className="select"
                disabled={isLocked}
                value={form.documentType}
                onChange={(event) =>
                  setForm((current) => ({
                    ...current,
                    documentType: event.target.value,
                    documentName: event.target.value === "other" ? current.documentName : "",
                  }))
                }
              >
                <option value="passport_rf">Паспорт РФ</option>
                <option value="national_id">Национальный ID</option>
                <option value="driving_license">Водительское удостоверение</option>
                <option value="other">Другой документ</option>
              </select>
            </label>

            {requiresDocumentName ? (
              <label className="field verification-field-span-2">
                <span>Название документа</span>
                <input
                  className="input"
                  required
                  disabled={isLocked}
                  value={form.documentName}
                  onChange={(event) => setForm({ ...form, documentName: event.target.value })}
                  placeholder="Например: загранпаспорт, ВНЖ, студенческий билет"
                />
              </label>
            ) : null}

            <label className="field verification-field-span-2">
              <span>Номер документа</span>
              <input
                className="input"
                required
                disabled={isLocked}
                value={form.documentNumber}
                onChange={(event) => setForm({ ...form, documentNumber: event.target.value })}
              />
            </label>
            <label className="field">
              <span>Дата выдачи</span>
              <input
                className="input"
                disabled={isLocked}
                type="date"
                value={form.documentIssueDate}
                onChange={(event) => setForm({ ...form, documentIssueDate: event.target.value })}
              />
            </label>
            <label className="field">
              <span>Действует до</span>
              <input
                className="input"
                disabled={isLocked}
                type="date"
                value={form.documentExpiryDate}
                onChange={(event) => setForm({ ...form, documentExpiryDate: event.target.value })}
              />
            </label>
          </div>
        </Surface>

        <Surface className="detail-panel sticky-panel">
          <div>
            <p className="eyebrow">Файлы</p>
            <h2 className="section-title">Фото для проверки</h2>
          </div>

          {isPendingReview ? (
            <div className="verification-review-state">
              <p className="muted">
                Файлы уже отправлены на проверку. Если нужно начать заново, удалите текущую заявку.
              </p>
              <button
                className="button button-secondary verification-delete-button"
                type="button"
                disabled={deleting}
                onClick={handleDeleteVerification}
              >
                <Trash2 size={16} />
                {deleting ? "Удаляем" : "Удалить заявку"}
              </button>
            </div>
          ) : isApproved ? (
            <div className="verification-review-state">
              <p className="muted">
                Проверка завершена успешно. Документы одобрены, повторно загружать файлы не нужно.
              </p>
              <Link className="button button-primary verification-delete-button" href="/catalog">
                Перейти в каталог
              </Link>
            </div>
          ) : (
            <>
              <FileInput label="Лицевая сторона" file={front} onChange={setFront} required />
              <FileInput label="Оборотная сторона" file={back} onChange={setBack} />
              <FileInput label="Селфи" file={selfie} onChange={setSelfie} required />
              <button className="button button-primary" type="submit" disabled={submitting}>
                {submitting ? "Отправляем" : "Отправить на проверку"}
              </button>
              {isRejected ? (
                <button
                  className="button button-secondary verification-delete-button"
                  type="button"
                  disabled={deleting}
                  onClick={handleDeleteVerification}
                >
                  <Trash2 size={16} />
                  {deleting ? "Удаляем" : "Удалить отклонённую заявку"}
                </button>
              ) : null}
            </>
          )}
        </Surface>
      </form>
    </>
  );
}

function FileInput({
  label,
  file,
  onChange,
  required,
}: {
  label: string;
  file: File | null;
  onChange: (file: File | null) => void;
  required?: boolean;
}) {
  const inputId = useId();

  return (
    <div className={`file-picker${file ? " is-selected" : ""}`}>
      <div className="file-picker-head">
        <span className="field-label">{label}</span>
        <span className={`file-picker-tag${required ? " is-required" : ""}`}>
          {required ? "обязательно" : "по желанию"}
        </span>
      </div>
      <label className="file-picker-control" htmlFor={inputId}>
        <input
          id={inputId}
          className="file-picker-input"
          type="file"
          accept="image/jpeg,image/png,image/webp"
          onChange={(event) => onChange(event.target.files?.[0] ?? null)}
        />
        <span className="file-picker-button">
          <Upload size={16} />
          {file ? "Заменить файл" : "Выбрать файл"}
        </span>
        <span className="file-picker-description">
          {file ? "Можно выбрать другой снимок" : "JPG, PNG или WEBP"}
        </span>
      </label>
      <span className={`file-hint${file ? " is-selected" : ""}`}>
        {file ? <CheckCircle2 size={15} /> : <FileImage size={15} />}
        {file ? `${file.name} · ${formatFileSize(file.size)}` : "Файл не выбран"}
      </span>
    </div>
  );
}

function formatFileSize(size: number) {
  if (size < 1024 * 1024) {
    return `${Math.max(1, Math.round(size / 1024))} КБ`;
  }

  return `${(size / (1024 * 1024)).toFixed(1)} МБ`;
}
