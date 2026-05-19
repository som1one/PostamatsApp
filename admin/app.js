const STORAGE_KEY = "postamats-admin-auth";
const API_ORIGIN_STORAGE_KEY = "postamatsApiOrigin";

function normalizeApiBaseOrigin(raw) {
  let o = String(raw || "")
    .trim()
    .replace(/\/+$/, "");
  if (!o) {
    return o;
  }
  o = o.replace(/\/admin\/?$/i, "");
  return o.replace(/\/+$/, "") || o;
}

(function applyApiOriginFromQuery() {
  try {
    const params = new URLSearchParams(window.location.search);
    const fromQuery = params.get("apiOrigin") || params.get("api");
    if (fromQuery && String(fromQuery).trim()) {
      sessionStorage.setItem(
        API_ORIGIN_STORAGE_KEY,
        normalizeApiBaseOrigin(String(fromQuery).trim()),
      );
    }
  } catch (_) {
    /* ignore */
  }
})();

const authScreen = document.getElementById("auth-screen");
const appShell = document.getElementById("app-shell");
const loginForm = document.getElementById("login-form");
const loginInput = document.getElementById("login-input");
const passwordInput = document.getElementById("password-input");
const submitButton = document.getElementById("submit-button");
const logoutButton = document.getElementById("logout-button");
const adminBadgeName = document.getElementById("admin-badge-name");
const navLinks = Array.from(document.querySelectorAll("[data-section]"));
const sectionPanels = Array.from(document.querySelectorAll("[data-section-panel]"));
const toastStack = document.getElementById("toast-stack");
const growthSummary = document.getElementById("growth-summary");
const growthChart = document.getElementById("growth-chart");
const usersMetric = document.getElementById("metric-users");
const citiesMetric = document.getElementById("metric-cities");
const lockersMetric = document.getElementById("metric-lockers");
const usersTotal = document.getElementById("users-total");
const usersTableBody = document.getElementById("users-table-body");
const usersEmpty = document.getElementById("users-empty");
const usersPrevPage = document.getElementById("users-prev-page");
const usersNextPage = document.getElementById("users-next-page");
const usersPageLabel = document.getElementById("users-page-label");
const usersSearchInput = document.getElementById("users-search-input");
const usersSearchButton = document.getElementById("users-search-button");
const usersFilterVerification = document.getElementById("users-filter-verification");
const usersFilterBlocked = document.getElementById("users-filter-blocked");
const userDetailModal = document.getElementById("user-detail-modal");
const userDetailBody = document.getElementById("user-detail-body");
const userDetailModalTitle = document.getElementById("user-detail-modal-title");
const lockerDetailModal = document.getElementById("locker-detail-modal");
const lockerDetailBody = document.getElementById("locker-detail-body");
const lockerDetailModalTitle = document.getElementById("locker-detail-modal-title");
const verificationTableBody = document.getElementById("verification-table-body");
const verificationEmpty = document.getElementById("verification-empty");
const verificationCount = document.getElementById("verification-count");
const citiesTableBody = document.getElementById("cities-table-body");
const citiesEmpty = document.getElementById("cities-empty");
const lockersTableBody = document.getElementById("lockers-table-body");
const lockersEmpty = document.getElementById("lockers-empty");
const rentalsTableBody = document.getElementById("rentals-table-body");
const rentalsEmpty = document.getElementById("rentals-empty");
const rentalsTotal = document.getElementById("rentals-total");
const rentalsFilterStatus = document.getElementById("rentals-filter-status");
const rentalsFilterCity = document.getElementById("rentals-filter-city");
const rentalsFilterLocker = document.getElementById("rentals-filter-locker");
const rentalsFilterOverdue = document.getElementById("rentals-filter-overdue");
const rentalDetailModal = document.getElementById("rental-detail-modal");
const rentalDetailBody = document.getElementById("rental-detail-body");
const rentalDetailModalTitle = document.getElementById("rental-detail-modal-title");
const productsTableBody = document.getElementById("products-table-body");
const productsEmpty = document.getElementById("products-empty");
const productsTotal = document.getElementById("products-total");
const productsSearchInput = document.getElementById("products-search-input");
const productsFilterActive = document.getElementById("products-filter-active");
const productsSearchButton = document.getElementById("products-search-button");
const productsPrevPage = document.getElementById("products-prev-page");
const productsNextPage = document.getElementById("products-next-page");
const productsPageLabel = document.getElementById("products-page-label");
const productNewButton = document.getElementById("product-new-button");
const productDetailModal = document.getElementById("product-detail-modal");
const productDetailBody = document.getElementById("product-detail-body");
const productDetailModalTitle = document.getElementById("product-detail-modal-title");
const auditTableBody = document.getElementById("audit-table-body");
const auditEmpty = document.getElementById("audit-empty");
const auditTotal = document.getElementById("audit-total");
const auditRefreshButton = document.getElementById("audit-refresh-button");
const auditPrevPage = document.getElementById("audit-prev-page");
const auditNextPage = document.getElementById("audit-next-page");
const auditPageLabel = document.getElementById("audit-page-label");
const modalBackdrop = document.getElementById("modal-backdrop");
const cityModal = document.getElementById("city-modal");
const lockerModal = document.getElementById("locker-modal");
const cityForm = document.getElementById("city-form");
const productCategoryModal = document.getElementById("product-category-modal");
const productCategoryForm = document.getElementById("product-category-form");
const cityDetailModal = document.getElementById("city-detail-modal");
const cityDetailBody = document.getElementById("city-detail-body");
const cityDetailModalTitle = document.getElementById("city-detail-modal-title");
const lockerForm = document.getElementById("locker-form");
const lockerCitySelect = document.getElementById("locker-city-select");
const lockerDiscoveryButton = document.getElementById("locker-discovery-button");
const lockerDiscoveryState = document.getElementById("locker-discovery-state");
const lockerCandidatesEmpty = document.getElementById("locker-candidates-empty");
const lockerCandidatesList = document.getElementById("locker-candidates-list");
const lockerNameInput = document.getElementById("locker-name-input");
const lockerAddressInput = document.getElementById("locker-address-input");
const lockerSubmitButton = document.getElementById("locker-submit-button");
const modalOpenButtons = Array.from(document.querySelectorAll("[data-open-modal]"));
const modalCloseButtons = Array.from(document.querySelectorAll("[data-close-modal]"));

const state = {
  accessToken: "",
  refreshToken: "",
  admin: null,
  activeSection: "home",
  isSubmitting: false,
  modalSubmitting: false,
  overview: null,
  users: [],
  usersMeta: { total: 0, page: 1, limit: 20 },
  usersPage: 1,
  usersListKey: "",
  usersSearchQuery: "",
  usersFilterVerification: "",
  usersFilterBlocked: "",
  userDetail: null,
  verificationQueue: [],
  cities: [],
  lockers: [],
  externalLockerCandidates: [],
  hasLoadedExternalLockerCandidates: false,
  selectedExternalLockerCandidate: null,
  lockerDetail: null,
  cityDetail: null,
  rentals: [],
  rentalsMeta: { total: 0 },
  rentalsFilterStatus: "",
  rentalsFilterCityId: "",
  rentalsFilterLockerId: "",
  rentalsFilterOverdue: false,
  rentalDetail: null,
  productCategories: [],
  products: [],
  productsMeta: { total: 0, page: 1, limit: 50 },
  productsListKey: "",
  productsSearch: "",
  productsFilterActive: "",
  productDetail: null,
  productDetailIsNew: false,
  auditEvents: [],
  auditMeta: { total: 0, page: 1, limit: 50 },
  inventory: {
    lockers: [],
    selectedLockerId: "",
    onlyFree: false,
    cells: [],
    products: [],
    productSearch: "",
    productOnlyActive: true,
    selectedProductId: "",
    activeCellId: "",
    isLoading: false,
    isPlacing: false,
    isServicing: false,
    productSearchTimer: null,
  },
};

let verificationPollTimerId = null;

function startVerificationPolling() {
  if (verificationPollTimerId != null) {
    return;
  }
  verificationPollTimerId = window.setInterval(() => {
    if (!state.accessToken || state.activeSection !== "verification") {
      return;
    }
    if (typeof document !== "undefined" && document.visibilityState === "hidden") {
      return;
    }
    loadVerificationQueue();
  }, 40000);
}

function stopVerificationPolling() {
  if (verificationPollTimerId == null) {
    return;
  }
  window.clearInterval(verificationPollTimerId);
  verificationPollTimerId = null;
}

function saveSession() {
  localStorage.setItem(
    STORAGE_KEY,
    JSON.stringify({
      accessToken: state.accessToken,
      refreshToken: state.refreshToken,
      admin: state.admin,
    }),
  );
}

function clearSession() {
  stopVerificationPolling();
  state.accessToken = "";
  state.refreshToken = "";
  state.admin = null;
  state.overview = null;
  state.users = [];
  state.usersMeta = { total: 0, page: 1, limit: 20 };
  state.usersPage = 1;
  state.usersListKey = "";
  state.usersSearchQuery = "";
  state.usersFilterVerification = "";
  state.usersFilterBlocked = "";
  state.userDetail = null;
  state.verificationQueue = [];
  state.cities = [];
  state.lockers = [];
  state.externalLockerCandidates = [];
  state.hasLoadedExternalLockerCandidates = false;
  state.selectedExternalLockerCandidate = null;
  state.lockerDetail = null;
  state.cityDetail = null;
  state.rentals = [];
  state.rentalsMeta = { total: 0 };
  state.rentalsFilterStatus = "";
  state.rentalsFilterCityId = "";
  state.rentalsFilterLockerId = "";
  state.rentalsFilterOverdue = false;
  state.rentalDetail = null;
  state.productCategories = [];
  state.products = [];
  state.productsMeta = { total: 0, page: 1, limit: 50 };
  state.productsListKey = "";
  state.productsSearch = "";
  state.productsFilterActive = "";
  state.productDetail = null;
  state.productDetailIsNew = false;
  state.auditEvents = [];
  state.auditMeta = { total: 0, page: 1, limit: 50 };
  localStorage.removeItem(STORAGE_KEY);
  if (usersSearchInput) {
    usersSearchInput.value = "";
  }
  if (usersFilterVerification) {
    usersFilterVerification.value = "";
  }
  if (usersFilterBlocked) {
    usersFilterBlocked.value = "";
  }
  if (rentalsFilterStatus) {
    rentalsFilterStatus.value = "";
  }
  if (rentalsFilterCity) {
    rentalsFilterCity.value = "";
  }
  if (rentalsFilterLocker) {
    rentalsFilterLocker.value = "";
  }
  if (rentalsFilterOverdue) {
    rentalsFilterOverdue.checked = false;
  }
  if (productsSearchInput) {
    productsSearchInput.value = "";
  }
  if (productsFilterActive) {
    productsFilterActive.value = "";
  }
}

function showToast(kind, message) {
  const toast = document.createElement("div");
  toast.className = `toast toast-${kind}`;
  toast.innerHTML = `
    <div>
      <div class="toast-title">${kind === "success" ? "Успешно" : "Ошибка"}</div>
      <div class="toast-message">${message}</div>
    </div>
  `;
  toastStack.appendChild(toast);

  window.setTimeout(() => {
    toast.style.opacity = "0";
    toast.style.transform = "translateY(-10px)";
  }, 3400);

  window.setTimeout(() => {
    toast.remove();
  }, 3800);
}

function formatNumber(value) {
  return new Intl.NumberFormat("ru-RU").format(value || 0);
}

function formatDate(value) {
  if (!value) {
    return "—";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "—";
  }
  return new Intl.DateTimeFormat("ru-RU", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
  }).format(date);
}

function formatDateTime(value) {
  if (!value) {
    return "—";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "—";
  }
  return new Intl.DateTimeFormat("ru-RU", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

function formatMoney(amount, currency) {
  const cur = currency || "RUB";
  try {
    return new Intl.NumberFormat("ru-RU", { style: "currency", currency: cur }).format(Number(amount) || 0);
  } catch (e) {
    return `${amount} ${cur}`;
  }
}

function escapeHtml(value) {
  if (value === null || value === undefined) {
    return "";
  }
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

/** target клика может быть текстовым узлом внутри кнопки — у него нет .closest() */
function clickTargetElement(event) {
  const t = event.target;
  if (t && t.nodeType === Node.TEXT_NODE) {
    return t.parentElement;
  }
  return t instanceof Element ? t : null;
}

function renderStatusPill(status) {
  const label = (status || "unknown").replaceAll("_", " ");
  return `<span class="status-pill status-${status}">${label}</span>`;
}

function setLoginLoading(isLoading) {
  state.isSubmitting = isLoading;
  submitButton.disabled = isLoading;
  submitButton.textContent = isLoading ? "Проверяю..." : "Войти";
}

function setModalSubmitting(isLoading, button) {
  state.modalSubmitting = isLoading;
  button.disabled = isLoading;
  if (button === lockerSubmitButton) {
    updateLockerSubmitAvailability();
  }
}

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

function parseUuidMultiline(value) {
  const raw = String(value || "").trim();
  if (!raw) {
    return [];
  }
  const parts = raw
    .split(/[\s,;]+/)
    .map((x) => x.trim())
    .filter(Boolean);
  const out = [];
  const seen = new Set();
  for (const token of parts) {
    if (!UUID_RE.test(token)) {
      throw new Error(`Некорректный UUID: ${token}`);
    }
    const normalized = token.toLowerCase();
    if (seen.has(normalized)) {
      continue;
    }
    seen.add(normalized);
    out.push(token);
  }
  return out;
}

function inferImageMimeType(file) {
  const fromType = String(file?.type || "").toLowerCase();
  if (fromType) {
    return fromType;
  }
  const name = String(file?.name || "").toLowerCase();
  if (name.endsWith(".jpg") || name.endsWith(".jpeg")) {
    return "image/jpeg";
  }
  if (name.endsWith(".png")) {
    return "image/png";
  }
  if (name.endsWith(".webp")) {
    return "image/webp";
  }
  return "";
}

function pickFiles({ multiple = false, accept = "image/*" } = {}) {
  return new Promise((resolve) => {
    const input = document.createElement("input");
    input.type = "file";
    input.accept = accept;
    input.multiple = Boolean(multiple);
    input.style.position = "fixed";
    input.style.left = "-9999px";
    document.body.appendChild(input);
    input.addEventListener(
      "change",
      () => {
        const files = Array.from(input.files || []);
        input.remove();
        resolve(files);
      },
      { once: true },
    );
    input.click();
  });
}

async function uploadAdminProductImageFile(file, kind) {
  const mimeType = inferImageMimeType(file);
  if (!["image/jpeg", "image/png", "image/webp"].includes(mimeType)) {
    throw new Error("Допустимы только JPG/PNG/WEBP.");
  }
  const presignPayload = await authorizedRequest("/api/admin/uploads/presign", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      fileName: file.name || "image",
      mimeType,
      fileSize: Number(file.size) || 0,
      kind,
    }),
  });
  const presignData = presignPayload?.data || {};
  if (!presignData.uploadUrl || !presignData.fileId) {
    throw new Error("Не удалось получить ссылку загрузки.");
  }
  const uploadResp = await fetch(presignData.uploadUrl, {
    method: presignData.method || "PUT",
    headers: presignData.headers || { "Content-Type": mimeType },
    body: file,
  });
  if (!uploadResp.ok) {
    throw new Error("Ошибка загрузки файла в хранилище.");
  }
  return String(presignData.fileId);
}

function _portNumber(loc) {
  if (loc.port) {
    return parseInt(loc.port, 10);
  }
  return loc.protocol === "https:" ? 443 : 80;
}

function _assumeApiOnSameHostPort8000(loc) {
  const { protocol, hostname } = loc;
  if (protocol === "file:" || !hostname) {
    return false;
  }
  const pn = _portNumber(loc);
  if (pn === 8000 || pn === 80 || pn === 443) {
    return false;
  }
  if (hostname === "localhost" || hostname === "127.0.0.1") {
    return true;
  }
  if (/^(192\.168\.|10\.|172\.(1[6-9]|2[0-9]|3[01])\.)/.test(hostname)) {
    return true;
  }
  return false;
}

function apiBaseOrigin() {
  if (typeof window.__POSTAMATS_API_ORIGIN__ === "string" && window.__POSTAMATS_API_ORIGIN__.trim()) {
    return normalizeApiBaseOrigin(window.__POSTAMATS_API_ORIGIN__);
  }
  try {
    const fromSession = sessionStorage.getItem(API_ORIGIN_STORAGE_KEY);
    if (fromSession && fromSession.trim()) {
      return normalizeApiBaseOrigin(fromSession.trim());
    }
    const fromLocal = localStorage.getItem(API_ORIGIN_STORAGE_KEY);
    if (fromLocal && fromLocal.trim()) {
      return normalizeApiBaseOrigin(fromLocal.trim());
    }
  } catch (_) {
    /* ignore */
  }
  const meta = document.querySelector('meta[name="postamats-api-origin"]');
  if (meta && meta.getAttribute("content") && meta.getAttribute("content").trim()) {
    return normalizeApiBaseOrigin(meta.getAttribute("content").trim());
  }
  const loc = window.location;
  const { protocol, hostname } = loc;
  if (protocol === "file:" || !hostname) {
    return normalizeApiBaseOrigin("http://127.0.0.1:8000");
  }
  if (_assumeApiOnSameHostPort8000(loc)) {
    return normalizeApiBaseOrigin(`${protocol}//${hostname}:8000`);
  }
  const p = loc.port ? `:${loc.port}` : "";
  return normalizeApiBaseOrigin(`${protocol}//${hostname}${p}`);
}

function apiUrl(path) {
  const normalized = path.startsWith("/") ? path : `/${path}`;
  return new URL(normalized, `${apiBaseOrigin()}/`).href;
}

