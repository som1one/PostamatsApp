import sys
from dataclasses import dataclass
from decimal import Decimal
from importlib import import_module
from pathlib import Path

from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import Session

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from backend.core.database import Base
from backend.core.settings import settings
from backend.models.admin_account import AdminAccount
from backend.models.city import City
from backend.models.enums import AdminRole, InventoryStatus, LockerCellStatus, LockerStatus
from backend.models.inventory_unit import InventoryUnit
from backend.models.locker_cell import LockerCell
from backend.models.locker_location import LockerLocation
from backend.models.price_plan import PricePlan
from backend.models.product import Product
from backend.models.product_category import ProductCategory
from backend.models.product_filter import ProductFilter
from backend.utils.admin_auth_utils import hash_password


MODEL_MODULES = (
    "backend.models.admin_account",
    "backend.models.admin_audit_event",
    "backend.models.admin_auth_session",
    "backend.models.admin_user",
    "backend.models.auth_session",
    "backend.models.auth_verification_session",
    "backend.models.city",
    "backend.models.condition_report",
    "backend.models.condition_report_photo",
    "backend.models.inventory_movement",
    "backend.models.inventory_unit",
    "backend.models.locker_cell",
    "backend.models.locker_location",
    "backend.models.media_file",
    "backend.models.payment",
    "backend.models.payment_event",
    "backend.models.price_plan",
    "backend.models.product",
    "backend.models.product_filter",
    "backend.models.product_category",
    "backend.models.product_image",
    "backend.models.rental",
    "backend.models.rental_event",
    "backend.models.reservation",
    "backend.models.user",
    "backend.models.verification_request",
)


@dataclass(frozen=True)
class ProductSeed:
    category_slug: str
    slug: str
    name: str
    brand: str
    short_description: str
    full_description: str
    rules_text: str
    kit_description: str
    specs_json: dict[str, str]
    plans: list[tuple[str, str, int, str]]


CITY_SEEDS = (
    {
        "slug": "spb",
        "name": "Санкт-Петербург",
        "timezone": "Europe/Moscow",
        "sort_order": 10,
    },
    {
        "slug": "velikiy-novgorod",
        "name": "Великий Новгород",
        "timezone": "Europe/Moscow",
        "sort_order": 20,
    },
)


CATEGORY_SEEDS = (
    {"slug": "consoles", "name": "Приставки", "sort_order": 10},
    {"slug": "projectors", "name": "Проекторы", "sort_order": 20},
    {"slug": "cleaning", "name": "Уборка", "sort_order": 30},
    {"slug": "tools", "name": "Инструменты", "sort_order": 40},
    {"slug": "home", "name": "Для дома", "sort_order": 50},
)


