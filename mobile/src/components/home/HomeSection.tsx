import { Image, Pressable, ScrollView, Text, View } from "react-native";

import { styles } from "../../styles/appStyles";
import type {
  AppUser,
  City,
  Locker,
  LockerAvailabilityItem,
  ProductDetail,
  ProductListItem,
  ReservationSummary,
  VerificationState,
} from "../../types";
import {
  formatCompactUserName,
  formatCountText,
  formatPriceTag,
  formatRentalEta,
  formatUserInitials,
  inferToolArtwork,
  statusLabel,
  type ToolArtworkKind,
  verificationLabel,
} from "../../utils/appFormatters";

type RuntimeMode = "live" | "fallback";

export function HomeTopBar({
  user,
  city,
  lockerCount,
  notificationCount,
  onOpenCatalog,
}: {
  user: AppUser | null;
  city: string;
  lockerCount: number;
  notificationCount: number;
  onOpenCatalog: () => void;
}) {
  const lockerBadgeValue = String(lockerCount);

  return (
    <View style={styles.homeTopBar}>
      <View style={styles.homeUserRow}>
        <View style={styles.homeUserInfo}>
          <HomeAvatar user={user} />
          <View style={styles.homeUserTextBlock}>
            <Text style={styles.homeUserName}>{formatCompactUserName(user)}</Text>
            <View style={styles.homeUserBadgeRow}>
              <View style={styles.pointsBadge}>
                <DiamondGlyph />
                <Text style={styles.pointsBadgeText}>{lockerBadgeValue}</Text>
              </View>
              <Text style={styles.homeCityText}>{city}</Text>
            </View>
          </View>
        </View>

        <View style={styles.homeUtilityRow}>
          <Pressable style={styles.utilityIconButton}>
            <SupportGlyph />
          </Pressable>
          <Pressable style={styles.utilityIconButton}>
            <BellGlyph />
            {notificationCount > 0 ? <View style={styles.utilityDot} /> : null}
          </Pressable>
        </View>
      </View>

      <Pressable style={styles.homeSearchBar} onPress={onOpenCatalog}>
        <SearchGlyph />
        <Text style={styles.homeSearchText}>Поиск</Text>
      </Pressable>
    </View>
  );
}

function SearchGlyph() {
  return (
    <View style={styles.searchGlyph}>
      <View style={styles.searchGlyphCircle} />
      <View style={styles.searchGlyphHandle} />
    </View>
  );
}

function HomeAvatar({ user }: { user: AppUser | null }) {
  return (
    <View style={styles.homeAvatar}>
      <Text style={styles.homeAvatarInitials}>{formatUserInitials(user)}</Text>
    </View>
  );
}

function DiamondGlyph() {
  return <View style={styles.diamondGlyph} />;
}

function SupportGlyph() {
  return (
    <View style={styles.supportGlyph}>
      <View style={styles.supportGlyphBand} />
      <View style={styles.supportGlyphLeft} />
      <View style={styles.supportGlyphRight} />
      <View style={styles.supportGlyphMic} />
    </View>
  );
}

function BellGlyph() {
  return (
    <View style={styles.bellGlyph}>
      <View style={styles.bellGlyphBody} />
      <View style={styles.bellGlyphClapper} />
    </View>
  );
}

function HomeSectionHeader({
  title,
  action,
  onActionPress,
}: {
  title: string;
  action?: string;
  onActionPress?: () => void;
}) {
  return (
    <View style={styles.homeSectionHeader}>
      <Text style={styles.homeSectionTitle}>{title}</Text>
      {action ? (
        <Pressable onPress={onActionPress}>
          <Text style={styles.homeSectionAction}>{action}</Text>
        </Pressable>
      ) : null}
    </View>
  );
}

function HomeNoticeCard({
  eyebrow,
  title,
  text,
}: {
  eyebrow: string;
  title: string;
  text: string;
}) {
  return (
    <View style={styles.homeNoticeCard}>
      <Text style={styles.homeNoticeEyebrow}>{eyebrow}</Text>
      <Text style={styles.homeNoticeTitle}>{title}</Text>
      <Text style={styles.homeNoticeText}>{text}</Text>
    </View>
  );
}

