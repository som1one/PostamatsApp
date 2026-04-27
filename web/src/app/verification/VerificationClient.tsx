"use client";

import { FormEvent, useEffect, useState } from "react";
import Link from "next/link";
import { FileImage, ShieldCheck } from "lucide-react";
import { PageChrome } from "@/components/PageChrome";
import { PageHeader } from "@/components/PageHeader";
import { RequireAuth } from "@/components/RequireAuth";
import { StatusPill } from "@/components/StatusPill";
import { Surface } from "@/components/Surface";
import {
  createVerification,
  fetchMe,
  fetchVerification,
  presignUpload,
} from "@/shared/api/endpoints";
import type { AppUser, VerificationState } from "@/shared/api/types";

type UploadKind = "verification_front" | "verification_back" | "verification_selfie";
type VerificationFileKind = "document_front" | "document_back" | "selfie";

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
    documentNumber: "",
    documentIssueDate: "",
    documentExpiryDate: "",
  });
  const [front, setFront] = useState<File | null>(null);
  const [back, setBack] = useState<File | null>(null);
  const [selfie, setSelfie] = useState<File | null>(null);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [message, setMessage] = useState("");
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
          documentNumber: kyc.documentNumber || "",
          documentIssueDate: kyc.documentIssueDate || "",
          documentExpiryDate: kyc.documentExpiryDate || "",
        }));
      })
      .catch((err: unknown) => {
        if (active) {
          setError(err instanceof Error ? err.message : "Не удалось загрузить KYC");
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
    const uploadResponse = await fetch(presign.uploadUrl, {
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

    setSubmitting(true);
    setMessage("");
    setError("");
    try {
      const files = [
        await uploadFile(front, "verification_front"),
        ...(back ? [await uploadFile(back, "verification_back")] : []),
        await uploadFile(selfie, "verification_selfie"),
      ];
      const next = await createVerification({
        ...form,
        documentIssueDate: form.documentIssueDate || undefined,
        documentExpiryDate: form.documentExpiryDate || undefined,
        files,
      });
      setVerification(next);
      setMessage("Заявка отправлена на проверку.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось отправить KYC");
    } finally {
      setSubmitting(false);
    }
  }

  if (loading) {
    return <div className="loader">Загружаем KYC</div>;
  }

  return (
    <>
      <PageHeader
        eyebrow="KYC"
        title="Верификация"
        subtitle={user?.phone || "Документы нужны перед первой бронью."}
        actions={<StatusPill status={verification?.status || user?.verificationStatus} />}
      />

      {message ? <div className="alert">{message}</div> : null}
      {error ? <div className="alert alert-danger">{error}</div> : null}

      {verification?.status === "approved" ? (
        <div className="alert">
          <ShieldCheck size={22} color="#158f5a" />
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
          <div className="form-grid">
            <label className="field">
              <span>Имя</span>
              <input
                className="input"
                required
                value={form.firstName}
                onChange={(event) => setForm({ ...form, firstName: event.target.value })}
              />
            </label>
            <label className="field">
              <span>Фамилия</span>
              <input
                className="input"
                required
                value={form.lastName}
                onChange={(event) => setForm({ ...form, lastName: event.target.value })}
              />
            </label>
            <label className="field">
              <span>Дата рождения</span>
              <input
                className="input"
                required
                type="date"
                value={form.birthDate}
                onChange={(event) => setForm({ ...form, birthDate: event.target.value })}
              />
            </label>
            <label className="field">
              <span>Тип документа</span>
              <select
                className="select"
                value={form.documentType}
                onChange={(event) => setForm({ ...form, documentType: event.target.value })}
              >
                <option value="passport_rf">Паспорт РФ</option>
                <option value="national_id">Национальный ID</option>
                <option value="driving_license">Водительское удостоверение</option>
                <option value="other">Другой документ</option>
              </select>
            </label>
            <label className="field">
              <span>Номер документа</span>
              <input
                className="input"
                required
                value={form.documentNumber}
                onChange={(event) =>
                  setForm({ ...form, documentNumber: event.target.value })
                }
              />
            </label>
            <label className="field">
              <span>Дата выдачи</span>
              <input
                className="input"
                type="date"
                value={form.documentIssueDate}
                onChange={(event) =>
                  setForm({ ...form, documentIssueDate: event.target.value })
                }
              />
            </label>
            <label className="field">
              <span>Действует до</span>
              <input
                className="input"
                type="date"
                value={form.documentExpiryDate}
                onChange={(event) =>
                  setForm({ ...form, documentExpiryDate: event.target.value })
                }
              />
            </label>
          </div>
        </Surface>

        <Surface className="detail-panel sticky-panel">
          <div>
            <p className="eyebrow">Файлы</p>
            <h2 className="section-title">Фото для проверки</h2>
          </div>
          <FileInput label="Лицевая сторона" file={front} onChange={setFront} required />
          <FileInput label="Оборотная сторона" file={back} onChange={setBack} />
          <FileInput label="Селфи" file={selfie} onChange={setSelfie} required />
          <button className="button button-primary" type="submit" disabled={submitting}>
            {submitting ? "Отправляем" : "Отправить на проверку"}
          </button>
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
  return (
    <label className="field">
      <span>{label}</span>
      <input
        className="input"
        type="file"
        accept="image/jpeg,image/png,image/webp"
        required={required}
        onChange={(event) => onChange(event.target.files?.[0] ?? null)}
      />
      <span className="file-hint">
        <FileImage size={15} />
        {file?.name || "файл не выбран"}
      </span>
    </label>
  );
}