PRODUCT_SEEDS = (
    ProductSeed(
        category_slug="consoles",
        slug="playstation-5-slim",
        name="PlayStation 5 Slim",
        brand="Sony",
        short_description="Консоль для вечерних игр дома или в гостях.",
        full_description="Аренда консоли с быстрым стартом: подключаете, входите в свой аккаунт и играете без лишних покупок.",
        rules_text="Проверьте кабели и геймпад при получении. Не оставляйте консоль без вентиляции и возвращайте комплект полностью.",
        kit_description="Консоль, геймпад DualSense, HDMI, питание, кабель USB-C для зарядки.",
        specs_json={"Разрешение": "4K", "Память": "1 ТБ", "Геймпады": "1"},
        plans=[
            ("6 часов", "hour", 6, "690"),
            ("12 часов", "hour", 12, "1090"),
            ("1 день", "day", 1, "1690"),
            ("2 дня", "day", 2, "2890"),
            ("3 дня", "day", 3, "3990"),
            ("7 дней", "day", 7, "7990"),
        ],
    ),
    ProductSeed(
        category_slug="consoles",
        slug="nintendo-switch-oled",
        name="Nintendo Switch OLED",
        brand="Nintendo",
        short_description="Портативная консоль для поездки, дачи или вечеринки.",
        full_description="Легкая консоль с OLED-экраном и быстрым стартом, чтобы взять ее на пару часов или на длинные выходные.",
        rules_text="Возвращайте консоль заряженной и без привязанных аккаунтов. Джойконы и блок питания должны быть в комплекте.",
        kit_description="Консоль, пара Joy-Con, ремешки, док-станция, блок питания, HDMI.",
        specs_json={"Экран": "7\" OLED", "Память": "64 ГБ", "Режимы": "Портативный / ТВ"},
        plans=[
            ("6 часов", "hour", 6, "490"),
            ("12 часов", "hour", 12, "790"),
            ("1 день", "day", 1, "1290"),
            ("2 дня", "day", 2, "2190"),
            ("3 дня", "day", 3, "2990"),
            ("7 дней", "day", 7, "5890"),
        ],
    ),
    ProductSeed(
        category_slug="projectors",
        slug="xgimi-mogo-2-pro",
        name="Xgimi MoGo 2 Pro",
        brand="Xgimi",
        short_description="Компактный проектор для кино, презентаций и выездов.",
        full_description="Проектор для вечера дома, дачи или быстрого показа в офисе. Удобно забрать в постамате по пути.",
        rules_text="Используйте на устойчивой поверхности, не перекрывайте вентиляцию и возвращайте с пультом и блоком питания.",
        kit_description="Проектор, пульт, питание, мягкий чехол, краткая инструкция.",
        specs_json={"Яркость": "400 ISO lm", "Разрешение": "Full HD", "Вес": "1.1 кг"},
        plans=[
            ("6 часов", "hour", 6, "590"),
            ("12 часов", "hour", 12, "950"),
            ("1 день", "day", 1, "1490"),
            ("2 дня", "day", 2, "2590"),
            ("3 дня", "day", 3, "3490"),
            ("7 дней", "day", 7, "6890"),
        ],
    ),
    ProductSeed(
        category_slug="cleaning",
        slug="karcher-se-3-compact",
        name="Karcher SE 3 Compact",
        brand="Karcher",
        short_description="Моющий пылесос для глубокой уборки мебели и салона.",
        full_description="Подходит для дивана, ковра и локальной уборки после ремонта. Берете на день и не храните технику дома.",
        rules_text="Используйте чистую воду и фирменную химию по инструкции. Перед возвратом слейте воду и протрите насадки.",
        kit_description="Пылесос, шланг, насадка для мебели, щелевая насадка, кабель питания.",
        specs_json={"Тип": "Моющий", "Бак": "1.7 л", "Кабель": "3.6 м"},
        plans=[
            ("6 часов", "hour", 6, "790"),
            ("12 часов", "hour", 12, "1190"),
            ("1 день", "day", 1, "1790"),
            ("2 дня", "day", 2, "3090"),
            ("3 дня", "day", 3, "4190"),
            ("7 дней", "day", 7, "8390"),
        ],
    ),
    ProductSeed(
        category_slug="tools",
        slug="bosch-ixo-7",
        name="Bosch IXO 7",
        brand="Bosch",
        short_description="Компактный шуруповерт для дома и быстрых задач.",
        full_description="Идеален для полок, карнизов и сборки мебели, когда инструмент нужен на пару часов, а не навсегда.",
        rules_text="Не используйте с неподходящими битами и не оставляйте инструмент под дождем. Верните все насадки в кейс.",
        kit_description="Шуруповерт, зарядка, набор бит, кейс.",
        specs_json={"Питание": "Аккумулятор", "Крутящий момент": "5.5 Нм", "Вес": "0.34 кг"},
        plans=[
            ("6 часов", "hour", 6, "290"),
            ("12 часов", "hour", 12, "450"),
            ("1 день", "day", 1, "690"),
            ("2 дня", "day", 2, "1190"),
            ("3 дня", "day", 3, "1590"),
            ("7 дней", "day", 7, "2990"),
        ],
    ),
    ProductSeed(
        category_slug="home",
        slug="dyson-am09",
        name="Dyson AM09",
        brand="Dyson",
        short_description="Тепловентилятор и вентилятор для дома на нужный сезон.",
        full_description="Берете климатическую технику на прохладные или жаркие дни, когда покупать ее ради недели просто не хочется.",
        rules_text="Не накрывайте прибор и не ставьте вплотную к тканям. Перед возвратом проверьте пульт и корпус.",
        kit_description="Прибор, пульт, кабель питания.",
        specs_json={"Режимы": "Обогрев / охлаждение", "Управление": "Пульт", "Шум": "Тихий режим"},
        plans=[
            ("6 часов", "hour", 6, "390"),
            ("12 часов", "hour", 12, "590"),
            ("1 день", "day", 1, "890"),
            ("2 дня", "day", 2, "1490"),
            ("3 дня", "day", 3, "1990"),
            ("7 дней", "day", 7, "3890"),
        ],
    ),
)


