import type { Dispatch, MutableRefObject, SetStateAction } from "react";

import {
  ApiError,
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
  isForbiddenError,
  isUnauthorizedError,
  logoutAuthSession,
  refreshAuthSession,
  requestCode,
} from "../api";
import {
  clearStoredAuthSession,
  readStoredAuthSession,
  writeStoredAuthSession,
} from "../authStorage";
import { isPhoneReady, normalizePhoneForApi } from "../auth/authUtils";
import {
  mockAvailability,
  mockCities,
  mockLockers,
  mockPricing,
  mockProductDetail,
  mockProducts,
} from "../mockData";
import type { GeoLocationState, GeoPoint } from "../map/mapHelpers";
import { formatCountText } from "../utils/appFormatters";
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
} from "../types";

type TabKey = "home" | "lockers" | "catalog" | "booking" | "profile";
type AuthStep = "landing" | "request" | "confirm";
type AuthIntent = "login" | "signup";
type RuntimeMode = "live" | "fallback";
type Setter<T> = Dispatch<SetStateAction<T>>;

const DEFAULT_AUTH_MESSAGE =
  "Введите номер телефона. РФ можно без +7, РБ только через +375.";
const DEFAULT_SCREEN_MESSAGE =
  "Показываем ближайшие точки, товары и стоимость аренды.";

const demoUser: AppUser = {
  id: "demo-user",
  phone: "+7 999 000 00 00",
  firstName: "Иван",
  lastName: "Петров",
  middleName: "Александрович",
  verificationStatus: "approved",
  preferredCityId: mockCities[0]?.id,
  isBlocked: false,
};

const demoVerification: VerificationState = {
  status: "approved",
};

type CreatePostamatsActionsParams = {
  runtimeMode: RuntimeMode;
  authIntent: AuthIntent;
  phone: string;
  smsCode: string;
  verificationSessionId: string;
  accessToken: string;
  refreshToken: string;
  cities: City[];
  selectedCityId: string;
  selectedLockerId: string;
  selectedProductId: string;
  availabilityByLockerId: Record<string, LockerAvailabilityItem[]>;
  selectedProduct: ProductDetail | null;
  selectedLocker: Locker | null;
  selectedPlan: PricePlan | null;
  canReserve: boolean;
  locationResolvedRef: MutableRefObject<boolean>;
  nearestCityResolvedRef: MutableRefObject<boolean>;
  setAuthStep: Setter<AuthStep>;
  setAuthIntent: Setter<AuthIntent>;
  setPhone: Setter<string>;
  setSmsCode: Setter<string>;
  setVerificationSessionId: Setter<string>;
  setCodeTtlSeconds: Setter<number>;
  setDevCode: Setter<string>;
  setAuthMessage: Setter<string>;
  setAuthError: Setter<string>;
  setAuthLoading: Setter<boolean>;
  setAccessToken: Setter<string>;
  setRefreshToken: Setter<string>;
  setUser: Setter<AppUser | null>;
  setVerification: Setter<VerificationState | null>;
  setCities: Setter<City[]>;
  setSelectedCityId: Setter<string>;
  setLockers: Setter<Locker[]>;
  setProducts: Setter<ProductListItem[]>;
  setAvailability: Setter<LockerAvailabilityItem[]>;
  setAvailabilityByLockerId: Setter<Record<string, LockerAvailabilityItem[]>>;
  setSelectedLockerId: Setter<string>;
  setSelectedProductId: Setter<string>;
  setSelectedPlanId: Setter<string>;
  setSelectedProduct: Setter<ProductDetail | null>;
  setPricing: Setter<PricingQuote | null>;
  setQuote: Setter<ReservationQuote | null>;
  setReservation: Setter<ReservationSummary | null>;
  setScreenMessage: Setter<string>;
  setScreenError: Setter<string>;
  setSessionRestoring: Setter<boolean>;
  setBootLoading: Setter<boolean>;
  setCatalogLoading: Setter<boolean>;
  setDetailLoading: Setter<boolean>;
  setBookingLoading: Setter<boolean>;
  setUserLocation: Setter<GeoPoint | null>;
  setGeoLocationState: Setter<GeoLocationState>;
  setTab: Setter<TabKey>;
  setNeedsCitySelection: Setter<boolean>;
  setRuntimeMode: Setter<RuntimeMode>;
};

