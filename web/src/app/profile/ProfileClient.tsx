"use client";

import { FormEvent, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { CheckCircle2, FileCheck2, LogOut, UserRound } from "lucide-react";
import { PageChrome } from "@/components/PageChrome";
import { PageHeader } from "@/components/PageHeader";
import { RequireAuth } from "@/components/RequireAuth";
import { StatusPill } from "@/components/StatusPill";
import { Surface } from "@/components/Surface";
import {
  fetchMe,
  fetchVerification,
  logoutSession,
  updateMe,
} from "@/shared/api/endpoints";
import type { AppUser, VerificationState } from "@/shared/api/types";
import { useAuth } from "@/shared/auth/auth-context";

export function ProfileClient() {
  return (
    <PageChrome>
      <RequireAuth>
        <ProfileContent />
      </RequireAuth>
    </PageChrome>
  );
}

function ProfileContent() {
  const router = useRouter();
  const { clearSession } = useAuth();
  const [user, setUser] = useState<AppUser | null>(null);
  const [verification, setVerification] = useState<VerificationState | null>(null);
  const [form, setForm] = useState({
    firstName: "",
    lastName: "",
    middleName: "",
    email: "",
  });
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
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
        setForm({
          firstName: me.firstName || "",
          lastName: me.lastName || "",
          middleName: me.middleName || "",
          email: me.email || "",
        });
      })
      .catch((err: unknown) => {
        if (active) {
          setError(err instanceof Error ? err.message : "Не удалось загрузить профиль");
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

  async function handleSave(event: FormEvent) {
    event.preventDefault();
    setSaving(true);
    setMessage("");
    setError("");
    try {
      const next = await updateMe(form);
      setUser(next);
      setMessage("Профиль обновлён.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось сохранить профиль");
    } finally {
      setSaving(false);
    }
  }

  async function handleLogout() {
    try {
      await logoutSession();
    } catch {
      // Local logout is enough when access token is already expired.
    }
    clearSession();
    router.push("/");
  }

  if (loading) {
    return <div className="loader">Загружаем профиль</div>;
  }

  return (
    <>
      <PageHeader
        eyebrow="Профиль"
        title={user?.phone || "Аккаунт"}
        subtitle="Контактные данные, статус проверки и быстрый переход к KYC."
        actions={
          <button className="button button-secondary" type="button" onClick={handleLogout}>
            <LogOut size={18} />
            Выйти
          </button>
        }
      />

      {error ? <div className="alert alert-danger">{error}</div> : null}
      {message ? <div className="alert">{message}</div> : null}

      <div className="layout-split">
        <Surface className="detail-panel">
          <div className="card-row">
            <span className="icon-badge">
              <UserRound size={20} />
            </span>
            <StatusPill status={user?.verificationStatus} />
          </div>
          <div>
            <p className="eyebrow">Данные</p>
            <h2 className="section-title">Личная информация</h2>
          </div>
          <form className="form-grid" onSubmit={handleSave}>
            <label className="field">
              <span>Имя</span>
              <input
                className="input"
                value={form.firstName}
                onChange={(event) => setForm({ ...form, firstName: event.target.value })}
              />
            </label>
            <label className="field">
              <span>Фамилия</span>
              <input
                className="input"
                value={form.lastName}
                onChange={(event) => setForm({ ...form, lastName: event.target.value })}
              />
            </label>
            <label className="field">
              <span>Отчество</span>
              <input
                className="input"
                value={form.middleName}
                onChange={(event) => setForm({ ...form, middleName: event.target.value })}
              />
            </label>
            <label className="field">
              <span>Email</span>
              <input
                className="input"
                value={form.email}
                type="email"
                onChange={(event) => setForm({ ...form, email: event.target.value })}
              />
            </label>
            <button className="button button-primary" type="submit" disabled={saving}>
              {saving ? "Сохраняем" : "Сохранить"}
            </button>
          </form>
        </Surface>

        <Surface className="detail-panel sticky-panel">
          <div className="card-row">
            <span className="icon-badge">
              <FileCheck2 size={20} />
            </span>
            <StatusPill status={verification?.status || user?.verificationStatus} />
          </div>
          <div>
            <p className="eyebrow">KYC</p>
            <h2 className="section-title">Верификация</h2>
          </div>
          <p className="muted">
            {verification?.rejectReason ||
              (verification?.status === "approved"
                ? "Документы одобрены, бронирование доступно."
                : "Подайте документы, чтобы открыть бронирование.")}
          </p>
          <div className="timeline">
            <div className="timeline-item">
              <span className="timeline-dot">
                <CheckCircle2 size={18} />
              </span>
              <div>
                <strong>Аккаунт</strong>
                <p className="muted small">{user?.phone}</p>
              </div>
            </div>
            <div className="timeline-item">
              <span className="timeline-dot">
                <FileCheck2 size={18} />
              </span>
              <div>
                <strong>Документы</strong>
                <p className="muted small">{verification?.documentType || "не поданы"}</p>
              </div>
            </div>
          </div>
          <Link className="button button-primary" href="/verification">
            Открыть KYC
          </Link>
        </Surface>
      </div>
    </>
  );
}
