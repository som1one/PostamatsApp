import { ActivityIndicator, Pressable, Text, View } from "react-native";

import { palette, styles } from "../../styles/appStyles";
import type {
  AppUser,
  Locker,
  PricePlan,
  PricingQuote,
  ProductDetail,
  ProductListItem,
  ReservationQuote,
  ReservationSummary,
  VerificationState,
} from "../../types";
import { formatMoney, productMonogram, verificationLabel } from "../../utils/appFormatters";

type RuntimeMode = "live" | "fallback";
type TabKey = "home" | "lockers" | "catalog" | "booking" | "profile";

export function CatalogTab({
  products,
  selectedProductId,
  selectedProduct,
  selectedLockerId,
  selectedPlanId,
  detailLoading,
  onSelectProduct,
  onSelectLocker,
  onSelectPlan,
  onGoToBooking,
}: {
  products: ProductListItem[];
  selectedProductId: string;
  selectedProduct: ProductDetail | null;
  selectedLockerId: string;
  selectedPlanId: string;
  detailLoading: boolean;
  onSelectProduct: (productId: string) => void;
  onSelectLocker: (lockerId: string) => void;
  onSelectPlan: (planId: string) => void;
  onGoToBooking: () => void;
}) {
  return (
    <View style={styles.tabBlock}>
      <SectionHeader title="Каталог" action="товары в наличии" />
      {products.map((product) => {
        const active = product.id === selectedProductId;
        return (
          <Pressable
            key={product.id}
            style={[styles.productCard, active && styles.productCardActive]}
            onPress={() => onSelectProduct(product.id)}
          >
            <View style={styles.productThumb}>
              <Text style={styles.productThumbText}>{productMonogram(product.name)}</Text>
            </View>
            <View style={styles.productMain}>
              <Text style={styles.cardTitle}>{product.name}</Text>
              <Text style={styles.cardText}>{product.shortDescription ?? "Короткое описание, тарифы и точки выдачи."}</Text>
            </View>
            <View style={styles.productMeta}>
              <Text style={styles.priceText}>{formatMoney(product.priceFrom, product.currency)}</Text>
              <Text style={styles.stockText}>{product.availableLockerCount} точки</Text>
            </View>
          </Pressable>
        );
      })}

      <SectionHeader title="Карточка товара" action="тарифы и точки" />
      <View style={styles.detailCard}>
        {detailLoading ? (
          <View style={styles.inlineLoader}>
            <ActivityIndicator size="small" color={palette.hero} />
            <Text style={styles.cardText}>Загружаем карточку товара, точки и тарифы.</Text>
          </View>
        ) : selectedProduct ? (
          <>
            <View style={styles.detailHeader}>
              <View style={styles.detailThumb}>
                <Text style={styles.detailThumbText}>{productMonogram(selectedProduct.name)}</Text>
              </View>
              <View style={styles.detailMain}>
                <Text style={styles.detailTitle}>{selectedProduct.name}</Text>
                <Text style={styles.cardText}>{selectedProduct.shortDescription}</Text>
              </View>
            </View>

            <Text style={styles.subsectionTitle}>Тарифы</Text>
            <View style={styles.tagRow}>
              {selectedProduct.pricePlans.map((plan) => {
                const active = plan.id === selectedPlanId;
                return (
                  <Pressable
                    key={plan.id}
                    style={[styles.tagChip, active && styles.tagChipActive]}
                    onPress={() => onSelectPlan(plan.id)}
                  >
                    <Text style={[styles.tagChipText, active && styles.tagChipTextActive]}>
                      {plan.name} • {formatMoney(plan.baseAmount, plan.currency)}
                    </Text>
                  </Pressable>
                );
              })}
            </View>

            <Text style={styles.subsectionTitle}>Точки выдачи</Text>
            <View style={styles.tagRow}>
              {selectedProduct.availableLockers.map((locker) => {
                const active = locker.lockerId === selectedLockerId;
                return (
                  <Pressable
                    key={locker.lockerId}
                    style={[styles.tagChip, active && styles.tagChipActive]}
                    onPress={() => onSelectLocker(locker.lockerId)}
                  >
                    <Text style={[styles.tagChipText, active && styles.tagChipTextActive]}>
                      {locker.name} • {locker.availableUnits} шт.
                    </Text>
                  </Pressable>
                );
              })}
            </View>

            <Text style={styles.bodyText}>{selectedProduct.fullDescription}</Text>
            <Text style={styles.subsectionTitle}>Комплект</Text>
            <Text style={styles.cardText}>{selectedProduct.kitDescription}</Text>
            <Pressable style={styles.primaryButton} onPress={onGoToBooking}>
              <Text style={styles.primaryButtonText}>К расчёту и брони</Text>
            </Pressable>
          </>
        ) : (
          <Text style={styles.cardText}>Выберите товар, чтобы увидеть тарифы, описание и доступные точки.</Text>
        )}
      </View>
    </View>
  );
}

