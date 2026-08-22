#!/usr/bin/env sh
# Exit immediately if any command exits with a non-zero status
set -e

echo "Running database migrations..."
alembic upgrade head  # Replace with python -m app.db.migrate if using a custom script

echo "Executing secondary setup task..."
python -m app.initial_data