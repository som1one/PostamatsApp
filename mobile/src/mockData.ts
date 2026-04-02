import type {
  City,
  Locker,
  LockerAvailabilityItem,
  PricingQuote,
  ProductDetail,
  ProductListItem,
} from "./types";

export const mockCities: City[] = [
  {
    id: "city-spb",
    name: "Санкт-Петербург",
    slug: "spb",
    timezone: "Europe/Moscow",
    isActive: true,
    sortOrder: 1,
  },
];

export const mockLockers: Locker[] = [
  {
    id: "locker-liteiny",
    cityId: "city-spb",
    name: "Литейный, 12",
    address: "Санкт-Петербург, Литейный пр., 12",
    status: "online",
    workingHours: { mode: "daily", from: "08:00", to: "22:00" },
    availableProductCount: 14,
    availableUnitCount: 18,
  },
  {
    id: "locker-vasileostrovsky",
    cityId: "city-spb",
    name: "Средний пр., 36",
    address: "Санкт-Петербург, Средний пр. В.О., 36",
    status: "online",
    workingHours: { mode: "daily", from: "09:00", to: "21:00" },
    availableProductCount: 11,
    availableUnitCount: 13,
  },
];

export const mockProducts: ProductListItem[] = [
  {
    id: "product-bosch-hammer",
    categoryId: "tools",
    name: "Перфоратор Bosch",
    slug: "bosch-hammer-drill",
    shortDescription: "Для сверления бетона и демонтажа",
    brand: "Bosch",
    priceFrom: 150000,
    currency: "RUB",
    available: true,
    availableLockerCount: 3,
  },
  {
    id: "product-makita-saw",
    categoryId: "tools",
    name: "Пила Makita",
    slug: "makita-saw",
    shortDescription: "Точная резка и чистый рез",
    brand: "Makita",
    priceFrom: 120000,
    currency: "RUB",
    available: true,
    availableLockerCount: 2,
  },
  {
    id: "product-laser-level",
    categoryId: "tools",
    name: "Лазерный уровень",
    slug: "laser-level",
    shortDescription: "Быстрая разметка в помещении",
    brand: "Huepar",
    priceFrom: 80000,
    currency: "RUB",
    available: true,
    availableLockerCount: 4,
  },
];

export const mockAvailability: LockerAvailabilityItem[] = [
  {
    productId: "product-bosch-hammer",
    productName: "Перфоратор Bosch",
    availableUnits: 2,
    minDurationType: "day",
    minDurationValue: 1,
    priceFrom: 150000,
    currency: "RUB",
  },
  {
    productId: "product-makita-saw",
    productName: "Пила Makita",
    availableUnits: 1,
    minDurationType: "day",
    minDurationValue: 1,
    priceFrom: 120000,
    currency: "RUB",
  },
];

export const mockProductDetail: ProductDetail = {
  id: "product-bosch-hammer",
  categoryId: "tools",
  name: "Перфоратор Bosch",
  slug: "bosch-hammer-drill",
  shortDescription: "Для сверления бетона и демонтажа",
  fullDescription:
    "Универсальный инструмент для монтажа, штробления и коротких демонтажных работ.",
  brand: "Bosch",
  specs: {
    мощность: "800 Вт",
    вес: "3.2 кг",
    режимы: "удар, сверление, долбление",
  },
  rulesText: "Использовать по назначению, вернуть в исходной комплектации.",
  kitDescription: "Кейс, ручка, ограничитель глубины, инструкция.",
  images: [],
  pricePlans: [
    {
      id: "plan-day-1",
      name: "1 день",
      durationType: "day",
      durationValue: 1,
      baseAmount: 150000,
      currency: "RUB",
    },
    {
      id: "plan-day-3",
      name: "3 дня",
      durationType: "day",
      durationValue: 3,
      baseAmount: 390000,
      currency: "RUB",
    },
  ],
  availableLockers: [
    {
      lockerId: "locker-liteiny",
      name: "Литейный, 12",
      address: "Санкт-Петербург, Литейный пр., 12",
      status: "online",
      availableUnits: 2,
    },
    {
      lockerId: "locker-vasileostrovsky",
      name: "Средний пр., 36",
      address: "Санкт-Петербург, Средний пр. В.О., 36",
      status: "online",
      availableUnits: 1,
    },
  ],
};

export const mockPricing: PricingQuote = {
  productId: "product-bosch-hammer",
  lockerId: "locker-liteiny",
  durationType: "day",
  durationValue: 1,
  currency: "RUB",
  baseAmount: 150000,
  discountAmount: 0,
  depositAmount: 0,
  preauthAmount: 150000,
  totalAmount: 150000,
  available: true,
};