LOCKER_SEEDS = (
    {
        "city_slug": "spb",
        "external_provider": "seed",
        "external_locker_id": "seed-spb-petrogradka",
        "name": "СПб Петроградская",
        "address": "Санкт-Петербург, Каменноостровский пр., 42",
        "lat": 59.966394,
        "lon": 30.311838,
        "status": LockerStatus.OFFLINE,
        "working_hours": {"mode": "daily", "from": "09:00", "to": "22:00"},
        "inventory": {
            "nintendo-switch-oled": 1,
            "bosch-ixo-7": 2,
            "dyson-am09": 1,
        },
    },
    {
        "city_slug": "velikiy-novgorod",
        "external_provider": "esi",
        "external_locker_id": "0980",
        "name": "Великий Новгород Центр",
        "address": "Великий Новгород, Большая Санкт-Петербургская ул., 39",
        "lat": 58.533147,
        "lon": 31.269947,
        "status": LockerStatus.ONLINE,
        "working_hours": {"mode": "daily", "from": "08:00", "to": "22:00"},
        "inventory": {
            "playstation-5-slim": 1,
            "nintendo-switch-oled": 1,
            "xgimi-mogo-2-pro": 1,
        },
    },
    {
        "city_slug": "velikiy-novgorod",
        "external_provider": "seed",
        "external_locker_id": "seed-vn-west",
        "name": "Великий Новгород Западный",
        "address": "Великий Новгород, ул. Кочетова, 10",
        "lat": 58.541245,
        "lon": 31.219804,
        "status": LockerStatus.OFFLINE,
        "working_hours": {"mode": "daily", "from": "09:00", "to": "21:00"},
        "inventory": {
            "karcher-se-3-compact": 1,
            "bosch-ixo-7": 1,
            "dyson-am09": 1,
        },
    },
)


FILTER_IMAGE_SEEDS = {
    "playstation-5-slim": {
        "cover": "ps5-cover.jpg",
        "gallery": ["ps5-gallery-1.jpg"],
    },
    "nintendo-switch-oled": {
        "cover": "switch-cover.jpg",
        "gallery": ["switch-gallery-1.jpg"],
    },
    "xgimi-mogo-2-pro": {
        "cover": "projector-cover.jpg",
        "gallery": ["projector-gallery-1.jpg"],
    },
    "karcher-se-3-compact": {
        "cover": "vacuum-cover.jpg",
        "gallery": ["vacuum-gallery-1.jpg"],
    },
    "bosch-ixo-7": {
        "cover": "drill-cover.jpg",
        "gallery": ["drill-gallery-1.jpg"],
    },
    "dyson-am09": {
        "cover": "home-cover.jpg",
        "gallery": ["home-gallery-1.jpg"],
    },
}

# Базовый URL для картинок товаров.
# Приоритет: MEDIA_PUBLIC_BASE_URL > WEB_APP_ORIGIN/assets > относительный
# /assets. Относительный путь — самый безопасный fallback: он не привязан
# к схеме (http/https) и не вызывает mixed content при HTTPS-проде.
ASSET_PUBLIC_BASE_URL = (
    (settings.MEDIA_PUBLIC_BASE_URL
        or (settings.WEB_APP_ORIGIN.rstrip("/") + "/assets" if settings.WEB_APP_ORIGIN else "/assets")
    ).rstrip("/")
    + "/uploads/items"
)


def load_models() -> None:
    for module_name in MODEL_MODULES:
        import_module(module_name)


def ensure_admin(session: Session) -> None:
    admin = session.execute(
        select(AdminAccount).where(AdminAccount.login == "admin")
    ).scalar_one_or_none()
    if admin is None:
        admin = AdminAccount(
            name="Test Admin",
            login="admin",
            role=AdminRole.SUPER_ADMIN,
            password_hash=hash_password("admin"),
        )
        session.add(admin)
    else:
        admin.name = "Test Admin"
        admin.role = AdminRole.SUPER_ADMIN
        admin.password_hash = hash_password("admin")


def ensure_city(session: Session, *, slug: str, name: str, timezone: str, sort_order: int) -> City:
    city = session.execute(select(City).where(City.slug == slug)).scalar_one_or_none()
    if city is None:
        city = City(
            slug=slug,
            name=name,
            timezone=timezone,
            sort_order=sort_order,
            is_active=True,
        )
        session.add(city)
        session.flush()
    else:
        city.name = name
        city.timezone = timezone
        city.sort_order = sort_order
        city.is_active = True
    return city


def ensure_category(session: Session, *, slug: str, name: str, sort_order: int) -> ProductCategory:
    category = session.execute(
        select(ProductCategory).where(ProductCategory.slug == slug)
    ).scalar_one_or_none()
    if category is None:
        category = ProductCategory(
            slug=slug,
            name=name,
            sort_order=sort_order,
            is_active=True,
        )
        session.add(category)
        session.flush()
    else:
        category.name = name
        category.sort_order = sort_order
        category.is_active = True
    return category


