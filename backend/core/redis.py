import logging

from redis.asyncio import Redis

from backend.core.settings import settings

logger = logging.getLogger(__name__)

redis_client: Redis | None = None


async def init_redis() -> None:
    global redis_client

    if not settings.REDIS_URL:
        redis_client = None
        return

    client = Redis.from_url(
        settings.REDIS_URL,
        encoding="utf-8",
        decode_responses=True,
    )
    try:
        await client.ping()
    except Exception:
        logger.exception("Redis ping failed; falling back to database-only featured product state")
        await client.aclose()
        redis_client = None
        return

    redis_client = client


def get_redis_client() -> Redis | None:
    return redis_client


async def close_redis() -> None:
    global redis_client

    if redis_client is None:
        return

    await redis_client.aclose()
    redis_client = None
