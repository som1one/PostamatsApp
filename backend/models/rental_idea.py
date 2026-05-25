from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from backend.core.database import Base


class RentalIdea(Base):
    """Заявка с публичной формы 'Идея для аренды'.

    Доступна гостям без авторизации, поэтому FK на пользователя нет.
    Фото опционально и привязывается к существующей таблице media_files
    (через kind=RENTAL_IDEA_PHOTO).
    """

    __tablename__ = "rental_ideas"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    idea: Mapped[str] = mapped_column(Text, nullable=False)
    reference_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    photo_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("media_files.id"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