function ToolArtwork({
  name,
  coverUrl,
  compact = false,
}: {
  name: string;
  coverUrl?: string | null;
  compact?: boolean;
}) {
  if (coverUrl) {
    return <Image source={{ uri: coverUrl }} style={styles.toolImage} resizeMode="contain" />;
  }

  const kind = inferToolArtwork(name);
  if (kind === "generator") {
    return <GeneratorArtwork compact={compact} />;
  }
  if (kind === "welder") {
    return <WelderArtwork compact={compact} />;
  }
  if (kind === "drill") {
    return <DrillArtwork compact={compact} />;
  }
  return <ToolboxArtwork compact={compact} />;
}

function DrillArtwork({ compact = false }: { compact?: boolean }) {
  return (
    <View style={[styles.toolArtFrame, compact && styles.toolArtFrameCompact]}>
      <View style={styles.drillShadow} />
      <View style={[styles.drillBody, compact && styles.drillBodyCompact]} />
      <View style={[styles.drillNose, compact && styles.drillNoseCompact]} />
      <View style={[styles.drillHandle, compact && styles.drillHandleCompact]} />
      <View style={[styles.drillBattery, compact && styles.drillBatteryCompact]} />
      <View style={styles.drillAccent} />
    </View>
  );
}

function GeneratorArtwork({ compact = false }: { compact?: boolean }) {
  return (
    <View style={[styles.toolArtFrame, compact && styles.toolArtFrameCompact]}>
      <View style={styles.generatorShadow} />
      <View style={[styles.generatorShell, compact && styles.generatorShellCompact]}>
        <View style={styles.generatorVent} />
        <View style={styles.generatorPanel} />
        <View style={styles.generatorHandle} />
      </View>
      <View style={styles.generatorWheelLeft} />
      <View style={styles.generatorWheelRight} />
    </View>
  );
}

function WelderArtwork({ compact = false }: { compact?: boolean }) {
  return (
    <View style={[styles.toolArtFrame, compact && styles.toolArtFrameCompact]}>
      <View style={styles.welderShadow} />
      <View style={[styles.welderBody, compact && styles.welderBodyCompact]}>
        <View style={styles.welderPanel} />
      </View>
      <View style={styles.welderHandle} />
      <View style={styles.welderCable} />
    </View>
  );
}

function ToolboxArtwork({ compact = false }: { compact?: boolean }) {
  return (
    <View style={[styles.toolArtFrame, compact && styles.toolArtFrameCompact]}>
      <View style={styles.toolboxShadow} />
      <View style={[styles.toolboxBody, compact && styles.toolboxBodyCompact]} />
      <View style={styles.toolboxHandle} />
      <View style={styles.toolboxLatchLeft} />
      <View style={styles.toolboxLatchRight} />
    </View>
  );
}

