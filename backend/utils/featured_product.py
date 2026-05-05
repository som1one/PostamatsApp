import asyncio
import json
import logging
import threading
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from random import Random
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import select

from backend.core.database import SessionLocal
from backend.core.redis import get_redis_client
from backend.models.featured_product_state import FeaturedProductState
from backend.models.product import Product
from backend.utils.product_filters import is_product_visible, load_product_filters_by_product_ids
from backend.utils.products_utils import aggregate_available_globally

logger = logging.getLogger(__name__)

MOSCOW_TZ = ZoneInfo("Europe/Moscow")
FEATURED_SPOTLIGHT_KEY = "product_of_day"
FEATURED_SPOTLIGHT_CACHE_KEY = "featured_product:state"
FEATURED_SWITCH_HOUR = 12


@dataclass(slots=True)
class FeaturedProductSnapshot:
    spotlight_key: str
    product_id: UUID
    active_date: date


def now_in_moscow() -> datetime:
    return datetime.now(MOSCOW_TZ)


def featured_product_business_date(now: datetime | None = None) -> date:
    current = now or now_in_moscow()
    if current.timetz().replace(tzinfo=None) >= time(hour=FEATURED_SWITCH_HOUR):
        return current.date()
    return current.date() - timedelta(days=1)


def seconds_until_next_featured_rotation(now: datetime | None = None) -> float:
    current = now or now_in_moscow()
    next_rotation = datetime.combine(
        current.date(),
        time(hour=FEATURED_SWITCH_HOUR),
        tzinfo=MOSCOW_TZ,
    )
    if current >= next_rotation:
        next_rotation = next_rotation + timedelta(days=1)
    return max((next_rotation - current).total_seconds(), 1.0)


def featured_cache_ttl_seconds(now: datetime | None = None) -> int:
    return max(int(seconds_until_next_featured_rotation(now)) + 5, 5)


def snapshot_from_state(state: FeaturedProductState) -> FeaturedProductSnapshot:
    return FeaturedProductSnapshot(
        spotlight_key=state.spotlight_key,
        product_id=state.product_id,
        active_date=state.active_date,
    )


async def cache_featured_product_state(snapshot: FeaturedProductSnapshot) -> None:
    redis = get_redis_client()
    if redis is None:
        return

    payload = json.dumps(
        {
            "spotlightKey": snapshot.spotlight_key,
            "productId": str(snapshot.product_id),
            "activeDate": snapshot.active_date.isoformat(),
        }
    )
    try:
        await redis.set(FEATURED_SPOTLIGHT_CACHE_KEY, payload, ex=featured_cache_ttl_seconds())
    except Exception:
        logger.exception("Failed to cache featured product state in Redis")


async def clear_cached_featured_product_state() -> None:
    redis = get_redis_client()
    if redis is None:
        return
    try:
        await redis.delete(FEATURED_SPOTLIGHT_CACHE_KEY)
    except Exception:
        logger.exception("Failed to clear featured product state from Redis")


async def get_cached_featured_product_state() -> FeaturedProductSnapshot | None:
    redis = get_redis_client()
    if redis is None:
        return None

    try:
        payload = await redis.get(FEATURED_SPOTLIGHT_CACHE_KEY)
    except Exception:
        logger.exception("Failed to read featured product state from Redis")
        return None

    if not payload:
        return None

    try:
        data = json.loads(payload)
        return FeaturedProductSnapshot(
            spotlight_key=str(data["spotlightKey"]),
            product_id=UUID(str(data["productId"])),
            active_date=date.fromisoformat(str(data["activeDate"])),
        )
    except Exception:
        logger.exception("Invalid featured product payload in Redis cache")
        return None


async def pick_featured_product_id(target_date: date) -> UUID | None:
    async with SessionLocal() as db:
        unit_counts, _ = await aggregate_available_globally(db)
        candidate_ids = [product_id for product_id, count in unit_counts.items() if count > 0]
        if not candidate_ids:
            return None

        products = list(
            (
                await db.scalars(
                    select(Product)
                    .where(Product.id.in_(candidate_ids), Product.is_active.is_(True))
                    .order_by(Product.slug.asc(), Product.name.asc())
                )
            ).all()
        )
        if not products:
            return None

        filters_by_product_id = await load_product_filters_by_product_ids(
            db,
            [product.id for product in products],
        )
        visible_products = [
            product
            for product in products
            if is_product_visible(product, filters_by_product_id.get(product.id))
        ]
        if not visible_products:
            return None

        visible_products.sort(key=lambda product: (product.slug, product.name, str(product.id)))
        randomizer = Random(f"{target_date.isoformat()}::{len(visible_products)}")
        return randomizer.choice(visible_products).id


async def sync_featured_product_state(
    target_date: date | None = None,
) -> FeaturedProductSnapshot | None:
    feature_date = target_date or featured_product_business_date()
    product_id = await pick_featured_product_id(feature_date)
    if product_id is None:
        await clear_cached_featured_product_state()
        return None

    async with SessionLocal() as db:
        state = await db.get(FeaturedProductState, FEATURED_SPOTLIGHT_KEY)
        if state is None:
            state = FeaturedProductState(
                spotlight_key=FEATURED_SPOTLIGHT_KEY,
                product_id=product_id,
                active_date=feature_date,
            )
            db.add(state)
        else:
            state.product_id = product_id
            state.active_date = feature_date

        await db.commit()
        await db.refresh(state)

    snapshot = FeaturedProductSnapshot(
        spotlight_key=FEATURED_SPOTLIGHT_KEY,
        product_id=product_id,
        active_date=feature_date,
    )
    await cache_featured_product_state(snapshot)
    return snapshot


async def get_featured_product_state() -> FeaturedProductSnapshot | None:
    target_date = featured_product_business_date()

    cached = await get_cached_featured_product_state()
    if cached is not None and cached.active_date == target_date:
        return cached

    async with SessionLocal() as db:
        state = await db.get(FeaturedProductState, FEATURED_SPOTLIGHT_KEY)
        if state is not None and state.active_date == target_date:
            snapshot = snapshot_from_state(state)
            await cache_featured_product_state(snapshot)
            return snapshot

    return await sync_featured_product_state(target_date)


def featured_product_scheduler_worker(
    loop: asyncio.AbstractEventLoop,
    stop_event: threading.Event,
) -> None:
    try:
        asyncio.run_coroutine_threadsafe(sync_featured_product_state(), loop).result()
        while not stop_event.wait(seconds_until_next_featured_rotation() + 1):
            asyncio.run_coroutine_threadsafe(sync_featured_product_state(), loop).result()
    except Exception:
        logger.exception("Featured product scheduler worker stopped unexpectedly")


def start_featured_product_scheduler(
    loop: asyncio.AbstractEventLoop,
) -> tuple[threading.Thread, threading.Event]:
    stop_event = threading.Event()
    worker = threading.Thread(
        target=featured_product_scheduler_worker,
        args=(loop, stop_event),
        name="featured-product-scheduler",
        daemon=True,
    )
    worker.start()
    return worker, stop_event


async def stop_featured_product_scheduler(
    worker: threading.Thread | None,
    stop_event: threading.Event | None,
) -> None:
    if worker is None or stop_event is None:
        return

    stop_event.set()
    await asyncio.to_thread(worker.join, 5)
