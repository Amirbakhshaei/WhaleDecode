FROM python:3.14-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    build-essential \
    libssl-dev \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir poetry

COPY pyproject.toml README.md poetry.lock* ./
COPY src/ ./src/
COPY alembic/ alembic/
COPY alembic.ini .
COPY scripts/ scripts/

RUN poetry config virtualenvs.create false \
    && poetry install --no-interaction --no-ansi --without dev

ENTRYPOINT ["whaledecode"]
CMD ["bot"]
