"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  AlertTriangle,
  CheckCircle2,
  Clock3,
  CreditCard,
  ImageIcon,
  MapPin,
  PackageCheck,
  RotateCcw,
  XCircle,
  Copy,
  ArrowLeftRight,
  type LucideIcon,
} from "lucide-react";
import { EmptyState } from "@/components/EmptyState";
import { PageChrome } from "@/components/PageChrome";
import { PageHeader } from "@/components/PageHeader";
import { RequireAuth } from "@/components/RequireAuth";
import { StatusPill } from "@/components/StatusPill";
import { Surface } from "@/components/Surface";
import {
  cancelReservation,
  confirmRentalReturn,
  createPaymentPreauth,
  fetchMyReservations,
  fetchReservation,
  fetchRentals,
  requestRentalReturn,
} from "@/shared/api/endpoints";
import { ApiError } from "@/shared/api/client";
import type { RentalListItem, UpcomingReservation } from "@/shared/api/types";
import { buildRescheduleProductHref } from "@/shared/checkout/reschedule";
import { writePendingCheckout } from "@/shared/checkout/pending";
import { formatCountRu, formatDateTime } from "@/shared/format";
import { resolvePublicAssetUrl } from "@/shared/media";
import { isRentalFinished } from "@/shared/rentalStatus";
import { useAuth } from "@/shared/auth/auth-context";

const DEV_PAYMENT_BYPASS_ENABLED =
  process.env.NEXT_PUBLIC_ENABLE_DEV_PAYMENT_BYPASS === "true";

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