function HeroCard({
  city,
  user,
  verification,
  selectedLocker,
  selectedProduct,
  lockersCount,
  productsCount,
  readyUnitsCount,
  screenMessage,
  runtimeMode,
  onOpenCatalog,
  onOpenLockers,
}: {
  city: string;
  user: AppUser | null;
  verification: VerificationState | null;
  selectedLocker: Locker | null;
  selectedProduct: ProductDetail | null;
  lockersCount: number;
  productsCount: number;
  readyUnitsCount: number;
  screenMessage: string;
  runtimeMode: RuntimeMode;
  onOpenCatalog: () => void;
  onOpenLockers: () => void;
}) {
  const verificationStatus = verificationLabel(verification?.status ?? user?.verificationStatus);
  const hasProducts = productsCount > 0;
  const hasLockers = lockersCount > 0;
  const overviewTitle = selectedProduct
    ? selectedLocker
      ? `${selectedProduct.name} можно забрать через ${selectedLocker.name}`
      : `${selectedProduct.name} готов к бронированию`
    : hasLockers
      ? `${formatCountText(lockersCount, "постамат", "постамата", "постаматов")} доступны в ${city}`
      : `В ${city} пока нет точек выдачи`;
  const overviewText = selectedProduct
    ? selectedLocker
      ? `${selectedLocker.address}. Откройте бронь или смените точку выдачи.`
      : "Товар выбран. Осталось привязать его к постамату для выдачи."
    : selectedLocker
      ? `${selectedLocker.address}. Статус точки: ${statusLabel(selectedLocker.status).toLowerCase()}.`
      : screenMessage;
  const focusLabel = selectedLocker ? "Выбранный постамат" : "Что сейчас по городу";
  const focusTitle = selectedLocker?.name ?? (hasProducts ? "Каталог активен" : "Каталог пуст");
  const focusText = selectedLocker?.address
    ?? (hasProducts
      ? `${formatCountText(productsCount, "товар", "товара", "товаров")} доступны к бронированию`
      : "Товары ещё не опубликованы");
  const primaryActionLabel = hasProducts ? "Открыть каталог" : "Открыть карту";
  const primaryAction = hasProducts ? onOpenCatalog : onOpenLockers;
  const secondaryActionLabel = hasProducts ? "Постаматы" : "Каталог";
  const secondaryAction = hasProducts ? onOpenLockers : onOpenCatalog;

  return (
    <View style={styles.heroCard}>
      <View style={styles.heroTopRow}>
        <View style={styles.heroBrandPill}>
          <Text style={styles.heroBrandPillText}>{city}</Text>
        </View>
        <View style={[styles.heroStatusPill, runtimeMode === "fallback" ? styles.heroStatusPillPending : styles.heroStatusPillApproved]}>
          <Text style={styles.heroStatusPillText}>{runtimeMode === "fallback" ? "Демо" : verificationStatus}</Text>
        </View>
      </View>

      <View style={styles.heroBody}>
        <View style={styles.heroCopyBlock}>
          <Text style={styles.heroKicker}>Главный экран</Text>
          <Text style={styles.heroTitle}>{overviewTitle}</Text>
          <Text style={styles.heroText}>{overviewText}</Text>
        </View>

        <View style={styles.heroVisualCard}>
          <Text style={styles.heroVisualLabel}>{focusLabel}</Text>
          <Text style={styles.heroVisualTitle} numberOfLines={2}>
            {focusTitle}
          </Text>
          <Text style={styles.heroVisualPrice} numberOfLines={3}>
            {focusText}
          </Text>
        </View>
      </View>

      <View style={styles.heroMetaRow}>
        <View style={styles.heroMetaCard}>
          <Text style={styles.heroMetaLabel}>Постаматы</Text>
          <Text style={styles.heroMetaValue}>{lockersCount}</Text>
        </View>
        <View style={styles.heroMetaCard}>
          <Text style={styles.heroMetaLabel}>Товары</Text>
          <Text style={styles.heroMetaValue}>{productsCount}</Text>
        </View>
        <View style={styles.heroMetaCard}>
          <Text style={styles.heroMetaLabel}>Готово</Text>
          <Text style={styles.heroMetaValue}>{readyUnitsCount}</Text>
        </View>
      </View>

      <View style={styles.heroMessageCard}>
        <Text style={styles.heroMessageLabel}>Аккаунт</Text>
        <Text style={styles.heroMessageText} numberOfLines={2}>
          {user?.phone ?? "Номер будет показан после входа"} • {verificationStatus}
        </Text>
      </View>

      <View style={styles.heroActions}>
        <Pressable style={[styles.heroAction, styles.heroActionPrimary]} onPress={primaryAction}>
          <Text style={styles.heroActionPrimaryText}>{primaryActionLabel}</Text>
        </Pressable>
        <Pressable style={[styles.heroAction, styles.heroActionGhost]} onPress={secondaryAction}>
          <Text style={styles.heroActionGhostText}>{secondaryActionLabel}</Text>
        </Pressable>
      </View>
    </View>
  );
}

export function CityStrip({
  cities,
  selectedCityId,
  onSelect,
}: {
  cities: City[];
  selectedCityId: string;
  onSelect: (cityId: string) => void;
}) {
  return (
    <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.cityRow}>
      {cities.map((city) => {
        const active = city.id === selectedCityId;
        return (
          <Pressable
            key={city.id}
            style={[styles.cityChip, active && styles.cityChipActive]}
            onPress={() => onSelect(city.id)}
          >
            <Text style={[styles.cityChipText, active && styles.cityChipTextActive]}>{city.name}</Text>
          </Pressable>
        );
      })}
    </ScrollView>
  );
}

