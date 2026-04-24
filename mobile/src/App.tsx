import { useEffect, useMemo, useRef, useState } from "react";
import {
  ActivityIndicator,
  SafeAreaView,
  ScrollView,
  Text,
  View,
} from "react-native";

import {
  fetchLockers,
} from "./api";
import {
  findNearestCityIdByLockers,
  resolveUserGeoPoint,
  type GeoLocationState,
  type GeoPoint,
} from "./map/mapHelpers";
import { mockLockers } from "./mockData";
import { AuthScreen, CitySelectionScreen } from "./auth/AuthScreens";
import { HomeTab, HomeTopBar, CityStrip } from "./components/home/HomeSection";
import { MapTab } from "./components/map/MapSection";
import {
  BottomNav,
  BookingTab,
  CatalogTab,
  ProfileTab,
} from "./components/tabs/CatalogBookingProfileNav";
import { createPostamatsActions } from "./app/postamatsActions";
import { palette, styles } from "./styles/appStyles";
import type {
  AppUser,
  City,
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

export function PostamatsApp() {
  const [runtimeMode, setRuntimeMode] = useState<RuntimeMode>("live");
  const [authStep, setAuthStep] = useState<AuthStep>("landing");
  const [authIntent, setAuthIntent] = useState<AuthIntent>("login");
  const [tab, setTab] = useState<TabKey>("home");
  const [needsCitySelection, setNeedsCitySelection] = useState(false);

  const [phone, setPhone] = useState("");
  const [smsCode, setSmsCode] = useState("");
  const [verificationSessionId, setVerificationSessionId] = useState("");
  const [codeTtlSeconds, setCodeTtlSeconds] = useState(0);
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
  const [availabilityByLockerId, setAvailabilityByLockerId] = useState<
    Record<string, LockerAvailabilityItem[]>
  >({});
  const [selectedLockerId, setSelectedLockerId] = useState("");
  const [selectedProductId, setSelectedProductId] = useState("");
  const [selectedPlanId, setSelectedPlanId] = useState("");
  const [selectedProduct, setSelectedProduct] = useState<ProductDetail | null>(null);
  const [pricing, setPricing] = useState<PricingQuote | null>(null);
  const [quote, setQuote] = useState<ReservationQuote | null>(null);
  const [reservation, setReservation] = useState<ReservationSummary | null>(null);
  const [screenMessage, setScreenMessage] = useState("Показываем ближайшие точки, товары и стоимость аренды.");
  const [screenError, setScreenError] = useState("");

  const [sessionRestoring, setSessionRestoring] = useState(true);
  const [bootLoading, setBootLoading] = useState(false);
  const [catalogLoading, setCatalogLoading] = useState(false);
  const [detailLoading, setDetailLoading] = useState(false);
  const [bookingLoading, setBookingLoading] = useState(false);
  const [userLocation, setUserLocation] = useState<GeoPoint | null>(null);
  const [geoLocationState, setGeoLocationState] = useState<GeoLocationState>("idle");

  const locationResolvedRef = useRef(false);
  const nearestCityResolvedRef = useRef(false);

  const isAuthed = Boolean(accessToken) || runtimeMode === "fallback";
  const canReserve =
    runtimeMode === "fallback" ||
    (user?.verificationStatus === "approved" && user?.isBlocked !== true);
  const isCodeTimerActive = authStep === "confirm" && codeTtlSeconds > 0;

  const selectedCity = useMemo(
    () => cities.find((item) => item.id === selectedCityId) ?? cities[0] ?? null,
    [cities, selectedCityId],
  );
  const selectedLocker = useMemo(
    () => lockers.find((item) => item.id === selectedLockerId) ?? null,
    [lockers, selectedLockerId],
  );
  const selectedPlan = useMemo<PricePlan | null>(
    () => selectedProduct?.pricePlans.find((item) => item.id === selectedPlanId) ?? selectedProduct?.pricePlans[0] ?? null,
    [selectedPlanId, selectedProduct],
  );
  const bookingBadgeCount = reservation ? 1 : 0;
  const isHomeTab = tab === "home";
  const isMapTab = tab === "lockers";
  const highlightNotificationCount = bookingBadgeCount;

  useEffect(() => {
    if (!isAuthed || locationResolvedRef.current) {
      return;
    }

    let active = true;
    locationResolvedRef.current = true;
    setGeoLocationState("loading");

    void resolveUserGeoPoint()
      .then((result) => {
        if (!active) {
          return;
        }
        setUserLocation(result.point);
        setGeoLocationState(result.state);
      })
      .catch(() => {
        if (!active) {
          return;
        }
        setUserLocation(null);
        setGeoLocationState("unavailable");
      });

    return () => {
      active = false;
    };
  }, [isAuthed]);

  useEffect(() => {
    if (!isAuthed || !cities.length || nearestCityResolvedRef.current) {
      return;
    }
    if (geoLocationState === "idle" || geoLocationState === "loading") {
      return;
    }

    let active = true;
    nearestCityResolvedRef.current = true;

    async function applyNearestCity() {
      if (geoLocationState === "ready" && userLocation) {
        try {
          const allLockers =
            runtimeMode === "fallback"
              ? mockLockers
              : await fetchLockers().catch(async () => {
                  const perCityLockers = await Promise.all(
                    cities.map((city) => fetchLockers(city.id).catch(() => [] as Locker[])),
                  );
                  return perCityLockers.flat();
                });
          if (!active) {
            return;
          }

          const nearestCityId = findNearestCityIdByLockers(userLocation, cities, allLockers);
          if (nearestCityId) {
            const nearestCityName =
              cities.find((city) => city.id === nearestCityId)?.name ?? "ближайший город";
            setSelectedCityId(nearestCityId);
            setNeedsCitySelection(false);
            setScreenMessage(`Определили вашу геолокацию и открыли ближайший город: ${nearestCityName}.`);
            return;
          }
        } catch {
          if (!active) {
            return;
          }
        }
      }

      if (!selectedCityId && cities[0]) {
        setSelectedCityId(cities[0].id);
        setNeedsCitySelection(false);
      }
    }

    void applyNearestCity();

    return () => {
      active = false;
    };
  }, [cities, geoLocationState, isAuthed, runtimeMode, selectedCityId, userLocation]);

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

  useEffect(() => {
    void restorePersistedSession();
  }, []);

  useEffect(() => {
    if (!isCodeTimerActive) {
      return;
    }

    const timer = setInterval(() => {
      setCodeTtlSeconds((current) => (current > 1 ? current - 1 : 0));
    }, 1000);

    return () => clearInterval(timer);
  }, [isCodeTimerActive]);

  const {
    restorePersistedSession,
    handleRequestCode,
    openAuthEntry,
    handleConfirmCode,
    loadCityData,
    loadAvailability,
    loadProductDetail,
    loadPricing,
    handleQuote,
    handleCreateReservation,
    enterDemoMode,
    handleLogout,
  } = createPostamatsActions({
    runtimeMode,
    authIntent,
    phone,
    smsCode,
    verificationSessionId,
    accessToken,
    refreshToken,
    cities,
    selectedCityId,
    selectedLockerId,
    selectedProductId,
    availabilityByLockerId,
    selectedProduct,
    selectedLocker,
    selectedPlan,
    canReserve,
    locationResolvedRef,
    nearestCityResolvedRef,
    setAuthStep,
    setAuthIntent,
    setPhone,
    setSmsCode,
    setVerificationSessionId,
    setCodeTtlSeconds,
    setDevCode,
    setAuthMessage,
    setAuthError,
    setAuthLoading,
    setAccessToken,
    setRefreshToken,
    setUser,
    setVerification,
    setCities,
    setSelectedCityId,
    setLockers,
    setProducts,
    setAvailability,
    setAvailabilityByLockerId,
    setSelectedLockerId,
    setSelectedProductId,
    setSelectedPlanId,
    setSelectedProduct,
    setPricing,
    setQuote,
    setReservation,
    setScreenMessage,
    setScreenError,
    setSessionRestoring,
    setBootLoading,
    setCatalogLoading,
    setDetailLoading,
    setBookingLoading,
    setUserLocation,
    setGeoLocationState,
    setTab,
    setNeedsCitySelection,
    setRuntimeMode,
  });

  if (sessionRestoring) {
    return (
      <SafeAreaView style={styles.loadingShell}>
        <View style={styles.loadingCard}>
          <ActivityIndicator size="large" color={palette.hero} />
          <Text style={styles.loadingTitle}>Восстанавливаем сессию</Text>
          <Text style={styles.loadingText}>Проверяем токены и подгружаем ваш профиль.</Text>
        </View>
      </SafeAreaView>
    );
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
          codeTtlSeconds={codeTtlSeconds}
          onPhoneChange={setPhone}
          onCodeChange={setSmsCode}
          onRequestCode={handleRequestCode}
          onConfirmCode={handleConfirmCode}
          onResendCode={handleRequestCode}
          onBack={() => {
            setAuthStep((current) => (current === "confirm" ? "request" : "landing"));
            setCodeTtlSeconds(0);
            setAuthError("");
            setSmsCode("");
            setDevCode("");
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
    <SafeAreaView style={styles.safeHome}>
      <View style={styles.appShellHome}>
        {isMapTab ? (
          <MapTab
            cityName={selectedCity?.name ?? "Город"}
            lockers={lockers}
            selectedLockerId={selectedLockerId}
            onSelectLocker={setSelectedLockerId}
            onBackHome={() => setTab("home")}
            loading={catalogLoading}
            errorMessage={screenError}
            userLocation={userLocation}
            locationState={geoLocationState}
            lockerAvailabilityById={availabilityByLockerId}
          />
        ) : (
          <ScrollView
            contentContainerStyle={[styles.scrollContent, styles.homeScrollContent]}
            showsVerticalScrollIndicator={false}
          >
            {isHomeTab ? (
              <>
                <HomeTopBar
                  user={user}
                  city={selectedCity?.name ?? "Город"}
                  lockerCount={lockers.length}
                  notificationCount={highlightNotificationCount}
                  onOpenCatalog={() => setTab("catalog")}
                />

                {screenError ? (
                  <View style={styles.alertDanger}>
                    <Text style={styles.alertTitle}>Не удалось загрузить данные</Text>
                    <Text style={styles.alertText}>{screenError}</Text>
                  </View>
                ) : null}

                {catalogLoading ? (
                  <View style={styles.loadingInlineCard}>
                    <ActivityIndicator size="small" color={palette.hero} />
                    <Text style={styles.cardText}>Обновляем точки и каталог по выбранному городу.</Text>
                  </View>
                ) : null}

                <HomeTab
                  cities={cities}
                  selectedCityId={selectedCityId}
                  user={user}
                  verification={verification}
                  runtimeMode={runtimeMode}
                  screenMessage={screenMessage}
                  products={products}
                  lockers={lockers}
                  availability={availability}
                  reservation={reservation}
                  selectedProduct={selectedProduct}
                  selectedLocker={selectedLocker}
                  onSelectCity={setSelectedCityId}
                  onSelectProduct={(productId) => {
                    setSelectedProductId(productId);
                    setTab("catalog");
                  }}
                  onOpenCatalog={() => setTab("catalog")}
                  onOpenLockers={() => setTab("lockers")}
                  onOpenLocker={(lockerId) => {
                    setSelectedLockerId(lockerId);
                    setTab("lockers");
                  }}
                  onOpenBooking={() => setTab("booking")}
                />
              </>
            ) : (
              <>
                <HomeTopBar
                  user={user}
                  city={selectedCity?.name ?? "Город"}
                  lockerCount={lockers.length}
                  notificationCount={highlightNotificationCount}
                  onOpenCatalog={() => setTab("catalog")}
                />

                <View style={styles.nonHomeMetaRow}>
                  <View style={[styles.modeBadge, runtimeMode === "live" ? styles.modeBadgeLive : styles.modeBadgeFallback]}>
                    <Text style={styles.modeBadgeText}>{runtimeMode === "live" ? "Подключено" : "Демо"}</Text>
                  </View>
                  <Text style={styles.nonHomeMetaText}>{screenMessage}</Text>
                </View>

                {screenError ? (
                  <View style={styles.alertDanger}>
                    <Text style={styles.alertTitle}>Не удалось загрузить данные</Text>
                    <Text style={styles.alertText}>{screenError}</Text>
                  </View>
                ) : null}

                {!canReserve && tab === "booking" ? (
                  <View style={styles.alertWarn}>
                    <Text style={styles.alertTitle}>Бронь пока недоступна</Text>
                    <Text style={styles.alertText}>
                      Как только аккаунт будет подтвержден, здесь откроется расчет суммы и оформление аренды.
                    </Text>
                  </View>
                ) : null}

                {tab !== "profile" ? (
                  <CityStrip cities={cities} selectedCityId={selectedCityId} onSelect={setSelectedCityId} />
                ) : null}

                {catalogLoading ? (
                  <View style={styles.loadingInlineCard}>
                    <ActivityIndicator size="small" color={palette.hero} />
                    <Text style={styles.cardText}>Обновляем точки и каталог по выбранному городу.</Text>
                  </View>
                ) : null}

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
              </>
            )}
          </ScrollView>
        )}

        <BottomNav current={tab} onChange={setTab} bookingBadgeCount={bookingBadgeCount} />
      </View>
    </SafeAreaView>
  );
}