def ensure_product(
    session: Session,
    *,
    category_id,
    seed: ProductSeed,
) -> Product:
    product = session.execute(select(Product).where(Product.slug == seed.slug)).scalar_one_or_none()
    if product is None:
        product = Product(
            category_id=category_id,
            slug=seed.slug,
            name=seed.name,
            brand=seed.brand,
            short_description=seed.short_description,
            full_description=seed.full_description,
            rules_text=seed.rules_text,
            kit_description=seed.kit_description,
            specs_json=seed.specs_json,
            is_active=True,
        )
        session.add(product)
        session.flush()
    else:
        product.category_id = category_id
        product.name = seed.name
        product.brand = seed.brand
        product.short_description = seed.short_description
        product.full_description = seed.full_description
        product.rules_text = seed.rules_text
        product.kit_description = seed.kit_description
        product.specs_json = seed.specs_json
        product.is_active = True
    return product


def sync_price_plans(session: Session, product: Product, plans: list[tuple[str, str, int, str]]) -> None:
    existing = {
        (plan.duration_type, plan.duration_value): plan
        for plan in session.execute(
            select(PricePlan).where(PricePlan.product_id == product.id)
        ).scalars()
    }
    keep_keys = set()
    for sort_order, (name, duration_type, duration_value, base_amount) in enumerate(plans, start=1):
        key = (duration_type, duration_value)
        keep_keys.add(key)
        plan = existing.get(key)
        if plan is None:
            plan = PricePlan(
                product_id=product.id,
                name=name,
                duration_type=duration_type,
                duration_value=duration_value,
                base_amount=Decimal(base_amount),
                currency="RUB",
                is_active=True,
                sort_order=sort_order,
            )
            session.add(plan)
        else:
            plan.name = name
            plan.base_amount = Decimal(base_amount)
            plan.currency = "RUB"
            plan.is_active = True
            plan.sort_order = sort_order

    for key, plan in existing.items():
        if key not in keep_keys:
            session.delete(plan)


def ensure_locker(
    session: Session,
    *,
    city_id,
    external_provider: str,
    external_locker_id: str,
    name: str,
    address: str,
    lat: float,
    lon: float,
    status: LockerStatus,
    working_hours: dict[str, str],
) -> LockerLocation:
    """Создаёт или обновляет dev-постамат.

    Поиск идёт по паре (`external_provider`, `external_locker_id`). Это
    важно: один и тот же сидовый постамат не должен дублироваться, если
    мы поменяли его провайдер с `seed` на `esi`. Поэтому если первая
    попытка ничего не нашла — пробуем найти по `external_locker_id` без
    учёта провайдера, чтобы безопасно перенести существующий локер на
    новый провайдер вместо создания дубля.
    """

    locker = session.execute(
        select(LockerLocation).where(
            LockerLocation.external_provider == external_provider,
            LockerLocation.external_locker_id == external_locker_id,
        )
    ).scalar_one_or_none()

    if locker is None:
        locker = session.execute(
            select(LockerLocation).where(
                LockerLocation.external_locker_id == external_locker_id,
            )
        ).scalar_one_or_none()

    partner_name = "Dev Seed" if external_provider == "seed" else "ESI"

    if locker is None:
        locker = LockerLocation(
            city_id=city_id,
            external_provider=external_provider,
            external_locker_id=external_locker_id,
            name=name,
            address=address,
            lat=Decimal(str(lat)),
            lon=Decimal(str(lon)),
            status=status,
            partner_name=partner_name,
            working_hours_json=working_hours,
        )
        session.add(locker)
        session.flush()
    else:
        locker.city_id = city_id
        locker.external_provider = external_provider
        locker.external_locker_id = external_locker_id
        locker.name = name
        locker.address = address
        locker.lat = Decimal(str(lat))
        locker.lon = Decimal(str(lon))
        locker.status = status
        locker.partner_name = partner_name
        locker.working_hours_json = working_hours
    return locker


