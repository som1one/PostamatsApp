export type ApiEnvelope<T> = {
  data: T;
  meta?: {
    page?: number;
    limit?: number;
    total?: number;
    [key: string]: unknown;
  };
};

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
  lat?: number | null;
  lon?: number | null;
  status: "online" | "offline" | "maintenance" | "degraded";
  workingHours?: {
    mode?: string;
    from?: string;
    to?: string;
  } | null;
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
  categoryName?: string | null;
  name: string;
  slug: string;
  coverUrl?: string | null;
  shortDescription?: string | null;
  brand?: string | null;
  priceFrom: number;
  currency: string;
  available: boolean;
  availableLockerCount: number;
  availableUnitCount?: number;
};

export type FeaturedProduct = {
  product: ProductListItem;
  activeDate: string;
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
  documentName?: string;
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

export type UpcomingReservation = {
  id: string;
  status: string;
  expiresAt: string;
  cancelledAt?: string | null;
  cancelReason?: string | null;
  product: {
    id: string;
    name?: string | null;
    coverUrl?: string | null;
  };
  locker: {
    id: string;
    name?: string | null;
    address?: string | null;
  };
};

export type PaymentSummary = {
  id: string;
  type: string;
  status: string;
  amount: number;
  currency: string;
  failureCode?: string | null;
  failureMessage?: string | null;
  processedAt?: string | null;
};

export type PreauthResponse = {
  payment: PaymentSummary;
  confirmation?: {
    type?: string;
    confirmationUrl?: string | null;
  };
};

export type PresignUploadResponse = {
  fileId: string;
  fileKey: string;
  uploadUrl: string;
  method: "PUT" | "POST";
  headers: Record<string, string>;
  expiresIn: number;
};

export type RentalListItem = {
  id: string;
  status: string;
  cancelReason?: string | null;
  plannedEndAt?: string | null;
  actualEndAt?: string | null;
  product: {
    id: string;
    name?: string | null;
    coverUrl?: string | null;
  };
  locker: {
    id: string;
    name?: string | null;
  };
};

export type RentalDetail = {
  id: string;
  status: string;
  pickupPin?: string | null;
  startsAt?: string | null;
  plannedEndAt?: string | null;
  actualEndAt?: string | null;
  product: {
    id: string;
    name?: string | null;
    coverUrl?: string | null;
  };
  pickupLocker: {
    id: string;
    name?: string | null;
    address?: string | null;
  };
  paymentSummary: {
    preauthAmount: number;
    capturedAmount: number;
    currency: string;
  };
  events: Array<{
    id: string;
    eventType: string;
    fromStatus?: string | null;
    toStatus?: string | null;
    source: string;
    createdAt: string;
  }>;
  reservationId?: string | null;
};
