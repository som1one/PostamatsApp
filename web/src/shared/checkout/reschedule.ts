import type { ReservationSummary } from "@/shared/api/types";

export function buildRescheduleProductHref(
  reservation: Pick<
    ReservationSummary,
    "id" | "productId" | "lockerId" | "durationType" | "durationValue"
  > &
    Partial<Pick<ReservationSummary, "product">>,
) {
  if (
    !reservation.id ||
    !reservation.productId ||
    !reservation.lockerId ||
    !reservation.durationType ||
    !reservation.durationValue
  ) {
    return null;
  }

  const params = new URLSearchParams({
    lockerId: reservation.lockerId,
    durationType: reservation.durationType,
    durationValue: String(reservation.durationValue),
    reservationId: reservation.id,
  });

  return `/catalog/${reservation.product?.id || reservation.productId}?${params.toString()}`;
}
