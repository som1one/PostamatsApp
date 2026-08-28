import type { BonusTransaction } from "./api/types";

/**
 * Бонусы — целые рубли, в API ходят в минорных единицах (как все суммы).
 * Один рубль бонусов = 100 минорных единиц.
 */
export const BONUS_MINOR_STEP = 100;

const TRANSACTION_LABELS: Record<BonusTransaction["type"], string> = {
  order_accrual: "Начисление за аренду",
  order_spend: "Оплата заказа бонусами",
  order_spend_refund: "Возврат за отменённый заказ",
  admin_accrual: "Начисление от поддержки",
  admin_withdrawal: "Списание поддержкой",
};

export function bonusTransactionLabel(transaction: BonusTransaction) {
  return transaction.comment?.trim() || TRANSACTION_LABELS[transaction.type] || "Операция";
}

/**
 * Потолок списания: меньшее из баланса и доли заказа, вниз до целого рубля.
 * Формула повторяет `max_spendable_for_order` на бэкенде — там она и решает,
 * здесь только чтобы не показывать заведомо отклоняемое значение.
 */
export function maxBonusSpend(
  balanceMinor: number,
  orderAmountMinor: number,
  maxSharePercent: number,
) {
  const share = Math.floor((orderAmountMinor * maxSharePercent) / 100);
  const cap = Math.min(Math.max(balanceMinor, 0), Math.max(share, 0));
  return Math.floor(cap / BONUS_MINOR_STEP) * BONUS_MINOR_STEP;
}

/**
 * Сколько бонусов вернётся за заказ. Считается от суммы, которая уйдёт
 * картой, а не от цены заказа: бонусы не порождают бонусы. Повторяет
 * `accrue_rental_bonus` на бэкенде, включая округление вниз до рубля.
 */
export function estimateBonusAccrual(cardAmountMinor: number, accrualPercent: number) {
  const raw = (Math.max(cardAmountMinor, 0) * accrualPercent) / 100;
  return Math.floor(raw / BONUS_MINOR_STEP) * BONUS_MINOR_STEP;
}

/** Значение поля ввода (целые рубли) → минорные единицы, с обрезкой по потолку. */
export function clampBonusInput(rubles: number, maxMinor: number) {
  if (!Number.isFinite(rubles) || rubles <= 0) {
    return 0;
  }
  return Math.min(Math.floor(rubles) * BONUS_MINOR_STEP, maxMinor);
}
