FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Upgrade pip first: poetry shells out to `pip uninstall/install` during
# reinstall cycles, and old pip + old top-level attrs crashes with
# "module 'attr.setters' has no attribute 'pipe'" inside vendored rich.
RUN pip install --no-cache-dir --upgrade pip "attrs>=22.2"
RUN pip install --no-cache-dir poetry

COPY pyproject.toml README.md poetry.lock* ./
COPY src/ ./src/
COPY data/ ./data/
COPY alembic/ alembic/
COPY alembic.ini .
COPY scripts/ ./scripts

RUN poetry config virtualenvs.create false \
    && poetry install --no-interaction --no-ansi --without dev

ENTRYPOINT ["whaledecode"]
CMD ["serve"]
