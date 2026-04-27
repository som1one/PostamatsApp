"use client";

import { useCallback, useEffect, useState } from "react";
import { Clock3, ImageIcon, PackageCheck, RotateCcw } from "lucide-react";
import { EmptyState } from "@/components/EmptyState";
import { PageChrome } from "@/components/PageChrome";
import { PageHeader } from "@/components/PageHeader";
import { RequireAuth } from "@/components/RequireAuth";
import { StatusPill } from "@/components/StatusPill";
import { Surface } from "@/components/Surface";
import { fetchRentals, requestRentalReturn } from "@/shared/api/endpoints";
import type { RentalListItem } from "@/shared/api/types";
import { formatDateTime } from "@/shared/format";

const filters = [
  { value: "", label: "Все" },
  { value: "active", label: "Активные" },
  { value: "completed", label: "Завершённые" },
  { value: "cancelled", label: "Отменённые" },
];

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
  const [rentals, setRentals] = useState<RentalListItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [busyId, setBusyId] = useState("");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const items = await fetchRentals(status || undefined);
      setRentals(items);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось загрузить аренды");
    } finally {
      setLoading(false);
    }
  }, [status]);

  useEffect(() => {
    void load();
  }, [load]);

  async function handleReturn(rentalId: string) {
    setBusyId(rentalId);
    setMessage("");
    setError("");
    try {
      const result = await requestRentalReturn(rentalId);
      setMessage(result.return.instructions || "Возврат запущен.");
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось начать возврат");
    } finally {
      setBusyId("");
    }
  }

  return (
    <>
      <PageHeader
        eyebrow="Аренды"
        title="Мои аренды"
        subtitle="Активные выдачи, история и возврат через доступные постаматы."
        actions={
          <select
            className="select"
            value={status}
            onChange={(event) => setStatus(event.target.value)}
          >
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
        <div className="loader">Загружаем аренды</div>
      ) : rentals.length ? (
        <div className="product-grid">
          {rentals.map((rental) => (
            <Surface className="product-card" key={rental.id}>
              <div className="product-cover">
                {rental.product.coverUrl ? (
                  <img src={rental.product.coverUrl} alt={rental.product.name || "Товар"} />
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
                {["active", "overdue"].includes(rental.status) ? (
                  <button
                    className="button button-secondary"
                    type="button"
                    disabled={busyId === rental.id}
                    onClick={() => handleReturn(rental.id)}
                  >
                    <RotateCcw size={18} />
                    Возврат
                  </button>
                ) : null}
              </div>
            </Surface>
          ))}
        </div>
      ) : (
        <EmptyState
          icon={<PackageCheck size={34} />}
          title="Аренд пока нет"
          text="После первой успешной оплаты здесь появятся активные и завершённые аренды."
        />
      )}
    </>
  );
}
