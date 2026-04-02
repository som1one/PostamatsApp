export type City = {
  id: string;
  name: string;
  slug: string;
  timezone: string;
  isActive: boolean;
  sortOrder: number;
};

export type Locker = {
  id: string;
  cityId: string;
  name: string;
  address: string;
  lat?: number;
  lon?: number;
  status: "online" | "offline" | "maintenance" | "degraded";
  workingHours?: {
    mode?: string;
    from?: string;
    to?: string;
  };
  availableProductCount: number;
  availableUnitCount?: number;
};

export type LockerAvailabilityItem = {
  productId: string;
  productName: string;
  availableUnits: number;
  minDurationType?: string;
  minDurationValue?: number;
  priceFrom: number;
  currency: string;
};

export type ProductListItem = {
  id: string;
  categoryId: string;
  name: string;
  slug: string;
  coverUrl?: string | null;
  shortDescription?: string | null;
  brand?: string | null;
  priceFrom: number;
  currency: string;
  available: boolean;
  availableLockerCount: number;
};

export type PricePlan = {
  id: string;
  name: string;
  durationType: string;
  durationValue: number;
  baseAmount: number;
  currency: string;
};

export type ProductDetail = {
  id: string;
  categoryId: string;
  name: string;
  slug: string;
  shortDescription?: string | null;
  fullDescription?: string | null;
  brand?: string | null;
  specs?: Record<string, string> | null;
  rulesText?: string | null;
  kitDescription?: string | null;
  coverUrl?: string | null;
  images: Array<{
    id: string;
    url: string;
    sortOrder: number;
  }>;
  pricePlans: PricePlan[];
  availableLockers: Array<{
    lockerId: string;
    name: string;
    address: string;
    status: string;
    availableUnits: number;
  }>;
};

export type PricingQuote = {
  productId: string;
  lockerId: string;
  durationType: string;
  durationValue: number;
  currency: string;
  baseAmount: number;
  discountAmount: number;
  depositAmount: number;
  preauthAmount: number;
  totalAmount: number;
  available: boolean;
};

export type AppUser = {
  id: string;
  phone: string;
  email?: string;
  firstName?: string;
  lastName?: string;
  middleName?: string;
  birthDate?: string;
  preferredCityId?: string;
  verificationStatus: string;
  isBlocked?: boolean;
  blockedReason?: string;
  lastLoginAt?: string;
};

export type RequestCodeResponse = {
  verificationSessionId: string;
  ttlSeconds: number;
  code?: string;
};

export type ConfirmCodeResponse = {
  accessToken: string;
  refreshToken: string;
  user: {
    id: string;
    phone: string;
    verificationStatus: string;
  };
};

export type VerificationState = {
  id?: string;
  status: string;
  documentType?: string;
  documentNumber?: string;
  documentIssueDate?: string;
  documentExpiryDate?: string;
  rejectReason?: string;
};

export type ReservationQuote = {
  productId: string;
  lockerId: string;
  durationType: string;
  durationValue: number;
  currency: string;
  quotedAmount: number;
  preauthAmount: number;
  expiresIn: number;
};

export type ReservationSummary = {
  id: string;
  status: string;
  productId?: string;
  inventoryUnitId?: string;
  lockerId?: string;
  durationType?: string;
  durationValue?: number;
  quotedAmount?: number;
  preauthAmount?: number;
  expiresAt: string;
  product?: {
    id: string;
    name?: string | null;
    coverUrl?: string | null;
  };
  locker?: {
    id: string;
    name?: string | null;
    address?: string | null;
  };
  pricing?: {
    quotedAmount: number;
    preauthAmount: number;
    currency: string;
  };
};
