"use client";

import { FormEvent, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { CheckCircle2, FileCheck2, LogOut, PackageCheck, UserRound } from "lucide-react";
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

type ProfileFormState = {
  firstName: string;
  lastName: string;
  middleName: string;
  email: string;
};

type ProfileNotice = {
  title: string;
  detail: string;
};

const PROFILE_REQUIRED_FIELDS: Array<{
  key: keyof Pick<ProfileFormState, "firstName" | "lastName" | "email">;
  label: string;
}> = [
  { key: "firstName", label: "имя" },
  { key: "lastName", label: "фамилию" },
  { key: "email", label: "e-mail" },
];

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
  const [form, setForm] = useState<ProfileFormState>({
    firstName: "",
    lastName: "",
    middleName: "",
    email: "",
  });
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<ProfileNotice | null>(null);
  const [error, setError] = useState("");
  const profileCompletion = getProfileCompletion(form);

  useEffect(() => {
    let active = true;
    Promise.all([fetchMe(), fetchVerification()])
      .then(([me, kyc]) => {
        if (!active) {
          return;
        }
        setUser(me);
        setVerification(kyc);
        setForm(toProfileForm(me));
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
    setMessage(null);
    setError("");
    try {
      const next = await updateMe(form);
      const nextForm = toProfileForm(next);
      setUser(next);
      setForm(nextForm);
      setMessage(buildProfileNotice(getProfileCompletion(nextForm)));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось сохранить профиль");
    } finally {
      setSaving(false);
    }
  }

  function handleFieldChange<K extends keyof ProfileFormState>(
    key: K,
    value: ProfileFormState[K],
  ) {
    setForm((current) => ({
      ...current,
      [key]: value,
    }));
    if (message) {
      setMessage(null);
    }
    if (error) {
      setError("");
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
        subtitle="Контактные данные, статус проверки и быстрый переход к верификации."
        actions={
          <button className="button button-secondary" type="button" onClick={handleLogout}>
            <LogOut size={18} />
            Выйти
          </button>
        }
      />

      {error ? <div className="alert alert-danger">{error}</div> : null}

      <div className="layout-split">
        <Surface className="detail-panel">
          <div className="card-row">
            <span className="icon-badge">
              <UserRound size={20} />
            </span>
            <StatusPill status={profileCompletion.status} />
          </div>
          <div>
            <p className="eyebrow">Данные</p>
            <h2 className="section-title">Личная информация</h2>
            <p className="muted small profile-summary">{profileCompletion.summary}</p>
          </div>
          {message ? (
            <div className="alert alert-success profile-feedback" role="status">
              <CheckCircle2 size={20} />
              <div>
                <strong>{message.title}</strong>
                <span>{message.detail}</span>
              </div>
            </div>
          ) : null}
          <form className="form-grid" onSubmit={handleSave}>
            <label className="field">
              <span>Имя</span>
              <input
                className="input"
                value={form.firstName}
                onChange={(event) => handleFieldChange("firstName", event.target.value)}
              />
            </label>
            <label className="field">
              <span>Фамилия</span>
              <input
                className="input"
                value={form.lastName}
                onChange={(event) => handleFieldChange("lastName", event.target.value)}
              />
            </label>
            <label className="field">
              <span>Отчество</span>
              <input
                className="input"
                value={form.middleName}
                onChange={(event) => handleFieldChange("middleName", event.target.value)}
              />
            </label>
            <label className="field">
              <span>Email</span>
              <input
                className="input"
                value={form.email}
                type="email"
                onChange={(event) => handleFieldChange("email", event.target.value)}
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
            <p className="eyebrow">Проверка</p>
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
            Открыть проверку
          </Link>
          <Link className="button button-secondary" href="/profile/orders">
            <PackageCheck size={18} />
            Мои заказы
          </Link>
        </Surface>
      </div>
    </>
  );
}

function toProfileForm(user: AppUser | null): ProfileFormState {
  return {
    firstName: user?.firstName || "",
    lastName: user?.lastName || "",
    middleName: user?.middleName || "",
    email: user?.email || "",
  };
}

function getProfileCompletion(form: ProfileFormState) {
  const missing = PROFILE_REQUIRED_FIELDS.filter(({ key }) => !form[key].trim()).map(
    ({ label }) => label,
  );
  const filledCount = PROFILE_REQUIRED_FIELDS.length - missing.length;
  const summaryBase = `${filledCount} из ${PROFILE_REQUIRED_FIELDS.length} основных полей заполнено.`;

  if (filledCount === 0) {
    return {
      status: "profile_empty",
      missing,
      summary: "Добавьте имя, фамилию и e-mail, чтобы анкета выглядела полной.",
    };
  }

  if (missing.length === 0) {
    return {
      status: "profile_ready",
      missing,
      summary: `${summaryBase} Можно переходить к проверке документов.`,
    };
  }

  return {
    status: "profile_partial",
    missing,
    summary: `${summaryBase} Осталось добавить ${formatFieldList(missing)}.`,
  };
}

function buildProfileNotice(completion: ReturnType<typeof getProfileCompletion>): ProfileNotice {
  if (completion.status === "profile_ready") {
    return {
      title: "Личная информация сохранена",
      detail: "Основные поля заполнены. Дальше можно переходить к проверке документов.",
    };
  }

  return {
    title: "Изменения сохранены",
    detail:
      completion.status === "profile_empty"
        ? "Добавьте имя, фамилию и e-mail, чтобы анкета была заполнена полностью."
        : `Ещё добавьте ${formatFieldList(completion.missing)}, и анкета будет выглядеть полной.`,
  };
}

function formatFieldList(items: string[]) {
  if (items.length <= 1) {
    return items[0] || "";
  }

  if (items.length === 2) {
    return `${items[0]} и ${items[1]}`;
  }

  return `${items.slice(0, -1).join(", ")} и ${items[items.length - 1]}`;
}