async function parseError(response) {
  try {
    const payload = await response.json();
    if (payload && typeof payload.detail === "string") {
      return payload.detail;
    }
    if (Array.isArray(payload?.detail)) {
      const first = payload.detail[0];
      if (first && typeof first.msg === "string") {
        return first.msg;
      }
    }
  } catch (error) {
    console.error(error);
  }
  return "Не удалось выполнить запрос";
}

function resourcePathFromResolvedUrl(resolvedUrl) {
  try {
    const u = new URL(resolvedUrl);
    return u.pathname + u.search;
  } catch (_) {
    return resolvedUrl;
  }
}

function humanizeApiErrorMessage(message, resourcePath) {
  const m = (message || "").trim();
  const pathHint = resourcePath ? ` Путь: ${resourcePath}.` : "";
  if (/^not\s*found$/i.test(m)) {
    let base;
    try {
      base = apiBaseOrigin();
    } catch (_) {
      base = "(не удалось определить)";
    }
    let pageOrigin = "";
    try {
      pageOrigin = `${window.location.protocol}//${window.location.host}`;
    } catch (_) {
      pageOrigin = "";
    }
    const sameHost =
      pageOrigin && base && pageOrigin.replace(/\/$/, "") === String(base).replace(/\/$/, "");
    if (sameHost) {
      return `API вернуло 404.${pathHint} Частая причина — в настройках указан URL с «/admin» (нужен только корень API, например http://127.0.0.1:8000). Перезапустите backend с актуальным кодом, если маршрутов каталога ещё нет.`;
    }
    return `Запрос ушёл на ${base}, ответ «Not Found».${pathHint} Если админка с другого порта — ?apiOrigin=http://127.0.0.1:8000 или meta postamats-api-origin / window.__POSTAMATS_API_ORIGIN__ (без /admin в конце).`;
  }
  return message;
}

async function fetchJson(url, options = {}) {
  const resolvedUrl =
    url.startsWith("http://") || url.startsWith("https://") ? url : apiUrl(url);
  const response = await fetch(resolvedUrl, options);
  if (!response.ok) {
    throw new Error(
      humanizeApiErrorMessage(await parseError(response), resourcePathFromResolvedUrl(resolvedUrl)),
    );
  }
  if (response.status === 204) {
    return null;
  }
  return response.json();
}

async function fetchCurrentAdmin(accessToken) {
  const payload = await fetchJson("/api/admin/auth/me", {
    method: "GET",
    headers: {
      Authorization: `Bearer ${accessToken}`,
    },
  });
  return payload.data.admin;
}

async function refreshSession() {
  const payload = await fetchJson("/api/admin/auth/refresh", {
    method: "POST",
    headers: {
      Authorization: `Bearer ${state.refreshToken}`,
    },
  });
  state.accessToken = payload.data.accessToken;
  state.refreshToken = payload.data.refreshToken;
  state.admin = payload.data.admin;
  saveSession();
}

async function authorizedRequest(url, options = {}, allowRetry = true) {
  const resolvedUrl =
    url.startsWith("http://") || url.startsWith("https://") ? url : apiUrl(url);
  const headers = new Headers(options.headers || {});
  headers.set("Authorization", `Bearer ${state.accessToken}`);

  const response = await fetch(resolvedUrl, {
    ...options,
    headers,
  });

  if (response.status === 401 && allowRetry && state.refreshToken) {
    await refreshSession();
    return authorizedRequest(url, options, false);
  }

  if (!response.ok) {
    throw new Error(
      humanizeApiErrorMessage(await parseError(response), resourcePathFromResolvedUrl(resolvedUrl)),
    );
  }

  if (response.status === 204) {
    return null;
  }

  return response.json();
}

function showAuthScreen() {
  authScreen.classList.remove("hidden");
  appShell.classList.add("hidden");
  closeModal();
}

function showAppShell() {
  authScreen.classList.add("hidden");
  appShell.classList.remove("hidden");
  adminBadgeName.textContent = state.admin ? state.admin.name : "Admin";
}

function setActiveSection(sectionName) {
  state.activeSection = sectionName;
  navLinks.forEach((link) => {
    link.classList.toggle("is-active", link.dataset.section === sectionName);
  });
  sectionPanels.forEach((panel) => {
    panel.classList.toggle("hidden", panel.dataset.sectionPanel !== sectionName);
  });
}

function openModal(modalType) {
  modalBackdrop.classList.remove("hidden");
  cityModal.classList.add("hidden");
  lockerModal.classList.add("hidden");
  if (userDetailModal) {
    userDetailModal.classList.add("hidden");
  }
  if (lockerDetailModal) {
    lockerDetailModal.classList.add("hidden");
  }
  if (cityDetailModal) {
    cityDetailModal.classList.add("hidden");
  }
  if (rentalDetailModal) {
    rentalDetailModal.classList.add("hidden");
  }
  if (productDetailModal) {
    productDetailModal.classList.add("hidden");
  }
  if (productCategoryModal) {
    productCategoryModal.classList.add("hidden");
  }

  if (modalType === "city") {
    cityModal.classList.remove("hidden");
  }

  if (modalType === "locker") {
    populateLockerCitySelect();
    resetLockerCreateState({ preserveCity: true });
    lockerModal.classList.remove("hidden");
    if (lockerCitySelect.value) {
      loadExternalLockerCandidates();
    }
  }

  if (modalType === "product-category" && productCategoryModal) {
    productCategoryModal.classList.remove("hidden");
  }
}

function closeModal() {
  modalBackdrop.classList.add("hidden");
  cityModal.classList.add("hidden");
  lockerModal.classList.add("hidden");
  if (userDetailModal) {
    userDetailModal.classList.add("hidden");
  }
  if (lockerDetailModal) {
    lockerDetailModal.classList.add("hidden");
  }
  if (cityDetailModal) {
    cityDetailModal.classList.add("hidden");
  }
  if (rentalDetailModal) {
    rentalDetailModal.classList.add("hidden");
  }
  if (productDetailModal) {
    productDetailModal.classList.add("hidden");
  }
  if (productCategoryModal) {
    productCategoryModal.classList.add("hidden");
  }
  state.userDetail = null;
  state.lockerDetail = null;
  state.cityDetail = null;
  state.rentalDetail = null;
  state.productDetail = null;
  state.productDetailIsNew = false;
  resetLockerCreateState();
  if (userDetailBody) {
    userDetailBody.innerHTML = "";
  }
  if (lockerDetailBody) {
    lockerDetailBody.innerHTML = "";
  }
  if (cityDetailBody) {
    cityDetailBody.innerHTML = "";
  }
  if (rentalDetailBody) {
    rentalDetailBody.innerHTML = "";
  }
  if (productDetailBody) {
    productDetailBody.innerHTML = "";
  }
  const inventoryPlaceModalEl = document.getElementById("inventory-place-modal");
  const inventoryServiceModalEl = document.getElementById("inventory-service-modal");
  if (inventoryPlaceModalEl) {
    inventoryPlaceModalEl.classList.add("hidden");
  }
  if (inventoryServiceModalEl) {
    inventoryServiceModalEl.classList.add("hidden");
  }
  if (state.inventory) {
    state.inventory.activeCellId = "";
    state.inventory.selectedProductId = "";
  }
}

function populateLockerCitySelect() {
  const currentValue = lockerCitySelect.value;
  lockerCitySelect.innerHTML = "";

  if (!state.cities.length) {
    const option = document.createElement("option");
    option.value = "";
    option.textContent = "Сначала добавьте город";
    lockerCitySelect.appendChild(option);
    lockerSubmitButton.disabled = true;
    return;
  }

  state.cities.forEach((city) => {
    const option = document.createElement("option");
    option.value = city.id;
    option.textContent = city.name;
    if (String(city.id) === String(currentValue)) {
      option.selected = true;
    }
    lockerCitySelect.appendChild(option);
  });
  if (!lockerCitySelect.value && state.cities[0]) {
    lockerCitySelect.value = state.cities[0].id;
  }
  updateLockerSubmitAvailability();
}

function setLockerDiscoveryLoading(isLoading) {
  if (!lockerDiscoveryButton) {
    return;
  }
  lockerDiscoveryButton.disabled = isLoading;
  lockerDiscoveryButton.textContent = isLoading ? "Ищем..." : "Найти постаматы";
}

function setLockerDiscoveryState(message = "") {
  if (!lockerDiscoveryState) {
    return;
  }
  const text = String(message || "").trim();
  lockerDiscoveryState.textContent = text;
  lockerDiscoveryState.classList.toggle("hidden", !text);
}

function updateLockerSubmitAvailability() {
  if (!lockerSubmitButton) {
    return;
  }
  lockerSubmitButton.disabled = Boolean(
    state.modalSubmitting || !state.cities.length || !state.selectedExternalLockerCandidate,
  );
}

function resetLockerCreateState({ preserveCity = false } = {}) {
  state.externalLockerCandidates = [];
  state.hasLoadedExternalLockerCandidates = false;
  state.selectedExternalLockerCandidate = null;

  if (lockerCandidatesList) {
    lockerCandidatesList.innerHTML = "";
  }
  if (lockerCandidatesEmpty) {
    lockerCandidatesEmpty.classList.remove("hidden");
    lockerCandidatesEmpty.textContent = lockerCitySelect.value
      ? "Нажмите «Найти постаматы», чтобы загрузить доступные точки."
      : "Сначала выберите город и загрузите список точек.";
  }
  setLockerDiscoveryState("");

  if (lockerForm && !preserveCity) {
    lockerForm.reset();
  }

  if (lockerNameInput) {
    lockerNameInput.value = "";
  }
  if (lockerAddressInput) {
    lockerAddressInput.value = "";
  }
  if (lockerForm?.elements?.status) {
    lockerForm.elements.status.value = "online";
  }

  updateLockerSubmitAvailability();
}

function selectExternalLockerCandidate(candidateId) {
  const candidate = state.externalLockerCandidates.find(
    (item) => String(item.externalLockerId) === String(candidateId),
  );
  state.selectedExternalLockerCandidate = candidate || null;

  if (candidate) {
    lockerNameInput.value = candidate.name || "";
    lockerAddressInput.value = candidate.address || "";
    setLockerDiscoveryState(
      `Выбран постамат ${candidate.name}. При необходимости поменяйте название и нажмите «Создать постамат».`,
    );
  } else {
    lockerNameInput.value = "";
    lockerAddressInput.value = "";
  }

  renderLockerCandidates();
  updateLockerSubmitAvailability();
}

function renderLockerCandidates() {
  if (!lockerCandidatesList || !lockerCandidatesEmpty) {
    return;
  }

  lockerCandidatesList.innerHTML = "";

  if (!lockerCitySelect.value) {
    lockerCandidatesEmpty.classList.remove("hidden");
    lockerCandidatesEmpty.textContent = "Сначала выберите город и загрузите список точек.";
    updateLockerSubmitAvailability();
    return;
  }

  if (!state.hasLoadedExternalLockerCandidates) {
    lockerCandidatesEmpty.classList.remove("hidden");
    lockerCandidatesEmpty.textContent = "Нажмите «Найти постаматы», чтобы загрузить доступные точки.";
    updateLockerSubmitAvailability();
    return;
  }

  if (!state.externalLockerCandidates.length) {
    lockerCandidatesEmpty.classList.remove("hidden");
    lockerCandidatesEmpty.textContent = "Новых постаматов для этого города не найдено.";
    updateLockerSubmitAvailability();
    return;
  }

  lockerCandidatesEmpty.classList.add("hidden");
  lockerCandidatesList.innerHTML = state.externalLockerCandidates
    .map((candidate) => {
      const isSelected =
        state.selectedExternalLockerCandidate &&
        String(state.selectedExternalLockerCandidate.externalLockerId) ===
          String(candidate.externalLockerId);
      return `
        <label class="locker-candidate-card${isSelected ? " is-selected" : ""}">
          <div class="locker-candidate-top">
            <div>
              <p class="locker-candidate-title">${escapeHtml(candidate.name || "Постамат")}</p>
              <p class="locker-candidate-address">${escapeHtml(candidate.address || "Адрес не указан")}</p>
            </div>
            <input
              class="locker-candidate-radio"
              type="radio"
              name="locker-candidate"
              value="${escapeHtml(candidate.externalLockerId)}"
              ${isSelected ? "checked" : ""}
            />
          </div>
          <p class="locker-candidate-meta">
            ${escapeHtml(candidate.cityName || "Без города")} · ${escapeHtml(candidate.provider || "esi")} · ID ${escapeHtml(candidate.externalLockerId)}
          </p>
        </label>
      `;
    })
    .join("");

  updateLockerSubmitAvailability();
}

async function loadExternalLockerCandidates() {
  const cityId = String(lockerCitySelect?.value || "").trim();
  if (!cityId) {
    resetLockerCreateState({ preserveCity: true });
    showToast("error", "Сначала выберите город.");
    return;
  }

  state.externalLockerCandidates = [];
  state.hasLoadedExternalLockerCandidates = false;
  state.selectedExternalLockerCandidate = null;
  if (lockerNameInput) {
    lockerNameInput.value = "";
  }
  if (lockerAddressInput) {
    lockerAddressInput.value = "";
  }
  renderLockerCandidates();
  setLockerDiscoveryLoading(true);
  setLockerDiscoveryState("Запрашиваем постаматы по API...");

  try {
    const payload = await authorizedRequest(
      `/api/admin/lockers/external-candidates?cityId=${encodeURIComponent(cityId)}`,
    );
    state.externalLockerCandidates = payload.data.items || [];
    state.hasLoadedExternalLockerCandidates = true;
    renderLockerCandidates();

    if (state.externalLockerCandidates.length) {
      setLockerDiscoveryState(
        `Найдено ${formatNumber(state.externalLockerCandidates.length)} новых постаматов. Выберите нужный вариант.`,
      );
      selectExternalLockerCandidate(state.externalLockerCandidates[0].externalLockerId);
    } else {
      setLockerDiscoveryState("API не вернул новых постаматов для выбранного города.");
    }
  } catch (error) {
    console.error(error);
    state.externalLockerCandidates = [];
    state.hasLoadedExternalLockerCandidates = true;
    state.selectedExternalLockerCandidate = null;
    renderLockerCandidates();
    setLockerDiscoveryState("Не удалось получить список постаматов.");
    showToast("error", error.message || "Не удалось загрузить постаматы");
  } finally {
    setLockerDiscoveryLoading(false);
    updateLockerSubmitAvailability();
  }
}

function renderOverview() {
  const metrics = state.overview?.metrics || {
    users: 0,
    cities: 0,
    lockers: 0,
    newUsersLast14Days: 0,
  };
  const series = state.overview?.userGrowth || [];

  usersMetric.textContent = formatNumber(metrics.users);
  citiesMetric.textContent = formatNumber(metrics.cities);
  lockersMetric.textContent = formatNumber(metrics.lockers);
  growthSummary.textContent = `${formatNumber(metrics.newUsersLast14Days)} новых пользователей`;

  if (!series.length) {
    growthChart.innerHTML = `<div class="empty-state">Нет данных для диаграммы.</div>`;
    return;
  }

  const maxCount = Math.max(...series.map((item) => item.count), 1);
  growthChart.innerHTML = series
    .map((item) => {
      const height = Math.max((item.count / maxCount) * 100, item.count > 0 ? 12 : 4);
      return `
        <div class="chart-column">
          <span class="chart-value">${item.count}</span>
          <div class="chart-bar-shell">
            <div class="chart-bar-fill" style="height: ${height}%"></div>
          </div>
          <span class="chart-label">${item.label}</span>
        </div>
      `;
    })
    .join("");
}

function syncUsersPageForFilters() {
  const ctx = `${state.usersSearchQuery}|${state.usersFilterVerification}|${state.usersFilterBlocked}`;
  if (ctx !== state.usersListKey) {
    state.usersPage = 1;
    state.usersListKey = ctx;
  }
}

function syncProductsPageForFilters() {
  const ctx = `${state.productsSearch}|${state.productsFilterActive}`;
  if (ctx !== state.productsListKey) {
    state.productsMeta.page = 1;
    state.productsListKey = ctx;
  }
}

function buildAdminUsersPath() {
  const params = new URLSearchParams();
  params.set("page", String(state.usersPage || 1));
  const q = state.usersSearchQuery.trim();
  if (q) {
    params.set("q", q);
    params.set("limit", "50");
  } else {
    params.set("limit", "20");
  }
  if (state.usersFilterVerification) {
    params.set("verificationStatus", state.usersFilterVerification);
  }
  if (state.usersFilterBlocked === "true" || state.usersFilterBlocked === "false") {
    params.set("isBlocked", state.usersFilterBlocked);
  }
  return `/api/admin/users?${params.toString()}`;
}

function usersHasActiveFilters() {
  return Boolean(
    state.usersSearchQuery.trim() ||
      state.usersFilterVerification ||
      state.usersFilterBlocked,
  );
}

function renderUsers() {
  usersTotal.textContent = `${formatNumber(state.usersMeta.total || 0)} пользователей`;
  usersTableBody.innerHTML = "";

  if (!state.users.length) {
    usersEmpty.classList.remove("hidden");
    usersEmpty.textContent = usersHasActiveFilters()
      ? "По запросу или фильтрам ничего не найдено."
      : "Пока нет пользователей.";
  } else {
    usersEmpty.classList.add("hidden");
    usersTableBody.innerHTML = state.users
      .map(
        (user) => `
        <tr>
          <td>
            <strong>${escapeHtml(user.name)}</strong>
            <div class="section-meta">${escapeHtml(user.email || "Без email")}</div>
          </td>
          <td>${escapeHtml(user.phone)}</td>
          <td>${escapeHtml(user.preferredCityName || "—")}</td>
          <td>${renderStatusPill(user.verificationStatus)}</td>
          <td>${formatDate(user.createdAt)}</td>
          <td class="data-table-col-actions">
            <button type="button" class="ghost-button table-inline-button" data-open-user="${escapeHtml(user.id)}">
              Открыть
            </button>
          </td>
        </tr>
      `,
      )
      .join("");
  }

  const total = state.usersMeta.total ?? state.users.length;
  const page = state.usersMeta.page ?? state.usersPage ?? 1;
  const limit = state.usersMeta.limit ?? 20;
  if (usersPageLabel) {
    const pages = Math.max(1, Math.ceil(total / limit) || 1);
    usersPageLabel.textContent = `Стр. ${page} из ${pages}`;
  }
  if (usersPrevPage) {
    usersPrevPage.disabled = page <= 1;
  }
  if (usersNextPage) {
    usersNextPage.disabled = page * limit >= total;
  }
}

