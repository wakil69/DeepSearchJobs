#!/bin/bash
set -e

# Build the base worker
cd base_worker

IMAGE_NAME_DEEPSEARCHJOBS_BASE="deepsearchjobs-base"

if docker image inspect "$IMAGE_NAME_DEEPSEARCHJOBS_BASE" >/dev/null 2>&1; then
  echo "Docker image '$IMAGE_NAME_DEEPSEARCHJOBS_BASE' already exists. Skipping build."
else
  echo "Building Docker image '$IMAGE_NAME_DEEPSEARCHJOBS_BASE'..."
  docker build -t "$IMAGE_NAME_DEEPSEARCHJOBS_BASE" .
  echo "Docker image '$IMAGE_NAME_DEEPSEARCHJOBS_BASE' built successfully."
fi

cd ..

# Start Docker Compose
docker compose down
docker compose up -d --build

# Configuration paths
CONNECT_CONTAINER="connect"
CONNECT_SCRIPT_PATH="/scripts/set_connectors.sh"
CONFIGURE_DB_SCRIPT="/scripts/configure_postgres_configuration.sh"
DB_DIR="/app/dist/db/drizzle"

# Database local connection info to postgres container
PG_HOST=localhost
PG_PORT=5433
PG_USER=admin
PG_PASSWORD=admin
PG_DB=play2path

# Ensure database exists
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


# Run Drizzle migrations inside the backend container
echo "Running Drizzle migrations inside backend container..."
docker compose exec backend-play2path bash -c "
  if [ -d '$DB_DIR' ]; then
    echo 'Found directory $DB_DIR. Running migrations...';
    cd '$DB_DIR' && NODE_ENV=production npx drizzle-kit push;
    echo 'Database schema is up to date.';
  else
    echo 'ERROR: Directory $DB_DIR not found inside container.';
    exit 1;
  fi
"


# Configure PostgreSQL (run inside the container)
echo "Configuring PostgreSQL for Debezium..."

docker exec -i postgres-play2path bash -c "
  if [ -f '/scripts/configure_postgres_configuration.sh' ]; then
    echo 'Running /scripts/configure_postgres_configuration.sh...'
    bash /scripts/configure_postgres_configuration.sh
  else
    echo 'ERROR: Script not found at /scripts/configure_postgres_configuration.sh inside container.'
    exit 1
  fi
"

# Run connector setup
echo "Running connector setup inside '$CONNECT_CONTAINER'..."
docker compose exec -T -e NODE_ENV=production "$CONNECT_CONTAINER" bash "$CONNECT_SCRIPT_PATH"

echo "Production environment is ready."