export function getRentalDeadlineMeta(rental: RentalListItem, nowMs: number): DeadlineMeta | null {
  if (rental.status === "return_in_progress") {
    return {
      tone: "success",
      title: "Возврат уже начат",
      text: "Завершите возврат через открытую ячейку постамата.",
      Icon: CheckCircle2,
    };
  }

  // Завершённые аренды (терминальный статус ИЛИ проставлен actualEndAt) не
  // рисуют deadline-плашку вне зависимости от того, прошло ли плановое
  // окончание. Это закрывает в т.ч. случаи, когда статус ещё не успел
  // прийти к "completed" (отставание webhook'а, ручная админская правка),
  // но фактический возврат уже зафиксирован.
  if (isRentalFinished(rental)) {
    return null;
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

  // Если до старта аренды ещё ждать — показываем дату выдачи, а не дедлайн.
  if (
    ["pickup_ready", "pickup_opened"].includes(rental.status) &&
    rental.startsAt
  ) {
    const startsMs = new Date(rental.startsAt).getTime();
    if (!Number.isNaN(startsMs) && startsMs - nowMs > 60 * 60 * 1000) {
      const wait = formatDurationLabel(startsMs - nowMs);
      return {
        tone: "warn",
        title: `Получение через ${wait}`,
        text: `Заберите товар после ${formatDateTime(rental.startsAt)}`,
        Icon: Clock3,
      };
    }
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
  const router = useRouter();
  const { session } = useAuth();
  const [status, setStatus] = useState("");
  const [reservations, setReservations] = useState<UpcomingReservation[]>([]);
  const [rentals, setRentals] = useState<RentalListItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [nowMs, setNowMs] = useState(() => Date.now());

  // Per-card busy state: maps item id → true
  const [busyIds, setBusyIds] = useState<Record<string, boolean>>({});
  const [cardError, setCardError] = useState<Record<string, string>>({});

  // Refund dialog (payment_authorized cancel)
  const [showRefundDialog, setShowRefundDialog] = useState(false);
  const [pendingCancelId, setPendingCancelId] = useState<string | null>(null);

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

  function setBusy(id: string, value: boolean) {
    setBusyIds((prev) => ({ ...prev, [id]: value }));
  }

  function setItemError(id: string, msg: string) {
    setCardError((prev) => ({ ...prev, [id]: msg }));
  }

  // ── Pay reservation ──────────────────────────────────────────
  async function handlePay(reservation: UpcomingReservation, e: React.MouseEvent) {
    e.stopPropagation();
    setBusy(reservation.id, true);
    setItemError(reservation.id, "");
    try {
      // Создаём платёж через ЮKassa и перенаправляем на страницу оплаты.
      const preauth = await createPaymentPreauth({
        reservationId: reservation.id,
      });

      writePendingCheckout({
        reservationId: reservation.id,
        paymentId: preauth.payment.id,
        userId: session?.user?.id || "",
        createdAt: new Date().toISOString(),
      });

      const confirmationUrl = preauth.confirmation?.confirmationUrl;
      if (confirmationUrl) {
        window.location.href = confirmationUrl;
      } else {
        router.push("/payment/return");
      }
    } catch (err) {
      if (err instanceof ApiError && err.code === "PAYMENT_ALREADY_EXISTS") {
        // Оплата уже прошла — перезагружаем список, чтобы обновить статус брони.
        await load();
        setBusy(reservation.id, false);
        return;
      }
      let msg = "Не удалось оформить оплату";
      if (err instanceof ApiError) {
        if (err.code === "LOCKER_OFFLINE") {
          msg =
            "Постамат сейчас офлайн. Попробуйте чуть позже — в ночные часы устройство может уходить в режим обслуживания.";
        } else if (err.code === "LOCKER_NOT_CONFIGURED") {
          msg = "Постамат пока не привязан к серверу. Обратитесь в поддержку.";
        } else if (err.code === "ESI_RESERVE_FAILED" || err.code === "ESI_HTTP_ERROR") {
          msg = "Не удалось зарезервировать ячейку. Попробуйте ещё раз через минуту.";
        } else if (err.message) {
          msg = err.message;
        }
      } else if (err instanceof Error) {
        msg = err.message;
      }
      setItemError(reservation.id, msg);
      setBusy(reservation.id, false);
    }
  }

  // ── Cancel reservation ───────────────────────────────────────
  function handleCancelClick(reservation: UpcomingReservation, e: React.MouseEvent) {
    e.stopPropagation();
    if (reservation.status === "payment_authorized") {
      setPendingCancelId(reservation.id);
      setShowRefundDialog(true);
      return;
    }
    void doCancel(reservation.id);
  }

  async function doCancel(reservationId: string) {
    setBusy(reservationId, true);
    setItemError(reservationId, "");
    try {
      const result = await cancelReservation(reservationId);
      setReservations((prev) =>
        prev.map((r) =>
          r.id === reservationId
            ? { ...r, status: result.reservation.status, cancelledAt: result.reservation.cancelledAt ?? null }
            : r,
        ),
      );
    } catch (err) {
      setItemError(reservationId, err instanceof Error ? err.message : "Не удалось отменить бронь");
    } finally {
      setBusy(reservationId, false);
    }
  }

  function handleRefundConfirm() {
    if (!pendingCancelId) return;
    const id = pendingCancelId;
    setShowRefundDialog(false);
    setPendingCancelId(null);
    void doCancel(id);
  }

  async function handleReschedule(reservationIdArg?: string) {
    setShowRefundDialog(false);
    const reservationId = reservationIdArg || pendingCancelId;
    setPendingCancelId(null);

    if (!reservationId) {
      router.push("/catalog");
      return;
    }

    try {
      const reservation = await fetchReservation(reservationId);
      const href = buildRescheduleProductHref(reservation);
      router.push(href || "/catalog");
    } catch {
      router.push("/catalog");
    }
  }

  // ── Return rental: simple action returning to pickup locker ──
  // Redirect to order detail page for return flow
  function handleReturnRental(rental: RentalListItem, e: React.MouseEvent) {
    e.stopPropagation();
    router.push(`/profile/orders/${rental.id}`);
  }

  async function handleConfirmReturnRental(rental: RentalListItem, e: React.MouseEvent) {
    e.stopPropagation();
    setBusy(rental.id, true);
    setItemError(rental.id, "");
    try {
      await confirmRentalReturn(rental.id);
      setRentals((prev) =>
        prev.map((r) => (r.id === rental.id ? { ...r, status: "completed" } : r)),
      );
      void load();
    } catch (err) {
      let msg = "Не удалось подтвердить возврат";
      if (err instanceof ApiError) {
        if (err.code === "RETURN_REQUEST_NOT_FOUND") {
          msg = "Активная заявка на возврат не найдена. Откройте детали заказа и оформите возврат заново.";
        } else if (err.code === "RENTAL_NOT_RETURNING") {
          msg = "Возврат ещё не начат или уже завершён.";
        } else if (err.message) {
          msg = err.message;
        }
      } else if (err instanceof Error) {
        msg = err.message;
      }
      setItemError(rental.id, msg);
    } finally {
      setBusy(rental.id, false);
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

      {error ? <div className="alert alert-danger">{error}</div> : null}

      {loading ? (
        <div className="loader">Загружаем заказы</div>
      ) : hasOrders ? (
        <div className="product-grid orders-grid">
          {reservations.map((reservation) => {
                  const deadlineMeta = getReservationDeadlineMeta(reservation, nowMs);
                  const busy = busyIds[reservation.id] ?? false;
                  const itemErr = cardError[reservation.id] ?? "";
                  const canPay = ["created", "awaiting_payment"].includes(reservation.status);
                  const canCancel = ["created", "awaiting_payment", "payment_authorized"].includes(reservation.status);
                  const showActions = canPay || canCancel;

                  return (
                    <div
                      key={reservation.id}
                      className="product-card-clickable"
                      onClick={() => router.push(`/profile/orders/${reservation.id}`)}
                      role="article"
                      tabIndex={0}
                      onKeyDown={(e) => e.key === "Enter" && router.push(`/profile/orders/${reservation.id}`)}
                    >
                    <Surface className="product-card">
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
                        </div>
                        {deadlineMeta ? (
                          <div className={`rental-deadline rental-deadline-${deadlineMeta.tone}`}>
                            <deadlineMeta.Icon size={16} />
                            <div>
                              <strong>{deadlineMeta.title}</strong>
                            </div>
                          </div>
                        ) : null}
                        {itemErr ? (
                          <p className="muted small" style={{ color: "var(--danger, #dd362d)" }}>{itemErr}</p>
                        ) : null}
                        {showActions ? (
                          <div className="card-actions" onClick={(e) => e.stopPropagation()}>
                            {canPay ? (
                              <button
                                className="button button-primary button-sm"
                                type="button"
                                disabled={busy}
                                onClick={(e) => handlePay(reservation, e)}
                              >
                                <CreditCard size={15} />
                                {busy ? "Открываем оплату…" : "Оплатить"}
                              </button>
                            ) : null}
                            {reservation.status === "payment_authorized" ? (
                              <button
                                className="button button-secondary button-sm"
                                type="button"
                                disabled={busy}
                                onClick={(e) => { e.stopPropagation(); void handleReschedule(reservation.id); }}
                              >
                                <ArrowLeftRight size={15} />
                                Перенести
                              </button>
                            ) : null}
                            {canCancel ? (
                              <button
                                className="button button-ghost button-sm"
                                type="button"
                                disabled={busy}
                                onClick={(e) => handleCancelClick(reservation, e)}
                              >
                                <XCircle size={15} />
                                Отменить
                              </button>
                            ) : null}
                          </div>
                        ) : null}
                        {DEV_PAYMENT_BYPASS_ENABLED && canPay ? (
                          <div className="card-actions" onClick={(e) => e.stopPropagation()}>
                            <span className="muted small">dev: любой код подойдёт</span>
                          </div>
                        ) : null}
                      </div>
                    </Surface>
                    </div>
                  );
                })}

          {rentals.map((rental) => {
                  const deadlineMeta = getRentalDeadlineMeta(rental, nowMs);
                  const busy = busyIds[rental.id] ?? false;
                  const itemErr = cardError[rental.id] ?? "";
                  const canReturn = ["active", "overdue"].includes(rental.status);
                  const canConfirmReturn = rental.status === "return_in_progress";

                  return (
                    <div
                      key={rental.id}
                      className="product-card-clickable"
                      onClick={() => router.push(`/profile/orders/${rental.id}`)}
                      role="article"
                      tabIndex={0}
                      onKeyDown={(e) => e.key === "Enter" && router.push(`/profile/orders/${rental.id}`)}
                    >
                    <Surface className="product-card">
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
                        {deadlineMeta ? (
                          <div className={`rental-deadline rental-deadline-${deadlineMeta.tone}`}>
                            <deadlineMeta.Icon size={16} />
                            <div>
                              <strong>{deadlineMeta.title}</strong>
                            </div>
                          </div>
                        ) : null}
                        {itemErr ? (
                          <p className="muted small" style={{ color: "var(--danger, #dd362d)" }}>{itemErr}</p>
                        ) : null}
                        {rental.pickupPin && ["pickup_ready", "pickup_opened"].includes(rental.status) ? (
                          <div className="pickup-pin-display" style={{ padding: "12px", backgroundColor: "#f0fdf4", borderRadius: "8px", border: "1px solid #bbf7d0", display: "flex", alignItems: "center", justifyContent: "space-between", marginTop: "12px", marginBottom: "12px" }}>
                            <div>
                              <div style={{ fontSize: "12px", color: "#166534", marginBottom: "2px" }}>Ваш PIN-код:</div>
                              <div style={{ fontSize: "24px", fontWeight: "bold", fontFamily: "monospace", color: "#15803d" }}>{rental.pickupPin}</div>
                            </div>
                            <button
                              type="button"
                              className="button button-ghost button-sm"
                              style={{ padding: "6px", minHeight: "unset", minWidth: "unset", borderRadius: "8px", color: "#15803d" }}
                              onClick={(e) => {
                                e.stopPropagation();
                                navigator.clipboard.writeText(rental.pickupPin!);
                              }}
                              title="Скопировать PIN-код"
                            >
                              <Copy size={18} />
                            </button>
                          </div>
                        ) : null}
                        {canReturn ? (
                          <div className="card-actions" onClick={(e) => e.stopPropagation()}>
                            <button
                              className="button button-primary button-sm"
                              type="button"
                              disabled={busy}
                              onClick={(e) => handleReturnRental(rental, e)}
                            >
                              <RotateCcw size={15} />
                              {busy ? "Открываем ячейку…" : "Вернуть"}
                            </button>
                          </div>
                        ) : null}
                        {canConfirmReturn ? (
                          <div className="card-actions" onClick={(e) => e.stopPropagation()}>
                            <Link
                              href={`/profile/orders/${rental.id}`}
                              className="button button-primary button-sm"
                              onClick={(e) => e.stopPropagation()}
                            >
                              <RotateCcw size={15} />
                              Детали возврата
                            </Link>
                          </div>
                        ) : null}
                      </div>
                    </Surface>
                    </div>
                  );
                })}
        </div>
      ) : (
        <EmptyState
          icon={<PackageCheck size={34} />}
          title="Заказов пока нет"
          text="После первого оформления здесь появятся будущие брони и активные аренды."
        />
      )}

      {/* Refund confirmation dialog */}
      {showRefundDialog ? (
        <div className="modal-overlay" role="dialog" aria-modal="true">
          <div className="modal-box">
            <div className="modal-icon">
              <XCircle size={26} />
            </div>
            <h2 className="modal-title">Отменить бронь?</h2>
            <p className="modal-text">
              Вы уверены, что хотите отменить? Средства вернутся на карту. Вы можете перенести запись на другое время.
            </p>
            <div className="modal-actions">
              <div className="modal-actions-row">
                <button
                  className="button button-secondary"
                  type="button"
                  onClick={() => void handleReschedule()}
                >
                  <ArrowLeftRight size={16} />
                  Перенести запись
                </button>
                <button
                  className="button button-primary"
                  type="button"
                  disabled={pendingCancelId ? (busyIds[pendingCancelId] ?? false) : false}
                  onClick={handleRefundConfirm}
                >
                  Да, отменить
                </button>
              </div>
              <div className="modal-back">
                <button
                  type="button"
                  onClick={() => { setShowRefundDialog(false); setPendingCancelId(null); }}
                >
                  Назад
                </button>
              </div>
            </div>
          </div>
        </div>
      ) : null}
    </>
  );
}
