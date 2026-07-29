FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN pip install --no-cache-dir poetry

COPY pyproject.toml README.md poetry.lock* ./
COPY src/ ./src/
COPY data/ ./data/
COPY alembic/ alembic/
COPY alembic.ini .

RUN poetry config virtualenvs.create false \
    && poetry install --no-interaction --no-ansi --without dev

ENTRYPOINT ["whaledecode"]
CMD ["bot"]
