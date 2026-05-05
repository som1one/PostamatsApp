FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

COPY alembic ./alembic
COPY backend/alembic.ini ./alembic.ini
RUN sed -i 's#%(here)s/../alembic#%(here)s/alembic#' /app/alembic.ini \
 && sed -i 's#%(here)s/..#%(here)s#' /app/alembic.ini
COPY backend ./backend
COPY admin ./admin
COPY assets ./assets

EXPOSE 8000

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