export function createPostamatsActions(ctx: CreatePostamatsActionsParams) {
  async function persistAuthSession(nextAccessToken: string, nextRefreshToken: string) {
    try {
      await writeStoredAuthSession({
        accessToken: nextAccessToken,
        refreshToken: nextRefreshToken,
      });
    } catch (error) {
      console.error("Failed to persist auth session", error);
    }
  }

  function applyAuthUserSnapshot(snapshot: ConfirmCodeResponse["user"]) {
    ctx.setUser((current) => ({
      ...(current ?? {
        id: "",
        phone: "",
        verificationStatus: "draft",
      }),
      id: snapshot.id,
      phone: snapshot.phone,
      verificationStatus: snapshot.verificationStatus,
    }));
  }

  async function applyLiveSession(result: ConfirmCodeResponse, persist = true) {
    ctx.setAccessToken(result.accessToken);
    ctx.setRefreshToken(result.refreshToken);
    ctx.setRuntimeMode("live");
    applyAuthUserSnapshot(result.user);

    if (persist) {
      await persistAuthSession(result.accessToken, result.refreshToken);
    }
  }

  async function clearLiveSessionState(options?: {
    nextAuthStep?: AuthStep;
    nextAuthIntent?: AuthIntent;
    authError?: string;
    authMessage?: string;
  }) {
    ctx.setAccessToken("");
    ctx.setRefreshToken("");
    ctx.setUser(null);
    ctx.setVerification(null);
    ctx.setCities([]);
    ctx.setSelectedCityId("");
    ctx.setLockers([]);
    ctx.setProducts([]);
    ctx.setAvailability([]);
    ctx.setAvailabilityByLockerId({});
    ctx.setSelectedLockerId("");
    ctx.setSelectedProductId("");
    ctx.setSelectedPlanId("");
    ctx.setSelectedProduct(null);
    ctx.setPricing(null);
    ctx.setQuote(null);
    ctx.setReservation(null);
    ctx.setRuntimeMode("live");
    ctx.setAuthStep(options?.nextAuthStep ?? "landing");
    ctx.setAuthIntent(options?.nextAuthIntent ?? "login");
    ctx.setNeedsCitySelection(false);
    ctx.setPhone("");
    ctx.setSmsCode("");
    ctx.setVerificationSessionId("");
    ctx.setCodeTtlSeconds(0);
    ctx.setDevCode("");
    ctx.setTab("home");
    ctx.setScreenError("");
    ctx.setScreenMessage(DEFAULT_SCREEN_MESSAGE);
    ctx.setAuthLoading(false);
    ctx.setBootLoading(false);
    ctx.setCatalogLoading(false);
    ctx.setDetailLoading(false);
    ctx.setBookingLoading(false);
    ctx.setUserLocation(null);
    ctx.setGeoLocationState("idle");
    ctx.locationResolvedRef.current = false;
    ctx.nearestCityResolvedRef.current = false;
    ctx.setAuthError(options?.authError ?? "");
    ctx.setAuthMessage(options?.authMessage ?? DEFAULT_AUTH_MESSAGE);

    try {
      await clearStoredAuthSession();
    } catch (error) {
      console.error("Failed to clear auth session", error);
    }
  }

  async function expireLiveSession() {
    await clearLiveSessionState({
      nextAuthStep: "request",
      nextAuthIntent: "login",
      authError: "Сессия истекла. Войдите снова.",
    });
  }

  async function refreshLiveSession(refreshTokenOverride?: string) {
    const token = refreshTokenOverride ?? ctx.refreshToken;
    if (!token) {
      throw new Error("Сессия истекла. Войдите снова.");
    }

    const result = await refreshAuthSession(token);
    await applyLiveSession(result);
    return result;
  }

  async function withFreshAccessToken<T>(
    operation: (token: string) => Promise<T>,
    options?: {
      accessToken?: string;
      refreshToken?: string;
      clearOnFailure?: boolean;
    },
  ): Promise<T> {
    const currentAccessToken = options?.accessToken ?? ctx.accessToken;
    const currentRefreshToken = options?.refreshToken ?? ctx.refreshToken;

    if (!currentAccessToken && currentRefreshToken) {
      const refreshed = await refreshLiveSession(currentRefreshToken);
      return operation(refreshed.accessToken);
    }

    if (!currentAccessToken) {
      throw new Error("Сессия отсутствует. Войдите снова.");
    }

    try {
      return await operation(currentAccessToken);
    } catch (error) {
      if (error instanceof ApiError && error.status === 403) {
        if (options?.clearOnFailure !== false) {
          await clearLiveSessionState({
            nextAuthStep: "request",
            nextAuthIntent: "login",
            authError: error.message,
          });
        }
        throw error;
      }
      if (isUnauthorizedError(error) && currentRefreshToken) {
        try {
          const refreshed = await refreshLiveSession(currentRefreshToken);
          return await operation(refreshed.accessToken);
        } catch (refreshError) {
          if (options?.clearOnFailure !== false) {
            await expireLiveSession();
          }
          throw refreshError;
        }
      }
      throw error;
    }
  }

  async function hydrateAuthorizedState(token: string, refreshTokenOverride?: string) {
    ctx.setBootLoading(true);
    ctx.setScreenError("");
    try {
      const [me, currentVerification, cityItems] = await withFreshAccessToken(
        (validAccessToken) =>
          Promise.all([
            fetchMe(validAccessToken),
            fetchVerification(validAccessToken),
            fetchCities(),
          ]),
        {
          accessToken: token,
          refreshToken: refreshTokenOverride,
        },
      );

      ctx.setUser(me);
      ctx.setVerification(currentVerification);
      ctx.nearestCityResolvedRef.current = false;
      ctx.setCities(cityItems);

      const shouldAskCity = ctx.authIntent === "signup" || !me.preferredCityId;
      const nextCityId = shouldAskCity ? "" : me.preferredCityId ?? "";
      ctx.setSelectedCityId(nextCityId);
      ctx.setNeedsCitySelection(shouldAskCity);
      ctx.setScreenMessage("Проверьте точки выдачи, выберите товар и переходите к бронированию.");
    } catch (error) {
      if (error instanceof ApiError && error.status === 403) {
        ctx.setBootLoading(false);
        return;
      }
      const message =
        error instanceof Error ? error.message : "Не удалось инициализировать приложение.";
      ctx.setScreenError(message);
      throw error instanceof Error ? error : new Error(message);
    } finally {
      ctx.setBootLoading(false);
    }
  }

  async function restorePersistedSession() {
    ctx.setSessionRestoring(true);

    try {
      const stored = await readStoredAuthSession();
      if (!stored) {
        return;
      }

      await applyLiveSession(
        {
          accessToken: stored.accessToken,
          refreshToken: stored.refreshToken,
          user: {
            id: "",
            phone: "",
            verificationStatus: "draft",
          },
        },
        false,
      );

      try {
        await hydrateAuthorizedState(stored.accessToken, stored.refreshToken);
      } catch (error) {
        console.error("Failed to restore persisted session", error);
        if (isForbiddenError(error)) {
          await clearLiveSessionState({
            nextAuthStep: "request",
            nextAuthIntent: "login",
            authError: error.message,
          });
        } else if (isUnauthorizedError(error) || error instanceof ApiError) {
          await expireLiveSession();
        } else {
          await clearLiveSessionState({
            nextAuthStep: "request",
            nextAuthIntent: "login",
            authError:
              error instanceof Error
                ? error.message
                : "Не удалось восстановить сессию. Войдите снова.",
          });
        }
      }
    } finally {
      ctx.setSessionRestoring(false);
    }
  }

  async function handleRequestCode() {
    const normalizedPhone = normalizePhoneForApi(ctx.phone);
    if (!isPhoneReady(normalizedPhone)) {
      ctx.setAuthError(
        "Поддерживаются только номера РФ и РБ. РФ можно вводить без +7, РБ только через +375.",
      );
      return;
    }

    ctx.setAuthLoading(true);
    ctx.setAuthError("");
    try {
      const result = await requestCode(normalizedPhone);
      ctx.setVerificationSessionId(result.verificationSessionId);
      ctx.setCodeTtlSeconds(result.ttlSeconds ?? 0);
      ctx.setDevCode(result.code ?? "");
      ctx.setAuthMessage(`Мы отправили код на ${normalizedPhone}.`);
      ctx.setSmsCode("");
      ctx.setAuthStep("confirm");
    } catch (error) {
      ctx.setAuthError(error instanceof Error ? error.message : "Не удалось запросить код.");
    } finally {
      ctx.setAuthLoading(false);
    }
  }

  function openAuthEntry(mode: "login" | "signup") {
    ctx.setAuthIntent(mode);
    ctx.setAuthStep("request");
    ctx.setAuthError("");
    ctx.setDevCode("");
    ctx.setSmsCode("");
    ctx.setVerificationSessionId("");
    ctx.setCodeTtlSeconds(0);
    ctx.setAuthMessage(
      mode === "login"
        ? "Введите номер РФ или РБ, чтобы войти в приложение."
        : "Введите номер РФ или РБ, чтобы создать аккаунт и продолжить.",
    );
  }

  async function completeLogin(result: ConfirmCodeResponse) {
    await applyLiveSession(result);
    ctx.setTab("home");
    ctx.setAuthMessage("Вход подтвержден. Загружаем ваш профиль.");
    await hydrateAuthorizedState(result.accessToken, result.refreshToken);
  }

  async function handleConfirmCode() {
    if (!ctx.verificationSessionId || !ctx.smsCode.trim()) {
      ctx.setAuthError("Введите код подтверждения.");
      return;
    }

    ctx.setAuthLoading(true);
    ctx.setAuthError("");
    try {
      const result = await confirmCode(ctx.verificationSessionId, ctx.smsCode.trim());
      await completeLogin(result);
    } catch (error) {
      ctx.setAuthError(error instanceof Error ? error.message : "Не удалось подтвердить код.");
    } finally {
      ctx.setAuthLoading(false);
    }
  }

  async function loadCityData(cityId: string) {
    if (ctx.runtimeMode === "fallback") {
      return;
    }

    ctx.setCatalogLoading(true);
    ctx.setScreenError("");
    try {
      const [lockerItems, productItems] = await Promise.all([
        fetchLockers(cityId),
        fetchProducts(cityId),
      ]);
      const cityName = ctx.cities.find((item) => item.id === cityId)?.name ?? "выбранном городе";
      ctx.setLockers(lockerItems);
      ctx.setProducts(productItems);
      ctx.setAvailabilityByLockerId((current) => {
        const next: Record<string, LockerAvailabilityItem[]> = {};
        lockerItems.forEach((locker) => {
          if (current[locker.id]) {
            next[locker.id] = current[locker.id];
          }
        });
        return next;
      });

      ctx.setSelectedLockerId((current) =>
        lockerItems.some((locker) => locker.id === current) ? current : "",
      );
      ctx.setSelectedProductId((current) =>
        productItems.some((product) => product.id === current) ? current : "",
      );

      if (!lockerItems.length) {
        ctx.setAvailability([]);
      }

      if (!lockerItems.some((locker) => locker.id === ctx.selectedLockerId)) {
        ctx.setAvailability([]);
      } else if (ctx.availabilityByLockerId[ctx.selectedLockerId]) {
        ctx.setAvailability(ctx.availabilityByLockerId[ctx.selectedLockerId]);
      }

      if (
        !productItems.length ||
        !productItems.some((product) => product.id === ctx.selectedProductId)
      ) {
        ctx.setSelectedProduct(null);
        ctx.setSelectedPlanId("");
        ctx.setPricing(null);
      }

      if (lockerItems.length && productItems.length) {
        ctx.setScreenMessage(
          `В ${cityName} доступны ${formatCountText(lockerItems.length, "постамат", "постамата", "постаматов")} и ${formatCountText(productItems.length, "товар", "товара", "товаров")}.`,
        );
      } else if (lockerItems.length) {
        ctx.setScreenMessage(
          `В ${cityName} доступны ${formatCountText(lockerItems.length, "постамат", "постамата", "постаматов")}. Каталог пока пуст.`,
        );
      } else if (productItems.length) {
        ctx.setScreenMessage(
          `В ${cityName} есть ${formatCountText(productItems.length, "товар", "товара", "товаров")}, но точки выдачи ещё не настроены.`,
        );
      } else {
        ctx.setScreenMessage(`Для ${cityName} пока нет доступных товаров и постаматов.`);
      }
    } catch (error) {
      ctx.setScreenError(error instanceof Error ? error.message : "Не удалось загрузить каталог.");
    } finally {
      ctx.setCatalogLoading(false);
    }
  }

  async function loadAvailability(lockerId: string) {
    if (ctx.runtimeMode === "fallback") {
      return;
    }

    try {
      const items = await fetchLockerAvailability(lockerId);
      ctx.setAvailability(items);
      ctx.setAvailabilityByLockerId((current) => ({
        ...current,
        [lockerId]: items,
      }));
    } catch (error) {
      ctx.setScreenError(
        error instanceof Error ? error.message : "Не удалось обновить наличие в точке.",
      );
    }
  }

  async function loadProductDetail(productId: string, cityId?: string) {
    ctx.setDetailLoading(true);
    try {
      const detail =
        ctx.runtimeMode === "fallback"
          ? mockProductDetail
          : await fetchProduct(productId, cityId);
      ctx.setSelectedProduct(detail);

      const firstPlanId = detail.pricePlans[0]?.id ?? "";

      if (firstPlanId) {
        ctx.setSelectedPlanId((current) =>
          detail.pricePlans.some((plan) => plan.id === current) ? current : firstPlanId,
        );
      }

      ctx.setSelectedLockerId((current) =>
        detail.availableLockers.some((locker) => locker.lockerId === current) ? current : "",
      );
    } catch (error) {
      ctx.setScreenError(
        error instanceof Error ? error.message : "Не удалось загрузить карточку товара.",
      );
    } finally {
      ctx.setDetailLoading(false);
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
        ctx.runtimeMode === "fallback"
          ? { ...mockPricing, productId, lockerId, durationType, durationValue }
          : await fetchProductPricing(productId, lockerId, durationType, durationValue);
      ctx.setPricing(result);
    } catch (error) {
      ctx.setScreenError(error instanceof Error ? error.message : "Не удалось рассчитать стоимость.");
    }
  }

  async function handleQuote() {
    const selectedPlan = ctx.selectedPlan;
    if (!ctx.selectedProductId || !ctx.selectedLockerId || !selectedPlan) {
      ctx.setScreenError("Сначала выберите товар, точку и тариф.");
      return;
    }

    if (!ctx.canReserve) {
      ctx.setScreenError("Бронирование откроется после подтверждения верификации.");
      return;
    }

    ctx.setBookingLoading(true);
    ctx.setScreenError("");
    try {
      const nextQuote =
        ctx.runtimeMode === "fallback"
          ? {
              productId: ctx.selectedProductId,
              lockerId: ctx.selectedLockerId,
              durationType: selectedPlan.durationType,
              durationValue: selectedPlan.durationValue,
              currency: selectedPlan.currency,
              quotedAmount: selectedPlan.baseAmount,
              preauthAmount: selectedPlan.baseAmount,
              expiresIn: 300,
            }
          : await withFreshAccessToken((validAccessToken) =>
              createReservationQuote(validAccessToken, {
                productId: ctx.selectedProductId,
                lockerId: ctx.selectedLockerId,
                durationType: selectedPlan.durationType,
                durationValue: selectedPlan.durationValue,
              }),
            );
      ctx.setQuote(nextQuote);
      ctx.setScreenMessage("Расчет готов. Проверьте сумму и подтвердите бронь.");
      ctx.setTab("booking");
    } catch (error) {
      ctx.setScreenError(error instanceof Error ? error.message : "Не удалось рассчитать сумму.");
    } finally {
      ctx.setBookingLoading(false);
    }
  }

  async function handleCreateReservation() {
    const selectedPlan = ctx.selectedPlan;
    if (!ctx.selectedProductId || !ctx.selectedLockerId || !selectedPlan) {
      ctx.setScreenError("Не хватает данных для брони.");
      return;
    }
    if (!ctx.canReserve) {
      ctx.setScreenError("Бронирование доступно только после верификации.");
      return;
    }

    ctx.setBookingLoading(true);
    ctx.setScreenError("");
    try {
      if (ctx.runtimeMode === "fallback") {
        const demoReservation: ReservationSummary = {
          id: "demo-reservation",
          status: "awaiting_payment",
          expiresAt: new Date(Date.now() + 120 * 60 * 1000).toISOString(),
          product: {
            id: ctx.selectedProductId,
            name: ctx.selectedProduct?.name,
            coverUrl: ctx.selectedProduct?.coverUrl,
          },
          locker: {
            id: ctx.selectedLockerId,
            name: ctx.selectedLocker?.name,
            address: ctx.selectedLocker?.address,
          },
          pricing: {
            quotedAmount: selectedPlan.baseAmount,
            preauthAmount: selectedPlan.baseAmount,
            currency: selectedPlan.currency,
          },
        };
        ctx.setReservation(demoReservation);
        ctx.setScreenMessage("Бронь создана. Следующим шагом останется оплата и получение.");
      } else {
        const created = await withFreshAccessToken((validAccessToken) =>
          createReservation(validAccessToken, {
            productId: ctx.selectedProductId,
            lockerId: ctx.selectedLockerId,
            durationType: selectedPlan.durationType,
            durationValue: selectedPlan.durationValue,
            pickupWindowMinutes: 120,
          }),
        );
        const expanded = await withFreshAccessToken((validAccessToken) =>
          fetchReservation(validAccessToken, created.id),
        );
        ctx.setReservation(expanded);
        ctx.setScreenMessage("Бронь создана. Дальше останется оплата и подтверждение выдачи.");
      }
      ctx.setTab("booking");
    } catch (error) {
      ctx.setScreenError(error instanceof Error ? error.message : "Не удалось создать бронь.");
    } finally {
      ctx.setBookingLoading(false);
    }
  }

  function enterDemoMode() {
    ctx.setRuntimeMode("fallback");
    ctx.setAccessToken("");
    ctx.setRefreshToken("");
    ctx.setUser(demoUser);
    ctx.setVerification(demoVerification);
    ctx.setCities(mockCities);
    ctx.setSelectedCityId(mockCities[0]?.id ?? "");
    ctx.setLockers(mockLockers);
    ctx.setProducts(mockProducts);
    ctx.setAvailability(mockAvailability);
    ctx.setAvailabilityByLockerId(mockLockers[0] ? { [mockLockers[0].id]: mockAvailability } : {});
    ctx.setSelectedLockerId(mockLockers[0]?.id ?? "");
    ctx.setSelectedProductId(mockProducts[0]?.id ?? "");
    ctx.setSelectedProduct(mockProductDetail);
    ctx.setSelectedPlanId(mockProductDetail.pricePlans[0]?.id ?? "");
    ctx.setPricing(mockPricing);
    ctx.setNeedsCitySelection(false);
    ctx.setQuote(null);
    ctx.setReservation(null);
    ctx.setTab("home");
    ctx.setAuthError("");
    ctx.setAuthMessage("Открыли демо-режим. Можно посмотреть путь аренды без сервера.");
    ctx.setUserLocation(null);
    ctx.setGeoLocationState("idle");
    ctx.locationResolvedRef.current = false;
    ctx.nearestCityResolvedRef.current = false;
  }

  async function handleLogout() {
    const liveAccessToken = ctx.accessToken;
    const liveRefreshToken = ctx.refreshToken;

    if (ctx.runtimeMode === "live" && (liveAccessToken || liveRefreshToken)) {
      try {
        await withFreshAccessToken((validAccessToken) => logoutAuthSession(validAccessToken), {
          accessToken: liveAccessToken,
          refreshToken: liveRefreshToken,
          clearOnFailure: false,
        });
      } catch (error) {
        console.error("Failed to logout on backend", error);
      }
    }

    await clearLiveSessionState();
  }

  return {
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
  };
}
