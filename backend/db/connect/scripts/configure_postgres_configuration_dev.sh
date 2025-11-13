#!/bin/bash
set -e  # Exit on error

echo "Starting PostgreSQL logical replication configuration (local setup)..."

# -----------------------------
# Load environment variables
# -----------------------------
ENV_FILE="./backend/db/.env"

if [[ -f "$ENV_FILE" ]]; then
  echo "Loading environment from $ENV_FILE"
  set -a
  source "$ENV_FILE"
  set +a
else
  echo "ERROR: $ENV_FILE not found (expected at ../../.env)"
  exit 1
fi

# -----------------------------
# Resolve connection variables
# -----------------------------
PG_HOST="${PG_HOST_DEV}"
PG_PORT="${PG_PORT}"
PG_USER="${PG_USER_DEV}"
PG_PASSWORD="${PG_PASSWORD_DEV}"
PG_DB="${PG_DATABASE_DEV}"

DEBEZIUM_USER="${DEBEZIUM_USER}"
DEBEZIUM_PASS="${DEBEZIUM_PWD}"

echo "Connecting to PostgreSQL at $PG_HOST:$PG_PORT (DB: $PG_DB, User: $PG_USER)"

# -----------------------------
# Wait for PostgreSQL to be ready
# -----------------------------
echo "Waiting for PostgreSQL to be ready..."
until PGPASSWORD=$PG_PASSWORD pg_isready -h "$PG_HOST" -p "$PG_PORT" -U "$PG_USER" -d "$PG_DB" > /dev/null 2>&1; do
  sleep 3
  echo "Still waiting for PostgreSQL..."
done
echo "PostgreSQL is ready."

# -----------------------------
# Find PostgreSQL config files
# -----------------------------
CONF_FILE=$(PGPASSWORD=$PG_PASSWORD psql -h "$PG_HOST" -p "$PG_PORT" -U "$PG_USER" -d "$PG_DB" -Atc "SHOW config_file;")
HBA_FILE=$(PGPASSWORD=$PG_PASSWORD psql -h "$PG_HOST" -p "$PG_PORT" -U "$PG_USER" -d "$PG_DB" -Atc "SHOW hba_file;")

echo "PG_HOSTConfiguration file: $CONF_FILE"
echo "PG_HOSTHBA file: $HBA_FILE"

# -----------------------------
# Update configuration for logical replication
# -----------------------------
echo "Updating PostgreSQL settings for logical replication..."

sudo bash -c "
  grep -q '^wal_level = logical' $CONF_FILE || echo 'wal_level = logical' >> $CONF_FILE
  grep -q '^max_replication_slots' $CONF_FILE || echo 'max_replication_slots = 10' >> $CONF_FILE
  grep -q '^max_wal_senders' $CONF_FILE || echo 'max_wal_senders = 10' >> $CONF_FILE

  grep -q 'debezium_user' $HBA_FILE || echo '
host replication ${DEBEZIUM_USER} 127.0.0.1/32       md5
host all         ${DEBEZIUM_USER} 127.0.0.1/32       md5
host all         all              172.17.0.0/16      md5
' >> $HBA_FILE
"

# -----------------------------
# Restart PostgreSQL
# -----------------------------
echo "PG_HOST Restarting PostgreSQL to apply changes..."
if command -v systemctl > /dev/null; then
  sudo systemctl restart postgresql
elif command -v brew > /dev/null; then
  brew services restart postgresql
else
  echo "PG_HOST Unable to detect PostgreSQL service manager. Please restart it manually."
fi

sleep 5
echo "PG_HOST PostgreSQL restarted successfully."

# -----------------------------
# Create replication user & publication
# -----------------------------
echo "PG_HOST Creating Debezium replication user and publication..."

PGPASSWORD=$PG_PASSWORD psql -h "$PG_HOST" -p "$PG_PORT" -U "$PG_USER" -d "$PG_DB" <<EOF
DO \$\$
BEGIN
   IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '${DEBEZIUM_USER}') THEN
      CREATE USER ${DEBEZIUM_USER} WITH REPLICATION PASSWORD '$DEBEZIUM_PASS';
   END IF;
END
\$\$;

GRANT CONNECT ON DATABASE $PG_DB TO ${DEBEZIUM_USER};
GRANT USAGE ON SCHEMA public TO ${DEBEZIUM_USER};
GRANT SELECT ON ALL TABLES IN SCHEMA public TO ${DEBEZIUM_USER};
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO ${DEBEZIUM_USER};

DO \$\$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_publication WHERE pubname = 'debezium_publication'
  ) THEN
    CREATE PUBLICATION debezium_publication FOR TABLE all_jobs, companies;
  END IF;
END
\$\$;
EOF

echo "Verifying connection with Debezium user..."

# Get the host IP for clarity (works on Linux & macOS)
HOST_IP=$(hostname -I 2>/dev/null | awk '{print $1}')
if [[ -z "$HOST_IP" ]]; then
  # Fallback for systems where hostname -I isn’t available (like macOS)
  HOST_IP=$(ipconfig getifaddr en0 2>/dev/null || echo "unknown")
fi

echo "Current host IP: $HOST_IP"
echo "Target PostgreSQL: $PG_HOST:$PG_PORT (DB: $PG_DB, User: $DEBEZIUM_USER)"

# Try until the connection works
until PGPASSWORD=$DEBEZIUM_PASS psql -h "$PG_HOST" -p "$PG_PORT" -U "$DEBEZIUM_USER" -d "$PG_DB" -c "SELECT NOW();" > /dev/null 2>&1; do
  echo "Still trying to connect as $DEBEZIUM_USER to $PG_HOST:$PG_PORT..."
  sleep 2
done

echo "Connection successful with Debezium user ($DEBEZIUM_USER)!"
echo "Host IP: $HOST_IP  →  PostgreSQL: $PG_HOST:$PG_PORT"
echo "Local PostgreSQL logical replication setup complete!"