function renderVerificationQueue() {
  if (!verificationTableBody || !verificationEmpty || !verificationCount) {
    return;
  }
  verificationCount.textContent = `${formatNumber(state.verificationQueue.length)} заявок`;
  verificationTableBody.innerHTML = "";

  if (!state.verificationQueue.length) {
    verificationEmpty.classList.remove("hidden");
    return;
  }

  verificationEmpty.classList.add("hidden");
  verificationTableBody.innerHTML = state.verificationQueue
    .map(
      (item) => `
        <tr>
          <td>
            <strong>${escapeHtml(item.userName)}</strong>
            <div class="section-meta">${escapeHtml(item.userEmail || "Без email")}</div>
          </td>
          <td>${escapeHtml(item.userPhone)}</td>
          <td>${escapeHtml(item.documentType)} · ${escapeHtml(item.documentNumber)}</td>
          <td>${formatDateTime(item.createdAt)}</td>
          <td class="data-table-col-actions">
            <button type="button" class="ghost-button table-inline-button" data-open-user="${item.userId}">
              Карточка
            </button>
          </td>
        </tr>
      `,
    )
    .join("");
}

function docLinkRow(label, url) {
  if (url) {
    const safe = escapeHtml(url);
    return `<a class="doc-link" href="${safe}" target="_blank" rel="noopener noreferrer">${label}</a>`;
  }
  return `<span class="muted-inline">нет публичной ссылки</span>`;
}

function renderUserDetailModal() {
  if (!userDetailBody || !userDetailModalTitle) {
    return;
  }
  const d = state.userDetail;
  if (!d || !d.user) {
    userDetailBody.innerHTML = `<div class="empty-state">Нет данных.</div>`;
    return;
  }

  const u = d.user;
  const v = d.verification;
  userDetailModalTitle.textContent = u.name || "Пользователь";

  const canModerate = v && v.status === "pending_review";
  const moderationBlock = canModerate
    ? `
      <div class="detail-block">
        <h4 class="detail-block-title">Решение по верификации</h4>
        <div class="user-detail-action-row">
          <button type="button" class="primary-button" data-user-action="approve">Подтвердить</button>
        </div>
        <label class="field">
          <span>Причина отклонения</span>
          <textarea id="user-reject-reason" rows="3" placeholder="Обязательно при отклонении"></textarea>
        </label>
        <button type="button" class="table-danger-button" data-user-action="reject">Отклонить верификацию</button>
      </div>
    `
    : v
      ? `
      <div class="detail-block">
        <h4 class="detail-block-title">Заявка верификации</h4>
        <p>Статус: ${renderStatusPill(v.status)}</p>
        ${v.rejectReason ? `<p class="reject-reason">Причина: ${escapeHtml(v.rejectReason)}</p>` : ""}
      </div>
    `
      : `<div class="detail-block"><p class="muted-inline">Заявок верификации нет.</p></div>`;

  const verificationDocs =
    v
      ? `
    <div class="detail-block">
      <h4 class="detail-block-title">Документы</h4>
      <p class="doc-meta">${escapeHtml(v.documentType)} · ${escapeHtml(v.documentNumber)}</p>
      <div class="doc-links">
        ${docLinkRow("Лицевая сторона", v.frontUrl)}
        ${docLinkRow("Оборот", v.backUrl)}
        ${docLinkRow("Селфи", v.selfieUrl)}
      </div>
    </div>
  `
      : "";

  const blockBlock = u.isBlocked
    ? `<p class="muted-inline">Заблокирован${u.blockedReason ? `: ${escapeHtml(u.blockedReason)}` : ""}</p>`
    : `
    <div class="detail-block">
      <h4 class="detail-block-title">Блокировка</h4>
      <label class="field">
        <span>Причина (необязательно)</span>
        <input id="user-block-reason" type="text" placeholder="Кратко, зачем блокируете" />
      </label>
      <button type="button" class="table-danger-button" data-user-action="block">Заблокировать пользователя</button>
    </div>
  `;

  const rentalsRows = (d.rentals || [])
    .map(
      (r) => `
      <tr>
        <td><code>${escapeHtml(r.id)}</code></td>
        <td>${renderStatusPill(r.status)}</td>
        <td>${formatDateTime(r.createdAt)}</td>
        <td>${formatDateTime(r.plannedEndAt)}</td>
      </tr>
    `,
    )
    .join("");

  const paymentsRows = (d.payments || [])
    .map(
      (p) => `
      <tr>
        <td><code>${escapeHtml(p.id)}</code></td>
        <td>${renderStatusPill(p.status)}</td>
        <td>${escapeHtml(p.type)}</td>
        <td>${formatMoney(p.amount, p.currency)}</td>
        <td>${formatDateTime(p.createdAt)}</td>
      </tr>
    `,
    )
    .join("");

  userDetailBody.innerHTML = `
    <div class="user-detail-grid">
      <div class="detail-block">
        <h4 class="detail-block-title">Профиль</h4>
        <ul class="detail-list">
          <li><span>Телефон</span><strong>${escapeHtml(u.phone)}</strong></li>
          <li><span>Email</span><strong>${escapeHtml(u.email || "—")}</strong></li>
          <li><span>Город</span><strong>${escapeHtml(u.preferredCityName || "—")}</strong></li>
          <li><span>Дата рождения</span><strong>${escapeHtml(u.birthDate || "—")}</strong></li>
          <li><span>Верификация (профиль)</span><strong>${renderStatusPill(u.verificationStatus)}</strong></li>
          <li><span>Регистрация</span><strong>${formatDateTime(u.createdAt)}</strong></li>
        </ul>
      </div>
      ${verificationDocs}
      ${moderationBlock}
      ${blockBlock}
    </div>
    <div class="detail-block">
      <h4 class="detail-block-title">Последние аренды</h4>
      <div class="table-scroll">
        <table class="data-table data-table-compact">
          <thead>
            <tr><th>ID</th><th>Статус</th><th>Создана</th><th>План окончания</th></tr>
          </thead>
          <tbody>${rentalsRows || `<tr><td colspan="4" class="muted-inline">Нет аренд</td></tr>`}</tbody>
        </table>
      </div>
    </div>
    <div class="detail-block">
      <h4 class="detail-block-title">Последние платежи</h4>
      <div class="table-scroll">
        <table class="data-table data-table-compact">
          <thead>
            <tr><th>ID</th><th>Статус</th><th>Тип</th><th>Сумма</th><th>Создан</th></tr>
          </thead>
          <tbody>${paymentsRows || `<tr><td colspan="5" class="muted-inline">Нет платежей</td></tr>`}</tbody>
        </table>
      </div>
    </div>
  `;
}

function openUserDetailModal() {
  if (!userDetailModal) {
    return;
  }
  modalBackdrop.classList.remove("hidden");
  cityModal.classList.add("hidden");
  lockerModal.classList.add("hidden");
  if (lockerDetailModal) {
    lockerDetailModal.classList.add("hidden");
  }
  if (cityDetailModal) {
    cityDetailModal.classList.add("hidden");
  }
  if (rentalDetailModal) {
    rentalDetailModal.classList.add("hidden");
  }
  userDetailModal.classList.remove("hidden");
}

function openCityDetailModal() {
  if (!cityDetailModal) {
    return;
  }
  modalBackdrop.classList.remove("hidden");
  cityModal.classList.add("hidden");
  lockerModal.classList.add("hidden");
  if (userDetailModal) {
    userDetailModal.classList.add("hidden");
  }
  if (lockerDetailModal) {
    lockerDetailModal.classList.add("hidden");
  }
  if (rentalDetailModal) {
    rentalDetailModal.classList.add("hidden");
  }
  cityDetailModal.classList.remove("hidden");
}

function openLockerDetailModal() {
  if (!lockerDetailModal) {
    return;
  }
  modalBackdrop.classList.remove("hidden");
  cityModal.classList.add("hidden");
  lockerModal.classList.add("hidden");
  if (userDetailModal) {
    userDetailModal.classList.add("hidden");
  }
  if (cityDetailModal) {
    cityDetailModal.classList.add("hidden");
  }
  if (rentalDetailModal) {
    rentalDetailModal.classList.add("hidden");
  }
  lockerDetailModal.classList.remove("hidden");
}

function openRentalDetailModal() {
  if (!rentalDetailModal) {
    return;
  }
  modalBackdrop.classList.remove("hidden");
  cityModal.classList.add("hidden");
  lockerModal.classList.add("hidden");
  if (userDetailModal) {
    userDetailModal.classList.add("hidden");
  }
  if (lockerDetailModal) {
    lockerDetailModal.classList.add("hidden");
  }
  if (cityDetailModal) {
    cityDetailModal.classList.add("hidden");
  }
  rentalDetailModal.classList.remove("hidden");
}

async function openUserDetail(userId) {
  const raw = String(userId ?? "").trim();
  if (!raw || !UUID_RE.test(raw)) {
    showToast("error", "Некорректный ID пользователя. Обновите список и попробуйте снова.");
    return;
  }
  openUserDetailModal();
  if (userDetailBody) {
    userDetailBody.innerHTML = `<div class="empty-state">Загрузка…</div>`;
  }
  try {
    const payload = await authorizedRequest(`/api/admin/users/${encodeURIComponent(raw)}`);
    state.userDetail = payload.data;
    renderUserDetailModal();
  } catch (error) {
    console.error(error);
    showToast("error", error.message || "Не удалось загрузить карточку");
    closeModal();
  }
}

async function refreshUserDetail(userId) {
  const raw = String(userId ?? "").trim();
  if (!raw || !UUID_RE.test(raw)) {
    return;
  }
  try {
    const payload = await authorizedRequest(`/api/admin/users/${encodeURIComponent(raw)}`);
    state.userDetail = payload.data;
    renderUserDetailModal();
  } catch (error) {
    console.error(error);
  }
}

async function reloadUserContext() {
  await loadUsersOnly();
  if (state.activeSection === "verification") {
    await loadVerificationQueue();
  }
  const uid = state.userDetail?.user?.id;
  if (uid && userDetailModal && !userDetailModal.classList.contains("hidden")) {
    await refreshUserDetail(uid);
  }
}

async function loadVerificationQueue() {
  if (!verificationTableBody) {
    return;
  }
  try {
    const payload = await authorizedRequest("/api/admin/verification-queue");
    state.verificationQueue = payload.data.items || [];
    renderVerificationQueue();
  } catch (error) {
    console.error(error);
    showToast("error", error.message || "Не удалось загрузить очередь верификации");
  }
}

let userDetailActionBusy = false;

async function handleUserDetailClick(event) {
  const root = clickTargetElement(event);
  if (!root) {
    return;
  }
  const btn = root.closest("[data-user-action]");
  if (!btn || userDetailActionBusy) {
    return;
  }
  const action = btn.dataset.userAction;
  const userId = state.userDetail?.user?.id;
  if (!action || !userId) {
    return;
  }

  userDetailActionBusy = true;
  btn.disabled = true;
  try {
    const safeId = encodeURIComponent(userId);
    if (action === "approve") {
      await authorizedRequest(`/api/admin/users/${safeId}/approve-verification`, { method: "POST" });
      showToast("success", "Верификация подтверждена.");
      await reloadUserContext();
    } else if (action === "reject") {
      const reasonEl = document.getElementById("user-reject-reason");
      const reason = (reasonEl && reasonEl.value ? reasonEl.value : "").trim();
      if (!reason) {
        showToast("error", "Укажите причину отклонения.");
        return;
      }
      await authorizedRequest(`/api/admin/users/${safeId}/reject-verification`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ reason }),
      });
      showToast("success", "Верификация отклонена.");
      await reloadUserContext();
    } else if (action === "block") {
      if (!window.confirm("Заблокировать пользователя? Он не сможет пользоваться сервисом.")) {
        return;
      }
      const reasonEl = document.getElementById("user-block-reason");
      const reason = (reasonEl && reasonEl.value ? reasonEl.value : "").trim();
      await authorizedRequest(`/api/admin/users/${safeId}/block`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(reason ? { reason } : {}),
      });
      showToast("success", "Пользователь заблокирован.");
      await reloadUserContext();
    }
  } catch (error) {
    console.error(error);
    showToast("error", error.message || "Действие не выполнено");
  } finally {
    userDetailActionBusy = false;
    btn.disabled = false;
  }
}

function handleOpenUserFromTable(event) {
  const root = clickTargetElement(event);
  if (!root) {
    return;
  }
  const button = root.closest("[data-open-user]");
  if (!button) {
    return;
  }
  const userId = (button.getAttribute("data-open-user") || button.dataset.openUser || "").trim();
  openUserDetail(userId);
}

function syncUserFiltersFromDom() {
  if (usersFilterVerification) {
    state.usersFilterVerification = usersFilterVerification.value;
  }
  if (usersFilterBlocked) {
    state.usersFilterBlocked = usersFilterBlocked.value;
  }
}

function renderCities() {
  citiesTableBody.innerHTML = "";

  if (!state.cities.length) {
    citiesEmpty.classList.remove("hidden");
    return;
  }

  citiesEmpty.classList.add("hidden");
  citiesTableBody.innerHTML = state.cities
    .map(
      (city) => `
        <tr>
          <td><strong>${escapeHtml(city.name)}</strong></td>
          <td>${escapeHtml(city.slug)}</td>
          <td>${escapeHtml(city.timezone)}</td>
          <td>${renderStatusPill(city.isActive ? "active" : "offline")}</td>
          <td>${formatNumber(city.lockerCount ?? 0)}</td>
          <td class="data-table-col-actions">
            <button type="button" class="ghost-button table-inline-button" data-open-city="${escapeHtml(city.id)}">
              Открыть
            </button>
            <button
              type="button"
              class="table-danger-button table-inline-button"
              data-delete-city="${escapeHtml(city.id)}"
            >Удалить</button>
          </td>
        </tr>
      `,
    )
    .join("");
}

function renderCityDetailModal() {
  if (!cityDetailBody || !cityDetailModalTitle) {
    return;
  }
  const d = state.cityDetail;
  if (!d || !d.city) {
    cityDetailBody.innerHTML = `<div class="empty-state">Нет данных.</div>`;
    return;
  }
  const c = d.city;
  cityDetailModalTitle.textContent = c.name || "Город";

  const lockersRows = (d.lockers || [])
    .map(
      (loc) => `
      <tr>
        <td><strong>${escapeHtml(loc.name)}</strong></td>
        <td>${escapeHtml(loc.address)}</td>
        <td>${renderStatusPill(loc.status)}</td>
        <td class="data-table-col-actions">
          <button type="button" class="ghost-button table-inline-button" data-city-open-locker="${escapeHtml(loc.id)}">
            Постамат
          </button>
        </td>
      </tr>`,
    )
    .join("");

  cityDetailBody.innerHTML = `
    <div class="user-detail-grid">
      <div class="detail-block">
        <h4 class="detail-block-title">Сводка</h4>
        <ul class="detail-list">
          <li><span>Постаматов</span><strong>${formatNumber(c.lockerCount ?? 0)}</strong></li>
          <li><span>Пользователей с этим городом в профиле</span><strong>${formatNumber(c.usersWithPreferredCityCount ?? 0)}</strong></li>
          <li><span>Создан</span><strong>${formatDateTime(c.createdAt)}</strong></li>
          <li><span>Обновлён</span><strong>${formatDateTime(c.updatedAt)}</strong></li>
        </ul>
      </div>
      <div class="detail-block">
        <h4 class="detail-block-title">Редактирование</h4>
        <label class="field"><span>Название</span><input id="city-edit-name" type="text" value="${escapeHtml(c.name)}" /></label>
        <label class="field"><span>Slug</span><input id="city-edit-slug" type="text" value="${escapeHtml(c.slug)}" /></label>
        <label class="field"><span>Часовой пояс</span><input id="city-edit-timezone" type="text" value="${escapeHtml(c.timezone)}" /></label>
        <label class="field"><span>Порядок сортировки</span><input id="city-edit-sort" type="number" value="${Number(c.sortOrder) || 0}" /></label>
        <label class="checkbox-field">
          <input id="city-edit-active" type="checkbox" ${c.isActive ? "checked" : ""} />
          <span>Активный город</span>
        </label>
        <div class="user-detail-action-row">
          <button type="button" class="primary-button" data-city-action="save">Сохранить</button>
        </div>
      </div>
      <div class="detail-block">
        <h4 class="detail-block-title">Постаматы в городе</h4>
        <div class="table-scroll">
          <table class="data-table data-table-compact">
            <thead><tr><th>Название</th><th>Адрес</th><th>Статус</th><th class="data-table-col-actions">Действия</th></tr></thead>
            <tbody>${
              lockersRows ||
              `<tr><td colspan="4" class="muted-inline">Нет постаматов — город можно удалить</td></tr>`
            }</tbody>
          </table>
        </div>
        <p class="muted-inline city-delete-hint">Удаление возможно только если постаматов нет (сначала перенесите или удалите точки в разделе «Постаматы»).</p>
        <div class="user-detail-action-row">
          <button type="button" class="table-danger-button" data-city-action="delete">Удалить город</button>
        </div>
      </div>
    </div>
  `;
}