export function BookingTab({
  selectedProduct,
  selectedLocker,
  selectedPlan,
  pricing,
  quote,
  reservation,
  bookingLoading,
  canReserve,
  isDemo,
  onGetQuote,
  onCreateReservation,
}: {
  selectedProduct: ProductDetail | null;
  selectedLocker: Locker | null;
  selectedPlan: PricePlan | null;
  pricing: PricingQuote | null;
  quote: ReservationQuote | null;
  reservation: ReservationSummary | null;
  bookingLoading: boolean;
  canReserve: boolean;
  isDemo: boolean;
  onGetQuote: () => void;
  onCreateReservation: () => void;
}) {
  return (
    <View style={styles.tabBlock}>
      <SectionHeader title="Бронирование" action="2 шага" />
      <View style={styles.checkoutHero}>
        <Text style={styles.checkoutHeroTitle}>Проверьте стоимость перед бронью</Text>
        <Text style={styles.checkoutHeroText}>
          Покажем сумму, удержание и окно, пока бронь ожидает подтверждения.
        </Text>
      </View>

      <View style={styles.checkoutCard}>
        <Text style={styles.subsectionTitle}>Что выбрано</Text>
        <Text style={styles.cardTitle}>{selectedProduct?.name ?? "Товар не выбран"}</Text>
        <Text style={styles.cardText}>{selectedLocker?.address ?? "Точка не выбрана"}</Text>
        <Text style={styles.cardText}>{selectedPlan ? `${selectedPlan.name} • ${formatMoney(selectedPlan.baseAmount, selectedPlan.currency)}` : "Тариф не выбран"}</Text>

        <View style={styles.checkoutDivider} />

        <Text style={styles.subsectionTitle}>Стоимость</Text>
        <CheckoutRow label="База" value={pricing ? formatMoney(pricing.baseAmount, pricing.currency) : "—"} />
        <CheckoutRow label="Предавторизация" value={pricing ? formatMoney(pricing.preauthAmount, pricing.currency) : "—"} />
        <CheckoutRow label="Итого" value={pricing ? formatMoney(pricing.totalAmount, pricing.currency) : "—"} strong />

        {!canReserve ? (
          <View style={styles.inlineNotice}>
            <Text style={styles.alertText}>Бронирование откроется после подтверждения аккаунта.</Text>
          </View>
        ) : null}

        <View style={styles.bookingActions}>
          <Pressable
            style={[styles.primaryButton, (!canReserve || bookingLoading) && styles.buttonDisabled]}
            onPress={onGetQuote}
            disabled={!canReserve || bookingLoading}
          >
            <Text style={styles.primaryButtonText}>{bookingLoading ? "Считаем..." : "Показать сумму"}</Text>
          </Pressable>

          <Pressable
            style={[styles.secondaryButton, (!quote || !canReserve || bookingLoading) && styles.buttonDisabled]}
            onPress={onCreateReservation}
            disabled={!quote || !canReserve || bookingLoading}
          >
            <Text style={styles.secondaryButtonText}>Подтвердить бронь</Text>
          </Pressable>
        </View>

        {quote ? (
          <>
            <View style={styles.checkoutDivider} />
            <Text style={styles.subsectionTitle}>Расчет</Text>
            <CheckoutRow label="Сумма" value={formatMoney(quote.quotedAmount, quote.currency)} />
            <CheckoutRow label="Действует" value={`${quote.expiresIn} сек`} />
          </>
        ) : null}

        {reservation ? (
          <>
            <View style={styles.checkoutDivider} />
            <Text style={styles.subsectionTitle}>Бронь создана</Text>
            <CheckoutRow label="ID" value={reservation.id} />
            <CheckoutRow label="Статус" value={reservation.status} />
            <CheckoutRow label="Истекает" value={new Date(reservation.expiresAt).toLocaleString("ru-RU")} />
            <Text style={styles.cardText}>
              {isDemo
                ? "В демо остаемся на этом экране."
                : "После подключения оплаты здесь появится следующий шаг с подтверждением выдачи."}
            </Text>
          </>
        ) : null}
      </View>
    </View>
  );
}

