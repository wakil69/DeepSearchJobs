#!/bin/bash
set -e

echo "======================================="
echo " Cleaning up old processes..."
echo "======================================="

# Kill old processes
pkill -9 -f "python -m worker_async.main" || true
pkill -9 -f "python -m worker_sync.main" || true
pkill -9 -f "playwright" || true
pkill -9 -f "npm run dev" || true
pkill -9 -f "concurrently" || true
pkill -9 -f "nodemon" || true
pkill -9 -f "vite" || true
pkill -f "chrome --type=renderer" || true
pkill -f "chrome --no-sandbox" || true
pkill -f "chromium" || true

echo "Old processes (if any) terminated."

# Flush Redis if available
if command -v redis-cli >/dev/null 2>&1; then
    echo "Deleting Redis keys with prefixes: company_jobs* and check_jobs*"

    for prefix in company_jobs check_jobs; do
        echo "Flushing keys for prefix: $prefix*"
        redis-cli --scan --pattern "${prefix}*" | xargs -r redis-cli del
    done

    echo "Redis selective flush complete."
else
    echo "redis-cli not found — skipping Redis prefix flush."
fi

###############################################
# Poetry Setup
###############################################
if command -v poetry >/dev/null 2>&1; then
    poetry config virtualenvs.in-project true
    echo "Installing PyTorch via Poetry..."
    poetry add torch==2.9.0 --source pytorch || true
    echo "PyTorch installation complete."

    echo "Installing remaining project dependencies..."
    poetry install --no-interaction --no-ansi
else
    echo "ERROR: Poetry not found. Please install Poetry before running this script."
    exit 1
fi



###############################################
# Node.js Dependency Installation
###############################################
echo "======================================="
echo " Installing Node.js dependencies..."
echo "======================================="

# FRONTEND
if [ -d "frontend" ]; then
    echo "Installing frontend dependencies..."
    cd frontend
    npm install
    cd -
else
    echo "WARNING: 'frontend' directory not found — skipping frontend npm install."
fi

# BACKEND
if [ -d "backend" ]; then
    echo "Installing backend dependencies..."
    cd backend
    npm install
    cd -
else
    echo "WARNING: 'backend' directory not found — skipping backend npm install."
fi

###############################################
# Environment Setup
###############################################
export NODE_ENV=development
echo "NODE_ENV set to $NODE_ENV"

# Configuration paths
COMPOSE_FILE="docker-compose-dev.yml"
CONNECT_CONTAINER="connect"
CONNECT_SCRIPT_PATH="/scripts/set_connectors.sh"
CONFIGURE_DB_SCRIPT="./backend/db/connect/scripts/configure_postgres_configuration_dev.sh"
DB_DIR="./backend/db/drizzle"
ENV_FILE="./backend/db/.env"


###############################################
# Load DB Environment Variables
###############################################
if [[ -f "$ENV_FILE" ]]; then
  echo "Loading environment variables from $ENV_FILE"
  set -a
  source "$ENV_FILE"
  set +a
else
  echo "ERROR: $ENV_FILE not found."
  exit 1
fi

# Database connection info
PG_HOST="${PG_HOST_DEV}"
PG_PORT="${PG_PORT}"
PG_USER="${PG_USER_DEV}"
PG_PASSWORD="${PG_PASSWORD_DEV}"
PG_DB="${PG_DATABASE_DEV}"

###############################################
# Docker Compose
###############################################
echo "Starting development environment..."
docker compose -f "$COMPOSE_FILE" down
docker compose -f "$COMPOSE_FILE" up -d --build

###############################################
# Ensure DB Exists
###############################################
echo "Checking if database '$PG_DB' exists on $PG_HOST:$PG_PORT..."
DB_EXISTS=$(PGPASSWORD="$PG_PASSWORD" psql -U "$PG_USER" -h "$PG_HOST" -p "$PG_PORT" -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname='$PG_DB';" || echo "error")

if [[ "$DB_EXISTS" == "1" ]]; then
  echo "Database '$PG_DB' already exists."
elif [[ "$DB_EXISTS" == "error" ]]; then
  echo "Could not connect to PostgreSQL at $PG_HOST:$PG_PORT. Please check credentials."
  exit 1
else
  echo "Creating database '$PG_DB'..."
  PGPASSWORD="$PG_PASSWORD" psql -U "$PG_USER" -h "$PG_HOST" -p "$PG_PORT" -d postgres -c "CREATE DATABASE \"$PG_DB\";"
  echo "Database '$PG_DB' created successfully."
fi


###############################################
# Run Drizzle Migrations
###############################################
if [ -d "$DB_DIR" ]; then
  echo "Running Drizzle migrations..."
  cd "$DB_DIR"
  npx drizzle-kit generate
  npx drizzle-kit push
  cd - > /dev/null
  echo "Database schema is up to date."
else
  echo "ERROR: Directory $DB_DIR not found."
  exit 1
fi

###############################################
# PostgreSQL Debezium Configuration
###############################################
if [ -f "$CONFIGURE_DB_SCRIPT" ]; then
  echo "Configuring PostgreSQL for Debezium..."
  bash "$CONFIGURE_DB_SCRIPT"
else
  echo "ERROR: Database configuration script not found at $CONFIGURE_DB_SCRIPT"
  exit 1
fi

###############################################
# Activate Python Virtual Env
###############################################
if [ -f ".venv/bin/activate" ]; then
  source .venv/bin/activate
else
  echo "ERROR: Python virtual environment not found at .venv/"
  exit 1
fi

###############################################
# Install Playwright Dependencies
###############################################
echo "Installing Playwright dependencies..."
playwright install-deps

###############################################
# Connectors Setup
###############################################
echo "Running connector setup inside '$CONNECT_CONTAINER'..."
docker compose -f "$COMPOSE_FILE" exec -T -e NODE_ENV=development "$CONNECT_CONTAINER" bash "$CONNECT_SCRIPT_PATH"


###############################################
# Start Frontend + Workers
###############################################
NODE_ENV=development WORKER_ID=analyser python -m worker_async.main & \
NODE_ENV=development WORKER_ID=checker python -m worker_async.main & \
npm run dev

echo "======================================="
echo " Development environment is ready!"
echo "======================================="
