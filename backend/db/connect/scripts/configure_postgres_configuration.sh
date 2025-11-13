#!/bin/bash
set -e

POSTGRES_USER="admin"
POSTGRES_DB="play2path"
DEBEZIUM_USER="debezium_user_play2path"
DEBEZIUM_PASS="admin"

CONF_FILE='/var/lib/postgresql/data/postgresql.conf'
HBA_FILE='/var/lib/postgresql/data/pg_hba.conf'

echo "Configuring PostgreSQL logical replication..."

# Ensure logical replication parameters
su postgres -c "grep -q '^wal_level = logical' $CONF_FILE || echo 'wal_level = logical' >> $CONF_FILE"
su postgres -c "grep -q '^max_replication_slots' $CONF_FILE || echo 'max_replication_slots = 10' >> $CONF_FILE"
su postgres -c "grep -q '^max_wal_senders' $CONF_FILE || echo 'max_wal_senders = 10' >> $CONF_FILE"

# Add replication access rules
su postgres -c "grep -q '$DEBEZIUM_USER' $HBA_FILE || echo '
host replication ${DEBEZIUM_USER} 0.0.0.0/0 md5
host all          ${DEBEZIUM_USER} 0.0.0.0/0 md5
' >> $HBA_FILE"

# Reload Postgres (no need to restart the whole container)
su postgres -c "pg_ctl reload -D /var/lib/postgresql/data"

# Create replication user and publication
su postgres -c "psql -U $POSTGRES_USER -d $POSTGRES_DB" <<EOF
DO \$\$
BEGIN
   IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '$DEBEZIUM_USER') THEN
      CREATE USER $DEBEZIUM_USER WITH REPLICATION PASSWORD '$DEBEZIUM_PASS';
   END IF;
END
\$\$;

GRANT CONNECT ON DATABASE play2path TO $DEBEZIUM_USER;
GRANT USAGE ON SCHEMA public TO $DEBEZIUM_USER;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO $DEBEZIUM_USER;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO $DEBEZIUM_USER;

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

echo "PostgreSQL replication setup complete!"