export function HomeTab({
  cities,
  selectedCityId,
  user,
  verification,
  runtimeMode,
  screenMessage,
  products,
  lockers,
  availability,
  reservation,
  selectedProduct,
  selectedLocker,
  onSelectCity,
  onSelectProduct,
  onOpenCatalog,
  onOpenLockers,
  onOpenLocker,
  onOpenBooking,
}: {
  cities: City[];
  selectedCityId: string;
  user: AppUser | null;
  verification: VerificationState | null;
  runtimeMode: RuntimeMode;
  screenMessage: string;
  products: ProductListItem[];
  lockers: Locker[];
  availability: LockerAvailabilityItem[];
  reservation: ReservationSummary | null;
  selectedProduct: ProductDetail | null;
  selectedLocker: Locker | null;
  onSelectCity: (cityId: string) => void;
  onSelectProduct: (productId: string) => void;
  onOpenCatalog: () => void;
  onOpenLockers: () => void;
  onOpenLocker: (lockerId: string) => void;
  onOpenBooking: () => void;
}) {
  const selectedCity = cities.find((city) => city.id === selectedCityId) ?? null;
  const hasActiveRental = Boolean(reservation);
  const hasDraftBookingContext = Boolean(selectedProduct || selectedLocker);
  const rentalName = hasActiveRental
    ? reservation?.product?.name ?? "Активная аренда"
    : selectedProduct?.name ?? "Товар ещё не выбран";
  const rentalCover = hasActiveRental
    ? reservation?.product?.coverUrl ?? null
    : selectedProduct?.coverUrl ?? null;
  const rentalAddress = hasActiveRental
    ? reservation?.locker?.address ?? reservation?.locker?.name ?? "Точка выдачи уточняется"
    : selectedLocker?.address ?? "Точка выдачи ещё не выбрана";
  const rentalEta = hasActiveRental ? formatRentalEta(reservation?.expiresAt) : "";
  const rentalSectionTitle = hasActiveRental ? "Текущая аренда" : "Следующий шаг";
  const rentalSectionAction = hasActiveRental
    ? undefined
    : selectedProduct && selectedLocker
      ? "Оформить"
      : selectedProduct
        ? "Точка"
        : selectedLocker
          ? "Товар"
          : "Каталог";
  const rentalEyebrow = hasActiveRental
    ? "Уже в работе"
    : hasDraftBookingContext
      ? "Подготовлено по вашему выбору"
      : "Выбор ещё не собран";
  const rentalMeta = hasActiveRental
    ? rentalAddress
    : selectedProduct && selectedLocker
      ? `${selectedLocker.address}. Перейдите к бронированию, чтобы зафиксировать выдачу ${selectedProduct.name}.`
      : selectedProduct
        ? `Выбран товар ${selectedProduct.name}. Теперь укажите постамат для выдачи.`
        : selectedLocker
          ? `Выбран постамат ${selectedLocker.name}. Теперь добавьте товар для бронирования.`
          : "Выберите товар и постамат, чтобы перейти к реальному бронированию.";
  const rentalBadgeLabel = hasActiveRental
    ? rentalEta
    : selectedProduct && selectedLocker
      ? "Перейти к брони"
      : selectedProduct
        ? "Выбрать точку"
        : selectedLocker
          ? "Выбрать товар"
          : "Открыть каталог";
  const rentalAction = hasActiveRental
    ? onOpenBooking
    : selectedProduct && selectedLocker
      ? onOpenBooking
      : selectedProduct
        ? onOpenLockers
        : onOpenCatalog;
  const readyUnits = availability.reduce((total, item) => total + item.availableUnits, 0);
  const nearbyLockers = lockers.slice(0, 6);
  const hasProducts = products.length > 0;
  const showRentalSection = hasActiveRental || hasDraftBookingContext;

  return (
    <View style={styles.homeTabBlock}>
      {hasProducts ? (
        <>
          {cities.length > 1 ? (
            <CityStrip cities={cities} selectedCityId={selectedCityId} onSelect={onSelectCity} />
          ) : null}

          <HomeSectionHeader
            title="Популярные инструменты"
            action="Смотреть все"
            onActionPress={onOpenCatalog}
          />
          <ScrollView
            horizontal
            showsHorizontalScrollIndicator={false}
            contentContainerStyle={styles.featuredToolsRow}
          >
            {products.slice(0, 6).map((product) => (
              <Pressable
                key={product.id}
                style={styles.featuredToolCard}
                onPress={() => onSelectProduct(product.id)}
              >
                <View style={styles.featuredToolArtwork}>
                  <ToolArtwork name={product.name} coverUrl={product.coverUrl} />
                </View>
                <Text style={styles.featuredToolTitle} numberOfLines={3}>
                  {product.name}
                </Text>
                <View style={styles.featuredToolPricePill}>
                  <Text style={styles.featuredToolPriceText}>{formatPriceTag(product.priceFrom)}</Text>
                </View>
              </Pressable>
            ))}
          </ScrollView>
        </>
      ) : cities.length > 1 ? (
        <CityStrip cities={cities} selectedCityId={selectedCityId} onSelect={onSelectCity} />
      ) : null}

      {showRentalSection ? (
        <>
          <HomeSectionHeader
            title="Текущая аренда"
            action={hasActiveRental ? undefined : rentalSectionAction}
            onActionPress={hasActiveRental ? undefined : rentalAction}
          />
          <Pressable
            style={[styles.currentRentalCard, !hasActiveRental && styles.currentRentalCardIdle]}
            onPress={rentalAction}
          >
            <View style={styles.currentRentalArtwork}>
              <ToolArtwork name={rentalName} coverUrl={rentalCover} compact />
            </View>
            <View style={styles.currentRentalMain}>
              <Text style={styles.currentRentalTitle} numberOfLines={3}>
                {rentalName}
              </Text>
              <Text style={styles.currentRentalMeta} numberOfLines={2}>
                {rentalMeta}
              </Text>
              <View style={[styles.currentRentalBadge, !hasActiveRental && styles.currentRentalBadgeIdle]}>
                <View
                  style={[styles.currentRentalBadgeDot, !hasActiveRental && styles.currentRentalBadgeDotIdle]}
                />
                <Text
                  style={[styles.currentRentalBadgeText, !hasActiveRental && styles.currentRentalBadgeTextIdle]}
                >
                  {rentalBadgeLabel}
                </Text>
              </View>
            </View>
          </Pressable>
        </>
      ) : null}

      {nearbyLockers.length ? (
        <>
          <HomeSectionHeader
            title={hasProducts ? "Пункты выдачи" : "Постаматы"}
            action="Карта"
            onActionPress={onOpenLockers}
          />
          <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.homeLockerRow}>
            {nearbyLockers.map((locker) => (
              <Pressable
                key={locker.id}
                style={[
                  styles.homeLockerCard,
                  locker.id === selectedLocker?.id && styles.homeLockerCardActive,
                ]}
                onPress={() => onOpenLocker(locker.id)}
              >
                <View style={styles.homeLockerCardTop}>
                  <Text style={styles.homeLockerCardTitle} numberOfLines={1}>
                    {locker.name}
                  </Text>
                  <View style={[styles.homeLockerStatusPill, locker.status === "online" ? styles.homeLockerStatusOnline : styles.homeLockerStatusOffline]}>
                    <Text style={styles.homeLockerStatusText}>{statusLabel(locker.status)}</Text>
                  </View>
                </View>
                <Text style={styles.homeLockerCardAddress} numberOfLines={2}>
                  {locker.address}
                </Text>
                <View style={styles.homeLockerMetricsRow}>
                  <Metric label="Товаров" value={locker.availableProductCount} />
                  <Metric label="Ячеек" value={locker.availableUnitCount ?? 0} />
                </View>
              </Pressable>
            ))}
          </ScrollView>
        </>
      ) : !hasProducts ? (
        <HomeNoticeCard
          eyebrow="Каталог"
          title="Товаров пока нет"
          text={
            lockers.length
              ? `В ${selectedCity?.name ?? "выбранном городе"} уже добавлены постаматы, но каталог ещё не заполнен.`
              : "Как только товары появятся, они будут показаны здесь без подстановок и шаблонов."
          }
        />
      ) : null}
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