export function ProfileTab({
  user,
  verification,
  runtimeMode,
  refreshToken,
  onLogout,
}: {
  user: AppUser | null;
  verification: VerificationState | null;
  runtimeMode: RuntimeMode;
  refreshToken: string;
  onLogout: () => void | Promise<void>;
}) {
  return (
    <View style={styles.tabBlock}>
      <SectionHeader title="Профиль" action="аккаунт" />
      <View style={styles.profileCard}>
        <Text style={styles.cardTitle}>{user?.firstName ? `${user.firstName} ${user.lastName ?? ""}`.trim() : user?.phone ?? "Пользователь"}</Text>
        <Text style={styles.cardText}>Телефон: {user?.phone ?? "—"}</Text>
        <Text style={styles.cardText}>Статус верификации: {verificationLabel(verification?.status ?? user?.verificationStatus)}</Text>
        <Text style={styles.cardText}>Режим: {runtimeMode === "live" ? "подключено к серверу" : "демо-режим"}</Text>
        <View style={styles.profileMeta}>
          <Metric label="Сессия" value={refreshToken ? "активна" : "нет"} />
          <Metric label="Блокировка" value={user?.isBlocked ? "да" : "нет"} />
        </View>
        <Pressable style={styles.ghostButtonDark} onPress={onLogout}>
          <Text style={styles.ghostButtonDarkText}>Выйти</Text>
        </Pressable>
      </View>
    </View>
  );
}

function MiniFeature({
  eyebrow,
  title,
  text,
  tone = "sand",
}: {
  eyebrow: string;
  title: string;
  text: string;
  tone?: "sand" | "clay" | "dark";
}) {
  return (
    <View
      style={[
        styles.miniFeature,
        tone === "clay" && styles.miniFeatureClay,
        tone === "dark" && styles.miniFeatureDark,
      ]}
    >
      <Text style={[styles.miniFeatureEyebrow, tone === "dark" && styles.miniFeatureEyebrowDark]}>
        {eyebrow}
      </Text>
      <Text style={[styles.miniFeatureTitle, tone === "dark" && styles.miniFeatureTitleDark]}>{title}</Text>
      <Text style={[styles.miniFeatureText, tone === "dark" && styles.miniFeatureTextDark]}>{text}</Text>
    </View>
  );
}

function SectionHeader({ title, action }: { title: string; action: string }) {
  return (
    <View style={styles.homeSectionHeader}>
      <Text style={styles.homeSectionTitle}>{title}</Text>
      <Text style={styles.homeSectionAction}>{action}</Text>
    </View>
  );
}

function Metric({ label, value, suffix }: { label: string; value: string | number; suffix?: string }) {
  return (
    <View style={styles.metric}>
      <Text style={styles.metricLabel}>{label}</Text>
      <Text style={styles.metricValue}>
        {value}
        {suffix ?? ""}
      </Text>
    </View>
  );
}

