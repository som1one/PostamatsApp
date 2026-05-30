from enum import Enum


class VerificationStatus(str, Enum):
    DRAFT = "draft"
    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    BLOCKED = "blocked"


class AdminRole(str, Enum):
    SUPER_ADMIN = "super_admin"
    OPERATOR = "operator"


class PushPlatform(str, Enum):
    IOS = "ios"
    ANDROID = "android"
    HUAWEI = "huawei"
    WEB = "web"


class AuthPlatform(str, Enum):
    IOS = "ios"
    ANDROID = "android"
    HUAWEI = "huawei"
    WEB = "web"
    ADMIN = "admin"


class AuthVerificationSessionStatus(str, Enum):
    PENDING = "pending"
    VERIFIED = "verified"
    EXPIRED = "expired"
    FAILED = "failed"


class MediaFileKind(str, Enum):
    VERIFICATION_FRONT = "verification_front"
    VERIFICATION_BACK = "verification_back"
    VERIFICATION_SELFIE = "verification_selfie"
    PRODUCT_COVER = "product_cover"
    PRODUCT_GALLERY = "product_gallery"
    INCIDENT_ATTACHMENT = "incident_attachment"
    CONDITION_PHOTO_BEFORE = "condition_photo_before"
    CONDITION_PHOTO_AFTER = "condition_photo_after"
    RENTAL_IDEA_PHOTO = "rental_idea_photo"


class DocumentType(str, Enum):
    PASSPORT_RF = "passport_rf"
    DRIVING_LICENSE = "driving_license"
    NATIONAL_ID = "national_id"
    OTHER = "other"


class LockerStatus(str, Enum):
    ONLINE = "online"
    OFFLINE = "offline"
    MAINTENANCE = "maintenance"
    DEGRADED = "degraded"


class LockerCellStatus(str, Enum):
    VACANT = "vacant"
    OCCUPIED = "occupied"
    RESERVED = "reserved"
    OPENED = "opened"
    FAULT = "fault"
    DISABLED = "disabled"


class InventoryStatus(str, Enum):
    AVAILABLE = "available"
    RESERVED = "reserved"
    RENTED = "rented"
    RETURN_PENDING = "return_pending"
    DAMAGED = "damaged"
    MAINTENANCE = "maintenance"
    LOST = "lost"
    RETIRED = "retired"


class ConditionReportType(str, Enum):
    BEFORE_PICKUP = "before_pickup"
    AFTER_RETURN = "after_return"
    INCIDENT_REVIEW = "incident_review"


class ReservationStatus(str, Enum):
    CREATED = "created"
    AWAITING_PAYMENT = "awaiting_payment"
    PAYMENT_AUTHORIZED = "payment_authorized"
    CONFIRMED = "confirmed"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


class PaymentType(str, Enum):
    PREAUTH = "preauth"
    CAPTURE = "capture"
    CANCEL = "cancel"
    REFUND = "refund"
    EXTRA_CHARGE = "extra_charge"


class PaymentStatus(str, Enum):
    CREATED = "created"
    PENDING = "pending"
    AUTHORIZED = "authorized"
    CAPTURED = "captured"
    CANCELLED = "cancelled"
    FAILED = "failed"
    REFUNDED = "refunded"


class RentalStatus(str, Enum):
    PICKUP_READY = "pickup_ready"
    PICKUP_OPENED = "pickup_opened"
    ACTIVE = "active"
    RETURN_IN_PROGRESS = "return_in_progress"
    COMPLETED = "completed"
    OVERDUE = "overdue"
    INCIDENT = "incident"
    CANCELLED = "cancelled"


class RentalEventSource(str, Enum):
    SYSTEM = "system"
    USER = "user"
    ADMIN = "admin"
    PAYMENT_WEBHOOK = "payment_webhook"
    LOCKER_WEBHOOK = "locker_webhook"


class ReturnRequestStatus(str, Enum):
    CREATED = "created"
    LOCKER_OPENED = "locker_opened"
    AWAITING_CLOSE = "awaiting_close"
    COMPLETED = "completed"
    FAILED = "failed"


class ConversationStatus(str, Enum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    CLOSED = "closed"


class MessageAuthorType(str, Enum):
    CLIENT = "client"
    OPERATOR = "operator"