async function openCityDetail(cityId) {
  const raw = String(cityId ?? "").trim();
  if (!raw || !UUID_RE.test(raw)) {
    showToast("error", "Некорректный ID города.");
    return;
  }
  openCityDetailModal();
  if (cityDetailBody) {
    cityDetailBody.innerHTML = `<div class="empty-state">Загрузка…</div>`;
  }
  try {
    const payload = await authorizedRequest(`/api/admin/cities/${encodeURIComponent(raw)}`);
    state.cityDetail = payload.data;
    renderCityDetailModal();
  } catch (error) {
    console.error(error);
    showToast("error", error.message || "Не удалось загрузить город");
    closeModal();
  }
}

async function refreshCityDetail(cityId) {
  const raw = String(cityId ?? "").trim();
  if (!raw || !UUID_RE.test(raw)) {
    return;
  }
  try {
    const payload = await authorizedRequest(`/api/admin/cities/${encodeURIComponent(raw)}`);
    state.cityDetail = payload.data;
    renderCityDetailModal();
  } catch (error) {
    console.error(error);
  }
}

async function loadCitiesOnly() {
  try {
    const citiesPayload = await authorizedRequest("/api/admin/cities");
    state.cities = citiesPayload.data.cities;
    renderCities();
  } catch (error) {
    console.error(error);
    showToast("error", error.message || "Не удалось обновить города");
  }
}

let cityDetailBusy = false;

