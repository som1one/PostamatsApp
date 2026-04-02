import { useEffect, useMemo, useRef, useState } from "react";
import {
  ActivityIndicator,
  Animated,
  LayoutChangeEvent,
  Pressable,
  SafeAreaView,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";

import {
  confirmCode,
  createReservation,
  createReservationQuote,
  fetchCities,
  fetchLockerAvailability,
  fetchLockers,
  fetchMe,
  fetchProduct,
  fetchProductPricing,
  fetchProducts,
  fetchReservation,
  fetchVerification,
  requestCode,
} from "./api";
import { mockAvailability, mockCities, mockLockers, mockPricing, mockProductDetail, mockProducts } from "./mockData";
import type {
  AppUser,
  City,
  ConfirmCodeResponse,
  Locker,
  LockerAvailabilityItem,
  PricePlan,
  PricingQuote,
  ProductDetail,
  ProductListItem,
  ReservationQuote,
  ReservationSummary,
  VerificationState,
} from "./types";

type TabKey = "home" | "lockers" | "catalog" | "booking" | "profile";
type AuthStep = "landing" | "request" | "confirm";
type AuthIntent = "login" | "signup";
type RuntimeMode = "live" | "fallback";

const palette = {
  bg: "#f5f1ea",
  panel: "#fffaf4",
  card: "#fffdf9",
  hero: "#c6281e",
  heroDark: "#8e1912",
  text: "#1f2330",
  subtext: "#6e6a67",
  border: "#eadfce",
  success: "#20603b",
  danger: "#b42d1c",
  muted: "#f0e5d9",
  accent: "#f4a261",
};

const demoUser: AppUser = {
  id: "demo-user",
  phone: "+7 999 000 00 00",
  firstName: "Demo",
  lastName: "User",
  verificationStatus: "approved",
  preferredCityId: mockCities[0]?.id,
  isBlocked: false,
};

const demoVerification: VerificationState = {
  status: "approved",
};

const landingSlides = [
  {
    key: "no-deposit",
    title: "Аренда без залога!",
    subtitle: "Берите нужное без лишних трат и замороженных денег.",
    illustration: "no-deposit" as const,
  },
  {
    key: "nearby",
    title: "Постаматы рядом",
    subtitle: "Выберите ближайшую точку и заберите товар по пути домой.",
    illustration: "nearby" as const,
  },
  {
    key: "fast",
    title: "Быстрое бронирование",
    subtitle: "Номер телефона, пара шагов и бронь уже ждёт вас в постамате.",
    illustration: "fast" as const,
  },
  {
    key: "return",
    title: "Простой возврат",
    subtitle: "Верните товар обратно в ячейку и закройте аренду за минуту.",
    illustration: "return" as const,
  },
];

function formatMoney(amount: number, currency = "RUB") {
  return new Intl.NumberFormat("ru-RU", {
    style: "currency",
    currency,
    maximumFractionDigits: 0,
  }).format(amount / 100);
}

function productMonogram(name: string) {
  return name
    .split(" ")
    .slice(0, 2)
    .map((chunk) => chunk[0]?.toUpperCase() ?? "")
    .join("");
}

function statusLabel(status: Locker["status"]) {
  if (status === "online") return "Онлайн";
  if (status === "offline") return "Офлайн";
  if (status === "maintenance") return "Сервис";
  return "Нестабильно";
}

function verificationLabel(status?: string) {
  if (status === "approved") return "Проверен";
  if (status === "pending_review") return "На проверке";
  if (status === "rejected") return "Отклонен";
  if (status === "blocked") return "Заблокирован";
  return "Нужна проверка";
}

function sanitizePhoneInput(value: string) {
  const compact = value.replace(/\s+/g, "");
  const plusNormalized = compact.startsWith("00") ? `+${compact.slice(2)}` : compact;
  const singlePlus = plusNormalized.replace(/(?!^)\+/g, "");

  if (singlePlus.startsWith("+")) {
    const digits = singlePlus.slice(1).replace(/\D/g, "").slice(0, 12);
    return digits ? `+${digits}` : "+";
  }

  return singlePlus.replace(/\D/g, "").slice(0, 12);
}

function normalizeRuByPhone(value: string) {
  const sanitized = sanitizePhoneInput(value);
  const digits = sanitized.replace(/\D/g, "");

  if (!digits) {
    return "";
  }

  if (sanitized.startsWith("+")) {
    if (digits.startsWith("375")) {
      return `+${digits.slice(0, 12)}`;
    }

    if (digits.startsWith("7")) {
      return `+${digits.slice(0, 11)}`;
    }

    return `+${digits}`;
  }

  if (digits.startsWith("375")) {
    return digits.length <= 12 ? `+${digits}` : `+${digits.slice(0, 12)}`;
  }

  if (digits.startsWith("7")) {
    return `+${digits.slice(0, 11)}`;
  }

  if (digits.startsWith("8")) {
    return `+7${digits.slice(1, 11)}`;
  }

  return `+7${digits.slice(0, 10)}`;
}

function normalizePhoneForApi(value: string) {
  return normalizeRuByPhone(value);
}

function isPhoneReady(value: string) {
  const normalized = normalizeRuByPhone(value);
  if (!normalized) {
    return false;
  }

  if (normalized.startsWith("+375")) {
    return normalized.length === 13;
  }

  if (normalized.startsWith("+7")) {
    return normalized.length === 12;
  }

  return false;
}

export function PostamatsApp() {
  const [runtimeMode, setRuntimeMode] = useState<RuntimeMode>("live");
  const [authStep, setAuthStep] = useState<AuthStep>("landing");
  const [authIntent, setAuthIntent] = useState<AuthIntent>("login");
  const [tab, setTab] = useState<TabKey>("home");
  const [needsCitySelection, setNeedsCitySelection] = useState(false);

  const [phone, setPhone] = useState("");
  const [smsCode, setSmsCode] = useState("");
  const [verificationSessionId, setVerificationSessionId] = useState("");
  const [devCode, setDevCode] = useState("");
  const [authMessage, setAuthMessage] = useState("Введите номер телефона. РФ можно без +7, РБ только через +375.");
  const [authError, setAuthError] = useState("");
  const [authLoading, setAuthLoading] = useState(false);

  const [accessToken, setAccessToken] = useState("");
  const [refreshToken, setRefreshToken] = useState("");
  const [user, setUser] = useState<AppUser | null>(null);
  const [verification, setVerification] = useState<VerificationState | null>(null);

  const [cities, setCities] = useState<City[]>([]);
  const [selectedCityId, setSelectedCityId] = useState("");
  const [lockers, setLockers] = useState<Locker[]>([]);
  const [products, setProducts] = useState<ProductListItem[]>([]);
  const [availability, setAvailability] = useState<LockerAvailabilityItem[]>([]);
  const [selectedLockerId, setSelectedLockerId] = useState("");
  const [selectedProductId, setSelectedProductId] = useState("");
  const [selectedPlanId, setSelectedPlanId] = useState("");
  const [selectedProduct, setSelectedProduct] = useState<ProductDetail | null>(null);
  const [pricing, setPricing] = useState<PricingQuote | null>(null);
  const [quote, setQuote] = useState<ReservationQuote | null>(null);
  const [reservation, setReservation] = useState<ReservationSummary | null>(null);
  const [screenMessage, setScreenMessage] = useState("Показываем ближайшие точки, товары и стоимость аренды.");
  const [screenError, setScreenError] = useState("");

  const [bootLoading, setBootLoading] = useState(false);
  const [catalogLoading, setCatalogLoading] = useState(false);
  const [detailLoading, setDetailLoading] = useState(false);
  const [bookingLoading, setBookingLoading] = useState(false);

  const isAuthed = Boolean(accessToken) || runtimeMode === "fallback";
  const canReserve =
    runtimeMode === "fallback" ||
    (user?.verificationStatus === "approved" && user?.isBlocked !== true);

  const selectedCity = useMemo(
    () => cities.find((item) => item.id === selectedCityId) ?? cities[0] ?? null,
    [cities, selectedCityId],
  );
  const selectedLocker = useMemo(
    () => lockers.find((item) => item.id === selectedLockerId) ?? lockers[0] ?? null,
    [lockers, selectedLockerId],
  );
  const selectedPlan = useMemo<PricePlan | null>(
    () => selectedProduct?.pricePlans.find((item) => item.id === selectedPlanId) ?? selectedProduct?.pricePlans[0] ?? null,
    [selectedPlanId, selectedProduct],
  );

  useEffect(() => {
    if (!isAuthed || !selectedCityId) {
      return;
    }
    void loadCityData(selectedCityId);
  }, [isAuthed, selectedCityId]);

  useEffect(() => {
    if (!isAuthed || !selectedLockerId) {
      return;
    }
    void loadAvailability(selectedLockerId);
  }, [isAuthed, selectedLockerId]);

  useEffect(() => {
    if (!isAuthed || !selectedProductId) {
      return;
    }
    void loadProductDetail(selectedProductId, selectedCityId || undefined);
  }, [isAuthed, selectedProductId, selectedCityId]);

  useEffect(() => {
    if (!isAuthed || !selectedProductId || !selectedLockerId || !selectedPlan) {
      return;
    }
    void loadPricing(selectedProductId, selectedLockerId, selectedPlan.durationType, selectedPlan.durationValue);
  }, [isAuthed, selectedProductId, selectedLockerId, selectedPlanId, selectedPlan]);

  useEffect(() => {
    setQuote(null);
    setReservation(null);
    setScreenError("");
  }, [selectedCityId, selectedLockerId, selectedProductId, selectedPlanId]);

  async function handleRequestCode() {
    const normalizedPhone = normalizePhoneForApi(phone);
    if (!isPhoneReady(normalizedPhone)) {
      setAuthError("Поддерживаются только номера РФ и РБ. РФ можно вводить без +7, РБ только через +375.");
      return;
    }

    setAuthLoading(true);
    setAuthError("");
    try {
      const result = await requestCode(normalizedPhone);
      setVerificationSessionId(result.verificationSessionId);
      setDevCode(result.code ?? "");
      setAuthMessage(`Мы отправили код на ${normalizedPhone}.`);
      setAuthStep("confirm");
      if (result.code) {
        setSmsCode(result.code);
      }
    } catch (error) {
      setAuthError(error instanceof Error ? error.message : "Не удалось запросить код.");
    } finally {
      setAuthLoading(false);
    }
  }

  function openAuthEntry(mode: "login" | "signup") {
    setAuthIntent(mode);
    setAuthStep("request");
    setAuthError("");
    setDevCode("");
    setSmsCode("");
    setVerificationSessionId("");
    setAuthMessage(
      mode === "login"
        ? "Введите номер РФ или РБ, чтобы войти в приложение."
        : "Введите номер РФ или РБ, чтобы создать аккаунт и продолжить.",
    );
  }

  async function handleConfirmCode() {
    if (!verificationSessionId || !smsCode.trim()) {
      setAuthError("Введите код подтверждения.");
      return;
    }

    setAuthLoading(true);
    setAuthError("");
    try {
      const result = await confirmCode(verificationSessionId, smsCode.trim());
      await completeLogin(result);
    } catch (error) {
      setAuthError(error instanceof Error ? error.message : "Не удалось подтвердить код.");
    } finally {
      setAuthLoading(false);
    }
  }

  async function completeLogin(result: ConfirmCodeResponse) {
    setAccessToken(result.accessToken);
    setRefreshToken(result.refreshToken);
    setRuntimeMode("live");
    setTab("home");
    setAuthMessage("Вход подтвержден. Загружаем ваш профиль.");
    await hydrateAuthorizedState(result.accessToken);
  }

  async function hydrateAuthorizedState(token: string) {
    setBootLoading(true);
    setScreenError("");
    try {
      const [me, currentVerification, cityItems] = await Promise.all([
        fetchMe(token),
        fetchVerification(token),
        fetchCities(),
      ]);

      setUser(me);
      setVerification(currentVerification);
      setCities(cityItems);

      const shouldAskCity = authIntent === "signup" || !me.preferredCityId;
      const nextCityId = shouldAskCity ? "" : me.preferredCityId ?? "";
      setSelectedCityId(nextCityId);
      setNeedsCitySelection(shouldAskCity);
      setScreenMessage("Проверьте точки выдачи, выберите товар и переходите к бронированию.");
    } catch (error) {
      setScreenError(error instanceof Error ? error.message : "Не удалось инициализировать приложение.");
    } finally {
      setBootLoading(false);
    }
  }

  async function loadCityData(cityId: string) {
    if (runtimeMode === "fallback") {
      return;
    }

    setCatalogLoading(true);
    setScreenError("");
    try {
      const [lockerItems, productItems] = await Promise.all([
        fetchLockers(cityId),
        fetchProducts(cityId),
      ]);
      setLockers(lockerItems);
      setProducts(productItems);

      const nextLockerId = lockerItems[0]?.id ?? "";
      const nextProductId = productItems[0]?.id ?? "";
      setSelectedLockerId((current) => current || nextLockerId);
      setSelectedProductId((current) => current || nextProductId);
      setScreenMessage("В выбранном городе уже показаны доступные точки и товары.");
    } catch (error) {
      setScreenError(error instanceof Error ? error.message : "Не удалось загрузить каталог.");
    } finally {
      setCatalogLoading(false);
    }
  }

  async function loadAvailability(lockerId: string) {
    if (runtimeMode === "fallback") {
      return;
    }

    try {
      const items = await fetchLockerAvailability(lockerId);
      setAvailability(items);
    } catch (error) {
      setScreenError(error instanceof Error ? error.message : "Не удалось обновить наличие в точке.");
    }
  }

  async function loadProductDetail(productId: string, cityId?: string) {
    setDetailLoading(true);
    try {
      const detail = runtimeMode === "fallback" ? mockProductDetail : await fetchProduct(productId, cityId);
      setSelectedProduct(detail);

      const firstLockerId = detail.availableLockers[0]?.lockerId ?? "";
      const firstPlanId = detail.pricePlans[0]?.id ?? "";

      if (firstPlanId) {
        setSelectedPlanId((current) =>
          detail.pricePlans.some((plan) => plan.id === current) ? current : firstPlanId,
        );
      }

      if (firstLockerId) {
        setSelectedLockerId((current) =>
          detail.availableLockers.some((locker) => locker.lockerId === current) ? current : firstLockerId,
        );
      }
    } catch (error) {
      setScreenError(error instanceof Error ? error.message : "Не удалось загрузить карточку товара.");
    } finally {
      setDetailLoading(false);
    }
  }

  async function loadPricing(
    productId: string,
    lockerId: string,
    durationType: string,
    durationValue: number,
  ) {
    try {
      const result =
        runtimeMode === "fallback"
          ? { ...mockPricing, productId, lockerId, durationType, durationValue }
          : await fetchProductPricing(productId, lockerId, durationType, durationValue);
      setPricing(result);
    } catch (error) {
      setScreenError(error instanceof Error ? error.message : "Не удалось рассчитать стоимость.");
    }
  }

  async function handleQuote() {
    if (!selectedProductId || !selectedLockerId || !selectedPlan) {
      setScreenError("Сначала выберите товар, точку и тариф.");
      return;
    }

    if (!canReserve) {
      setScreenError("Бронирование откроется после подтверждения верификации.");
      return;
    }

    setBookingLoading(true);
    setScreenError("");
    try {
      const nextQuote =
        runtimeMode === "fallback"
          ? {
              productId: selectedProductId,
              lockerId: selectedLockerId,
              durationType: selectedPlan.durationType,
              durationValue: selectedPlan.durationValue,
              currency: selectedPlan.currency,
              quotedAmount: selectedPlan.baseAmount,
              preauthAmount: selectedPlan.baseAmount,
              expiresIn: 300,
            }
          : await createReservationQuote(accessToken, {
              productId: selectedProductId,
              lockerId: selectedLockerId,
              durationType: selectedPlan.durationType,
              durationValue: selectedPlan.durationValue,
            });
      setQuote(nextQuote);
      setScreenMessage("Расчет готов. Проверьте сумму и подтвердите бронь.");
      setTab("booking");
    } catch (error) {
      setScreenError(error instanceof Error ? error.message : "Не удалось рассчитать сумму.");
    } finally {
      setBookingLoading(false);
    }
  }

  async function handleCreateReservation() {
    if (!selectedProductId || !selectedLockerId || !selectedPlan) {
      setScreenError("Не хватает данных для брони.");
      return;
    }
    if (!canReserve) {
      setScreenError("Бронирование доступно только после верификации.");
      return;
    }

    setBookingLoading(true);
    setScreenError("");
    try {
      if (runtimeMode === "fallback") {
        const demoReservation: ReservationSummary = {
          id: "demo-reservation",
          status: "awaiting_payment",
          expiresAt: new Date(Date.now() + 120 * 60 * 1000).toISOString(),
          product: {
            id: selectedProductId,
            name: selectedProduct?.name,
            coverUrl: selectedProduct?.coverUrl,
          },
          locker: {
            id: selectedLockerId,
            name: selectedLocker?.name,
            address: selectedLocker?.address,
          },
          pricing: {
            quotedAmount: selectedPlan.baseAmount,
            preauthAmount: selectedPlan.baseAmount,
            currency: selectedPlan.currency,
          },
        };
        setReservation(demoReservation);
        setScreenMessage("Бронь создана. Следующим шагом останется оплата и получение.");
      } else {
        const created = await createReservation(accessToken, {
          productId: selectedProductId,
          lockerId: selectedLockerId,
          durationType: selectedPlan.durationType,
          durationValue: selectedPlan.durationValue,
          pickupWindowMinutes: 120,
        });
        const expanded = await fetchReservation(accessToken, created.id);
        setReservation(expanded);
        setScreenMessage("Бронь создана. Дальше останется оплата и подтверждение выдачи.");
      }
      setTab("booking");
    } catch (error) {
      setScreenError(error instanceof Error ? error.message : "Не удалось создать бронь.");
    } finally {
      setBookingLoading(false);
    }
  }

  function enterDemoMode() {
    setRuntimeMode("fallback");
    setAccessToken("");
    setRefreshToken("");
    setUser(demoUser);
    setVerification(demoVerification);
    setCities(mockCities);
    setSelectedCityId(mockCities[0]?.id ?? "");
    setLockers(mockLockers);
    setProducts(mockProducts);
    setAvailability(mockAvailability);
    setSelectedLockerId(mockLockers[0]?.id ?? "");
    setSelectedProductId(mockProducts[0]?.id ?? "");
    setSelectedProduct(mockProductDetail);
    setSelectedPlanId(mockProductDetail.pricePlans[0]?.id ?? "");
    setPricing(mockPricing);
    setNeedsCitySelection(false);
    setQuote(null);
    setReservation(null);
    setTab("home");
    setAuthError("");
    setAuthMessage("Открыли демо-режим. Можно посмотреть путь аренды без сервера.");
  }

  function handleLogout() {
    setAccessToken("");
    setRefreshToken("");
    setUser(null);
    setVerification(null);
    setCities([]);
    setSelectedCityId("");
    setLockers([]);
    setProducts([]);
    setAvailability([]);
    setSelectedLockerId("");
    setSelectedProductId("");
    setSelectedPlanId("");
    setSelectedProduct(null);
    setPricing(null);
    setQuote(null);
    setReservation(null);
    setRuntimeMode("live");
    setAuthStep("landing");
    setAuthIntent("login");
    setNeedsCitySelection(false);
    setPhone("");
    setSmsCode("");
    setVerificationSessionId("");
    setDevCode("");
    setTab("home");
    setScreenError("");
    setAuthMessage("Введите номер телефона. РФ можно без +7, РБ только через +375.");
  }

  if (!isAuthed) {
    return (
      <SafeAreaView style={styles.safe}>
        <AuthScreen
          authStep={authStep}
          authIntent={authIntent}
          phone={phone}
          smsCode={smsCode}
          devCode={devCode}
          authMessage={authMessage}
          authError={authError}
          authLoading={authLoading}
          onPhoneChange={setPhone}
          onCodeChange={setSmsCode}
          onRequestCode={handleRequestCode}
          onConfirmCode={handleConfirmCode}
          onBack={() => {
            setAuthStep((current) => (current === "confirm" ? "request" : "landing"));
            setAuthError("");
          }}
          onDemo={enterDemoMode}
          onStartLogin={() => openAuthEntry("login")}
          onStartRegistration={() => openAuthEntry("signup")}
        />
      </SafeAreaView>
    );
  }

  if (bootLoading) {
    return (
      <SafeAreaView style={styles.loadingShell}>
        <View style={styles.loadingCard}>
          <ActivityIndicator size="large" color={palette.hero} />
          <Text style={styles.loadingTitle}>Подготовка аренды</Text>
          <Text style={styles.loadingText}>Загружаем профиль, точки выдачи и каталог.</Text>
        </View>
      </SafeAreaView>
    );
  }

  if (needsCitySelection) {
    return (
      <SafeAreaView style={styles.safe}>
        <CitySelectionScreen
          cities={cities}
          selectedCityId={selectedCityId}
          onSelectCity={setSelectedCityId}
          onContinue={() => setNeedsCitySelection(false)}
        />
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={styles.safe}>
      <View style={styles.appShell}>
        <View style={styles.header}>
          <View>
            <Text style={styles.eyebrow}>Своими руками</Text>
            <Text style={styles.headerTitle}>Аренда рядом</Text>
          </View>
          <View style={[styles.modeBadge, runtimeMode === "live" ? styles.modeBadgeLive : styles.modeBadgeFallback]}>
            <Text style={styles.modeBadgeText}>{runtimeMode === "live" ? "Подключено" : "Демо"}</Text>
          </View>
        </View>

        <ScrollView contentContainerStyle={styles.scrollContent} showsVerticalScrollIndicator={false}>
          <HeroCard
            city={selectedCity?.name ?? "Город"}
            locker={selectedLocker?.name ?? "Выберите постамат"}
            user={user}
            verification={verification}
            onOpenCatalog={() => setTab("catalog")}
            onOpenLockers={() => setTab("lockers")}
          />

          {screenError ? (
            <View style={styles.alertDanger}>
              <Text style={styles.alertTitle}>Не удалось загрузить данные</Text>
              <Text style={styles.alertText}>{screenError}</Text>
            </View>
          ) : null}

          {!canReserve ? (
            <View style={styles.alertWarn}>
              <Text style={styles.alertTitle}>Бронь пока недоступна</Text>
              <Text style={styles.alertText}>
                Как только аккаунт будет подтвержден, здесь откроется расчет суммы и оформление аренды.
              </Text>
            </View>
          ) : null}

          <View style={styles.sectionHeader}>
            <Text style={styles.sectionTitle}>Сейчас в приложении</Text>
            <Text style={styles.sectionHint}>{screenMessage}</Text>
          </View>

          <CityStrip cities={cities} selectedCityId={selectedCityId} onSelect={setSelectedCityId} />

          {catalogLoading ? (
            <View style={styles.loadingInlineCard}>
              <ActivityIndicator size="small" color={palette.hero} />
              <Text style={styles.cardText}>Обновляем точки и каталог по выбранному городу.</Text>
            </View>
          ) : null}

          {tab === "home" && (
            <HomeTab
              lockers={lockers}
              products={products}
              availability={availability}
              selectedLockerId={selectedLockerId}
              onSelectLocker={setSelectedLockerId}
              onSelectProduct={(productId) => {
                setSelectedProductId(productId);
                setTab("catalog");
              }}
            />
          )}

          {tab === "lockers" && (
            <LockersTab
              lockers={lockers}
              selectedLockerId={selectedLockerId}
              onSelectLocker={setSelectedLockerId}
              availability={availability}
            />
          )}

          {tab === "catalog" && (
            <CatalogTab
              products={products}
              selectedProductId={selectedProductId}
              selectedProduct={selectedProduct}
              selectedLockerId={selectedLockerId}
              selectedPlanId={selectedPlanId}
              detailLoading={detailLoading}
              onSelectProduct={setSelectedProductId}
              onSelectLocker={setSelectedLockerId}
              onSelectPlan={setSelectedPlanId}
              onGoToBooking={() => setTab("booking")}
            />
          )}

          {tab === "booking" && (
            <BookingTab
              selectedProduct={selectedProduct}
              selectedLocker={selectedLocker}
              selectedPlan={selectedPlan}
              pricing={pricing}
              quote={quote}
              reservation={reservation}
              bookingLoading={bookingLoading}
              canReserve={canReserve}
              isDemo={runtimeMode === "fallback"}
              onGetQuote={handleQuote}
              onCreateReservation={handleCreateReservation}
            />
          )}

          {tab === "profile" && (
            <ProfileTab
              user={user}
              verification={verification}
              runtimeMode={runtimeMode}
              refreshToken={refreshToken}
              onLogout={handleLogout}
            />
          )}
        </ScrollView>

        <BottomNav current={tab} onChange={setTab} />
      </View>
    </SafeAreaView>
  );
}

function AuthScreen({
  authStep,
  authIntent,
  phone,
  smsCode,
  devCode,
  authMessage,
  authError,
  authLoading,
  onPhoneChange,
  onCodeChange,
  onRequestCode,
  onConfirmCode,
  onBack,
  onDemo,
  onStartLogin,
  onStartRegistration,
}: {
  authStep: AuthStep;
  authIntent: AuthIntent;
  phone: string;
  smsCode: string;
  devCode: string;
  authMessage: string;
  authError: string;
  authLoading: boolean;
  onPhoneChange: (value: string) => void;
  onCodeChange: (value: string) => void;
  onRequestCode: () => void;
  onConfirmCode: () => void;
  onBack: () => void;
  onDemo: () => void;
  onStartLogin: () => void;
  onStartRegistration: () => void;
}) {
  const codeInputRef = useRef<TextInput | null>(null);
  const welcomeScrollRef = useRef<ScrollView | null>(null);
  const welcomeScrollX = useRef(new Animated.Value(0)).current;
  const codeDigits = Array.from({ length: 4 }, (_, index) => smsCode[index] ?? "");
  const isSignup = authIntent === "signup";
  const isPhoneValid = isPhoneReady(phone);
  const isCodeReady = smsCode.trim().length === 4;
  const [carouselWidth, setCarouselWidth] = useState(0);
  const slideWidth = carouselWidth || 320;
  const dotSize = 10;
  const dotGap = 10;
  const dotStep = dotSize + dotGap;
  const indicatorFrames = useMemo(
    () =>
      landingSlides.reduce<{
        inputRange: number[];
        translateRange: number[];
        widthRange: number[];
      }>(
        (acc, _, index) => {
          const slideOffset = index * slideWidth;
          acc.inputRange.push(slideOffset);
          acc.translateRange.push(index * dotStep);
          acc.widthRange.push(dotSize);

          if (index < landingSlides.length - 1) {
            acc.inputRange.push(slideOffset + slideWidth / 2);
            acc.translateRange.push(index * dotStep);
            acc.widthRange.push(dotSize + dotStep);
          }

          return acc;
        },
        { inputRange: [], translateRange: [], widthRange: [] },
      ),
    [dotSize, dotStep, slideWidth],
  );
  const activeDotTranslateX = welcomeScrollX.interpolate({
    inputRange: indicatorFrames.inputRange,
    outputRange: indicatorFrames.translateRange,
    extrapolate: "clamp",
  });
  const activeDotWidth = welcomeScrollX.interpolate({
    inputRange: indicatorFrames.inputRange,
    outputRange: indicatorFrames.widthRange,
    extrapolate: "clamp",
  });

  function handleWelcomeLayout(event: LayoutChangeEvent) {
    const width = event.nativeEvent.layout.width;
    if (width > 0 && width !== carouselWidth) {
      setCarouselWidth(width);
    }
  }

  if (authStep === "landing") {
    return (
      <ScrollView
        contentContainerStyle={styles.welcomeShell}
        keyboardShouldPersistTaps="handled"
        showsVerticalScrollIndicator={false}
      >
        <View style={styles.welcomeTopBlock}>
          <Animated.ScrollView
            ref={welcomeScrollRef}
            horizontal
            pagingEnabled
            decelerationRate="fast"
            bounces={false}
            directionalLockEnabled
            showsHorizontalScrollIndicator={false}
            contentContainerStyle={styles.welcomeCarouselContent}
            style={styles.welcomeCarousel}
            onLayout={handleWelcomeLayout}
            onScroll={Animated.event(
              [{ nativeEvent: { contentOffset: { x: welcomeScrollX } } }],
              { useNativeDriver: false },
            )}
            scrollEventThrottle={16}
          >
            {landingSlides.map((slide) => (
              <View key={slide.key} style={[styles.welcomeSlide, { width: slideWidth }]}>
                <View style={styles.welcomeIllustrationWrap}>
                  <WelcomeSlideIllustration kind={slide.illustration} />
                </View>
                <Text style={styles.welcomeTitle}>{slide.title}</Text>
                <Text style={styles.welcomeSubtitle}>{slide.subtitle}</Text>
              </View>
            ))}
          </Animated.ScrollView>

          <View style={styles.welcomeDotsRow}>
            {landingSlides.map((slide, index) => (
              <Pressable
                key={slide.key}
                onPress={() => {
                  welcomeScrollRef.current?.scrollTo({ x: slideWidth * index, animated: true });
                }}
              >
                <View style={styles.welcomeDot} />
              </Pressable>
            ))}
            <Animated.View
              pointerEvents="none"
              style={[
                styles.welcomeDotActive,
                {
                  width: activeDotWidth,
                  transform: [{ translateX: activeDotTranslateX }],
                },
              ]}
            />
          </View>

          <Pressable onPress={onDemo} style={styles.welcomeLinkWrap}>
            <Text style={styles.welcomeLink}>Посмотреть каталог</Text>
          </Pressable>
        </View>

        <View style={styles.welcomeButtonsBlock}>
          <Pressable style={styles.welcomePrimaryButton} onPress={onStartLogin}>
            <Text style={styles.welcomePrimaryButtonText}>Войти</Text>
          </Pressable>
          <Pressable style={styles.welcomeSecondaryButton} onPress={onStartRegistration}>
            <Text style={styles.welcomeSecondaryButtonText}>Зарегистрироваться</Text>
          </Pressable>
        </View>
      </ScrollView>
    );
  }

  return (
    <ScrollView
      contentContainerStyle={styles.entryShell}
      keyboardShouldPersistTaps="handled"
      showsVerticalScrollIndicator={false}
    >
      <View style={styles.entryCenteredArea}>
        <View style={styles.entryTitleBlock}>
          <Text style={styles.entryTitle}>{authStep === "request" ? (isSignup ? "Регистрация" : "Вход") : "Подтверждение"}</Text>
          <Text style={styles.entrySubtitle}>
            {authStep === "request"
              ? isSignup
                ? "Добро пожаловать"
                : "Введите номер РФ или РБ"
              : authMessage}
          </Text>
        </View>

        {authStep === "request" ? (
          <>
            <View style={styles.softInputShell}>
              <View style={styles.softInputIconWrap}>
                <PhoneGlyph />
              </View>
              <TextInput
                value={phone}
                onChangeText={(value) => onPhoneChange(sanitizePhoneInput(value))}
                style={styles.softInputText}
                placeholder="+79991234567"
                placeholderTextColor="#d1d3db"
                keyboardType="phone-pad"
                autoCapitalize="none"
                autoCorrect={false}
                autoComplete="tel"
              />
            </View>

            <Text style={styles.entrySupportText}>РФ можно вводить без `+7`. Номера РБ вводите только через `+375`.</Text>

            <Pressable
              style={[
                styles.softPrimaryButton,
                (!isPhoneValid || authLoading) && styles.softPrimaryButtonDisabled,
              ]}
              onPress={onRequestCode}
              disabled={!isPhoneValid || authLoading}
            >
              <Text style={styles.softPrimaryButtonText}>
                {authLoading ? "Отправляем..." : "Далее"}
              </Text>
            </Pressable>

            <View style={styles.entrySwitchBlock}>
              <Text style={styles.entrySwitchText}>{isSignup ? "Есть аккаунт?" : "Нет аккаунта?"}</Text>
              <Pressable onPress={isSignup ? onStartLogin : onStartRegistration}>
                <Text style={styles.entrySwitchLink}>{isSignup ? "Войти" : "Зарегистрироваться"}</Text>
              </Pressable>
            </View>

            <Pressable style={styles.entryBackButton} onPress={onBack}>
              <Text style={styles.entryBackButtonText}>Назад</Text>
            </Pressable>
          </>
        ) : (
          <>
            <Pressable style={styles.entryOtpRow} onPress={() => codeInputRef.current?.focus()}>
              {codeDigits.map((digit, index) => (
                <View key={`${digit}-${index}`} style={[styles.entryOtpBox, digit && styles.entryOtpBoxFilled]}>
                  <Text style={styles.entryOtpBoxText}>{digit || "•"}</Text>
                </View>
              ))}
            </Pressable>

            <TextInput
              ref={codeInputRef}
              value={smsCode}
              onChangeText={(value) => onCodeChange(value.replace(/[^0-9]/g, "").slice(0, 4))}
              style={styles.hiddenOtpInput}
              placeholder="1234"
              placeholderTextColor="transparent"
              keyboardType="number-pad"
              maxLength={4}
              autoFocus
            />

            {devCode ? (
              <View style={styles.entryHintCard}>
                <Text style={styles.entryHintLabel}>Тестовый код</Text>
                <Text style={styles.entryHintValue}>{devCode}</Text>
              </View>
            ) : null}

            <Pressable
              style={[
                styles.softPrimaryButton,
                (!isCodeReady || authLoading) && styles.softPrimaryButtonDisabled,
              ]}
              onPress={onConfirmCode}
              disabled={!isCodeReady || authLoading}
            >
              <Text style={styles.softPrimaryButtonText}>
                {authLoading ? "Проверяем..." : "Далее"}
              </Text>
            </Pressable>

            <Pressable style={styles.entryBackButton} onPress={onBack}>
              <Text style={styles.entryBackButtonText}>Назад</Text>
            </Pressable>
          </>
        )}

        {authError ? <Text style={styles.entryErrorText}>{authError}</Text> : null}
      </View>

      {authStep === "request" ? (
        <Text style={styles.entryLegalText}>
          Выполняя вход, я подтверждаю, что прочитал Политику Конфиденциальности
        </Text>
      ) : null}

    </ScrollView>
  );
}

function CitySelectionScreen({
  cities,
  selectedCityId,
  onSelectCity,
  onContinue,
}: {
  cities: City[];
  selectedCityId: string;
  onSelectCity: (cityId: string) => void;
  onContinue: () => void;
}) {
  const [isOpen, setIsOpen] = useState(false);
  const selectedCity = cities.find((city) => city.id === selectedCityId) ?? null;

  return (
    <ScrollView
      contentContainerStyle={styles.entryShell}
      keyboardShouldPersistTaps="handled"
      showsVerticalScrollIndicator={false}
    >
      <View style={styles.entryCenteredArea}>
        <View style={styles.entryTitleBlock}>
          <Text style={styles.entryTitle}>Выбор города</Text>
          <Text style={styles.entrySubtitle}>
            Город, в котором будут арендованы инструменты
          </Text>
        </View>

        <Pressable style={styles.softInputShell} onPress={() => setIsOpen((current) => !current)}>
          <View style={styles.softInputIconWrap}>
            <SearchGlyph />
          </View>
          <Text style={[styles.softInputText, !selectedCity && styles.softInputPlaceholder]}>
            {selectedCity?.name ?? "Город"}
          </Text>
          <ChevronGlyph open={isOpen} />
        </Pressable>

        {isOpen ? (
          <View style={styles.cityDropdownCard}>
            {cities.map((city) => {
              const active = city.id === selectedCityId;
              return (
                <Pressable
                  key={city.id}
                  style={[styles.cityDropdownItem, active && styles.cityDropdownItemActive]}
                  onPress={() => {
                    onSelectCity(city.id);
                    setIsOpen(false);
                  }}
                >
                  <Text style={[styles.cityDropdownText, active && styles.cityDropdownTextActive]}>
                    {city.name}
                  </Text>
                </Pressable>
              );
            })}
          </View>
        ) : null}

        <Pressable
          style={[styles.softPrimaryButton, !selectedCityId && styles.softPrimaryButtonDisabled]}
          onPress={onContinue}
          disabled={!selectedCityId}
        >
          <Text style={styles.softPrimaryButtonText}>Далее</Text>
        </Pressable>
      </View>
    </ScrollView>
  );
}

function PhoneGlyph() {
  return (
    <View style={styles.phoneGlyph}>
      <View style={styles.phoneGlyphScreen} />
      <View style={styles.phoneGlyphDot} />
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

function ChevronGlyph({ open }: { open: boolean }) {
  return (
    <View style={[styles.chevronGlyph, open && styles.chevronGlyphOpen]}>
      <View style={[styles.chevronGlyphLine, styles.chevronGlyphLineLeft]} />
      <View style={[styles.chevronGlyphLine, styles.chevronGlyphLineRight]} />
    </View>
  );
}

function AuthStepPill({
  label,
  active,
  done,
}: {
  label: string;
  active: boolean;
  done: boolean;
}) {
  return (
    <View style={[styles.authStepPill, active && styles.authStepPillActive, done && styles.authStepPillDone]}>
      <Text
        style={[
          styles.authStepPillText,
          (active || done) && styles.authStepPillTextActive,
        ]}
      >
        {done ? `✓ ${label}` : label}
      </Text>
    </View>
  );
}

function AuthTrustItem({ title, text }: { title: string; text: string }) {
  return (
    <View style={styles.authTrustItem}>
      <Text style={styles.authTrustItemTitle}>{title}</Text>
      <Text style={styles.authTrustItemText}>{text}</Text>
    </View>
  );
}

function NoDepositIllustration() {
  return (
    <View style={styles.depositArt}>
      <View style={styles.depositArtShadow} />

      <View style={styles.depositRing}>
        <View style={styles.depositRingSlash} />
      </View>

      <View style={[styles.depositBill, styles.depositBillBack]}>
        <View style={styles.depositBillCorner} />
        <View style={styles.depositBillCircle} />
      </View>

      <View style={[styles.depositBill, styles.depositBillFront]}>
        <View style={styles.depositBillCorner} />
        <View style={styles.depositBillCircle} />
      </View>

      <View style={[styles.depositCoin, styles.depositCoinTop]}>
        <View style={styles.depositCoinInner} />
      </View>
      <View style={[styles.depositCoin, styles.depositCoinRight]}>
        <View style={styles.depositCoinInner} />
      </View>
    </View>
  );
}

function WelcomeSlideIllustration({
  kind,
}: {
  kind: "no-deposit" | "nearby" | "fast" | "return";
}) {
  if (kind === "nearby") {
    return <NearbyLockerIllustration />;
  }
  if (kind === "fast") {
    return <FastBookingIllustration />;
  }
  if (kind === "return") {
    return <EasyReturnIllustration />;
  }
  return <NoDepositIllustration />;
}

function NearbyLockerIllustration() {
  return (
    <View style={styles.nearbyArt}>
      <View style={styles.nearbyArtShadow} />
      <View style={styles.nearbyPin}>
        <View style={styles.nearbyPinInner} />
      </View>
      <View style={styles.nearbyLocker}>
        <View style={styles.nearbyLockerHeader} />
        <View style={styles.nearbyLockerGrid}>
          <View style={styles.nearbyLockerCell} />
          <View style={styles.nearbyLockerCell} />
          <View style={styles.nearbyLockerCell} />
          <View style={styles.nearbyLockerCell} />
        </View>
      </View>
      <View style={styles.nearbyMapCard}>
        <View style={styles.nearbyMapRoadHorizontal} />
        <View style={styles.nearbyMapRoadVertical} />
        <View style={styles.nearbyMapDot} />
      </View>
    </View>
  );
}

function FastBookingIllustration() {
  return (
    <View style={styles.fastArt}>
      <View style={styles.fastArtShadow} />
      <View style={styles.fastPhone}>
        <View style={styles.fastPhoneTop} />
        <View style={styles.fastPhoneScreen}>
          <View style={styles.fastPhoneLineShort} />
          <View style={styles.fastPhoneLineLong} />
          <View style={styles.fastPhonePill} />
        </View>
      </View>
      <View style={styles.fastCheckBubble}>
        <View style={styles.fastCheckMarkLeft} />
        <View style={styles.fastCheckMarkRight} />
      </View>
      <View style={styles.fastSpeedLineOne} />
      <View style={styles.fastSpeedLineTwo} />
    </View>
  );
}

function EasyReturnIllustration() {
  return (
    <View style={styles.returnArt}>
      <View style={styles.returnArtShadow} />
      <View style={styles.returnCircle}>
        <View style={styles.returnArrowTop} />
        <View style={styles.returnArrowBottom} />
      </View>
      <View style={styles.returnLocker}>
        <View style={styles.returnLockerDoor} />
      </View>
      <View style={styles.returnBox}>
        <View style={styles.returnBoxTop} />
      </View>
    </View>
  );
}

function HeroCard({
  city,
  locker,
  user,
  verification,
  onOpenCatalog,
  onOpenLockers,
}: {
  city: string;
  locker: string;
  user: AppUser | null;
  verification: VerificationState | null;
  onOpenCatalog: () => void;
  onOpenLockers: () => void;
}) {
  return (
    <View style={styles.heroCard}>
      <View style={styles.heroGlowOne} />
      <View style={styles.heroGlowTwo} />
      <Text style={styles.heroKicker}>Ваш аккаунт</Text>
      <Text style={styles.heroTitle}>Выберите постамат, забронируйте товар и заберите его по PIN.</Text>
      <Text style={styles.heroText}>
        Аккаунт: {user?.phone ?? "неизвестен"} • статус: {verificationLabel(verification?.status ?? user?.verificationStatus)}
      </Text>
      <View style={styles.heroMetaRow}>
        <View style={styles.heroMetaCard}>
          <Text style={styles.heroMetaLabel}>Город</Text>
          <Text style={styles.heroMetaValue}>{city}</Text>
        </View>
        <View style={styles.heroMetaCard}>
          <Text style={styles.heroMetaLabel}>Точка</Text>
          <Text style={styles.heroMetaValue}>{locker}</Text>
        </View>
      </View>
      <View style={styles.heroActions}>
        <Pressable style={[styles.heroAction, styles.heroActionPrimary]} onPress={onOpenCatalog}>
          <Text style={styles.heroActionPrimaryText}>Открыть каталог</Text>
        </Pressable>
        <Pressable style={[styles.heroAction, styles.heroActionGhost]} onPress={onOpenLockers}>
          <Text style={styles.heroActionGhostText}>Выбрать точку</Text>
        </Pressable>
      </View>
    </View>
  );
}

function CityStrip({
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

function HomeTab({
  lockers,
  products,
  availability,
  selectedLockerId,
  onSelectLocker,
  onSelectProduct,
}: {
  lockers: Locker[];
  products: ProductListItem[];
  availability: LockerAvailabilityItem[];
  selectedLockerId: string;
  onSelectLocker: (lockerId: string) => void;
  onSelectProduct: (productId: string) => void;
}) {
  return (
    <View style={styles.tabBlock}>
      <SectionHeader title="Ближайшие точки" action="рядом с вами" />
      {lockers.slice(0, 2).map((locker) => {
        const active = locker.id === selectedLockerId;
        return (
          <Pressable
            key={locker.id}
            style={[styles.lockerCard, active && styles.lockerCardActive]}
            onPress={() => onSelectLocker(locker.id)}
          >
            <View style={styles.lockerCardTop}>
              <View>
                <Text style={styles.cardTitle}>{locker.name}</Text>
                <Text style={styles.cardText}>{locker.address}</Text>
              </View>
              <View style={[styles.statusPill, locker.status === "online" ? styles.statusGood : styles.statusWarn]}>
                <Text style={styles.statusText}>{statusLabel(locker.status)}</Text>
              </View>
            </View>
            <View style={styles.lockerStats}>
              <Metric label="SKU" value={locker.availableProductCount} />
              <Metric label="Единиц" value={locker.availableUnitCount ?? 0} />
              <Metric
                label="Окно"
                value={locker.workingHours?.from ?? "08:00"}
                suffix={`–${locker.workingHours?.to ?? "22:00"}`}
              />
            </View>
          </Pressable>
        );
      })}

      <SectionHeader title="Доступно сейчас" action="в выбранной точке" />
      <View style={styles.availabilityRow}>
        {availability.slice(0, 2).map((item) => (
          <View key={item.productId} style={styles.availabilityCard}>
            <Text style={styles.cardTitle}>{item.productName}</Text>
            <Text style={styles.cardText}>
              {item.availableUnits} шт. • от {formatMoney(item.priceFrom, item.currency)}
            </Text>
          </View>
        ))}
      </View>

      <SectionHeader title="Популярное" action="часто берут" />
      {products.slice(0, 3).map((product) => (
        <Pressable key={product.id} style={styles.productCard} onPress={() => onSelectProduct(product.id)}>
          <View style={styles.productThumb}>
            <Text style={styles.productThumbText}>{productMonogram(product.name)}</Text>
          </View>
          <View style={styles.productMain}>
            <Text style={styles.cardTitle}>{product.name}</Text>
            <Text style={styles.cardText}>{product.shortDescription ?? "Тарифы, комплект и ближайшие точки."}</Text>
          </View>
          <View style={styles.productMeta}>
            <Text style={styles.priceText}>{formatMoney(product.priceFrom, product.currency)}</Text>
            <Text style={styles.stockText}>{product.availableLockerCount} точки</Text>
          </View>
        </Pressable>
      ))}
    </View>
  );
}

function LockersTab({
  lockers,
  selectedLockerId,
  onSelectLocker,
  availability,
}: {
  lockers: Locker[];
  selectedLockerId: string;
  onSelectLocker: (lockerId: string) => void;
  availability: LockerAvailabilityItem[];
}) {
  return (
    <View style={styles.tabBlock}>
      <SectionHeader title="Постаматы" action="список точек" />
      {lockers.map((locker) => {
        const active = locker.id === selectedLockerId;
        return (
          <Pressable
            key={locker.id}
            style={[styles.lockersListCard, active && styles.lockersListCardActive]}
            onPress={() => onSelectLocker(locker.id)}
          >
            <Text style={styles.cardTitle}>{locker.name}</Text>
            <Text style={styles.cardText}>{locker.address}</Text>
            <View style={styles.lockersMetaRow}>
              <Text style={styles.stockText}>{locker.availableProductCount} SKU</Text>
              <Text style={styles.stockText}>{statusLabel(locker.status)}</Text>
            </View>
          </Pressable>
        );
      })}

      <View style={styles.mapStub}>
        <Text style={styles.mapStubLabel}>Карта</Text>
        <Text style={styles.mapStubText}>
          Здесь будет карта постаматов. Пока уже можно выбрать точку и проверить наличие по списку.
        </Text>
      </View>

      <SectionHeader title="Что можно взять" action={`${availability.length} позиции`} />
      {availability.map((item) => (
        <View key={item.productId} style={styles.availabilityCardWide}>
          <Text style={styles.cardTitle}>{item.productName}</Text>
          <Text style={styles.cardText}>
            {item.availableUnits} доступно • {formatMoney(item.priceFrom, item.currency)}
          </Text>
        </View>
      ))}
    </View>
  );
}

function CatalogTab({
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

function BookingTab({
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

function ProfileTab({
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
  onLogout: () => void;
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

function MiniFeature({ title, text }: { title: string; text: string }) {
  return (
    <View style={styles.miniFeature}>
      <Text style={styles.miniFeatureTitle}>{title}</Text>
      <Text style={styles.miniFeatureText}>{text}</Text>
    </View>
  );
}

function SectionHeader({ title, action }: { title: string; action: string }) {
  return (
    <View style={styles.sectionHeader}>
      <Text style={styles.sectionTitle}>{title}</Text>
      <Text style={styles.sectionAction}>{action}</Text>
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

function BottomNav({
  current,
  onChange,
}: {
  current: TabKey;
  onChange: (tab: TabKey) => void;
}) {
  const items: Array<{ key: TabKey; label: string }> = [
    { key: "home", label: "Главная" },
    { key: "lockers", label: "Точки" },
    { key: "catalog", label: "Каталог" },
    { key: "booking", label: "Бронь" },
    { key: "profile", label: "Профиль" },
  ];

  return (
    <View style={styles.bottomNav}>
      {items.map((item) => {
        const active = item.key === current;
        return (
          <Pressable
            key={item.key}
            style={[styles.navItem, active && styles.navItemActive]}
            onPress={() => onChange(item.key)}
          >
            <Text style={[styles.navItemText, active && styles.navItemTextActive]}>{item.label}</Text>
          </Pressable>
        );
      })}
    </View>
  );
}

const styles = StyleSheet.create({
  safe: {
    flex: 1,
    backgroundColor: palette.bg,
  },
  appShell: {
    flex: 1,
    backgroundColor: palette.bg,
  },
  welcomeShell: {
    flexGrow: 1,
    backgroundColor: "#ffffff",
    paddingHorizontal: 28,
    paddingTop: 26,
    paddingBottom: 28,
    justifyContent: "space-between",
  },
  welcomeTopBlock: {
    alignItems: "center",
    paddingTop: 34,
  },
  welcomeCarousel: {
    width: "100%",
  },
  welcomeCarouselContent: {
    alignItems: "stretch",
  },
  welcomeSlide: {
    alignItems: "center",
  },
  welcomeIllustrationWrap: {
    width: "100%",
    alignItems: "center",
    marginBottom: 26,
  },
  depositArt: {
    width: 238,
    height: 238,
    alignItems: "center",
    justifyContent: "center",
  },
  depositArtShadow: {
    position: "absolute",
    width: 132,
    height: 18,
    borderRadius: 999,
    backgroundColor: "rgba(211, 51, 42, 0.10)",
    bottom: 18,
  },
  depositRing: {
    position: "absolute",
    width: 160,
    height: 160,
    borderRadius: 999,
    borderWidth: 18,
    borderColor: "#e5574e",
    backgroundColor: "#ffffff",
    shadowColor: "#b6342b",
    shadowOpacity: 0.18,
    shadowRadius: 18,
    shadowOffset: { width: 0, height: 10 },
  },
  depositRingSlash: {
    position: "absolute",
    width: 114,
    height: 18,
    borderRadius: 999,
    backgroundColor: "#de4b42",
    top: 54,
    left: 18,
    transform: [{ rotate: "-25deg" }],
  },
  depositBill: {
    position: "absolute",
    width: 88,
    height: 58,
    borderRadius: 18,
    backgroundColor: "#a6edff",
    borderWidth: 3,
    borderColor: "#5dbedf",
    padding: 10,
    shadowColor: "#60cde4",
    shadowOpacity: 0.14,
    shadowRadius: 10,
    shadowOffset: { width: 0, height: 6 },
  },
  depositBillFront: {
    left: 32,
    top: 78,
    transform: [{ rotate: "-13deg" }],
  },
  depositBillBack: {
    right: 42,
    top: 102,
    transform: [{ rotate: "18deg" }],
  },
  depositBillCorner: {
    position: "absolute",
    width: 18,
    height: 18,
    borderBottomRightRadius: 14,
    backgroundColor: "#d9f8ff",
    top: 0,
    left: 0,
  },
  depositBillCircle: {
    width: 38,
    height: 26,
    borderRadius: 999,
    backgroundColor: "#7fd7f5",
    alignSelf: "center",
    marginTop: 9,
  },
  depositCoin: {
    position: "absolute",
    width: 42,
    height: 42,
    borderRadius: 999,
    backgroundColor: "#f3cc75",
    borderWidth: 3,
    borderColor: "#d9b45a",
    alignItems: "center",
    justifyContent: "center",
    shadowColor: "#cda54c",
    shadowOpacity: 0.18,
    shadowRadius: 10,
    shadowOffset: { width: 0, height: 6 },
  },
  depositCoinTop: {
    top: 64,
    right: 56,
  },
  depositCoinRight: {
    top: 122,
    right: 34,
  },
  depositCoinInner: {
    width: 20,
    height: 20,
    borderRadius: 999,
    borderWidth: 2,
    borderColor: "#ddb962",
  },
  nearbyArt: {
    width: 238,
    height: 238,
    alignItems: "center",
    justifyContent: "center",
  },
  nearbyArtShadow: {
    position: "absolute",
    width: 132,
    height: 18,
    borderRadius: 999,
    backgroundColor: "rgba(60, 181, 220, 0.10)",
    bottom: 20,
  },
  nearbyMapCard: {
    position: "absolute",
    width: 154,
    height: 112,
    borderRadius: 28,
    backgroundColor: "#ebfbff",
    borderWidth: 3,
    borderColor: "#9de7fb",
    transform: [{ rotate: "-10deg" }],
  },
  nearbyMapRoadHorizontal: {
    position: "absolute",
    height: 12,
    left: 12,
    right: 12,
    top: 46,
    borderRadius: 999,
    backgroundColor: "#ffffff",
  },
  nearbyMapRoadVertical: {
    position: "absolute",
    width: 12,
    top: 10,
    bottom: 10,
    left: 66,
    borderRadius: 999,
    backgroundColor: "#ffffff",
  },
  nearbyMapDot: {
    position: "absolute",
    width: 20,
    height: 20,
    borderRadius: 999,
    backgroundColor: "#ff8f87",
    right: 30,
    top: 28,
  },
  nearbyPin: {
    position: "absolute",
    left: 38,
    top: 42,
    width: 54,
    height: 70,
    borderTopLeftRadius: 27,
    borderTopRightRadius: 27,
    borderBottomLeftRadius: 27,
    borderBottomRightRadius: 8,
    backgroundColor: "#e54f44",
    alignItems: "center",
    justifyContent: "center",
    transform: [{ rotate: "-35deg" }],
    zIndex: 2,
  },
  nearbyPinInner: {
    width: 22,
    height: 22,
    borderRadius: 999,
    backgroundColor: "#ffffff",
  },
  nearbyLocker: {
    position: "absolute",
    right: 46,
    top: 72,
    width: 86,
    height: 104,
    borderRadius: 20,
    backgroundColor: "#8ee3fb",
    borderWidth: 3,
    borderColor: "#58bfdf",
    padding: 10,
    zIndex: 2,
  },
  nearbyLockerHeader: {
    height: 10,
    borderRadius: 999,
    backgroundColor: "#e9fbff",
    marginBottom: 10,
  },
  nearbyLockerGrid: {
    flex: 1,
    flexDirection: "row",
    flexWrap: "wrap",
    gap: 6,
  },
  nearbyLockerCell: {
    width: 24,
    height: 24,
    borderRadius: 8,
    backgroundColor: "#d9f8ff",
  },
  fastArt: {
    width: 238,
    height: 238,
    alignItems: "center",
    justifyContent: "center",
  },
  fastArtShadow: {
    position: "absolute",
    width: 132,
    height: 18,
    borderRadius: 999,
    backgroundColor: "rgba(221, 54, 45, 0.10)",
    bottom: 22,
  },
  fastPhone: {
    width: 118,
    height: 176,
    borderRadius: 28,
    backgroundColor: "#fefefe",
    borderWidth: 6,
    borderColor: "#ee5c54",
    padding: 10,
    shadowColor: "#d9483f",
    shadowOpacity: 0.14,
    shadowRadius: 14,
    shadowOffset: { width: 0, height: 8 },
  },
  fastPhoneTop: {
    width: 46,
    height: 6,
    borderRadius: 999,
    backgroundColor: "#f3c1be",
    alignSelf: "center",
    marginBottom: 12,
  },
  fastPhoneScreen: {
    flex: 1,
    borderRadius: 18,
    backgroundColor: "#fff4f3",
    padding: 12,
  },
  fastPhoneLineShort: {
    width: "45%",
    height: 10,
    borderRadius: 999,
    backgroundColor: "#f4b8b5",
    marginBottom: 8,
  },
  fastPhoneLineLong: {
    width: "80%",
    height: 10,
    borderRadius: 999,
    backgroundColor: "#f8d6d3",
    marginBottom: 12,
  },
  fastPhonePill: {
    width: "100%",
    height: 36,
    borderRadius: 18,
    backgroundColor: "#ea8d87",
    marginTop: 10,
  },
  fastCheckBubble: {
    position: "absolute",
    right: 36,
    top: 64,
    width: 56,
    height: 56,
    borderRadius: 999,
    backgroundColor: "#8ee3a5",
    alignItems: "center",
    justifyContent: "center",
    shadowColor: "#6cc886",
    shadowOpacity: 0.16,
    shadowRadius: 12,
    shadowOffset: { width: 0, height: 8 },
  },
  fastCheckMarkLeft: {
    position: "absolute",
    width: 12,
    height: 4,
    borderRadius: 999,
    backgroundColor: "#ffffff",
    left: 16,
    top: 30,
    transform: [{ rotate: "45deg" }],
  },
  fastCheckMarkRight: {
    position: "absolute",
    width: 22,
    height: 4,
    borderRadius: 999,
    backgroundColor: "#ffffff",
    right: 12,
    top: 24,
    transform: [{ rotate: "-45deg" }],
  },
  fastSpeedLineOne: {
    position: "absolute",
    left: 32,
    top: 92,
    width: 42,
    height: 8,
    borderRadius: 999,
    backgroundColor: "#ffd0cd",
  },
  fastSpeedLineTwo: {
    position: "absolute",
    left: 26,
    top: 114,
    width: 58,
    height: 8,
    borderRadius: 999,
    backgroundColor: "#ffdede",
  },
  returnArt: {
    width: 238,
    height: 238,
    alignItems: "center",
    justifyContent: "center",
  },
  returnArtShadow: {
    position: "absolute",
    width: 132,
    height: 18,
    borderRadius: 999,
    backgroundColor: "rgba(80, 160, 220, 0.08)",
    bottom: 18,
  },
  returnCircle: {
    position: "absolute",
    width: 170,
    height: 170,
    borderRadius: 999,
    borderWidth: 12,
    borderColor: "#db4137",
    opacity: 0.18,
  },
  returnArrowTop: {
    position: "absolute",
    width: 24,
    height: 24,
    borderTopWidth: 8,
    borderRightWidth: 8,
    borderColor: "#db4137",
    right: 10,
    top: 20,
    transform: [{ rotate: "20deg" }],
  },
  returnArrowBottom: {
    position: "absolute",
    width: 24,
    height: 24,
    borderBottomWidth: 8,
    borderLeftWidth: 8,
    borderColor: "#db4137",
    left: 10,
    bottom: 20,
    transform: [{ rotate: "20deg" }],
  },
  returnLocker: {
    position: "absolute",
    right: 42,
    top: 74,
    width: 82,
    height: 98,
    borderRadius: 20,
    backgroundColor: "#a7edff",
    borderWidth: 3,
    borderColor: "#59bfdf",
    alignItems: "center",
    justifyContent: "center",
  },
  returnLockerDoor: {
    width: 50,
    height: 66,
    borderRadius: 14,
    backgroundColor: "#dffaff",
    borderWidth: 2,
    borderColor: "#93def4",
  },
  returnBox: {
    position: "absolute",
    left: 46,
    top: 120,
    width: 68,
    height: 54,
    borderRadius: 14,
    backgroundColor: "#ffd78f",
    borderWidth: 3,
    borderColor: "#e5b95d",
    justifyContent: "flex-start",
    alignItems: "center",
    paddingTop: 12,
  },
  returnBoxTop: {
    width: 48,
    height: 12,
    borderRadius: 8,
    backgroundColor: "#ffe9bc",
  },
  welcomeDotsRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 10,
    marginBottom: 22,
    position: "relative",
  },
  welcomeDot: {
    width: 10,
    height: 10,
    borderRadius: 999,
    backgroundColor: "#f6d5d5",
  },
  welcomeDotActive: {
    position: "absolute",
    left: 0,
    top: 0,
    width: 10,
    height: 10,
    borderRadius: 999,
    backgroundColor: "#da362d",
  },
  welcomeTitle: {
    fontSize: 28,
    lineHeight: 34,
    color: "#171d2e",
    fontWeight: "900",
    textAlign: "center",
    marginBottom: 10,
    maxWidth: 320,
  },
  welcomeSubtitle: {
    fontSize: 16,
    lineHeight: 22,
    color: "#a8aebb",
    textAlign: "center",
    maxWidth: 310,
    marginBottom: 18,
  },
  welcomeLinkWrap: {
    paddingVertical: 8,
  },
  welcomeLink: {
    fontSize: 18,
    lineHeight: 22,
    color: "#df4035",
    fontWeight: "700",
  },
  welcomeButtonsBlock: {
    gap: 14,
  },
  welcomePrimaryButton: {
    borderRadius: 18,
    backgroundColor: "#dd362d",
    paddingVertical: 18,
    alignItems: "center",
    justifyContent: "center",
    shadowColor: "#ca342b",
    shadowOpacity: 0.12,
    shadowRadius: 10,
    shadowOffset: { width: 0, height: 6 },
  },
  welcomePrimaryButtonText: {
    color: "#ffffff",
    fontSize: 18,
    fontWeight: "800",
  },
  welcomeSecondaryButton: {
    borderRadius: 18,
    borderWidth: 1.5,
    borderColor: "#ee4b40",
    paddingVertical: 18,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: "#ffffff",
  },
  welcomeSecondaryButtonText: {
    color: "#df4035",
    fontSize: 18,
    fontWeight: "700",
  },
  entryShell: {
    flexGrow: 1,
    backgroundColor: "#ffffff",
    paddingHorizontal: 26,
    paddingTop: 34,
    paddingBottom: 22,
    justifyContent: "space-between",
  },
  entryCenteredArea: {
    flex: 1,
    justifyContent: "center",
  },
  entryTitleBlock: {
    alignItems: "center",
    marginBottom: 34,
  },
  entryTitle: {
    fontSize: 28,
    lineHeight: 34,
    color: "#151b2e",
    fontWeight: "900",
    textAlign: "center",
    marginBottom: 8,
  },
  entrySubtitle: {
    fontSize: 15,
    lineHeight: 21,
    color: "#b1b5c1",
    textAlign: "center",
    maxWidth: 280,
  },
  softInputShell: {
    minHeight: 58,
    borderRadius: 20,
    backgroundColor: "#f5f5f6",
    flexDirection: "row",
    alignItems: "center",
    paddingHorizontal: 18,
    marginBottom: 18,
  },
  softInputIconWrap: {
    width: 24,
    height: 24,
    alignItems: "center",
    justifyContent: "center",
    marginRight: 12,
  },
  softInputText: {
    flex: 1,
    fontSize: 17,
    color: "#7e8594",
    fontWeight: "500",
  },
  entrySupportText: {
    fontSize: 13,
    lineHeight: 18,
    color: "#b1b5c1",
    textAlign: "center",
    marginTop: -6,
    marginBottom: 18,
    paddingHorizontal: 10,
  },
  softInputPlaceholder: {
    color: "#bfc3cd",
  },
  softPrimaryButton: {
    minHeight: 58,
    borderRadius: 20,
    backgroundColor: "#dd362d",
    alignItems: "center",
    justifyContent: "center",
    shadowColor: "#ca342b",
    shadowOpacity: 0.14,
    shadowRadius: 12,
    shadowOffset: { width: 0, height: 8 },
  },
  softPrimaryButtonDisabled: {
    backgroundColor: "#f2a8a4",
    shadowOpacity: 0,
  },
  softPrimaryButtonText: {
    color: "#ffffff",
    fontSize: 18,
    fontWeight: "800",
  },
  entrySwitchBlock: {
    alignItems: "center",
    marginTop: 34,
    gap: 8,
  },
  entrySwitchText: {
    color: "#b1b5c1",
    fontSize: 15,
    fontWeight: "600",
  },
  entrySwitchLink: {
    color: "#e53e33",
    fontSize: 17,
    fontWeight: "800",
  },
  entryBackButton: {
    marginTop: 18,
    alignItems: "center",
  },
  entryBackButtonText: {
    color: "#b1b5c1",
    fontSize: 15,
    fontWeight: "700",
  },
  entryLegalText: {
    fontSize: 13,
    lineHeight: 18,
    color: "#a7acb8",
    textAlign: "center",
    paddingHorizontal: 18,
  },
  entryDemoLink: {
    marginTop: 10,
    alignItems: "center",
  },
  entryDemoLinkText: {
    color: "#dd4338",
    fontSize: 15,
    fontWeight: "700",
  },
  entryOtpRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    gap: 10,
    marginBottom: 18,
  },
  entryOtpBox: {
    flex: 1,
    height: 66,
    borderRadius: 20,
    backgroundColor: "#f5f5f6",
    alignItems: "center",
    justifyContent: "center",
    borderWidth: 1,
    borderColor: "#f0f0f0",
  },
  entryOtpBoxFilled: {
    backgroundColor: "#fff3f2",
    borderColor: "#ef9993",
  },
  entryOtpBoxText: {
    color: "#1a2032",
    fontSize: 24,
    fontWeight: "800",
  },
  entryHintCard: {
    borderRadius: 18,
    backgroundColor: "#f8f4f4",
    paddingHorizontal: 16,
    paddingVertical: 14,
    marginBottom: 18,
    alignItems: "center",
  },
  entryHintLabel: {
    color: "#9ea4b2",
    fontSize: 12,
    fontWeight: "700",
    marginBottom: 6,
  },
  entryHintValue: {
    color: "#de4137",
    fontSize: 22,
    fontWeight: "900",
    letterSpacing: 3,
  },
  entryErrorText: {
    marginTop: 16,
    color: "#d43d33",
    fontSize: 14,
    lineHeight: 19,
    textAlign: "center",
    fontWeight: "600",
  },
  cityDropdownCard: {
    borderRadius: 18,
    backgroundColor: "#ffffff",
    borderWidth: 1,
    borderColor: "#efeff0",
    marginTop: -6,
    marginBottom: 18,
    overflow: "hidden",
    shadowColor: "#b7bcc9",
    shadowOpacity: 0.08,
    shadowRadius: 12,
    shadowOffset: { width: 0, height: 8 },
  },
  cityDropdownItem: {
    paddingHorizontal: 18,
    paddingVertical: 15,
    borderBottomWidth: 1,
    borderBottomColor: "#f2f2f2",
  },
  cityDropdownItemActive: {
    backgroundColor: "#fff3f2",
  },
  cityDropdownText: {
    color: "#707788",
    fontSize: 16,
    fontWeight: "600",
  },
  cityDropdownTextActive: {
    color: "#db4036",
  },
  phoneGlyph: {
    width: 12,
    height: 20,
    borderRadius: 4,
    borderWidth: 2,
    borderColor: "#a8aebb",
    alignItems: "center",
    justifyContent: "space-between",
    paddingTop: 3,
    paddingBottom: 2,
  },
  phoneGlyphScreen: {
    width: 4,
    height: 1,
    borderRadius: 2,
    backgroundColor: "#a8aebb",
  },
  phoneGlyphDot: {
    width: 3,
    height: 3,
    borderRadius: 999,
    backgroundColor: "#a8aebb",
  },
  searchGlyph: {
    width: 18,
    height: 18,
    position: "relative",
  },
  searchGlyphCircle: {
    position: "absolute",
    width: 12,
    height: 12,
    borderRadius: 999,
    borderWidth: 2,
    borderColor: "#a8aebb",
    left: 0,
    top: 0,
  },
  searchGlyphHandle: {
    position: "absolute",
    width: 8,
    height: 2,
    borderRadius: 2,
    backgroundColor: "#a8aebb",
    right: 0,
    bottom: 2,
    transform: [{ rotate: "45deg" }],
  },
  chevronGlyph: {
    width: 14,
    height: 14,
    marginLeft: 10,
    position: "relative",
  },
  chevronGlyphOpen: {
    transform: [{ rotate: "180deg" }],
  },
  chevronGlyphLine: {
    position: "absolute",
    width: 8,
    height: 2,
    borderRadius: 2,
    backgroundColor: "#a8aebb",
    top: 6,
  },
  chevronGlyphLineLeft: {
    left: 0,
    transform: [{ rotate: "45deg" }],
  },
  chevronGlyphLineRight: {
    right: 0,
    transform: [{ rotate: "-45deg" }],
  },
  authShell: {
    paddingHorizontal: 18,
    paddingTop: 16,
    paddingBottom: 44,
    backgroundColor: palette.bg,
  },
  authHero: {
    borderRadius: 36,
    paddingHorizontal: 22,
    paddingTop: 24,
    paddingBottom: 28,
    overflow: "hidden",
  },
  authHeroOrbLarge: {
    position: "absolute",
    width: 260,
    height: 260,
    borderRadius: 260,
    backgroundColor: "rgba(255,255,255,0.10)",
    top: -90,
    right: -50,
  },
  authHeroOrbSmall: {
    position: "absolute",
    width: 150,
    height: 150,
    borderRadius: 150,
    backgroundColor: "rgba(255,255,255,0.08)",
    bottom: -40,
    left: -20,
  },
  authBrandRow: {
    flexDirection: "row",
    alignItems: "center",
    marginBottom: 18,
  },
  authBrandBadge: {
    width: 44,
    height: 44,
    borderRadius: 16,
    backgroundColor: "rgba(255,255,255,0.18)",
    alignItems: "center",
    justifyContent: "center",
    marginRight: 12,
  },
  authBrandBadgeText: {
    color: "#fffaf7",
    fontSize: 15,
    fontWeight: "900",
    letterSpacing: 1.2,
  },
  authBrandTextWrap: {
    flex: 1,
  },
  authKicker: {
    color: "#fff2ee",
    textTransform: "uppercase",
    letterSpacing: 1.6,
    fontSize: 11,
    marginBottom: 3,
    fontWeight: "700",
  },
  authBrandSubtitle: {
    color: "#ffd7cf",
    fontSize: 13,
    fontWeight: "600",
  },
  authTitle: {
    color: "#fffaf7",
    fontSize: 34,
    lineHeight: 38,
    fontWeight: "800",
    marginBottom: 12,
    maxWidth: 300,
  },
  authSubtitle: {
    color: "#ffd9d1",
    lineHeight: 22,
    fontSize: 15,
    maxWidth: 310,
  },
  authHeroPills: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: 8,
    marginTop: 18,
    marginBottom: 18,
  },
  authHeroPill: {
    borderRadius: 999,
    paddingHorizontal: 12,
    paddingVertical: 8,
    backgroundColor: "rgba(255,255,255,0.12)",
  },
  authHeroPillText: {
    color: "#fff6f2",
    fontSize: 12,
    fontWeight: "700",
  },
  authHeroMetrics: {
    flexDirection: "row",
    gap: 10,
  },
  authHeroMetric: {
    flex: 1,
    borderRadius: 20,
    padding: 14,
    backgroundColor: "rgba(255,255,255,0.10)",
  },
  authHeroMetricValue: {
    color: "#fffaf7",
    fontSize: 20,
    fontWeight: "900",
    marginBottom: 4,
  },
  authHeroMetricLabel: {
    color: "#ffd7cf",
    fontSize: 12,
    lineHeight: 16,
    fontWeight: "600",
  },
  authCardWrap: {
    marginTop: -30,
    paddingHorizontal: 8,
  },
  authCard: {
    backgroundColor: palette.card,
    borderRadius: 30,
    padding: 20,
    borderWidth: 1,
    borderColor: palette.border,
    shadowColor: "#3b2017",
    shadowOpacity: 0.12,
    shadowRadius: 24,
    shadowOffset: { width: 0, height: 14 },
  },
  authStepRow: {
    flexDirection: "row",
    alignItems: "center",
    marginBottom: 18,
  },
  authStepPill: {
    borderRadius: 999,
    paddingHorizontal: 12,
    paddingVertical: 8,
    backgroundColor: palette.panel,
  },
  authStepPillActive: {
    backgroundColor: "#1f2330",
  },
  authStepPillDone: {
    backgroundColor: "#dff2e5",
  },
  authStepPillText: {
    color: palette.subtext,
    fontSize: 12,
    fontWeight: "800",
  },
  authStepPillTextActive: {
    color: "#fffaf7",
  },
  authStepLine: {
    flex: 1,
    height: 1,
    backgroundColor: palette.border,
    marginHorizontal: 10,
  },
  authCardHeader: {
    marginBottom: 8,
  },
  authCardTitle: {
    color: palette.text,
    fontSize: 26,
    lineHeight: 30,
    fontWeight: "800",
    marginBottom: 6,
  },
  authCardSubtitle: {
    color: palette.subtext,
    fontSize: 14,
    lineHeight: 20,
  },
  inputLabel: {
    fontSize: 13,
    color: palette.subtext,
    fontWeight: "700",
    marginTop: 18,
    marginBottom: 8,
  },
  authInputShell: {
    flexDirection: "row",
    alignItems: "center",
    borderRadius: 22,
    borderWidth: 1,
    borderColor: palette.border,
    backgroundColor: palette.panel,
    padding: 6,
  },
  authInputPrefix: {
    minWidth: 58,
    borderRadius: 16,
    backgroundColor: "#f1e2d4",
    paddingVertical: 14,
    alignItems: "center",
    justifyContent: "center",
    marginRight: 8,
  },
  authInputPrefixText: {
    color: palette.text,
    fontSize: 15,
    fontWeight: "800",
  },
  authTextInput: {
    flex: 1,
    paddingRight: 14,
    paddingVertical: 14,
    fontSize: 16,
    color: palette.text,
  },
  authInfoStrip: {
    marginTop: 12,
    borderRadius: 18,
    backgroundColor: "#f6ede4",
    paddingHorizontal: 14,
    paddingVertical: 12,
  },
  authInfoStripText: {
    color: palette.subtext,
    fontSize: 13,
    lineHeight: 18,
    fontWeight: "600",
  },
  authPrimaryPressable: {
    marginTop: 16,
  },
  authBackLink: {
    marginTop: 12,
    alignItems: "center",
  },
  authBackLinkText: {
    color: palette.subtext,
    fontSize: 14,
    fontWeight: "700",
  },
  authPrimaryButton: {
    borderRadius: 999,
    paddingVertical: 16,
    alignItems: "center",
    justifyContent: "center",
  },
  authPrimaryButtonText: {
    color: "#fffaf7",
    fontSize: 15,
    fontWeight: "900",
    letterSpacing: 0.2,
  },
  authSecondaryButton: {
    marginTop: 12,
    borderRadius: 999,
    paddingVertical: 14,
    alignItems: "center",
    backgroundColor: palette.panel,
    borderWidth: 1,
    borderColor: palette.border,
  },
  authSecondaryButtonText: {
    color: palette.text,
    fontSize: 14,
    fontWeight: "800",
  },
  otpPreviewRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    gap: 10,
  },
  otpBox: {
    flex: 1,
    height: 68,
    borderRadius: 22,
    borderWidth: 1,
    borderColor: palette.border,
    backgroundColor: palette.panel,
    alignItems: "center",
    justifyContent: "center",
  },
  otpBoxFilled: {
    borderColor: palette.hero,
    backgroundColor: "#fff4f1",
  },
  otpBoxText: {
    color: palette.text,
    fontSize: 24,
    fontWeight: "800",
  },
  hiddenOtpInput: {
    position: "absolute",
    opacity: 0,
    pointerEvents: "none",
  },
  devHint: {
    marginTop: 14,
    borderRadius: 20,
    backgroundColor: "#fce7d8",
    paddingHorizontal: 16,
    paddingVertical: 14,
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
  },
  devHintLabel: {
    fontSize: 12,
    color: palette.subtext,
    marginBottom: 2,
    fontWeight: "700",
  },
  devHintCaption: {
    fontSize: 12,
    color: palette.subtext,
  },
  devHintValue: {
    fontSize: 24,
    color: palette.heroDark,
    fontWeight: "900",
    letterSpacing: 2,
  },
  authErrorCard: {
    marginTop: 14,
    borderRadius: 20,
    backgroundColor: "#fde0da",
    padding: 14,
  },
  authFeatureRow: {
    flexDirection: "row",
    gap: 10,
    marginTop: 18,
  },
  miniFeature: {
    flex: 1,
    borderRadius: 20,
    backgroundColor: "#f7efe8",
    padding: 14,
  },
  miniFeatureTitle: {
    fontSize: 12,
    color: palette.text,
    fontWeight: "800",
    marginBottom: 6,
  },
  miniFeatureText: {
    fontSize: 12,
    lineHeight: 16,
    color: palette.subtext,
  },
  authTrustPanel: {
    marginTop: 18,
    borderRadius: 30,
    backgroundColor: palette.card,
    padding: 20,
    borderWidth: 1,
    borderColor: palette.border,
  },
  authTrustTitle: {
    color: palette.text,
    fontSize: 19,
    fontWeight: "800",
    marginBottom: 14,
  },
  authTrustGrid: {
    gap: 10,
  },
  authTrustItem: {
    borderRadius: 20,
    backgroundColor: palette.panel,
    padding: 14,
  },
  authTrustItemTitle: {
    color: palette.text,
    fontSize: 14,
    fontWeight: "800",
    marginBottom: 4,
  },
  authTrustItemText: {
    color: palette.subtext,
    fontSize: 13,
    lineHeight: 18,
  },
  demoButton: {
    marginTop: 16,
    borderRadius: 999,
    paddingVertical: 15,
    alignItems: "center",
    backgroundColor: "#efe3d6",
  },
  demoButtonText: {
    color: palette.text,
    fontWeight: "800",
  },
  header: {
    paddingHorizontal: 20,
    paddingTop: 18,
    paddingBottom: 10,
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "flex-start",
  },
  eyebrow: {
    fontSize: 12,
    color: palette.subtext,
    textTransform: "uppercase",
    letterSpacing: 1.4,
    marginBottom: 6,
  },
  headerTitle: {
    fontSize: 28,
    lineHeight: 30,
    color: palette.text,
    fontWeight: "800",
    maxWidth: 220,
  },
  modeBadge: {
    borderRadius: 999,
    paddingHorizontal: 12,
    paddingVertical: 8,
  },
  modeBadgeLive: {
    backgroundColor: "#dbf4e3",
  },
  modeBadgeFallback: {
    backgroundColor: "#fde5cf",
  },
  modeBadgeText: {
    fontSize: 12,
    fontWeight: "700",
    color: palette.text,
  },
  scrollContent: {
    paddingHorizontal: 20,
    paddingBottom: 124,
  },
  heroCard: {
    backgroundColor: palette.hero,
    borderRadius: 30,
    padding: 24,
    overflow: "hidden",
    marginBottom: 22,
  },
  heroGlowOne: {
    position: "absolute",
    width: 220,
    height: 220,
    borderRadius: 220,
    backgroundColor: "rgba(255,255,255,0.10)",
    top: -70,
    right: -40,
  },
  heroGlowTwo: {
    position: "absolute",
    width: 160,
    height: 160,
    borderRadius: 160,
    backgroundColor: "rgba(255,255,255,0.08)",
    bottom: -50,
    left: -20,
  },
  heroKicker: {
    color: "#ffd9d1",
    textTransform: "uppercase",
    letterSpacing: 1.4,
    fontSize: 12,
    marginBottom: 12,
    fontWeight: "700",
  },
  heroTitle: {
    color: "#fffaf7",
    fontSize: 30,
    lineHeight: 34,
    fontWeight: "800",
    marginBottom: 12,
    maxWidth: 320,
  },
  heroText: {
    color: "#ffd9d1",
    fontSize: 15,
    lineHeight: 21,
    maxWidth: 320,
  },
  heroMetaRow: {
    flexDirection: "row",
    gap: 12,
    marginTop: 18,
  },
  heroMetaCard: {
    flex: 1,
    borderRadius: 20,
    backgroundColor: "rgba(255,255,255,0.12)",
    padding: 16,
  },
  heroMetaLabel: {
    color: "#ffd9d1",
    fontSize: 12,
    marginBottom: 6,
  },
  heroMetaValue: {
    color: "#fffaf7",
    fontSize: 15,
    fontWeight: "700",
  },
  heroActions: {
    flexDirection: "row",
    gap: 10,
    marginTop: 18,
  },
  heroAction: {
    flex: 1,
    borderRadius: 999,
    paddingVertical: 14,
    alignItems: "center",
  },
  heroActionPrimary: {
    backgroundColor: "#fffaf7",
  },
  heroActionGhost: {
    backgroundColor: "rgba(255,255,255,0.12)",
  },
  heroActionPrimaryText: {
    color: palette.heroDark,
    fontWeight: "800",
  },
  heroActionGhostText: {
    color: "#fffaf7",
    fontWeight: "700",
  },
  alertWarn: {
    backgroundColor: "#fde5cf",
    borderRadius: 20,
    padding: 16,
    marginBottom: 16,
  },
  alertDanger: {
    backgroundColor: "#fde0da",
    borderRadius: 20,
    padding: 16,
    marginBottom: 16,
  },
  alertTitle: {
    color: palette.text,
    fontSize: 14,
    fontWeight: "800",
    marginBottom: 6,
  },
  alertText: {
    color: palette.text,
    fontSize: 14,
    lineHeight: 20,
  },
  sectionHeader: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    marginBottom: 12,
  },
  sectionTitle: {
    fontSize: 20,
    color: palette.text,
    fontWeight: "800",
  },
  sectionHint: {
    color: palette.subtext,
    fontSize: 12,
    maxWidth: 160,
    textAlign: "right",
  },
  sectionAction: {
    fontSize: 12,
    color: palette.hero,
    fontWeight: "700",
  },
  cityRow: {
    gap: 10,
    paddingBottom: 18,
  },
  cityChip: {
    borderRadius: 999,
    backgroundColor: palette.card,
    borderWidth: 1,
    borderColor: palette.border,
    paddingHorizontal: 16,
    paddingVertical: 10,
  },
  cityChipActive: {
    backgroundColor: palette.text,
    borderColor: palette.text,
  },
  cityChipText: {
    color: palette.text,
    fontWeight: "700",
  },
  cityChipTextActive: {
    color: "#fffaf7",
  },
  loadingInlineCard: {
    borderRadius: 20,
    backgroundColor: palette.panel,
    padding: 16,
    marginBottom: 16,
    flexDirection: "row",
    alignItems: "center",
    gap: 10,
  },
  tabBlock: {
    gap: 12,
  },
  lockerCard: {
    backgroundColor: palette.card,
    borderRadius: 24,
    padding: 18,
    borderWidth: 1,
    borderColor: palette.border,
  },
  lockerCardActive: {
    borderColor: palette.hero,
    shadowColor: palette.hero,
    shadowOpacity: 0.14,
    shadowRadius: 12,
    shadowOffset: { width: 0, height: 8 },
  },
  lockerCardTop: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "flex-start",
    gap: 12,
    marginBottom: 16,
  },
  cardTitle: {
    fontSize: 17,
    color: palette.text,
    fontWeight: "800",
    marginBottom: 4,
  },
  cardText: {
    fontSize: 14,
    lineHeight: 19,
    color: palette.subtext,
  },
  statusPill: {
    borderRadius: 999,
    paddingHorizontal: 10,
    paddingVertical: 6,
  },
  statusGood: {
    backgroundColor: "#dff2e5",
  },
  statusWarn: {
    backgroundColor: "#fde5cf",
  },
  statusText: {
    fontSize: 12,
    fontWeight: "700",
    color: palette.text,
  },
  lockerStats: {
    flexDirection: "row",
    gap: 10,
  },
  metric: {
    flex: 1,
    borderRadius: 18,
    backgroundColor: palette.panel,
    padding: 12,
  },
  metricLabel: {
    fontSize: 11,
    color: palette.subtext,
    marginBottom: 6,
    textTransform: "uppercase",
    letterSpacing: 0.6,
  },
  metricValue: {
    color: palette.text,
    fontWeight: "800",
    fontSize: 15,
  },
  availabilityRow: {
    gap: 10,
  },
  availabilityCard: {
    backgroundColor: palette.panel,
    borderRadius: 20,
    padding: 16,
  },
  availabilityCardWide: {
    backgroundColor: palette.card,
    borderRadius: 20,
    padding: 16,
    borderWidth: 1,
    borderColor: palette.border,
  },
  productCard: {
    backgroundColor: palette.card,
    borderRadius: 24,
    padding: 16,
    borderWidth: 1,
    borderColor: palette.border,
    flexDirection: "row",
    gap: 14,
    alignItems: "center",
  },
  productCardActive: {
    borderColor: palette.hero,
  },
  productThumb: {
    width: 58,
    height: 58,
    borderRadius: 18,
    backgroundColor: "#f2d9be",
    justifyContent: "center",
    alignItems: "center",
  },
  productThumbText: {
    fontSize: 18,
    fontWeight: "900",
    color: palette.heroDark,
  },
  productMain: {
    flex: 1,
  },
  productMeta: {
    alignItems: "flex-end",
    gap: 4,
  },
  priceText: {
    fontSize: 15,
    fontWeight: "800",
    color: palette.text,
  },
  stockText: {
    fontSize: 12,
    color: palette.subtext,
    fontWeight: "700",
  },
  lockersListCard: {
    backgroundColor: palette.card,
    borderRadius: 22,
    padding: 16,
    borderWidth: 1,
    borderColor: palette.border,
  },
  lockersListCardActive: {
    borderColor: palette.hero,
  },
  lockersMetaRow: {
    marginTop: 10,
    flexDirection: "row",
    justifyContent: "space-between",
  },
  mapStub: {
    backgroundColor: palette.text,
    borderRadius: 28,
    padding: 22,
    marginVertical: 8,
  },
  mapStubLabel: {
    color: "#f5d9ce",
    textTransform: "uppercase",
    letterSpacing: 1.2,
    fontSize: 12,
    marginBottom: 8,
    fontWeight: "700",
  },
  mapStubText: {
    color: "#fffaf7",
    fontSize: 16,
    lineHeight: 22,
    fontWeight: "700",
    maxWidth: 280,
  },
  detailCard: {
    backgroundColor: palette.card,
    borderRadius: 28,
    padding: 20,
    borderWidth: 1,
    borderColor: palette.border,
  },
  inlineLoader: {
    flexDirection: "row",
    gap: 10,
    alignItems: "center",
  },
  detailHeader: {
    flexDirection: "row",
    gap: 14,
    marginBottom: 14,
  },
  detailThumb: {
    width: 72,
    height: 72,
    borderRadius: 24,
    backgroundColor: "#f0ddc7",
    justifyContent: "center",
    alignItems: "center",
  },
  detailThumbText: {
    fontSize: 20,
    fontWeight: "900",
    color: palette.heroDark,
  },
  detailMain: {
    flex: 1,
    justifyContent: "center",
  },
  detailTitle: {
    fontSize: 24,
    color: palette.text,
    fontWeight: "800",
    marginBottom: 6,
  },
  tagRow: {
    flexDirection: "row",
    gap: 8,
    flexWrap: "wrap",
    marginBottom: 14,
  },
  tagChip: {
    borderRadius: 999,
    backgroundColor: palette.panel,
    paddingHorizontal: 12,
    paddingVertical: 8,
  },
  tagChipActive: {
    backgroundColor: palette.text,
  },
  tagChipText: {
    color: palette.text,
    fontSize: 12,
    fontWeight: "700",
  },
  tagChipTextActive: {
    color: "#fffaf7",
  },
  subsectionTitle: {
    fontSize: 15,
    color: palette.text,
    fontWeight: "800",
    marginBottom: 8,
    marginTop: 6,
  },
  bodyText: {
    fontSize: 15,
    lineHeight: 22,
    color: palette.text,
    marginBottom: 8,
  },
  primaryButton: {
    marginTop: 18,
    backgroundColor: palette.hero,
    borderRadius: 999,
    paddingVertical: 15,
    alignItems: "center",
  },
  primaryButtonText: {
    color: "#fffaf7",
    fontSize: 15,
    fontWeight: "800",
  },
  secondaryButton: {
    marginTop: 12,
    backgroundColor: palette.text,
    borderRadius: 999,
    paddingVertical: 15,
    alignItems: "center",
  },
  secondaryButtonText: {
    color: "#fffaf7",
    fontSize: 15,
    fontWeight: "800",
  },
  ghostButton: {
    marginTop: 12,
    borderRadius: 999,
    paddingVertical: 14,
    alignItems: "center",
    backgroundColor: palette.panel,
  },
  ghostButtonText: {
    color: palette.text,
    fontWeight: "800",
  },
  ghostButtonDark: {
    marginTop: 18,
    borderRadius: 999,
    paddingVertical: 14,
    alignItems: "center",
    backgroundColor: palette.text,
  },
  ghostButtonDarkText: {
    color: "#fffaf7",
    fontWeight: "800",
  },
  buttonDisabled: {
    opacity: 0.45,
  },
  checkoutHero: {
    backgroundColor: "#f7dbcf",
    borderRadius: 26,
    padding: 18,
  },
  checkoutHeroTitle: {
    fontSize: 22,
    color: palette.text,
    fontWeight: "800",
    marginBottom: 8,
  },
  checkoutHeroText: {
    color: palette.subtext,
    lineHeight: 20,
  },
  checkoutCard: {
    backgroundColor: palette.card,
    borderRadius: 28,
    padding: 20,
    borderWidth: 1,
    borderColor: palette.border,
  },
  checkoutDivider: {
    height: 1,
    backgroundColor: palette.border,
    marginVertical: 16,
  },
  checkoutRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    marginBottom: 10,
  },
  checkoutStrong: {
    color: palette.text,
    fontWeight: "800",
  },
  bookingActions: {
    marginTop: 4,
  },
  inlineNotice: {
    marginTop: 12,
    borderRadius: 16,
    backgroundColor: "#fde5cf",
    padding: 14,
  },
  profileCard: {
    backgroundColor: palette.card,
    borderRadius: 26,
    padding: 20,
    borderWidth: 1,
    borderColor: palette.border,
  },
  profileMeta: {
    flexDirection: "row",
    gap: 10,
    marginTop: 16,
  },
  bottomNav: {
    position: "absolute",
    left: 18,
    right: 18,
    bottom: 22,
    backgroundColor: "#fffaf7",
    borderRadius: 999,
    padding: 8,
    flexDirection: "row",
    gap: 6,
    borderWidth: 1,
    borderColor: palette.border,
    shadowColor: "#47271d",
    shadowOpacity: 0.1,
    shadowRadius: 18,
    shadowOffset: { width: 0, height: 10 },
  },
  navItem: {
    flex: 1,
    paddingVertical: 12,
    borderRadius: 999,
    alignItems: "center",
  },
  navItemActive: {
    backgroundColor: palette.hero,
  },
  navItemText: {
    color: palette.subtext,
    fontSize: 12,
    fontWeight: "700",
  },
  navItemTextActive: {
    color: "#fffaf7",
  },
  loadingShell: {
    flex: 1,
    backgroundColor: palette.bg,
    justifyContent: "center",
    padding: 24,
  },
  loadingCard: {
    backgroundColor: palette.card,
    borderRadius: 30,
    padding: 28,
    borderWidth: 1,
    borderColor: palette.border,
    alignItems: "center",
    gap: 12,
  },
  loadingTitle: {
    fontSize: 24,
    fontWeight: "800",
    color: palette.text,
  },
  loadingText: {
    fontSize: 15,
    lineHeight: 21,
    color: palette.subtext,
    textAlign: "center",
  },
});
