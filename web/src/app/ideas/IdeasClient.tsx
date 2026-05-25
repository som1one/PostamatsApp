"use client";

import { useRef, useState } from "react";
import { Lightbulb, ArrowRight, ImagePlus, Check } from "lucide-react";
import Link from "next/link";
import { PageChrome } from "@/components/PageChrome";
import { apiBaseUrl } from "@/shared/api/client";
import { presignPublicUpload, submitRentalIdea } from "@/shared/api/endpoints";

const MAX_FILE_SIZE = 10 * 1024 * 1024; // 10 MB
const ACCEPTED_MIME = ["image/jpeg", "image/png", "image/gif", "image/webp"];

type FormStatus =
  | { kind: "idle" }
  | { kind: "submitting" }
  | { kind: "success" }
  | { kind: "error"; message: string };

export function IdeasClient() {
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [idea, setIdea] = useState("");
  const [referenceUrl, setReferenceUrl] = useState("");
  const [photo, setPhoto] = useState<File | null>(null);
  const [status, setStatus] = useState<FormStatus>({ kind: "idle" });
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  function handlePhotoPick(event: React.ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0] || null;
    if (!file) {
      setPhoto(null);
      return;
    }
    if (!ACCEPTED_MIME.includes(file.type)) {
      setStatus({
        kind: "error",
        message: "Можно загрузить только JPG, PNG, GIF или WEBP.",
      });
      event.target.value = "";
      return;
    }
    if (file.size > MAX_FILE_SIZE) {
      setStatus({
        kind: "error",
        message: "Размер фото должен быть не больше 10 МБ.",
      });
      event.target.value = "";
      return;
    }
    setStatus({ kind: "idle" });
    setPhoto(file);
  }

  async function uploadPhoto(file: File): Promise<string> {
    const presign = await presignPublicUpload({
      fileName: file.name,
      mimeType: file.type,
      fileSize: file.size,
      kind: "rental_idea_photo",
    });
    const targetUrl = /^https?:\/\//i.test(presign.uploadUrl)
      ? presign.uploadUrl
      : `${apiBaseUrl()}${presign.uploadUrl.startsWith("/") ? "" : "/"}${presign.uploadUrl}`;
    const response = await fetch(targetUrl, {
      method: presign.method || "PUT",
      headers: presign.headers,
      body: file,
    });
    if (!response.ok) {
      throw new Error("PHOTO_UPLOAD_FAILED");
    }
    return presign.fileId;
  }

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (status.kind === "submitting") {
      return;
    }
    const trimmedName = name.trim();
    const trimmedEmail = email.trim();
    const trimmedIdea = idea.trim();
    if (!trimmedName || !trimmedEmail || !trimmedIdea) {
      setStatus({
        kind: "error",
        message: "Заполните имя, email и опишите идею.",
      });
      return;
    }
    setStatus({ kind: "submitting" });
    try {
      let photoId: string | null = null;
      if (photo) {
        photoId = await uploadPhoto(photo);
      }
      const trimmedRef = referenceUrl.trim();
      await submitRentalIdea({
        name: trimmedName,
        email: trimmedEmail,
        idea: trimmedIdea,
        referenceUrl: trimmedRef || null,
        photoId,
      });
      setStatus({ kind: "success" });
      setName("");
      setEmail("");
      setIdea("");
      setReferenceUrl("");
      setPhoto(null);
      if (fileInputRef.current) {
        fileInputRef.current.value = "";
      }
    } catch (error) {
      const message =
        error instanceof Error && error.message
          ? error.message === "PHOTO_UPLOAD_FAILED"
            ? "Не удалось загрузить фото. Попробуйте ещё раз."
            : error.message
          : "Не удалось отправить идею. Попробуйте ещё раз.";
      setStatus({ kind: "error", message });
    }
  }

  const submitting = status.kind === "submitting";

  return (
    <PageChrome>
      <nav className="breadcrumbs" aria-label="Хлебные крошки">
        <Link href="/">Главная</Link>
        <span aria-hidden>/</span>
        <span>Идея для аренды</span>
      </nav>

      <section className="ideas-hero">
        <p className="eyebrow">
          <Lightbulb size={16} /> Подскажите нам
        </p>
        <h1 className="page-title">Предложить идею для аренды</h1>
        <p className="page-subtitle">
          Не нашли в каталоге то, что хотите взять напрокат? Напишите нам —
          постараемся добавить.
        </p>
      </section>

      <form className="surface ideas-form" onSubmit={handleSubmit} noValidate>
        <div className="ideas-form-grid">
          <label className="field">
            <span>Имя</span>
            <input
              className="input"
              type="text"
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder="Ваше имя"
              autoComplete="name"
              maxLength={120}
              required
            />
          </label>
          <label className="field">
            <span>Email</span>
            <input
              className="input"
              type="email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              placeholder="ваш@email"
              autoComplete="email"
              maxLength={255}
              required
            />
          </label>
        </div>

        <label className="field">
          <span>Идея</span>
          <textarea
            className="textarea ideas-textarea"
            value={idea}
            onChange={(event) => setIdea(event.target.value)}
            placeholder="Напишите вашу идею"
            maxLength={4000}
            rows={6}
            required
          />
        </label>

        <label className="field">
          <span>Ссылка на вещь в интернете</span>
          <input
            className="input"
            type="url"
            value={referenceUrl}
            onChange={(event) => setReferenceUrl(event.target.value)}
            placeholder="https://..."
            inputMode="url"
            maxLength={2048}
          />
        </label>

        <div className="ideas-photo-row">
          <button
            type="button"
            className="button button-secondary"
            onClick={() => fileInputRef.current?.click()}
          >
            <ImagePlus size={18} />
            {photo ? "Заменить фото" : "Загрузить фотографию"}
          </button>
          <input
            ref={fileInputRef}
            type="file"
            accept="image/jpeg,image/png,image/gif,image/webp"
            hidden
            onChange={handlePhotoPick}
          />
          {photo ? (
            <span className="ideas-photo-name">
              <Check size={14} /> {photo.name}
            </span>
          ) : (
            <p className="muted ideas-photo-hint">
              JPG, PNG, GIF или WEBP. До 10 МБ.
            </p>
          )}
        </div>

        {status.kind === "error" ? (
          <p className="form-error" role="alert">
            {status.message}
          </p>
        ) : null}
        {status.kind === "success" ? (
          <p className="form-success" role="status">
            Спасибо! Идея отправлена. Мы рассмотрим её и при необходимости
            свяжемся с вами по email.
          </p>
        ) : null}

        <button
          type="submit"
          className="button button-primary ideas-submit"
          disabled={submitting}
        >
          {submitting ? "Отправляем..." : "Предложить идею для аренды"}
          <ArrowRight size={18} />
        </button>
      </form>
    </PageChrome>
  );
}