async function handleCityDetailClick(event) {
  const root = clickTargetElement(event);
  if (!root) {
    return;
  }

  const lockerJump = root.closest("[data-city-open-locker]");
  if (lockerJump && !cityDetailBusy) {
    const lid = (lockerJump.getAttribute("data-city-open-locker") || "").trim();
    if (!lid) {
      return;
    }
    cityDetailBusy = true;
    try {
      if (cityDetailModal) {
        cityDetailModal.classList.add("hidden");
      }
      state.cityDetail = null;
      if (cityDetailBody) {
        cityDetailBody.innerHTML = "";
      }
      await openLockerDetail(lid);
    } finally {
      cityDetailBusy = false;
    }
    return;
  }

  const btn = root.closest("[data-city-action]");
  if (!btn || cityDetailBusy) {
    return;
  }
  const action = btn.dataset.cityAction;
  const cityId = state.cityDetail?.city?.id;
  if (!action || !cityId) {
    return;
  }
  const safeId = encodeURIComponent(cityId);

  cityDetailBusy = true;
  btn.disabled = true;
  try {
    if (action === "save") {
      const body = {
        name: String(document.getElementById("city-edit-name")?.value || "").trim(),
        slug: String(document.getElementById("city-edit-slug")?.value || "").trim(),
        timezone: String(document.getElementById("city-edit-timezone")?.value || "").trim(),
        sortOrder: Number(document.getElementById("city-edit-sort")?.value || 0),
        isActive: Boolean(document.getElementById("city-edit-active")?.checked),
      };
      await authorizedRequest(`/api/admin/cities/${safeId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      showToast("success", "Город сохранён.");
      await loadAdminData();
      await refreshCityDetail(cityId);
      return;
    }
    if (action === "delete") {
      const lockers = state.cityDetail?.city?.lockerCount ?? 0;
      if (lockers > 0) {
        showToast("error", "Сначала удалите или перенесите постаматы, привязанные к этому городу.");
        return;
      }
      if (!window.confirm("Удалить город безвозвратно?")) {
        return;
      }
      await authorizedRequest(`/api/admin/cities/${safeId}/delete`, { method: "POST" });
      showToast("success", "Город удалён.");
      closeModal();
      await loadAdminData();
    }
  } catch (error) {
    console.error(error);
    showToast("error", error.message || "Действие не выполнено");
  } finally {
    cityDetailBusy = false;
    btn.disabled = false;
  }
}

function renderLockers() {
  lockersTableBody.innerHTML = "";

  if (!state.lockers.length) {
    lockersEmpty.classList.remove("hidden");
    return;
  }

  lockersEmpty.classList.add("hidden");
  lockersTableBody.innerHTML = state.lockers
    .map(
      (locker) => `
        <tr>
          <td><strong>${escapeHtml(locker.name)}</strong></td>
          <td>${escapeHtml(locker.cityName || "—")}</td>
          <td>${escapeHtml(locker.address)}</td>
          <td>${renderStatusPill(locker.status)}</td>
          <td>${formatNumber(locker.availableUnitCount || 0)}</td>
          <td class="data-table-col-actions">
            <button type="button" class="ghost-button table-inline-button" data-open-locker="${escapeHtml(locker.id)}">
              Настроить
            </button>
          </td>
        </tr>
      `,
    )
    .join("");
}

const LOCKER_CELL_STATUSES = ["vacant", "occupied", "reserved", "opened", "fault", "disabled"];

function lockerCellStatusOptions(selected) {
  return LOCKER_CELL_STATUSES.map(
    (s) => `<option value="${s}"${s === selected ? " selected" : ""}>${s}</option>`,
  ).join("");
}

function parseWorkingHoursInput(text) {
  const raw = String(text || "").trim();
  if (!raw) {
    return null;
  }
  try {
    return JSON.parse(raw);
  } catch (error) {
    throw new Error("Часы работы: невалидный JSON");
  }
}

function parseOptionalCoord(value) {
  const t = String(value ?? "").trim();
  if (!t) {
    return null;
  }
  const n = Number(t.replace(",", "."));
  if (Number.isNaN(n)) {
    throw new Error("Некорректные координаты");
  }
  return n;
}

function renderLockerDetailModal() {
  if (!lockerDetailBody || !lockerDetailModalTitle) {
    return;
  }
  const d = state.lockerDetail;
  if (!d || !d.locker) {
    lockerDetailBody.innerHTML = `<div class="empty-state">Нет данных.</div>`;
    return;
  }
  const L = d.locker;
  lockerDetailModalTitle.textContent = L.name || "Постамат";

  const cityOptions = state.cities
    .map(
      (c) =>
        `<option value="${escapeHtml(c.id)}"${String(c.id) === String(L.cityId) ? " selected" : ""}>${escapeHtml(c.name)}</option>`,
    )
    .join("");

  let whText = "";
  if (L.workingHours && typeof L.workingHours === "object") {
    whText = JSON.stringify(L.workingHours, null, 2);
  } else if (L.workingHours) {
    whText = String(L.workingHours);
  }

  const productsRows = (d.productSummaries || [])
    .map(
      (p) => `
      <tr>
        <td>${escapeHtml(p.name)}</td>
        <td>${p.priceFrom != null ? `${formatNumber(p.priceFrom / 100)} ₽` : "—"}</td>
      </tr>`,
    )
    .join("");

  const cellsRows = (d.cells || [])
    .map((cell) => {
      const inv = cell.inventoryUnit;
      const productLine = inv
        ? escapeHtml(inv.productName || "—")
        : '<span class="muted-inline">Свободно</span>';
      return `
        <tr>
          <td>${escapeHtml(cell.label || cell.externalCellId || "—")}</td>
          <td>${escapeHtml(cell.size || "—")}</td>
          <td>${renderStatusPill(cell.status)}</td>
          <td>${productLine}</td>
          <td class="data-table-col-actions">
            <button type="button" class="table-danger-button table-inline-button" data-locker-action="open-cell" data-cell-id="${escapeHtml(cell.id)}">Открыть ячейку</button>
          </td>
        </tr>`;
    })
    .join("");

  const incidentsRows = (d.incidents || [])
    .map(
      (item) => `
      <tr>
        <td>${escapeHtml(item.kind || "incident")}</td>
        <td>${escapeHtml(item.title || "Инцидент")}</td>
        <td class="muted-inline">${escapeHtml(item.details || "—")}</td>
      </tr>`,
    )
    .join("");

  const eventsRows = (d.recentEvents || [])
    .slice(0, 25)
    .map(
      (ev) => `
      <tr>
        <td>${formatDateTime(ev.createdAt)}</td>
        <td>${escapeHtml(ev.eventType)}</td>
        <td>${escapeHtml(ev.source || "")}</td>
        <td class="muted-inline">${escapeHtml(ev.rentalId)}</td>
      </tr>`,
    )
    .join("");

  lockerDetailBody.innerHTML = `
    <div class="user-detail-grid">
      <div class="detail-block">
        <h4 class="detail-block-title">Параметры точки</h4>
        <form id="locker-edit-form" class="locker-edit-form">
          <label class="field"><span>Название</span><input id="locker-edit-name" type="text" value="${escapeHtml(L.name)}" /></label>
          <label class="field"><span>Адрес</span><input id="locker-edit-address" type="text" value="${escapeHtml(L.address)}" /></label>
          <label class="field"><span>Город</span><select id="locker-edit-city">${cityOptions}</select></label>
          <label class="field"><span>Статус точки</span>
            <select id="locker-edit-status">
              <option value="online"${L.status === "online" ? " selected" : ""}>online</option>
              <option value="offline"${L.status === "offline" ? " selected" : ""}>offline</option>
              <option value="maintenance"${L.status === "maintenance" ? " selected" : ""}>maintenance</option>
              <option value="degraded"${L.status === "degraded" ? " selected" : ""}>degraded</option>
            </select>
          </label>
          <details class="locker-advanced">
            <summary>Расширенные настройки</summary>
            <label class="field"><span>Партнёр</span><input id="locker-edit-partner" type="text" value="${escapeHtml(L.partnerName || "")}" /></label>
            <label class="field"><span>Внешний ID</span><input id="locker-edit-external-id" type="text" value="${escapeHtml(L.externalLockerId || "")}" /></label>
            <label class="field"><span>Провайдер</span><input id="locker-edit-provider" type="text" value="${escapeHtml(L.externalProvider || "")}" /></label>
            <label class="field"><span>Широта</span><input id="locker-edit-lat" type="text" value="${L.lat != null ? escapeHtml(String(L.lat)) : ""}" /></label>
            <label class="field"><span>Долгота</span><input id="locker-edit-lon" type="text" value="${L.lon != null ? escapeHtml(String(L.lon)) : ""}" /></label>
            <label class="field"><span>Часы работы (JSON)</span><textarea id="locker-edit-hours" rows="4">${escapeHtml(whText)}</textarea></label>
          </details>
          <div class="user-detail-action-row">
            <button type="button" class="primary-button" data-locker-action="save-locker">Сохранить изменения</button>
            <button type="button" class="table-danger-button" data-locker-action="delete-locker">
              Удалить постамат
            </button>
          </div>
        </form>
      </div>
      <div class="detail-block">
        <h4 class="detail-block-title">Ячейки</h4>
        <p class="muted-inline">Размещение товаров и обслуживание — в разделе «Размещение товаров».</p>
        <div class="table-scroll">
          <table class="data-table data-table-compact">
            <thead><tr><th>Ячейка</th><th>Размер</th><th>Статус</th><th>Товар</th><th class="data-table-col-actions">Действия</th></tr></thead>
            <tbody>${
              cellsRows || `<tr><td colspan="5" class="muted-inline">Ячеек пока нет — добавьте ниже</td></tr>`
            }</tbody>
          </table>
        </div>
        <details class="locker-advanced">
          <summary>Добавить ячейку</summary>
          <div class="locker-add-cell-row">
            <input id="locker-new-cell-label" type="text" placeholder="Метка" />
            <input id="locker-new-cell-ext" type="text" placeholder="Внешний ID" />
            <input id="locker-new-cell-size" type="text" placeholder="Размер" />
            <label class="checkbox-field locker-inline-check"><input id="locker-new-cell-return" type="checkbox" checked /><span>Приём возврата</span></label>
            <button type="button" class="primary-button" data-locker-action="add-cell">Добавить</button>
          </div>
        </details>
      </div>
      <div class="detail-block">
        <h4 class="detail-block-title">Доступные товары</h4>
        <div class="table-scroll">
          <table class="data-table data-table-compact">
            <thead><tr><th>Товар</th><th>Цена от</th></tr></thead>
            <tbody>${
              productsRows ||
              `<tr><td colspan="2" class="muted-inline">Нет доступных позиций по инвентарю</td></tr>`
            }</tbody>
          </table>
        </div>
      </div>
      <div class="detail-block">
        <h4 class="detail-block-title">Инциденты и рассинхрон</h4>
        <div class="table-scroll">
          <table class="data-table data-table-compact">
            <thead><tr><th>Тип</th><th>Заголовок</th><th>Детали</th></tr></thead>
            <tbody>${
              incidentsRows || `<tr><td colspan="3" class="muted-inline">Пока всё чисто</td></tr>`
            }</tbody>
          </table>
        </div>
      </div>
      <div class="detail-block">
        <h4 class="detail-block-title">События по арендам на этой точке</h4>
        <div class="table-scroll">
          <table class="data-table data-table-compact">
            <thead><tr><th>Время</th><th>Событие</th><th>Источник</th><th>Аренда</th></tr></thead>
            <tbody>${
              eventsRows || `<tr><td colspan="4" class="muted-inline">Пока нет событий</td></tr>`
            }</tbody>
          </table>
        </div>
      </div>
    </div>
  `;
}

async function openLockerDetail(lockerId) {
  const raw = String(lockerId ?? "").trim();
  if (!raw || !UUID_RE.test(raw)) {
    showToast("error", "Некорректный ID постамата.");
    return;
  }
  openLockerDetailModal();
  if (lockerDetailBody) {
    lockerDetailBody.innerHTML = `<div class="empty-state">Загрузка…</div>`;
  }
  try {
    const payload = await authorizedRequest(`/api/admin/lockers/${encodeURIComponent(raw)}`);
    state.lockerDetail = payload.data;
    renderLockerDetailModal();
  } catch (error) {
    console.error(error);
    showToast("error", error.message || "Не удалось загрузить постамат");
    closeModal();
  }
}

async function refreshLockerDetail(lockerId) {
  const raw = String(lockerId ?? "").trim();
  if (!raw || !UUID_RE.test(raw)) {
    return;
  }
  try {
    const payload = await authorizedRequest(`/api/admin/lockers/${encodeURIComponent(raw)}`);
    state.lockerDetail = payload.data;
    renderLockerDetailModal();
  } catch (error) {
    console.error(error);
  }
}

async function loadLockersOnly() {
  try {
    const lockersPayload = await authorizedRequest("/api/admin/lockers");
    state.lockers = lockersPayload.data.lockers;
    renderLockers();
  } catch (error) {
    console.error(error);
    showToast("error", error.message || "Не удалось обновить постаматы");
  }
}

let lockerDetailBusy = false;

async function handleLockerDetailClick(event) {
  const root = clickTargetElement(event);
  if (!root) {
    return;
  }
  const btn = root.closest("[data-locker-action]");
  if (!btn || lockerDetailBusy) {
    return;
  }
  const action = btn.dataset.lockerAction;
  const lockerId = state.lockerDetail?.locker?.id;
  if (!action || !lockerId) {
    return;
  }
  const safeLid = encodeURIComponent(lockerId);

  lockerDetailBusy = true;
  btn.disabled = true;
  try {
    if (action === "save-locker") {
      const whRaw = document.getElementById("locker-edit-hours")?.value ?? "";
      let workingHours;
      try {
        workingHours = parseWorkingHoursInput(whRaw);
      } catch (e) {
        showToast("error", e.message || "Ошибка JSON");
        return;
      }
      let lat;
      let lon;
      try {
        lat = parseOptionalCoord(document.getElementById("locker-edit-lat")?.value);
        lon = parseOptionalCoord(document.getElementById("locker-edit-lon")?.value);
      } catch (e) {
        showToast("error", e.message || "Ошибка координат");
        return;
      }
      const body = {
        name: String(document.getElementById("locker-edit-name")?.value || "").trim(),
        address: String(document.getElementById("locker-edit-address")?.value || "").trim(),
        cityId: String(document.getElementById("locker-edit-city")?.value || ""),
        status: String(document.getElementById("locker-edit-status")?.value || "online"),
        partnerName: String(document.getElementById("locker-edit-partner")?.value || "").trim() || null,
        externalLockerId: String(document.getElementById("locker-edit-external-id")?.value || "").trim() || null,
        externalProvider: String(document.getElementById("locker-edit-provider")?.value || "").trim() || null,
        lat,
        lon,
        workingHours,
      };
      await authorizedRequest(`/api/admin/lockers/${safeLid}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      showToast("success", "Постамат обновлён.");
      await refreshLockerDetail(lockerId);
      await loadLockersOnly();
      return;
    }

    if (action === "delete-locker") {
      if (
        !window.confirm(
          "Удалить постамат безвозвратно? Допустимо только если нет броней, аренд, движений инвентаря и единиц в ячейках.",
        )
      ) {
        return;
      }
      await authorizedRequest(`/api/admin/lockers/${safeLid}/delete`, { method: "POST" });
      showToast("success", "Постамат удалён.");
      state.lockerDetail = null;
      closeModal();
      await loadLockersOnly();
      return;
    }

    if (action === "add-cell") {
      const label = String(document.getElementById("locker-new-cell-label")?.value || "").trim() || null;
      const externalCellId =
        String(document.getElementById("locker-new-cell-ext")?.value || "").trim() || null;
      const size = String(document.getElementById("locker-new-cell-size")?.value || "").trim() || null;
      const supportsReturn = Boolean(document.getElementById("locker-new-cell-return")?.checked);
      await authorizedRequest(`/api/admin/lockers/${safeLid}/cells`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ label, externalCellId, size, supportsReturn }),
      });
      showToast("success", "Ячейка добавлена.");
      document.getElementById("locker-new-cell-label").value = "";
      document.getElementById("locker-new-cell-ext").value = "";
      document.getElementById("locker-new-cell-size").value = "";
      await refreshLockerDetail(lockerId);
      await loadLockersOnly();
      return;
    }

    if (action === "assign-unit") {
      const cellId = btn.getAttribute("data-cell-id");
      if (!cellId) {
        return;
      }
      const inventoryUnitId = String(document.getElementById(`cell-unit-${cellId}`)?.value || "").trim();
      if (!UUID_RE.test(inventoryUnitId)) {
        showToast("error", "Введите UUID юнита.");
        return;
      }
      await authorizedRequest(
        `/api/admin/lockers/${safeLid}/cells/${encodeURIComponent(cellId)}/assign-unit`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ inventoryUnitId }),
        },
      );
      showToast("success", "Юнит привязан к ячейке.");
      await refreshLockerDetail(lockerId);
      await loadLockersOnly();
      return;
    }

    if (action === "unassign-unit") {
      const cellId = btn.getAttribute("data-cell-id");
      if (!cellId) {
        return;
      }
      await authorizedRequest(
        `/api/admin/lockers/${safeLid}/cells/${encodeURIComponent(cellId)}/assignment`,
        {
          method: "DELETE",
        },
      );
      showToast("success", "Привязка снята.");
      await refreshLockerDetail(lockerId);
      await loadLockersOnly();
      return;
    }

    if (action === "save-cell") {
      const cellId = btn.getAttribute("data-cell-id");
      if (!cellId) {
        return;
      }
      const sel = document.getElementById(`cell-status-${cellId}`);
      const status = sel ? String(sel.value || "") : "";
      await authorizedRequest(`/api/admin/lockers/${safeLid}/cells/${encodeURIComponent(cellId)}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status }),
      });
      showToast("success", "Ячейка обновлена.");
      await refreshLockerDetail(lockerId);
      await loadLockersOnly();
      return;
    }

    if (action === "open-cell") {
      const cellId = btn.getAttribute("data-cell-id");
      if (!cellId) {
        return;
      }
      if (
        !window.confirm(
          "Отправить команду открытия ячейки на постамат? Используйте только при сбое выдачи/возврата.",
        )
      ) {
        return;
      }
      await authorizedRequest(`/api/admin/lockers/${safeLid}/open-cell`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ cellId }),
      });
      showToast("success", "Команда открытия отправлена.");
      await refreshLockerDetail(lockerId);
      return;
    }
  } catch (error) {
    console.error(error);
    showToast("error", error.message || "Действие не выполнено");
  } finally {
    lockerDetailBusy = false;
    btn.disabled = false;
  }
}

function handleOpenLockerFromTable(event) {
  const root = clickTargetElement(event);
  if (!root) {
    return;
  }
  const button = root.closest("[data-open-locker]");
  if (!button) {
    return;
  }
  const lockerId = (button.getAttribute("data-open-locker") || button.dataset.openLocker || "").trim();
  openLockerDetail(lockerId);
}

const RENTAL_DELETABLE_STATUSES = new Set(["completed", "cancelled", "incident"]);

function rentalIsDeletable(status) {
  return RENTAL_DELETABLE_STATUSES.has(String(status || ""));
}

function rentalCanCancel(status) {
  const s = String(status || "");
  return s !== "completed" && s !== "cancelled";
}

function rentalIsTerminalForDetailActions(status) {
  return !rentalCanCancel(status);
}

function syncRentalsFiltersFromDom() {
  if (rentalsFilterStatus) {
    state.rentalsFilterStatus = String(rentalsFilterStatus.value || "");
  }
  if (rentalsFilterCity) {
    state.rentalsFilterCityId = String(rentalsFilterCity.value || "");
  }
  if (rentalsFilterLocker) {
    state.rentalsFilterLockerId = String(rentalsFilterLocker.value || "");
  }
  if (rentalsFilterOverdue) {
    state.rentalsFilterOverdue = Boolean(rentalsFilterOverdue.checked);
  }
}

function populateRentalsCityLockerSelects() {
  if (!rentalsFilterCity || !rentalsFilterLocker) {
    return;
  }
  const cityVal = state.rentalsFilterCityId;
  const lockerVal = state.rentalsFilterLockerId;

  rentalsFilterCity.innerHTML = '<option value="">Все</option>';
  (state.cities || []).forEach((c) => {
    const opt = document.createElement("option");
    opt.value = c.id;
    opt.textContent = c.name;
    rentalsFilterCity.appendChild(opt);
  });
  if (cityVal && [...rentalsFilterCity.options].some((o) => o.value === cityVal)) {
    rentalsFilterCity.value = cityVal;
  }

  rentalsFilterLocker.innerHTML = '<option value="">Все</option>';
  (state.lockers || []).forEach((l) => {
    const opt = document.createElement("option");
    opt.value = l.id;
    opt.textContent = l.name || l.address || l.id;
    rentalsFilterLocker.appendChild(opt);
  });
  if (lockerVal && [...rentalsFilterLocker.options].some((o) => o.value === lockerVal)) {
    rentalsFilterLocker.value = lockerVal;
  }
}

function buildAdminRentalsPath() {
  const params = new URLSearchParams();
  if (state.rentalsFilterStatus) {
    params.set("status", state.rentalsFilterStatus);
  }
  if (state.rentalsFilterCityId) {
    params.set("city_id", state.rentalsFilterCityId);
  }
  if (state.rentalsFilterLockerId) {
    params.set("locker_id", state.rentalsFilterLockerId);
  }
  if (state.rentalsFilterOverdue) {
    params.set("overdue_only", "true");
  }
  params.set("page", "1");
  params.set("limit", "50");
  const q = params.toString();
  return `/api/admin/rentals?${q}`;
}

async function loadRentalsOnly() {
  if (!rentalsTableBody) {
    return;
  }
  try {
    const payload = await authorizedRequest(buildAdminRentalsPath());
    state.rentals = payload.data.rentals || [];
    state.rentalsMeta = payload.meta || { total: state.rentals.length };
    renderRentals();
  } catch (error) {
    console.error(error);
    showToast("error", error.message || "Не удалось загрузить аренды");
  }
}

function renderRentals() {
  if (!rentalsTableBody || !rentalsEmpty || !rentalsTotal) {
    return;
  }
  const list = state.rentals || [];
  rentalsTotal.textContent = `${formatNumber(state.rentalsMeta.total || list.length)} аренд`;

  if (!list.length) {
    rentalsTableBody.innerHTML = "";
    rentalsEmpty.classList.remove("hidden");
    return;
  }
  rentalsEmpty.classList.add("hidden");

  rentalsTableBody.innerHTML = list
    .map((row) => {
      const canDel = rentalIsDeletable(row.status);
      const canRel = rentalCanCancel(row.status);
      const overdueTag = row.isOverdue
        ? ` <span class="overdue-badge" title="Просрочено">!</span>`
        : "";
      const cancelBtn = canRel
        ? `<button type="button" class="ghost-button table-inline-button" data-rental-cancel="${escapeHtml(row.id)}">Снять</button>`
        : "";
      const deleteBtn = canDel
        ? `<button type="button" class="table-danger-button table-inline-button" data-rental-delete="${escapeHtml(row.id)}">Удалить</button>`
        : "";
      return `
        <tr>
          <td>
            <strong>${escapeHtml(row.user?.name || "—")}</strong>
            <div class="section-meta">${escapeHtml(row.user?.phone || "")}</div>
          </td>
          <td>${escapeHtml(row.product?.name || "—")}</td>
          <td>
            ${escapeHtml(row.pickupLocker?.name || "—")}
            <div class="section-meta">${escapeHtml(row.pickupLocker?.cityName || "")}</div>
          </td>
          <td>${renderStatusPill(row.status)}${overdueTag}</td>
          <td>${formatDateTime(row.plannedEndAt)}</td>
          <td class="data-table-col-actions rental-actions-cell">
            <button type="button" class="ghost-button table-inline-button" data-open-rental="${escapeHtml(row.id)}">Открыть</button>
            ${cancelBtn}
            ${deleteBtn}
          </td>
        </tr>
      `;
    })
    .join("");
}

function renderRentalDetailModal() {
  if (!rentalDetailBody || !rentalDetailModalTitle) {
    return;
  }
  const d = state.rentalDetail;
  const r = d?.rental;
  if (!r) {
    rentalDetailBody.innerHTML = `<div class="empty-state">Нет данных.</div>`;
    return;
  }

  rentalDetailModalTitle.textContent = `Аренда ${r.id.slice(0, 8)}…`;

  const u = d.user;
  const inv = d.inventoryUnit;
  const term = rentalIsTerminalForDetailActions(r.status);
  const canDeleteRecord = rentalIsDeletable(r.status);

  const eventsRows = (r.events || [])
    .map(
      (ev) => `
      <tr>
        <td>${formatDateTime(ev.createdAt)}</td>
        <td><code>${escapeHtml(ev.eventType)}</code></td>
        <td>${escapeHtml(ev.fromStatus || "—")} → ${escapeHtml(ev.toStatus || "—")}</td>
        <td>${escapeHtml(ev.source)}</td>
      </tr>
    `,
    )
    .join("");

  const operatorBlock = term
    ? ""
    : `
    <div class="detail-block">
      <h4 class="detail-block-title">Оператор</h4>
      <p class="muted-inline">Снять — отменить аренду и вернуть юнит в доступные. Принудительно завершить — закрыть как успешный возврат (без вебхука).</p>
      <div class="user-detail-action-row">
        <button type="button" class="ghost-button" data-rental-detail-cancel>Снять аренду</button>
        <button type="button" class="table-danger-button" data-rental-detail-force-complete>Форс-мажор: завершить</button>
      </div>
    </div>
  `;

  const deleteBlock = canDeleteRecord
    ? `
    <div class="detail-block">
      <h4 class="detail-block-title">Запись</h4>
      <button type="button" class="table-danger-button" data-rental-detail-delete>Удалить из базы</button>
      <p class="muted-inline">Только для завершённых, отменённых или инцидентных аренд. Необратимо.</p>
    </div>
  `
    : "";

  rentalDetailBody.innerHTML = `
    <div class="user-detail-grid">
      <div class="detail-block">
        <h4 class="detail-block-title">Статус</h4>
        <p>${renderStatusPill(r.status)}</p>
        <ul class="detail-list">
          <li><span>PIN выдачи</span><strong>${escapeHtml(r.pickupPin || "—")}</strong></li>
          <li><span>Начало</span><strong>${formatDateTime(r.startsAt)}</strong></li>
          <li><span>План окончания</span><strong>${formatDateTime(r.plannedEndAt)}</strong></li>
          <li><span>Факт окончания</span><strong>${formatDateTime(r.actualEndAt)}</strong></li>
        </ul>
      </div>
      <div class="detail-block">
        <h4 class="detail-block-title">Пользователь</h4>
        ${
          u
            ? `<ul class="detail-list">
          <li><span>Имя</span><strong>${escapeHtml(u.name)}</strong></li>
          <li><span>Телефон</span><strong>${escapeHtml(u.phone)}</strong></li>
          <li><span>ID</span><strong><code>${escapeHtml(u.id)}</code></strong></li>
        </ul>
        <button type="button" class="ghost-button table-inline-button" data-open-user-from-rental="${escapeHtml(u.id)}">Карточка пользователя</button>`
            : `<p class="muted-inline">—</p>`
        }
      </div>
      <div class="detail-block">
        <h4 class="detail-block-title">Товар и юнит</h4>
        <ul class="detail-list">
          <li><span>Товар</span><strong>${escapeHtml(r.product?.name || "—")}</strong></li>
          <li><span>Юнит</span><strong>${inv ? escapeHtml(inv.id) : "—"}</strong></li>
          <li><span>Статус юнита</span><strong>${inv ? renderStatusPill(inv.status) : "—"}</strong></li>
          <li><span>Серийный №</span><strong>${escapeHtml(inv?.serialNumber || "—")}</strong></li>
        </ul>
      </div>
      <div class="detail-block">
        <h4 class="detail-block-title">Постамат выдачи</h4>
        <ul class="detail-list">
          <li><span>Название</span><strong>${escapeHtml(r.pickupLocker?.name || "—")}</strong></li>
          <li><span>Адрес</span><strong>${escapeHtml(r.pickupLocker?.address || "—")}</strong></li>
        </ul>
      </div>
      <div class="detail-block">
        <h4 class="detail-block-title">Платёж (сводка)</h4>
        <ul class="detail-list">
          <li><span>Предавторизация</span><strong>${formatMoney((r.paymentSummary?.preauthAmount || 0) / 100, r.paymentSummary?.currency)}</strong></li>
          <li><span>Списано</span><strong>${formatMoney((r.paymentSummary?.capturedAmount || 0) / 100, r.paymentSummary?.currency)}</strong></li>
        </ul>
      </div>
    </div>
    ${operatorBlock}
    ${deleteBlock}
    <div class="detail-block">
      <h4 class="detail-block-title">События</h4>
      <div class="table-scroll">
        <table class="data-table data-table-compact">
          <thead>
            <tr><th>Время</th><th>Событие</th><th>Переход</th><th>Источник</th></tr>
          </thead>
          <tbody>${eventsRows || `<tr><td colspan="4" class="muted-inline">Нет событий</td></tr>`}</tbody>
        </table>
      </div>
    </div>
  `;
}

async function openRentalDetail(rentalId) {
  const raw = String(rentalId ?? "").trim();
  if (!raw || !UUID_RE.test(raw)) {
    showToast("error", "Некорректный ID аренды.");
    return;
  }
  openRentalDetailModal();
  if (rentalDetailBody) {
    rentalDetailBody.innerHTML = `<div class="empty-state">Загрузка…</div>`;
  }
  try {
    const payload = await authorizedRequest(`/api/admin/rentals/${encodeURIComponent(raw)}`);
    state.rentalDetail = payload.data;
    renderRentalDetailModal();
  } catch (error) {
    console.error(error);
    showToast("error", error.message || "Не удалось загрузить аренду");
    closeModal();
  }
}

async function refreshRentalDetail(rentalId) {
  const raw = String(rentalId ?? "").trim();
  if (!raw || !UUID_RE.test(raw)) {
    return;
  }
  try {
    const payload = await authorizedRequest(`/api/admin/rentals/${encodeURIComponent(raw)}`);
    state.rentalDetail = payload.data;
    renderRentalDetailModal();
  } catch (error) {
    console.error(error);
  }
}

async function reloadRentalsContext() {
  await loadRentalsOnly();
  const rid = state.rentalDetail?.rental?.id;
  if (rid && rentalDetailModal && !rentalDetailModal.classList.contains("hidden")) {
    await refreshRentalDetail(rid);
  }
}

let rentalsTableBusy = false;

async function handleRentalsTableClick(event) {
  const root = clickTargetElement(event);
  if (!root || rentalsTableBusy) {
    return;
  }
  const openBtn = root.closest("[data-open-rental]");
  if (openBtn) {
    const id = (openBtn.getAttribute("data-open-rental") || "").trim();
    openRentalDetail(id);
    return;
  }
  const cancelBtn = root.closest("[data-rental-cancel]");
  if (cancelBtn) {
    const id = (cancelBtn.getAttribute("data-rental-cancel") || "").trim();
    if (!window.confirm("Снять аренду? Статус станет «отменено», товар вернётся в доступные.")) {
      return;
    }
    rentalsTableBusy = true;
    cancelBtn.disabled = true;
    try {
      await authorizedRequest(`/api/admin/rentals/${encodeURIComponent(id)}/cancel`, { method: "POST" });
      showToast("success", "Аренда снята.");
      await reloadRentalsContext();
    } catch (error) {
      console.error(error);
      showToast("error", error.message || "Не удалось снять аренду");
    } finally {
      rentalsTableBusy = false;
      cancelBtn.disabled = false;
    }
    return;
  }
  const deleteBtn = root.closest("[data-rental-delete]");
  if (deleteBtn) {
    const id = (deleteBtn.getAttribute("data-rental-delete") || "").trim();
    if (!window.confirm("Удалить запись об аренде из базы? Действие необратимо.")) {
      return;
    }
    rentalsTableBusy = true;
    deleteBtn.disabled = true;
    try {
      await authorizedRequest(`/api/admin/rentals/${encodeURIComponent(id)}`, { method: "DELETE" });
      showToast("success", "Запись удалена.");
      await loadRentalsOnly();
    } catch (error) {
      console.error(error);
      showToast("error", error.message || "Не удалось удалить");
    } finally {
      rentalsTableBusy = false;
      deleteBtn.disabled = false;
    }
  }
}

let rentalDetailActionBusy = false;

async function handleRentalDetailClick(event) {
  const root = clickTargetElement(event);
  if (!root || rentalDetailActionBusy) {
    return;
  }
  const userBtn = root.closest("[data-open-user-from-rental]");
  if (userBtn) {
    const uid = (userBtn.getAttribute("data-open-user-from-rental") || "").trim();
    closeModal();
    setActiveSection("users");
    await openUserDetail(uid);
    return;
  }

  const btn = root.closest("[data-rental-detail-cancel], [data-rental-detail-force-complete], [data-rental-detail-delete]");
  if (!btn) {
    return;
  }

  const rid = state.rentalDetail?.rental?.id;
  if (!rid) {
    return;
  }
  const safeId = encodeURIComponent(rid);

  rentalDetailActionBusy = true;
  btn.disabled = true;
  try {
    if (btn.hasAttribute("data-rental-detail-cancel")) {
      if (!window.confirm("Снять аренду? Статус «отменено».")) {
        return;
      }
      await authorizedRequest(`/api/admin/rentals/${safeId}/cancel`, { method: "POST" });
      showToast("success", "Аренда снята.");
      await reloadRentalsContext();
    } else if (btn.hasAttribute("data-rental-detail-force-complete")) {
      if (
        !window.confirm(
          "Принудительно завершить аренду? Используйте при потере вебхуков или форс-мажоре. Юнит вернётся в доступные.",
        )
      ) {
        return;
      }
      await authorizedRequest(`/api/admin/rentals/${safeId}/force-complete`, { method: "POST" });
      showToast("success", "Аренда принудительно завершена.");
      await reloadRentalsContext();
    } else if (btn.hasAttribute("data-rental-detail-delete")) {
      if (!window.confirm("Удалить запись об аренде? Необратимо.")) {
        return;
      }
      await authorizedRequest(`/api/admin/rentals/${safeId}`, { method: "DELETE" });
      showToast("success", "Удалено.");
      closeModal();
      await loadRentalsOnly();
    }
  } catch (error) {
    console.error(error);
    showToast("error", error.message || "Действие не выполнено");
  } finally {
    rentalDetailActionBusy = false;
    btn.disabled = false;
  }
}

function formatJsonSnippet(obj, maxLen) {
  if (obj == null) {
    return "—";
  }
  try {
    const s = JSON.stringify(obj);
    if (s.length <= maxLen) {
      return s;
    }
    return `${s.slice(0, maxLen)}…`;
  } catch {
    return "—";
  }
}

function escapeForTextareaContent(s) {
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

async function loadProductCategories() {
  const payload = await authorizedRequest("/api/admin/product-categories");
  state.productCategories = payload.data.categories || [];
}

function buildProductsQuery() {
  const params = new URLSearchParams();
  params.set("page", String(state.productsMeta.page || 1));
  params.set("limit", String(state.productsMeta.limit || 50));
  if (state.productsSearch && state.productsSearch.trim()) {
    params.set("q", state.productsSearch.trim());
  }
  if (state.productsFilterActive === "true" || state.productsFilterActive === "false") {
    params.set("isActive", state.productsFilterActive);
  }
  return `/api/admin/products?${params.toString()}`;
}

async function loadProducts() {
  if (!productsTableBody) {
    return;
  }
  syncProductsPageForFilters();
  try {
    const payload = await authorizedRequest(buildProductsQuery());
    state.products = payload.data.products || [];
    state.productsMeta = payload.meta || state.productsMeta;
    renderProducts();
  } catch (error) {
    console.error(error);
    showToast("error", error.message || "Не удалось загрузить каталог");
  }
}

function renderProducts() {
  if (!productsTableBody || !productsEmpty || !productsTotal) {
    return;
  }
  const list = state.products || [];
  const total = state.productsMeta.total ?? list.length;
  productsTotal.textContent = `${formatNumber(total)} товаров`;
  if (!list.length) {
    productsTableBody.innerHTML = "";
    productsEmpty.classList.remove("hidden");
  } else {
    productsEmpty.classList.add("hidden");
    productsTableBody.innerHTML = list
      .map(
        (p) => `
      <tr>
        <td>${escapeHtml(p.name)}</td>
        <td class="muted-inline">${escapeHtml(p.slug)}</td>
        <td>${escapeHtml(p.categoryName || "—")}</td>
        <td>${formatNumber(p.unitCount ?? 0)}</td>
        <td>${renderStatusPill(p.isActive ? "online" : "offline")}</td>
        <td class="data-table-col-actions">
          <button type="button" class="ghost-button table-inline-button" data-open-product="${escapeHtml(p.id)}">Открыть</button>
        </td>
      </tr>`,
      )
      .join("");
  }

  const page = state.productsMeta.page || 1;
  const limit = state.productsMeta.limit || 50;
  if (productsPageLabel) {
    const pages = Math.max(1, Math.ceil(total / limit) || 1);
    productsPageLabel.textContent = `Стр. ${page} из ${pages}`;
  }
  if (productsPrevPage) {
    productsPrevPage.disabled = page <= 1;
  }
  if (productsNextPage) {
    productsNextPage.disabled = page * limit >= total;
  }
}

function openProductModalShell() {
  modalBackdrop.classList.remove("hidden");
  cityModal.classList.add("hidden");
  lockerModal.classList.add("hidden");
  if (userDetailModal) {
    userDetailModal.classList.add("hidden");
  }
  if (lockerDetailModal) {
    lockerDetailModal.classList.add("hidden");
  }
  if (cityDetailModal) {
    cityDetailModal.classList.add("hidden");
  }
  if (rentalDetailModal) {
    rentalDetailModal.classList.add("hidden");
  }
  if (productDetailModal) {
    productDetailModal.classList.remove("hidden");
  }
}

function renderProductDetailModal() {
  if (!productDetailBody || !productDetailModalTitle) {
    return;
  }
  const isNew = state.productDetailIsNew;
  const P = state.productDetail;
  productDetailModalTitle.textContent = isNew ? "Новый товар" : P?.name || "Товар";

  const catOpts = (state.productCategories || [])
    .map(
      (c) =>
        `<option value="${escapeHtml(c.id)}"${
          !isNew && P && String(c.id) === String(P.categoryId) ? " selected" : ""
        }>${escapeHtml(c.name)}</option>`,
    )
    .join("");

  const plansRows =
    !isNew && P && Array.isArray(P.pricePlans)
      ? P.pricePlans
          .map(
            (pl) => `
        <tr>
          <td>${escapeHtml(pl.name)}</td>
          <td>${escapeHtml(pl.durationType)} × ${pl.durationValue}</td>
          <td>${formatNumber(pl.baseAmount)} ${escapeHtml(pl.currency)}</td>
          <td>${pl.isActive ? "да" : "нет"}</td>
        </tr>`,
          )
          .join("")
      : "";

  let specsText = "";
  if (isNew) {
    specsText = "{}";
  } else if (P && P.specsJson != null) {
    try {
      specsText = JSON.stringify(P.specsJson, null, 2);
    } catch {
      specsText = "{}";
    }
  }

  const coverFileId = isNew ? "" : String(P?.coverFileId || "");
  const coverUrl = isNew ? "" : String(P?.coverUrl || "");
  const galleryFileIds = !isNew && P && Array.isArray(P.images)
    ? P.images
        .map((img) => String(img?.fileId || "").trim())
        .filter((id) => UUID_RE.test(id))
    : [];
  const galleryFileIdsText = galleryFileIds.join("\n");
  const galleryPreviewRows = !isNew && P && Array.isArray(P.images)
    ? P.images
        .map((img) => {
          const fileId = String(img?.fileId || "");
          const url = String(img?.url || "");
          const sortOrder = Number.isFinite(Number(img?.sortOrder)) ? Number(img.sortOrder) : "—";
          return `
            <div class="product-image-card">
              ${
                url
                  ? `<a href="${escapeHtml(url)}" target="_blank" rel="noreferrer"><img class="product-image-thumb" src="${escapeHtml(url)}" alt="product image" /></a>`
                  : `<div class="product-image-thumb product-image-thumb-empty">Нет URL</div>`
              }
              <div class="product-image-meta">
                <code>${escapeHtml(fileId || "—")}</code>
                <span class="muted-inline">sort: ${escapeHtml(sortOrder)}</span>
              </div>
            </div>
          `;
        })
        .join("")
    : "";

  productDetailBody.innerHTML = `
    <div class="user-detail-grid">
      <div class="detail-block">
        <h4 class="detail-block-title">${isNew ? "Создание" : "Редактирование"}</h4>
        <form id="product-edit-form" class="locker-edit-form">
          <label class="field"><span>Категория</span>
            <select id="product-edit-category" required>${catOpts || '<option value="">Нет категорий</option>'}</select>
          </label>
          <label class="field"><span>Название</span>
            <input id="product-edit-name" type="text" value="${isNew ? "" : escapeHtml(P.name)}" required />
          </label>
          <label class="field"><span>Slug (латиница)</span>
            <input id="product-edit-slug" type="text" value="${isNew ? "" : escapeHtml(P.slug)}" ${
              isNew ? "" : "required"
            } placeholder="${isNew ? "Необязательно — сгенерируем из названия" : ""}" />
          </label>
          <label class="field"><span>Краткое описание</span>
            <textarea id="product-edit-short" rows="2">${isNew ? "" : escapeForTextareaContent(P.shortDescription || "")}</textarea>
          </label>
          <label class="field"><span>Полное описание</span>
            <textarea id="product-edit-full" rows="4">${isNew ? "" : escapeForTextareaContent(P.fullDescription || "")}</textarea>
          </label>
          <label class="field"><span>Правила</span>
            <textarea id="product-edit-rules" rows="2">${isNew ? "" : escapeForTextareaContent(P.rulesText || "")}</textarea>
          </label>
          <label class="field"><span>Комплект</span>
            <textarea id="product-edit-kit" rows="2">${isNew ? "" : escapeForTextareaContent(P.kitDescription || "")}</textarea>
          </label>
          <label class="field"><span>Бренд</span>
            <input id="product-edit-brand" type="text" value="${isNew ? "" : escapeHtml(P.brand || "")}" />
          </label>
          <label class="field"><span>Обложка (media file ID)</span>
            <input id="product-edit-cover-file-id" type="text" value="${escapeHtml(coverFileId)}" placeholder="UUID из media_files.id" />
          </label>
          <label class="field"><span>Галерея (по одному media file ID на строку)</span>
            <textarea id="product-edit-gallery-file-ids" rows="4" placeholder="uuid-1&#10;uuid-2">${escapeForTextareaContent(galleryFileIdsText)}</textarea>
          </label>
          <div class="product-upload-row">
            <button type="button" class="ghost-button" data-product-action="upload-cover">Загрузить обложку</button>
            <button type="button" class="ghost-button" data-product-action="upload-gallery">Добавить фото в галерею</button>
          </div>
          <p class="muted-inline">Порядок строк = порядок фото в галерее. Пусто — очистить галерею.</p>
          <label class="field"><span>Характеристики (JSON)</span>
            <textarea id="product-edit-specs" rows="4" placeholder="{}">${escapeForTextareaContent(specsText)}</textarea>
          </label>
          <label class="checkbox-field"><input id="product-edit-active" type="checkbox" ${
            isNew || P?.isActive ? " checked" : ""
          } /><span>Активен в каталоге</span></label>
          <div class="user-detail-action-row">
            <button type="button" class="primary-button" data-product-action="save">${isNew ? "Создать" : "Сохранить"}</button>
          </div>
        </form>
      </div>
      ${
        !isNew && plansRows
          ? `<div class="detail-block">
        <h4 class="detail-block-title">Тарифы (только просмотр)</h4>
        <div class="table-scroll">
          <table class="data-table data-table-compact">
            <thead><tr><th>Название</th><th>Период</th><th>Цена</th><th>Активен</th></tr></thead>
            <tbody>${plansRows}</tbody>
          </table>
        </div>
      </div>`
          : ""
      }
      ${
        !isNew
          ? `<div class="detail-block">
        <h4 class="detail-block-title">Картинки (предпросмотр)</h4>
        ${
          coverUrl
            ? `<a href="${escapeHtml(coverUrl)}" target="_blank" rel="noreferrer"><img class="product-cover-preview" src="${escapeHtml(coverUrl)}" alt="product cover" /></a>`
            : `<p class="muted-inline">Обложка не задана.</p>`
        }
        ${
          galleryPreviewRows
            ? `<div class="product-images-grid">${galleryPreviewRows}</div>`
            : `<p class="muted-inline">Галерея пока пустая.</p>`
        }
      </div>`
          : ""
      }
    </div>
  `;
}

async function openProductCreate() {
  await loadProductCategories();
  if (!state.productCategories.length) {
    showToast("error", "Сначала создайте категорию кнопкой «+ Категория».");
    return;
  }
  state.productDetailIsNew = true;
  state.productDetail = null;
  renderProductDetailModal();
  openProductModalShell();
}

async function openProductDetail(productId) {
  const raw = String(productId ?? "").trim();
  if (!raw || !UUID_RE.test(raw)) {
    showToast("error", "Некорректный ID товара.");
    return;
  }
  await loadProductCategories();
  state.productDetailIsNew = false;
  if (productDetailBody) {
    productDetailBody.innerHTML = `<div class="empty-state">Загрузка…</div>`;
  }
  openProductModalShell();
  try {
    const payload = await authorizedRequest(`/api/admin/products/${encodeURIComponent(raw)}`);
    state.productDetail = payload.data.product;
    renderProductDetailModal();
  } catch (error) {
    console.error(error);
    showToast("error", error.message || "Не удалось загрузить товар");
    closeModal();
  }
}

let productDetailBusy = false;

async function handleProductDetailClick(event) {
  const root = clickTargetElement(event);
  if (!root || productDetailBusy) {
    return;
  }
  const btn = root.closest("[data-product-action]");
  if (!btn) {
    return;
  }
  const action = btn.dataset.productAction;

  productDetailBusy = true;
  btn.disabled = true;
  try {
    if (action === "upload-cover") {
      const files = await pickFiles({ multiple: false, accept: "image/jpeg,image/png,image/webp" });
      if (!files.length) {
        return;
      }
      const fileId = await uploadAdminProductImageFile(files[0], "product_cover");
      const coverInput = document.getElementById("product-edit-cover-file-id");
      if (coverInput) {
        coverInput.value = fileId;
      }
      showToast("success", "Обложка загружена. Сохраните карточку товара.");
      return;
    }
    if (action === "upload-gallery") {
      const files = await pickFiles({ multiple: true, accept: "image/jpeg,image/png,image/webp" });
      if (!files.length) {
        return;
      }
      const uploadedIds = [];
      for (const file of files) {
        const fileId = await uploadAdminProductImageFile(file, "product_gallery");
        uploadedIds.push(fileId);
      }
      const galleryInput = document.getElementById("product-edit-gallery-file-ids");
      const existingRaw = String(galleryInput?.value || "");
      const mergedIds = [...parseUuidMultiline(existingRaw), ...uploadedIds];
      const deduped = parseUuidMultiline(mergedIds.join("\n"));
      if (galleryInput) {
        galleryInput.value = deduped.join("\n");
      }
      showToast("success", `Загружено файлов: ${uploadedIds.length}. Сохраните карточку товара.`);
      return;
    }
    if (action !== "save") {
      return;
    }

    const categoryId = document.getElementById("product-edit-category")?.value;
    const name = String(document.getElementById("product-edit-name")?.value || "").trim();
    const slugRaw = String(document.getElementById("product-edit-slug")?.value || "").trim();
    const shortDescription =
      String(document.getElementById("product-edit-short")?.value || "").trim() || null;
    const fullDescription =
      String(document.getElementById("product-edit-full")?.value || "").trim() || null;
    const rulesText = String(document.getElementById("product-edit-rules")?.value || "").trim() || null;
    const kitDescription =
      String(document.getElementById("product-edit-kit")?.value || "").trim() || null;
    const brand = String(document.getElementById("product-edit-brand")?.value || "").trim() || null;
    const coverFileIdRaw = String(document.getElementById("product-edit-cover-file-id")?.value || "").trim();
    const galleryFileIdsRaw = String(
      document.getElementById("product-edit-gallery-file-ids")?.value || "",
    );
    const isActive = Boolean(document.getElementById("product-edit-active")?.checked);
    const specsRaw = String(document.getElementById("product-edit-specs")?.value || "").trim();
    let specsJson = null;
    if (specsRaw) {
      try {
        specsJson = JSON.parse(specsRaw);
        if (specsJson !== null && typeof specsJson !== "object") {
          throw new Error("invalid");
        }
      } catch {
        showToast("error", "Некорректный JSON в характеристиках.");
        return;
      }
    }
    let coverFileId = null;
    if (coverFileIdRaw) {
      if (!UUID_RE.test(coverFileIdRaw)) {
        showToast("error", "Некорректный UUID в поле обложки.");
        return;
      }
      coverFileId = coverFileIdRaw;
    }
    let galleryFileIds = [];
    try {
      galleryFileIds = parseUuidMultiline(galleryFileIdsRaw);
    } catch (error) {
      showToast("error", error.message || "Некорректные UUID в галерее.");
      return;
    }

    if (state.productDetailIsNew) {
      await authorizedRequest("/api/admin/products", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          categoryId,
          name,
          slug: slugRaw || null,
          shortDescription,
          fullDescription,
          rulesText,
          kitDescription,
          brand,
          coverFileId,
          galleryFileIds,
          isActive,
          specsJson,
        }),
      });
      showToast("success", "Товар создан.");
    } else {
      const id = state.productDetail?.id;
      if (!id) {
        return;
      }
      const patchBody = {
        categoryId,
        name,
        shortDescription,
        fullDescription,
        rulesText,
        kitDescription,
        brand,
        coverFileId,
        galleryFileIds,
        isActive,
        specsJson,
      };
      if (slugRaw) {
        patchBody.slug = slugRaw;
      }
      await authorizedRequest(`/api/admin/products/${encodeURIComponent(id)}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(patchBody),
      });
      showToast("success", "Сохранено.");
    }
    closeModal();
    await loadProducts();
  } catch (error) {
    console.error(error);
    showToast("error", error.message || "Ошибка сохранения");
  } finally {
    productDetailBusy = false;
    btn.disabled = false;
  }
}

