"use client";

import { useCallback, useEffect, useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  Clock3,
  ImageIcon,
  MapPin,
  PackageCheck,
  RotateCcw,
  XCircle,
  type LucideIcon,
} from "lucide-react";
import { EmptyState } from "@/components/EmptyState";
import { PageChrome } from "@/components/PageChrome";
import { PageHeader } from "@/components/PageHeader";
import { RequireAuth } from "@/components/RequireAuth";
import { StatusPill } from "@/components/StatusPill";
import { Surface } from "@/components/Surface";
import { ApiError } from "@/shared/api/client";
import {
  cancelReservation,
  fetchMyReservations,
  fetchRentals,
  requestRentalReturn,
} from "@/shared/api/endpoints";
import type { RentalListItem, UpcomingReservation } from "@/shared/api/types";
import { formatCountRu, formatDateTime } from "@/shared/format";
import { resolvePublicAssetUrl } from "@/shared/media";

const filters = [
  { value: "", label: "Все" },
  { value: "active", label: "Активные" },
  { value: "completed", label: "Завершённые" },
  { value: "cancelled", label: "Отменённые" },
];

type DeadlineMeta = {
  tone: "warn" | "danger" | "success";
  title: string;
  text: string;
  Icon: LucideIcon;
};

function formatDurationLabel(diffMs: number) {
  const totalMinutes = Math.max(1, Math.ceil(Math.abs(diffMs) / 60_000));
  const days = Math.floor(totalMinutes / (60 * 24));
  const hours = Math.floor((totalMinutes % (60 * 24)) / 60);
  const minutes = totalMinutes % 60;
  const parts: string[] = [];

  if (days > 0) {
    parts.push(formatCountRu(days, ["день", "дня", "дней"]));
  }
  if (hours > 0) {
    parts.push(formatCountRu(hours, ["час", "часа", "часов"]));
  }
  if (days === 0 && minutes > 0) {
    parts.push(formatCountRu(minutes, ["минута", "минуты", "минут"]));
  }

  return parts.join(" ");
}

function getReservationDeadlineMeta(reservation: UpcomingReservation, nowMs: number): DeadlineMeta | null {
  const expiresMs = new Date(reservation.expiresAt).getTime();
  if (Number.isNaN(expiresMs)) {
    return null;
  }

  const diffMs = expiresMs - nowMs;
  const duration = formatDurationLabel(diffMs);

  if (diffMs <= 0) {
    return {
      tone: "danger",
      title: `Бронь истекла ${duration} назад`,
      text: "Эта бронь уже недоступна для выдачи.",
      Icon: AlertTriangle,
    };
  }

  if (reservation.status === "payment_authorized") {
    return {
      tone: "success",
      title: `До выдачи: ${duration}`,
      text: `Оплата подтверждена. Заберите до ${formatDateTime(reservation.expiresAt)}.`,
      Icon: CheckCircle2,
    };
  }

  return {
    tone: "warn",
    title: `До отмены брони: ${duration}`,
    text: `Оплатите и заберите до ${formatDateTime(reservation.expiresAt)}.`,
    Icon: Clock3,
  };
}

function getRentalDeadlineMeta(rental: RentalListItem, nowMs: number): DeadlineMeta | null {
  if (rental.status === "return_in_progress") {
    return {
      tone: "success",
      title: "Возврат уже начат",
      text: "Завершите возврат через открытую ячейку постамата.",
      Icon: CheckCircle2,
    };
  }

  if (!rental.plannedEndAt) {
    return null;
  }

  const plannedEndMs = new Date(rental.plannedEndAt).getTime();
  if (Number.isNaN(plannedEndMs)) {
    return null;
  }

  const diffMs = plannedEndMs - nowMs;
  const duration = formatDurationLabel(diffMs);

  if (rental.status === "overdue" || diffMs <= 0) {
    return {
      tone: "danger",
      title: `Просрочено на ${duration}`,
      text: "Стоит оформить возврат как можно скорее.",
      Icon: AlertTriangle,
    };
  }

  if (["pickup_ready", "pickup_opened", "active"].includes(rental.status)) {
    return {
      tone: "warn",
      title: `До возврата: ${duration}`,
      text: `Вернуть до ${formatDateTime(rental.plannedEndAt)}`,
      Icon: Clock3,
    };
  }

  return null;
}

