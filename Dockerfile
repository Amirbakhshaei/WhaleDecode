FROM python:3.14-slim

WORKDIR /app

RUN pip install --no-cache-dir poetry

COPY pyproject.toml poetry.lock* ./
COPY src/ ./src/
COPY alembic/ alembic/
COPY alembic.ini .
COPY scripts/ scripts/

RUN poetry config virtualenvs.create false \
    && poetry install --no-interaction --no-ansi --without dev

ENTRYPOINT ["whaledecode"]