function syncProductsFiltersFromDom() {
  if (productsSearchInput) {
    state.productsSearch = String(productsSearchInput.value || "");
  }
  if (productsFilterActive) {
    state.productsFilterActive = String(productsFilterActive.value || "");
  }
}

async function loadAuditPage() {
  if (!auditTableBody) {
    return;
  }
  try {
    const params = new URLSearchParams();
    params.set("page", String(state.auditMeta.page || 1));
    params.set("limit", String(state.auditMeta.limit || 50));
    const payload = await authorizedRequest(`/api/admin/audit?${params.toString()}`);
    state.auditEvents = payload.data.events || [];
    state.auditMeta = payload.meta || state.auditMeta;
    renderAudit();
  } catch (error) {
    console.error(error);
    showToast("error", error.message || "Не удалось загрузить аудит");
  }
}

function renderAudit() {
  if (!auditTableBody || !auditEmpty || !auditTotal) {
    return;
  }
  const list = state.auditEvents || [];
  const total = state.auditMeta.total ?? 0;
  const page = state.auditMeta.page || 1;
  const limit = state.auditMeta.limit || 50;
  auditTotal.textContent = `${formatNumber(total)} записей`;
  if (auditPageLabel) {
    const pages = Math.max(1, Math.ceil(total / limit) || 1);
    auditPageLabel.textContent = `Стр. ${page} из ${pages}`;
  }
  if (auditPrevPage) {
    auditPrevPage.disabled = page <= 1;
  }
  if (auditNextPage) {
    auditNextPage.disabled = page * limit >= total;
  }
  if (!list.length) {
    auditTableBody.innerHTML = "";
    auditEmpty.classList.remove("hidden");
    return;
  }
  auditEmpty.classList.add("hidden");
  auditTableBody.innerHTML = list
    .map((ev) => {
      const adminLine = ev.admin
        ? `${escapeHtml(ev.admin.name)} (${escapeHtml(ev.admin.login)})`
        : "—";
      const res = ev.resourceType
        ? ev.resourceId
          ? `${escapeHtml(ev.resourceType)} · ${escapeHtml(ev.resourceId)}`
          : escapeHtml(ev.resourceType)
        : "—";
      return `
        <tr>
          <td>${formatDateTime(ev.createdAt)}</td>
          <td class="muted-inline">${adminLine}</td>
          <td><code>${escapeHtml(ev.action)}</code></td>
          <td class="muted-inline">${res}</td>
          <td><code class="audit-payload">${escapeHtml(formatJsonSnippet(ev.payload, 120))}</code></td>
        </tr>`;
    })
    .join("");
}