def rebuild_locker_inventory(
    session: Session,
    *,
    locker: LockerLocation,
    inventory_map: dict[str, int],
    products_by_slug: dict[str, Product],
) -> None:
    existing_cells = session.execute(
        select(LockerCell).where(LockerCell.locker_id == locker.id)
    ).scalars().all()
    existing_cell_ids = [cell.id for cell in existing_cells]

    if existing_cell_ids:
        session.execute(
            delete(InventoryUnit).where(InventoryUnit.locker_cell_id.in_(existing_cell_ids))
        )
        session.execute(delete(LockerCell).where(LockerCell.id.in_(existing_cell_ids)))
        session.flush()

    index = 1
    for product_slug, count in inventory_map.items():
        product = products_by_slug[product_slug]
        for unit_number in range(1, count + 1):
            cell = LockerCell(
                locker_id=locker.id,
                external_cell_id=f"{locker.external_locker_id}-cell-{index:02d}",
                label=f"A{index}",
                size="M",
                status=LockerCellStatus.OCCUPIED,
                supports_return=True,
            )
            session.add(cell)
            session.flush()

            unit = InventoryUnit(
                product_id=product.id,
                locker_cell_id=cell.id,
                serial_number=f"{locker.external_locker_id.upper()}-{product.slug.upper()}-{unit_number}",
                barcode=f"{locker.external_locker_id}-{product.slug}-{unit_number}",
                status=InventoryStatus.AVAILABLE,
                condition_grade="A",
                condition_note="Готов к аренде",
            )
            session.add(unit)
            index += 1

    for empty_index in range(2):
        cell = LockerCell(
            locker_id=locker.id,
            external_cell_id=f"{locker.external_locker_id}-empty-{empty_index + 1}",
            label=f"B{empty_index + 1}",
            size="L",
            status=LockerCellStatus.VACANT,
            supports_return=True,
        )
        session.add(cell)


def ensure_product_filter(
    session: Session,
    *,
    product: Product,
    cover_url: str,
    gallery_urls: list[str],
) -> None:
    product_filter = session.execute(
        select(ProductFilter).where(ProductFilter.product_id == product.id)
    ).scalar_one_or_none()

    if product_filter is None:
        product_filter = ProductFilter(
            product_id=product.id,
            is_active=True,
        )
        session.add(product_filter)

    product_filter.cover_url = cover_url
    product_filter.gallery_urls_json = gallery_urls
    product_filter.is_active = True


def sync_product_filters(session: Session, products_by_slug: dict[str, Product]) -> None:
    for slug, image_seed in FILTER_IMAGE_SEEDS.items():
        product = products_by_slug.get(slug)
        if product is None:
            continue

        cover_url = f"{ASSET_PUBLIC_BASE_URL}/{image_seed['cover']}"
        gallery_urls = [
            f"{ASSET_PUBLIC_BASE_URL}/{file_name}"
            for file_name in image_seed["gallery"]
        ]
        ensure_product_filter(
            session,
            product=product,
            cover_url=cover_url,
            gallery_urls=gallery_urls,
        )


def main() -> None:
    if not settings.DB_URL:
        raise RuntimeError("DB_URL is not configured")

    load_models()
    engine = create_engine(settings.DB_URL)
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        ensure_admin(session)

        cities_by_slug = {
            seed["slug"]: ensure_city(
                session,
                slug=seed["slug"],
                name=seed["name"],
                timezone=seed["timezone"],
                sort_order=seed["sort_order"],
            )
            for seed in CITY_SEEDS
        }

        categories_by_slug = {
            seed["slug"]: ensure_category(
                session,
                slug=seed["slug"],
                name=seed["name"],
                sort_order=seed["sort_order"],
            )
            for seed in CATEGORY_SEEDS
        }

        products_by_slug: dict[str, Product] = {}
        for seed in PRODUCT_SEEDS:
            product = ensure_product(
                session,
                category_id=categories_by_slug[seed.category_slug].id,
                seed=seed,
            )
            sync_price_plans(session, product, seed.plans)
            products_by_slug[seed.slug] = product

        for seed in LOCKER_SEEDS:
            locker = ensure_locker(
                session,
                city_id=cities_by_slug[seed["city_slug"]].id,
                external_provider=seed["external_provider"],
                external_locker_id=seed["external_locker_id"],
                name=seed["name"],
                address=seed["address"],
                lat=seed["lat"],
                lon=seed["lon"],
                status=seed["status"],
                working_hours=seed["working_hours"],
            )
            rebuild_locker_inventory(
                session,
                locker=locker,
                inventory_map=seed["inventory"],
                products_by_slug=products_by_slug,
            )

        sync_product_filters(session, products_by_slug)
        session.commit()

    print("Dev backend seed completed.")
    print("Cities: Санкт-Петербург, Великий Новгород")
    print("Admin: login=admin password=admin")


if __name__ == "__main__":
    main()