function getReservationCancelMessage(error: unknown) {
  if (error instanceof ApiError) {
    if (error.code === "RESERVATION_NOT_CANCELLABLE") {
      return "Эту бронь уже нельзя отменить вручную.";
    }
    if (error.code === "RESERVATION_CANCEL_FAILED") {
      return "Не удалось отменить бронь. Попробуйте ещё раз.";
    }
  }

  return error instanceof Error ? error.message : "Не удалось отменить бронь";
}

export function RentalsClient() {
  return (
    <PageChrome>
      <RequireAuth>
        <RentalsContent />
      </RequireAuth>
    </PageChrome>
  );
}

function RentalsContent() {
  const [status, setStatus] = useState("");
  const [reservations, setReservations] = useState<UpcomingReservation[]>([]);
  const [rentals, setRentals] = useState<RentalListItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [busyRentalId, setBusyRentalId] = useState("");
  const [busyReservationId, setBusyReservationId] = useState("");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [nowMs, setNowMs] = useState(() => Date.now());

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [nextReservations, nextRentals] = await Promise.all([
        fetchMyReservations(),
        fetchRentals(status || undefined),
      ]);
      setReservations(nextReservations);
      setRentals(nextRentals);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось загрузить заказы");
    } finally {
      setLoading(false);
    }
  }, [status]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    const timer = window.setInterval(() => {
      setNowMs(Date.now());
    }, 60_000);
    return () => window.clearInterval(timer);
  }, []);

  async function handleReturn(rentalId: string) {
    setBusyRentalId(rentalId);
    setMessage("");
    setError("");
    try {
      const result = await requestRentalReturn(rentalId);
      setMessage(result.return.instructions || "Возврат запущен.");
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось начать возврат");
    } finally {
      setBusyRentalId("");
    }
  }

  async function handleCancelReservation(reservationId: string) {
    setBusyReservationId(reservationId);
    setMessage("");
    setError("");
    try {
      await cancelReservation(reservationId);
      setMessage("Бронь отменена.");
      await load();
    } catch (err) {
      setError(getReservationCancelMessage(err));
    } finally {
      setBusyReservationId("");
    }
  }

  const hasOrders = reservations.length > 0 || rentals.length > 0;

  return (
    <>
      <PageHeader
        eyebrow="Заказы"
        title="Мои заказы"
        subtitle="Будущие брони, активные аренды, история и возврат через доступные постаматы."
        actions={
          <select className="select" value={status} onChange={(event) => setStatus(event.target.value)}>
            {filters.map((item) => (
              <option key={item.value} value={item.value}>
                {item.label}
              </option>
            ))}
          </select>
        }
      />

      {message ? <div className="alert">{message}</div> : null}
      {error ? <div className="alert alert-danger">{error}</div> : null}

      {loading ? (
        <div className="loader">Загружаем заказы</div>
      ) : hasOrders ? (
        <div className="orders-stack">
          {reservations.length ? (
            <section className="orders-section">
              <div className="orders-section-head">
                <div>
                  <p className="eyebrow">Брони</p>
                  <h2 className="section-title">Будущие аренды</h2>
                </div>
                <p className="muted small">Показываем, сколько осталось до выдачи или автоматической отмены.</p>
              </div>
              <div className="product-grid">
                {reservations.map((reservation) => {
                  const deadlineMeta = getReservationDeadlineMeta(reservation, nowMs);
                  return (
                    <Surface className="product-card" key={reservation.id}>
                      <div className="product-cover">
                        {resolvePublicAssetUrl(reservation.product.coverUrl) ? (
                          <img
                            src={resolvePublicAssetUrl(reservation.product.coverUrl) || undefined}
                            alt={reservation.product.name || "Товар"}
                          />
                        ) : (
                          <ImageIcon size={44} color="#dd362d" />
                        )}
                      </div>
                      <div className="product-body">
                        <div className="card-row">
                          <span className="icon-badge">
                            <PackageCheck size={20} />
                          </span>
                          <StatusPill status={reservation.status} />
                        </div>
                        <div>
                          <p className="eyebrow">Будущая бронь</p>
                          <h2 className="section-title">{reservation.product.name || "Товар"}</h2>
                        </div>
                        <div className="timeline">
                          <div className="timeline-item">
                            <span className="timeline-dot">
                              <MapPin size={17} />
                            </span>
                            <div>
                              <strong>{reservation.locker.name || "Постамат выдачи"}</strong>
                              <p className="muted small">{reservation.locker.address || "Адрес уточняется"}</p>
                            </div>
                          </div>
                          <div className="timeline-item">
                            <span className="timeline-dot">
                              <Clock3 size={17} />
                            </span>
                            <div>
                              <strong>Забрать до</strong>
                              <p className="muted small">{formatDateTime(reservation.expiresAt)}</p>
                            </div>
                          </div>
                        </div>
                        {deadlineMeta ? (
                          <div className={`rental-deadline rental-deadline-${deadlineMeta.tone}`}>
                            <deadlineMeta.Icon size={16} />
                            <div>
                              <strong>{deadlineMeta.title}</strong>
                              <span>{deadlineMeta.text}</span>
                            </div>
                          </div>
                        ) : null}
                        {["created", "awaiting_payment"].includes(reservation.status) ? (
                          <button
                            className="button button-secondary"
                            type="button"
                            disabled={busyReservationId === reservation.id}
                            onClick={() => handleCancelReservation(reservation.id)}
                          >
                            <XCircle size={18} />
                            Отменить
                          </button>
                        ) : null}
                      </div>
                    </Surface>
                  );
                })}
              </div>
            </section>
          ) : null}

          {rentals.length ? (
            <section className="orders-section">
              <div className="orders-section-head">
                <div>
                  <p className="eyebrow">Аренды</p>
                  <h2 className="section-title">Текущие и прошлые</h2>
                </div>
              </div>
              <div className="product-grid">
                {rentals.map((rental) => {
                  const deadlineMeta = getRentalDeadlineMeta(rental, nowMs);
                  return (
                    <Surface className="product-card" key={rental.id}>
                      <div className="product-cover">
                        {resolvePublicAssetUrl(rental.product.coverUrl) ? (
                          <img
                            src={resolvePublicAssetUrl(rental.product.coverUrl) || undefined}
                            alt={rental.product.name || "Товар"}
                          />
                        ) : (
                          <ImageIcon size={44} color="#dd362d" />
                        )}
                      </div>
                      <div className="product-body">
                        <div className="card-row">
                          <span className="icon-badge">
                            <PackageCheck size={20} />
                          </span>
                          <StatusPill status={rental.status} />
                        </div>
                        <div>
                          <p className="eyebrow">{rental.locker.name}</p>
                          <h2 className="section-title">{rental.product.name || "Товар"}</h2>
                        </div>
                        <div className="timeline">
                          <div className="timeline-item">
                            <span className="timeline-dot">
                              <Clock3 size={17} />
                            </span>
                            <div>
                              <strong>Плановое окончание</strong>
                              <p className="muted small">{formatDateTime(rental.plannedEndAt)}</p>
                            </div>
                          </div>
                        </div>
                        {deadlineMeta ? (
                          <div className={`rental-deadline rental-deadline-${deadlineMeta.tone}`}>
                            <deadlineMeta.Icon size={16} />
                            <div>
                              <strong>{deadlineMeta.title}</strong>
                              <span>{deadlineMeta.text}</span>
                            </div>
                          </div>
                        ) : null}
                        {["active", "overdue"].includes(rental.status) ? (
                          <button
                            className="button button-secondary"
                            type="button"
                            disabled={busyRentalId === rental.id}
                            onClick={() => handleReturn(rental.id)}
                          >
                            <RotateCcw size={18} />
                            Возврат
                          </button>
                        ) : null}
                      </div>
                    </Surface>
                  );
                })}
              </div>
            </section>
          ) : null}
        </div>
      ) : (
        <EmptyState
          icon={<PackageCheck size={34} />}
          title="Заказов пока нет"
          text="После первого оформления здесь появятся будущие брони и активные аренды."
        />
      )}
    </>
  );
}