function handleProductsTableClick(event) {
  const root = clickTargetElement(event);
  if (!root) {
    return;
  }
  const btn = root.closest("[data-open-product]");
  if (!btn) {
    return;
  }
  const id = btn.getAttribute("data-open-product");
  if (id) {
    openProductDetail(id);
  }
}

function renderApp() {
  renderOverview();
  renderUsers();
  renderVerificationQueue();
  renderCities();
  renderLockers();
  populateLockerCitySelect();
  populateRentalsCityLockerSelects();
  renderRentals();
  adminBadgeName.textContent = state.admin ? state.admin.name : "Admin";
}

async function loadUsersOnly() {
  try {
    syncUsersPageForFilters();
    const usersPayload = await authorizedRequest(buildAdminUsersPath());
    state.users = usersPayload.data.users;
    state.usersMeta = usersPayload.meta || {
      total: state.users.length,
      page: state.usersPage,
      limit: 20,
    };
    if (state.usersMeta.page != null) {
      state.usersPage = state.usersMeta.page;
    }
    renderUsers();
  } catch (error) {
    console.error(error);
    showToast("error", error.message || "Не удалось обновить список пользователей");
  }
}

async function loadAdminData() {
  syncUsersPageForFilters();
  const [overviewPayload, usersPayload, citiesPayload, lockersPayload] = await Promise.all([
    authorizedRequest("/api/admin/dashboard/overview"),
    authorizedRequest(buildAdminUsersPath()),
    authorizedRequest("/api/admin/cities"),
    authorizedRequest("/api/admin/lockers"),
  ]);

  state.overview = overviewPayload.data;
  state.users = usersPayload.data.users;
  state.usersMeta = usersPayload.meta || {
    total: state.users.length,
    page: state.usersPage,
    limit: 20,
  };
  if (state.usersMeta.page != null) {
    state.usersPage = state.usersMeta.page;
  }
  state.cities = citiesPayload.data.cities;
  state.lockers = lockersPayload.data.lockers;
  renderApp();
}

async function restoreSession() {
  const rawSession = localStorage.getItem(STORAGE_KEY);
  if (!rawSession) {
    return false;
  }

  try {
    const payload = JSON.parse(rawSession);
    state.accessToken = payload.accessToken || "";
    state.refreshToken = payload.refreshToken || "";
    state.admin = payload.admin || null;
  } catch (error) {
    console.error(error);
    clearSession();
    return false;
  }

  try {
    if (!state.refreshToken) {
      throw new Error("Сессия отсутствует");
    }

    if (state.accessToken) {
      try {
        state.admin = await fetchCurrentAdmin(state.accessToken);
        saveSession();
        return true;
      } catch (error) {
        console.error(error);
        state.accessToken = "";
      }
    }

    await refreshSession();
    state.admin = await fetchCurrentAdmin(state.accessToken);
    saveSession();
    return true;
  } catch (error) {
    console.error(error);
    clearSession();
    return false;
  }
}

async function bootstrapAuthorizedApp() {
  showAppShell();
  try {
    await loadAdminData();
  } catch (error) {
    console.error(error);
    showToast("error", error.message || "Не удалось загрузить админку");
  }
  startVerificationPolling();
}

async function handleLogin(event) {
  event.preventDefault();
  if (state.isSubmitting) {
    return;
  }

  setLoginLoading(true);

  try {
    const payload = await fetchJson("/api/admin/auth/login", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        login: loginInput.value,
        password: passwordInput.value,
      }),
    });

    state.accessToken = payload.data.accessToken;
    state.refreshToken = payload.data.refreshToken;
    state.admin = payload.data.admin;
    saveSession();
    passwordInput.value = "";
    showToast("success", `Вы вошли как ${state.admin.name}.`);
    await bootstrapAuthorizedApp();
  } catch (error) {
    console.error(error);
    showToast("error", error.message || "Неверный логин или пароль");
  } finally {
    setLoginLoading(false);
  }
}

async function handleLogout() {
  try {
    if (state.accessToken) {
      await authorizedRequest("/api/admin/auth/logout", { method: "POST" }, false);
    }
  } catch (error) {
    console.error(error);
  }

  clearSession();
  showAuthScreen();
  setActiveSection("home");
  showToast("success", "Сессия закрыта.");
}

async function handleCityCreate(event) {
  event.preventDefault();
  if (state.modalSubmitting) {
    return;
  }

  const submitBtn = cityForm.querySelector('button[type="submit"]');
  const formData = new FormData(cityForm);

  setModalSubmitting(true, submitBtn);
  try {
    await authorizedRequest("/api/admin/cities", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        name: String(formData.get("name") || ""),
        slug: String(formData.get("slug") || ""),
        timezone: String(formData.get("timezone") || ""),
        sortOrder: Number(formData.get("sortOrder") || 0),
        isActive: formData.get("isActive") === "on",
      }),
    });

    cityForm.reset();
    cityForm.elements.timezone.value = "Europe/Minsk";
    cityForm.elements.sortOrder.value = "0";
    cityForm.elements.isActive.checked = true;
    await loadAdminData();
    closeModal();
    showToast("success", "Город добавлен.");
  } catch (error) {
    console.error(error);
    showToast("error", error.message || "Не удалось создать город");
  } finally {
    setModalSubmitting(false, submitBtn);
  }
}

async function handleProductCategoryCreate(event) {
  event.preventDefault();
  if (!productCategoryForm || state.modalSubmitting) {
    return;
  }

  const submitBtn = productCategoryForm.querySelector('button[type="submit"]');
  const formData = new FormData(productCategoryForm);

  setModalSubmitting(true, submitBtn);
  try {
    await authorizedRequest("/api/admin/product-categories", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name: String(formData.get("name") || ""),
        slug: String(formData.get("slug") || ""),
        sortOrder: Number(formData.get("sortOrder") || 0),
        isActive: formData.get("isActive") === "on",
      }),
    });

    productCategoryForm.reset();
    if (productCategoryForm.elements.sortOrder) {
      productCategoryForm.elements.sortOrder.value = "0";
    }
    if (productCategoryForm.elements.isActive) {
      productCategoryForm.elements.isActive.checked = true;
    }
    await loadProductCategories();
    if (state.activeSection === "catalog") {
      await loadProducts();
    }
    closeModal();
    showToast("success", "Категория создана.");
  } catch (error) {
    console.error(error);
    showToast("error", error.message || "Не удалось создать категорию");
  } finally {
    setModalSubmitting(false, submitBtn);
  }
}

async function handleLockerCreate(event) {
  event.preventDefault();
  if (state.modalSubmitting) {
    return;
  }

  const submitBtn = lockerForm.querySelector('button[type="submit"]');
  const formData = new FormData(lockerForm);

  setModalSubmitting(true, submitBtn);
  try {
    const selectedCandidate = state.selectedExternalLockerCandidate;
    if (!selectedCandidate) {
      showToast("error", "Выберите постамат из списка, который пришёл по API.");
      return;
    }

    await authorizedRequest("/api/admin/lockers", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        cityId: String(formData.get("cityId") || ""),
        name: String(formData.get("name") || ""),
        address: selectedCandidate.address || String(formData.get("address") || ""),
        status: String(formData.get("status") || "online"),
        partnerName: null,
        externalLockerId: selectedCandidate.externalLockerId,
        externalProvider: selectedCandidate.provider || "esi",
        lat: selectedCandidate.lat ?? null,
        lon: selectedCandidate.lon ?? null,
        workingHours: selectedCandidate.workingHours ?? null,
      }),
    });

    resetLockerCreateState();
    await loadAdminData();
    closeModal();
    showToast("success", "Постамат добавлен.");
  } catch (error) {
    console.error(error);
    showToast("error", error.message || "Не удалось создать постамат");
  } finally {
    setModalSubmitting(false, submitBtn);
  }
}

let cityDeleteBusy = false;

async function handleCityTableClick(event) {
  const root = clickTargetElement(event);
  if (!root) {
    return;
  }
  const openBtn = root.closest("[data-open-city]");
  if (openBtn) {
    const cityId = (openBtn.getAttribute("data-open-city") || "").trim();
    if (cityId) {
      openCityDetail(cityId);
    }
    return;
  }
  const button = root.closest("[data-delete-city]");
  if (!button || cityDeleteBusy) {
    return;
  }
  if (!window.confirm("Удалить город? Если к городу привязаны постаматы, удаление будет отклонено.")) {
    return;
  }
  const cityId = (
    button.getAttribute("data-delete-city") ||
    button.dataset.deleteCity ||
    ""
  ).trim();
  if (!cityId) {
    return;
  }
  cityDeleteBusy = true;
  button.disabled = true;
  try {
    const safeId = encodeURIComponent(cityId);
    await authorizedRequest(`/api/admin/cities/${safeId}/delete`, { method: "POST" });
    await loadAdminData();
    showToast("success", "Город удалён.");
  } catch (error) {
    console.error(error);
    showToast("error", error.message || "Не удалось удалить город");
  } finally {
    cityDeleteBusy = false;
    button.disabled = false;
  }
}

loginForm.addEventListener("submit", handleLogin);
cityForm.addEventListener("submit", handleCityCreate);
if (productCategoryForm) {
  productCategoryForm.addEventListener("submit", handleProductCategoryCreate);
}
citiesTableBody.addEventListener("click", handleCityTableClick);
if (cityDetailModal) {
  cityDetailModal.addEventListener("click", handleCityDetailClick);
}
lockerForm.addEventListener("submit", handleLockerCreate);
logoutButton.addEventListener("click", handleLogout);

if (lockerDiscoveryButton) {
  lockerDiscoveryButton.addEventListener("click", () => {
    loadExternalLockerCandidates();
  });
}

if (lockerCitySelect) {
  lockerCitySelect.addEventListener("change", () => {
    resetLockerCreateState({ preserveCity: true });
    loadExternalLockerCandidates();
  });
}

if (lockerCandidatesList) {
  lockerCandidatesList.addEventListener("change", (event) => {
    const root = clickTargetElement(event);
    if (!root) {
      return;
    }
    const input = root.closest('input[name="locker-candidate"]');
    if (!input) {
      return;
    }
    selectExternalLockerCandidate(input.value);
  });
}

let usersSearchDebounceTimer = null;
if (usersSearchInput) {
  usersSearchInput.addEventListener("input", () => {
    state.usersSearchQuery = usersSearchInput.value;
    window.clearTimeout(usersSearchDebounceTimer);
    usersSearchDebounceTimer = window.setTimeout(() => {
      loadUsersOnly();
    }, 320);
  });
  usersSearchInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      window.clearTimeout(usersSearchDebounceTimer);
      state.usersSearchQuery = usersSearchInput.value;
      loadUsersOnly();
    }
  });
}

if (usersSearchButton && usersSearchInput) {
  usersSearchButton.addEventListener("click", () => {
    window.clearTimeout(usersSearchDebounceTimer);
    state.usersSearchQuery = usersSearchInput.value;
    loadUsersOnly();
  });
}

[usersFilterVerification, usersFilterBlocked].forEach((el) => {
  if (el) {
    el.addEventListener("change", () => {
      syncUserFiltersFromDom();
      loadUsersOnly();
    });
  }
});

if (usersPrevPage) {
  usersPrevPage.addEventListener("click", () => {
    if (state.usersPage > 1) {
      state.usersPage -= 1;
      loadUsersOnly();
    }
  });
}
if (usersNextPage) {
  usersNextPage.addEventListener("click", () => {
    state.usersPage += 1;
    loadUsersOnly();
  });
}

usersTableBody.addEventListener("click", handleOpenUserFromTable);
if (verificationTableBody) {
  verificationTableBody.addEventListener("click", handleOpenUserFromTable);
}
if (userDetailModal) {
  userDetailModal.addEventListener("click", handleUserDetailClick);
}

if (lockerDetailModal) {
  lockerDetailModal.addEventListener("click", handleLockerDetailClick);
}

lockersTableBody.addEventListener("click", handleOpenLockerFromTable);

if (productsTableBody) {
  productsTableBody.addEventListener("click", handleProductsTableClick);
}

let productsSearchDebounceTimer = null;
if (productsSearchInput) {
  productsSearchInput.addEventListener("input", () => {
    state.productsSearch = String(productsSearchInput.value || "");
    window.clearTimeout(productsSearchDebounceTimer);
    productsSearchDebounceTimer = window.setTimeout(() => {
      loadProducts();
    }, 400);
  });
}
if (productsFilterActive) {
  productsFilterActive.addEventListener("change", () => {
    syncProductsFiltersFromDom();
    loadProducts();
  });
}

if (productsSearchButton) {
  productsSearchButton.addEventListener("click", () => {
    window.clearTimeout(productsSearchDebounceTimer);
    syncProductsFiltersFromDom();
    state.productsMeta.page = 1;
    loadProducts();
  });
}
if (productsPrevPage) {
  productsPrevPage.addEventListener("click", () => {
    if (state.productsMeta.page > 1) {
      state.productsMeta.page -= 1;
      loadProducts();
    }
  });
}
if (productsNextPage) {
  productsNextPage.addEventListener("click", () => {
    state.productsMeta.page += 1;
    loadProducts();
  });
}
if (productNewButton) {
  productNewButton.addEventListener("click", () => {
    openProductCreate();
  });
}
if (productDetailModal) {
  productDetailModal.addEventListener("click", handleProductDetailClick);
}
if (auditRefreshButton) {
  auditRefreshButton.addEventListener("click", () => {
    loadAuditPage();
  });
}
if (auditPrevPage) {
  auditPrevPage.addEventListener("click", () => {
    if (state.auditMeta.page > 1) {
      state.auditMeta.page -= 1;
      loadAuditPage();
    }
  });
}
if (auditNextPage) {
  auditNextPage.addEventListener("click", () => {
    state.auditMeta.page += 1;
    loadAuditPage();
  });
}

if (rentalsTableBody) {
  rentalsTableBody.addEventListener("click", handleRentalsTableClick);
}
if (rentalDetailModal) {
  rentalDetailModal.addEventListener("click", handleRentalDetailClick);
}

[rentalsFilterStatus, rentalsFilterCity, rentalsFilterLocker].forEach((el) => {
  if (el) {
    el.addEventListener("change", () => {
      syncRentalsFiltersFromDom();
      loadRentalsOnly();
    });
  }
});
if (rentalsFilterOverdue) {
  rentalsFilterOverdue.addEventListener("change", () => {
    syncRentalsFiltersFromDom();
    loadRentalsOnly();
  });
}

navLinks.forEach((link) => {
  link.addEventListener("click", () => {
    setActiveSection(link.dataset.section);
    if (link.dataset.section === "verification") {
      loadVerificationQueue();
    }
    if (link.dataset.section === "rentals") {
      populateRentalsCityLockerSelects();
      syncRentalsFiltersFromDom();
      loadRentalsOnly();
    }
    if (link.dataset.section === "catalog") {
      state.productsMeta.page = 1;
      syncProductsFiltersFromDom();
      if (productsSearchInput) {
        productsSearchInput.value = state.productsSearch;
      }
      if (productsFilterActive) {
        productsFilterActive.value = state.productsFilterActive;
      }
      loadProducts();
    }
    if (link.dataset.section === "audit") {
      state.auditMeta.page = 1;
      loadAuditPage();
    }
    if (link.dataset.section === "inventory") {
      bootstrapInventorySection();
    }
  });
});

modalOpenButtons.forEach((button) => {
  button.addEventListener("click", () => openModal(button.dataset.openModal));
});

modalCloseButtons.forEach((button) => {
  button.addEventListener("click", closeModal);
});

modalBackdrop.addEventListener("click", (event) => {
  if (event.target === modalBackdrop) {
    closeModal();
  }
});

const navToggle = document.getElementById("nav-toggle");
const appNav = document.getElementById("app-nav");
const appTools = document.querySelector(".app-tools");
const mobileNavQuery = window.matchMedia("(max-width: 760px)");

function setMobileNavOpen(isOpen) {
  if (!navToggle || !appNav) return;
  navToggle.classList.toggle("is-open", isOpen);
  navToggle.setAttribute("aria-expanded", isOpen ? "true" : "false");
  navToggle.setAttribute("aria-label", isOpen ? "Закрыть меню" : "Открыть меню");
  appNav.classList.toggle("is-open", isOpen);
  if (appTools) {
    appTools.classList.toggle("is-open", isOpen);
  }
}