function CheckoutRow({
  label,
  value,
  strong = false,
}: {
  label: string;
  value: string;
  strong?: boolean;
}) {
  return (
    <View style={styles.checkoutRow}>
      <Text style={[styles.cardText, strong && styles.checkoutStrong]}>{label}</Text>
      <Text style={[styles.cardText, strong && styles.checkoutStrong]}>{value}</Text>
    </View>
  );
}

export function BottomNavIcon({
  kind,
  active,
  badgeCount = 0,
}: {
  kind: "home" | "map" | "catalog" | "booking" | "more";
  active: boolean;
  badgeCount?: number;
}) {
  const fillTone = active ? styles.navGlyphFillActive : styles.navGlyphFillInactive;
  const strokeTone = active ? styles.navGlyphStrokeActive : styles.navGlyphStrokeInactive;

  return (
    <View style={styles.navIconWrap}>
      {kind === "home" ? (
        <View style={styles.navHomeGlyph}>
          <View style={[styles.navHomeRoof, fillTone]} />
          <View style={[styles.navHomeBody, fillTone]} />
          <View style={[styles.navHomeDoor, active && styles.navHomeDoorActive]} />
        </View>
      ) : null}

      {kind === "map" ? (
        <View style={styles.navMapGlyph}>
          <View style={[styles.navMapPin, strokeTone]}>
            <View style={[styles.navMapPinDot, active && styles.navMapPinDotActive]} />
          </View>
          <View style={[styles.navMapBase, fillTone]} />
        </View>
      ) : null}

      {kind === "catalog" ? (
        <View style={styles.navCatalogGlyph}>
          <View style={[styles.navCatalogHandleLeft, fillTone]} />
          <View style={[styles.navCatalogHeadLeft, fillTone]} />
          <View style={[styles.navCatalogHandleRight, fillTone]} />
          <View style={[styles.navCatalogHeadRight, strokeTone]} />
        </View>
      ) : null}

      {kind === "booking" ? (
        <View style={styles.navBookingGlyph}>
          <View style={[styles.navBookingCircle, strokeTone]} />
          <View style={[styles.navBookingHandShort, fillTone]} />
          <View style={[styles.navBookingHandLong, fillTone]} />
        </View>
      ) : null}

      {kind === "more" ? (
        <View style={styles.navMoreGlyph}>
          <View style={[styles.navMoreDot, active && styles.navMoreDotActive]} />
          <View style={[styles.navMoreDot, active && styles.navMoreDotActive]} />
          <View style={[styles.navMoreDot, active && styles.navMoreDotActive]} />
        </View>
      ) : null}

      {badgeCount > 0 ? (
        <View style={styles.navBadge}>
          <Text style={styles.navBadgeText}>{badgeCount}</Text>
        </View>
      ) : null}
    </View>
  );
}

export function BottomNav({
  current,
  onChange,
  bookingBadgeCount,
}: {
  current: TabKey;
  onChange: (tab: TabKey) => void;
  bookingBadgeCount: number;
}) {
  const items: Array<{
    key: TabKey;
    label: string;
    icon: "home" | "map" | "catalog" | "booking" | "more";
    badgeCount?: number;
  }> = [
    { key: "home", label: "Главная", icon: "home" },
    { key: "lockers", label: "Карта", icon: "map" },
    { key: "catalog", label: "Каталог", icon: "catalog" },
    { key: "booking", label: "В аренде", icon: "booking", badgeCount: bookingBadgeCount },
    { key: "profile", label: "Ещё", icon: "more" },
  ];

  return (
    <View style={styles.bottomNav}>
      {items.map((item) => {
        const active = item.key === current;
        return (
          <Pressable
            key={item.key}
            style={styles.navItem}
            onPress={() => onChange(item.key)}
          >
            <BottomNavIcon kind={item.icon} active={active} badgeCount={item.badgeCount} />
            <Text style={[styles.navItemText, active && styles.navItemTextActive]}>{item.label}</Text>
          </Pressable>
        );
      })}
    </View>
  );
}
