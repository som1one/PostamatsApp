from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from backend.core.settings import settings
from backend.models.enums import MediaFileKind
from backend.models.media_file import MediaFile
from backend.models.product import Product
from backend.models.product_image import ProductImage
from backend.utils.local_storage import store_local_upload
from backend.utils.uploads_utils import bucket_for_media_kind

ROOT_DIR = Path(__file__).resolve().parents[1]


def _normalize_db_url(raw_url: str | None) -> str | None:
    if not raw_url:
        return None
    normalized = raw_url.strip()
    if normalized.startswith("sqlite+aiosqlite://"):
        return "sqlite://" + normalized[len("sqlite+aiosqlite://") :]
    if normalized.startswith("postgresql+asyncpg://"):
        return "postgresql+psycopg2://" + normalized[len("postgresql+asyncpg://") :]
    return normalized


def _get_db_url() -> str:
    db_url = _normalize_db_url(settings.DB_URL or settings.ASYNC_DB_URL)
    if not db_url:
        raise RuntimeError("DB_URL is not set")
    return db_url


def replace_product_image(session: Session, product_name_like: str, image_filename: str) -> None:
    # Find the product
    product = session.scalar(select(Product).where(Product.name.ilike(f"%{product_name_like}%")))
    if not product:
        print(f"Product matching '{product_name_like}' not found.")
        return

    # Read the seed image
    seed_image_path = ROOT_DIR / "assets" / "uploads" / "seed_images" / image_filename
    if not seed_image_path.exists():
        print(f"Seed image not found: {seed_image_path}")
        return

    image_bytes = seed_image_path.read_bytes()
    file_key = f"uploads/items/{image_filename}"

    # Upsert MediaFile
    media = session.scalar(select(MediaFile).where(MediaFile.file_key == file_key))
    if not media:
        media = MediaFile(
            storage_provider="local",
            bucket=bucket_for_media_kind(MediaFileKind.PRODUCT_COVER),
            file_key=file_key,
            mime_type="image/webp",
            file_size=len(image_bytes),
            original_name=image_filename,
            kind=MediaFileKind.PRODUCT_COVER,
            created_at=datetime.now(UTC),
        )
        session.add(media)
        session.flush()

    # Store file in local storage
    store_local_upload(file_key, image_bytes)

    # Update Product cover
    product.cover_file_id = media.id

    # Update Product gallery (replace with this single image)
    existing_images = session.scalars(select(ProductImage).where(ProductImage.product_id == product.id)).all()
    for img in existing_images:
        session.delete(img)
    
    session.add(ProductImage(product_id=product.id, file_id=media.id, sort_order=0))
    print(f"Updated images for product: {product.name}")


def main() -> None:
    engine = create_engine(_get_db_url())
    with Session(engine) as session:
        replace_product_image(session, "JBL Partybox", "jbl-partybox-520.webp")
        replace_product_image(session, "Karcher WD 5", "karcher-wd5.webp")
        replace_product_image(session, "Караоке", "karaoke.webp")
        replace_product_image(session, "Puzzi", "puzzi-101.webp")
        replace_product_image(session, "sup board", "sup-board.webp")
        session.commit()
    print("All specified products updated.")


if __name__ == "__main__":
    main()