if (navToggle) {
  navToggle.addEventListener("click", () => {
    const willOpen = !navToggle.classList.contains("is-open");
    setMobileNavOpen(willOpen);
  });
}

navLinks.forEach((link) => {
  link.addEventListener("click", () => {
    if (mobileNavQuery.matches) {
      setMobileNavOpen(false);
    }
  });
});

const handleNavMediaChange = (event) => {
  if (!event.matches) {
    setMobileNavOpen(false);
  }
};
if (typeof mobileNavQuery.addEventListener === "function") {
  mobileNavQuery.addEventListener("change", handleNavMediaChange);
} else if (typeof mobileNavQuery.addListener === "function") {
  mobileNavQuery.addListener(handleNavMediaChange);
}

// =====================
// Раздел «Размещение товаров»
// =====================

const inventoryLockerSelect = document.getElementById("inventory-locker-select");
const inventoryOnlyFreeCheckbox = document.getElementById("inventory-only-free");
const inventoryRefreshButton = document.getElementById("inventory-refresh-button");
const inventoryCellsGrid = document.getElementById("inventory-cells-grid");
const inventoryEmpty = document.getElementById("inventory-empty");
const inventorySummary = document.getElementById("inventory-summary");
const inventoryPlaceModal = document.getElementById("inventory-place-modal");
const inventoryPlaceCellInfo = document.getElementById("inventory-place-cell-info");
const inventoryProductSearchInput = document.getElementById("inventory-product-search");
const inventoryProductOnlyActive = document.getElementById("inventory-product-only-active");
const inventoryProductList = document.getElementById("inventory-product-list");
const inventoryProductEmpty = document.getElementById("inventory-product-empty");
const inventoryPlaceComment = document.getElementById("inventory-place-comment");
const inventoryPlaceSubmit = document.getElementById("inventory-place-submit");
const inventoryServiceModal = document.getElementById("inventory-service-modal");
const inventoryServiceCellInfo = document.getElementById("inventory-service-cell-info");
const inventoryServiceTarget = document.getElementById("inventory-service-target");
const inventoryServiceOpen = document.getElementById("inventory-service-open");
const inventoryServiceReason = document.getElementById("inventory-service-reason");
const inventoryServiceSubmit = document.getElementById("inventory-service-submit");

function inventoryFormatLockerLabel(locker) {
  if (!locker) return "";
  const city = locker.cityName ? `${locker.cityName}, ` : "";
  return `${city}${locker.name} · ${locker.address}`;
}

function renderInventoryLockerOptions() {
  if (!inventoryLockerSelect) return;
  const previous = state.inventory.selectedLockerId;
  const items = state.inventory.lockers || [];
  inventoryLockerSelect.innerHTML = `<option value="">Выберите постамат</option>${items
    .map((locker) => {
      const free = Number(locker.freeCells || 0);
      const total = Number(locker.totalCells || 0);
      const cellsLabel = total ? ` (${free}/${total} свободно)` : "";
      return `<option value="${escapeHtml(locker.id)}">${escapeHtml(
        inventoryFormatLockerLabel(locker),
      )}${escapeHtml(cellsLabel)}</option>`;
    })
    .join("")}`;
  if (previous && items.some((l) => l.id === previous)) {
    inventoryLockerSelect.value = previous;
  } else {
    inventoryLockerSelect.value = "";
    state.inventory.selectedLockerId = "";
  }
}

function renderInventoryCells() {
  if (!inventoryCellsGrid || !inventoryEmpty) return;
  const cells = state.inventory.cells || [];
  const onlyFree = Boolean(state.inventory.onlyFree);
  const filtered = onlyFree
    ? cells.filter((c) => c.status === "vacant" && !c.currentUnit)
    : cells;

  if (!state.inventory.selectedLockerId) {
    inventoryCellsGrid.innerHTML = "";
    inventoryEmpty.textContent = "Выберите постамат, чтобы увидеть ячейки.";
    inventoryEmpty.classList.remove("hidden");
    return;
  }

  if (!filtered.length) {
    inventoryCellsGrid.innerHTML = "";
    inventoryEmpty.textContent = onlyFree
      ? "Свободных ячеек не нашлось. Снимите фильтр, чтобы увидеть все."
      : "В этом постамате пока нет ячеек. Добавьте их в разделе «Постаматы».";
    inventoryEmpty.classList.remove("hidden");
    return;
  }

  inventoryEmpty.classList.add("hidden");
  inventoryCellsGrid.innerHTML = filtered
    .map((cell) => {
      const occupied = Boolean(cell.currentUnit);
      const cellLabel = cell.label || cell.externalCellId || "—";
      const sizeLabel = cell.size ? `Размер: ${escapeHtml(cell.size)}` : "Размер не указан";
      const cover = cell.currentUnit?.coverUrl
        ? `<img class="cell-card__cover" src="${escapeHtml(
            cell.currentUnit.coverUrl,
          )}" alt="" loading="lazy" />`
        : `<div class="cell-card__cover cell-card__cover--placeholder">${
            occupied ? "Без обложки" : "Свободно"
          }</div>`;
      const productName = occupied
        ? `<p class="cell-card__product-name">${escapeHtml(
            cell.currentUnit.productName || "Без названия",
          )}</p>`
        : `<p class="cell-card__product-name muted-inline">Свободная ячейка</p>`;
      const unitMeta = occupied
        ? `<p class="muted-inline cell-card__meta">${escapeHtml(
            cell.currentUnit.serialNumber || "Без серийного номера",
          )}</p>`
        : "";
      const action = occupied
        ? `<button type="button" class="table-danger-button cell-card__action" data-inventory-action="open-service" data-cell-id="${escapeHtml(
            cell.id,
          )}">Забрать на обслуживание</button>`
        : `<button type="button" class="primary-button cell-card__action" data-inventory-action="open-place" data-cell-id="${escapeHtml(
            cell.id,
          )}">Положить товар</button>`;
      const statusPill = renderStatusPill(cell.status);
      return `
        <article class="cell-card cell-card--${occupied ? "occupied" : "free"}">
          <header class="cell-card__head">
            <div>
              <p class="cell-card__label">Ячейка ${escapeHtml(cellLabel)}</p>
              <p class="muted-inline cell-card__meta">${escapeHtml(sizeLabel)}</p>
            </div>
            ${statusPill}
          </header>
          ${cover}
          ${productName}
          ${unitMeta}
          ${action}
        </article>
      `;
    })
    .join("");
}

function updateInventorySummary() {
  if (!inventorySummary) return;
  const locker = (state.inventory.lockers || []).find(
    (l) => l.id === state.inventory.selectedLockerId,
  );
  if (!locker) {
    inventorySummary.textContent = "Выберите постамат";
    return;
  }
  const free = Number(locker.freeCells || 0);
  const total = Number(locker.totalCells || 0);
  inventorySummary.textContent = `${free}/${total} ячеек свободны`;
}

async function loadInventoryLockers() {
  try {
    const payload = await authorizedRequest("/api/admin/inventory/lockers");
    state.inventory.lockers = payload.data?.lockers || [];
    renderInventoryLockerOptions();
    updateInventorySummary();
  } catch (error) {
    console.error(error);
    showToast("error", error.message || "Не удалось загрузить постаматы");
  }
}

async function loadInventoryCells() {
  if (!state.inventory.selectedLockerId) {
    state.inventory.cells = [];
    renderInventoryCells();
    return;
  }
  state.inventory.isLoading = true;
  try {
    const payload = await authorizedRequest(
      `/api/admin/inventory/lockers/${encodeURIComponent(
        state.inventory.selectedLockerId,
      )}/cells`,
    );
    state.inventory.cells = payload.data?.cells || [];
    renderInventoryCells();
    updateInventorySummary();
  } catch (error) {
    console.error(error);
    showToast("error", error.message || "Не удалось загрузить ячейки");
  } finally {
    state.inventory.isLoading = false;
  }
}

async function bootstrapInventorySection() {
  if (!state.inventory.lockers.length) {
    await loadInventoryLockers();
  } else {
    renderInventoryLockerOptions();
  }
  if (state.inventory.selectedLockerId) {
    await loadInventoryCells();
  } else {
    renderInventoryCells();
  }
}

async function loadInventoryProducts() {
  try {
    const params = new URLSearchParams();
    if (state.inventory.productSearch) {
      params.set("q", state.inventory.productSearch);
    }
    params.set("onlyActive", state.inventory.productOnlyActive ? "true" : "false");
    params.set("limit", "50");
    const payload = await authorizedRequest(
      `/api/admin/inventory/products?${params.toString()}`,
    );
    state.inventory.products = payload.data?.products || [];
    renderInventoryProductList();
  } catch (error) {
    console.error(error);
    showToast("error", error.message || "Не удалось загрузить товары");
  }
}

function renderInventoryProductList() {
  if (!inventoryProductList || !inventoryProductEmpty) return;
  const products = state.inventory.products || [];
  if (!products.length) {
    inventoryProductList.innerHTML = "";
    inventoryProductEmpty.classList.remove("hidden");
    inventoryPlaceSubmit.disabled = true;
    return;
  }
  inventoryProductEmpty.classList.add("hidden");
  inventoryProductList.innerHTML = products
    .map((product) => {
      const isSelected = product.id === state.inventory.selectedProductId;
      const cover = product.coverUrl
        ? `<img class="inventory-product-card__cover" src="${escapeHtml(
            product.coverUrl,
          )}" alt="" loading="lazy" />`
        : `<div class="inventory-product-card__cover inventory-product-card__cover--placeholder">Без фото</div>`;
      const free = Number(product.availableUnits || 0);
      const total = Number(product.totalUnits || 0);
      const stockLine =
        free > 0
          ? `Готовых юнитов: ${free}`
          : total > 0
            ? `Все ${total} юнитов уже разложены — создадим новый`
            : "Юнитов ещё нет — создадим новый";
      return `
        <button
          type="button"
          class="inventory-product-card${isSelected ? " is-selected" : ""}"
          data-inventory-product-id="${escapeHtml(product.id)}"
          ${product.isActive ? "" : 'data-inactive="1"'}
        >
          ${cover}
          <div class="inventory-product-card__body">
            <p class="inventory-product-card__name">${escapeHtml(product.name)}</p>
            <p class="muted-inline">${escapeHtml(product.categoryName || "Без категории")}</p>
            <p class="muted-inline">${escapeHtml(stockLine)}</p>
            ${product.isActive ? "" : '<p class="muted-inline">Не активен в каталоге</p>'}
          </div>
        </button>
      `;
    })
    .join("");
  inventoryPlaceSubmit.disabled = !state.inventory.selectedProductId;
}

function inventoryOpenPlaceModal(cellId) {
  const cell = (state.inventory.cells || []).find((c) => c.id === cellId);
  if (!cell) return;
  state.inventory.activeCellId = cellId;
  state.inventory.selectedProductId = "";
  state.inventory.productSearch = "";
  if (inventoryProductSearchInput) inventoryProductSearchInput.value = "";
  if (inventoryPlaceComment) inventoryPlaceComment.value = "";
  if (inventoryProductOnlyActive) inventoryProductOnlyActive.checked = state.inventory.productOnlyActive;
  if (inventoryPlaceCellInfo) {
    inventoryPlaceCellInfo.textContent = `Ячейка: ${cell.label || cell.externalCellId || "—"}`;
  }
  inventoryPlaceSubmit.disabled = true;
  modalBackdrop.classList.remove("hidden");
  hideAllModals();
  inventoryPlaceModal.classList.remove("hidden");
  loadInventoryProducts();
}

function inventoryOpenServiceModal(cellId) {
  const cell = (state.inventory.cells || []).find((c) => c.id === cellId);
  if (!cell || !cell.currentUnit) return;
  state.inventory.activeCellId = cellId;
  if (inventoryServiceCellInfo) {
    inventoryServiceCellInfo.textContent = `Ячейка ${cell.label || cell.externalCellId || "—"} · ${
      cell.currentUnit.productName || "Без названия"
    }`;
  }
  if (inventoryServiceTarget) inventoryServiceTarget.value = "maintenance";
  if (inventoryServiceOpen) inventoryServiceOpen.checked = true;
  if (inventoryServiceReason) inventoryServiceReason.value = "";
  modalBackdrop.classList.remove("hidden");
  hideAllModals();
  inventoryServiceModal.classList.remove("hidden");
}

function hideAllModals() {
  cityModal.classList.add("hidden");
  lockerModal.classList.add("hidden");
  if (userDetailModal) userDetailModal.classList.add("hidden");
  if (lockerDetailModal) lockerDetailModal.classList.add("hidden");
  if (cityDetailModal) cityDetailModal.classList.add("hidden");
  if (rentalDetailModal) rentalDetailModal.classList.add("hidden");
  if (productDetailModal) productDetailModal.classList.add("hidden");
  if (productCategoryModal) productCategoryModal.classList.add("hidden");
  if (inventoryPlaceModal) inventoryPlaceModal.classList.add("hidden");
  if (inventoryServiceModal) inventoryServiceModal.classList.add("hidden");
}

async function inventoryPlaceSelectedProduct() {
  if (state.inventory.isPlacing) return;
  const cellId = state.inventory.activeCellId;
  const productId = state.inventory.selectedProductId;
  if (!cellId || !productId) {
    showToast("error", "Выберите товар");
    return;
  }
  state.inventory.isPlacing = true;
  inventoryPlaceSubmit.disabled = true;
  try {
    await authorizedRequest(
      `/api/admin/inventory/cells/${encodeURIComponent(cellId)}/place`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          productId,
          comment: (inventoryPlaceComment?.value || "").trim() || null,
        }),
      },
    );
    showToast("success", "Товар разложен в ячейку.");
    closeModal();
    await Promise.all([loadInventoryCells(), loadInventoryLockers()]);
  } catch (error) {
    console.error(error);
    showToast("error", error.message || "Не удалось положить товар");
  } finally {
    state.inventory.isPlacing = false;
    inventoryPlaceSubmit.disabled = !state.inventory.selectedProductId;
  }
}

async function inventoryTakeForService() {
  if (state.inventory.isServicing) return;
  const cellId = state.inventory.activeCellId;
  if (!cellId) {
    return;
  }
  state.inventory.isServicing = true;
  inventoryServiceSubmit.disabled = true;
  try {
    const body = {
      reason: (inventoryServiceReason?.value || "").trim() || null,
      openCell: Boolean(inventoryServiceOpen?.checked),
      targetStatus: inventoryServiceTarget?.value === "damaged" ? "damaged" : "maintenance",
    };
    await authorizedRequest(
      `/api/admin/inventory/cells/${encodeURIComponent(cellId)}/take-for-service`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      },
    );
    showToast("success", "Товар изъят на обслуживание.");
    closeModal();
    await Promise.all([loadInventoryCells(), loadInventoryLockers()]);
  } catch (error) {
    console.error(error);
    showToast("error", error.message || "Не удалось изъять товар");
  } finally {
    state.inventory.isServicing = false;
    inventoryServiceSubmit.disabled = false;
  }
}

if (inventoryLockerSelect) {
  inventoryLockerSelect.addEventListener("change", () => {
    state.inventory.selectedLockerId = inventoryLockerSelect.value || "";
    loadInventoryCells();
    updateInventorySummary();
  });
}
if (inventoryOnlyFreeCheckbox) {
  inventoryOnlyFreeCheckbox.addEventListener("change", () => {
    state.inventory.onlyFree = Boolean(inventoryOnlyFreeCheckbox.checked);
    renderInventoryCells();
  });
}
if (inventoryRefreshButton) {
  inventoryRefreshButton.addEventListener("click", () => {
    loadInventoryLockers().then(() => loadInventoryCells());
  });
}
if (inventoryCellsGrid) {
  inventoryCellsGrid.addEventListener("click", (event) => {
    const root = clickTargetElement(event);
    if (!root) return;
    const btn = root.closest("[data-inventory-action]");
    if (!btn) return;
    const action = btn.getAttribute("data-inventory-action");
    const cellId = btn.getAttribute("data-cell-id");
    if (!cellId) return;
    if (action === "open-place") {
      inventoryOpenPlaceModal(cellId);
    } else if (action === "open-service") {
      inventoryOpenServiceModal(cellId);
    }
  });
}
if (inventoryProductList) {
  inventoryProductList.addEventListener("click", (event) => {
    const root = clickTargetElement(event);
    if (!root) return;
    const card = root.closest("[data-inventory-product-id]");
    if (!card) return;
    state.inventory.selectedProductId = card.getAttribute("data-inventory-product-id") || "";
    renderInventoryProductList();
  });
}
if (inventoryProductSearchInput) {
  inventoryProductSearchInput.addEventListener("input", () => {
    if (state.inventory.productSearchTimer) {
      window.clearTimeout(state.inventory.productSearchTimer);
    }
    state.inventory.productSearchTimer = window.setTimeout(() => {
      state.inventory.productSearch = inventoryProductSearchInput.value.trim();
      loadInventoryProducts();
    }, 250);
  });
}
if (inventoryProductOnlyActive) {
  inventoryProductOnlyActive.addEventListener("change", () => {
    state.inventory.productOnlyActive = Boolean(inventoryProductOnlyActive.checked);
    loadInventoryProducts();
  });
}
if (inventoryPlaceSubmit) {
  inventoryPlaceSubmit.addEventListener("click", inventoryPlaceSelectedProduct);
}
if (inventoryServiceSubmit) {
  inventoryServiceSubmit.addEventListener("click", inventoryTakeForService);
}

(async function init() {
  const hasSession = await restoreSession();
  if (hasSession) {
    await bootstrapAuthorizedApp();
    return;
  }
  showAuthScreen();
})();
