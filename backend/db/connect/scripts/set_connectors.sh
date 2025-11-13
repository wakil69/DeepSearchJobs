#!/bin/bash
set -e

# ==============================
# Register Kafka Connect connectors (idempotent)
# ==============================

CONNECT_URL="http://connect:8083"
ELASTIC_URL="http://elasticsearch:9200"

# ==============================
# Load Postgres credentials from backend/db/.env
# ==============================
NODE_ENV=${NODE_ENV}
echo "Current environment: $NODE_ENV"

ENV_FILE="/env/.env"
if [[ -f "$ENV_FILE" ]]; then
  echo "Loading environment from $ENV_FILE"
  set -a
  source "$ENV_FILE"
  set +a
else
  echo "ERROR: $ENV_FILE not found (expected from repo root)."
  exit 1
fi

if [[ "$NODE_ENV" == "development" ]]; then
  PG_HOST="${PG_HOST_DEV}"
  PG_DB="${PG_DATABASE_DEV}"
  PG_USER="${DEBEZIUM_USER}"
  PG_PASS="${PG_PASSWORD_DEV}"
else
  PG_HOST="${PG_HOST}"
  PG_DB="${PG_DATABASE}"
  PG_USER="${DEBEZIUM_USER}"
  PG_PASS="${PG_PASSWORD}"
fi

PG_PORT="${PG_PORT}"

# Elasticsearch credentials (if enabled)
ES_USER="elastic"
ES_PASS="${ELASTIC_PASSWORD:-changeme}"

# ========== Helper function ==========
register_connector () {
  local NAME=$1
  local CONFIG=$2

  echo "Registering connector: $NAME ....."

  # Check if connector exists
  local STATUS=$(curl -s -o /dev/null -w "%{http_code}" "$CONNECT_URL/connectors/$NAME")

  if [[ "$STATUS" == "200" ]]; then
    echo "deep-search-jobs-networkUpdating existing connector $NAME"
    RESPONSE=$(curl -s -w "\nHTTP_STATUS:%{http_code}" -X PUT \
      "$CONNECT_URL/connectors/$NAME/config" \
      -H "Content-Type: application/json" \
      -d "$CONFIG")
  else
    echo "Creating new connector $NAME"
    RESPONSE=$(curl -s -w "\nHTTP_STATUS:%{http_code}" -X POST \
      "$CONNECT_URL/connectors" \
      -H "Content-Type: application/json" \
      -d "{
        \"name\": \"$NAME\",
        \"config\": $CONFIG
      }")
  fi

  # Parse response
  HTTP_BODY=$(echo "$RESPONSE" | sed -e 's/HTTP_STATUS\:.*//g')
  HTTP_STATUS=$(echo "$RESPONSE" | tr -d '\n' | sed -e 's/.*HTTP_STATUS://')

  if [[ "$HTTP_STATUS" -ge 200 && "$HTTP_STATUS" -lt 300 ]]; then
    echo "Connector $NAME configured successfully."
  else
    echo "ERROR configuring connector $NAME (HTTP $HTTP_STATUS):"
    echo "$HTTP_BODY"
  fi
}

# ========== Wait for Connect ==========
echo "Waiting for Kafka Connect to be available at $CONNECT_URL ...."
until curl -s $CONNECT_URL/connectors > /dev/null; do
  sleep 5
  echo "   Still waiting for Kafka Connect..."
done
echo "Kafka Connect is UP."

# ========== Wait for Elasticsearch ==========
echo "Waiting for Elasticsearch to be available at $ELASTIC_URL ...."
until curl -s -u "$ES_USER:$ES_PASS" "$ELASTIC_URL/_cluster/health" | grep -q '"status"'; do
  sleep 5
  echo "   Still waiting for Elasticsearch..."
done
echo "Elasticsearch is UP."

# ========== Check available plugins ==========
echo "Checking available connector plugins...."
AVAILABLE_PLUGINS=$(curl -s $CONNECT_URL/connector-plugins | grep -o '"class":"[^"]*' | cut -d'"' -f4)


# ========== Debezium PostgreSQL Connector ==========
if echo "$AVAILABLE_PLUGINS" | grep -q "io.debezium.connector.postgresql.PostgresConnector"; then
  register_connector "postgres-connector" "{
    \"connector.class\": \"io.debezium.connector.postgresql.PostgresConnector\",
    \"tasks.max\": \"1\",
    \"database.hostname\": \"$PG_HOST\",
    \"database.port\": \"$PG_PORT\",
    \"database.user\": \"$PG_USER\",
    \"database.password\": \"$PG_PASS\",
    \"database.dbname\": \"$PG_DB\",
    \"plugin.name\": \"pgoutput\",
    \"slot.name\": \"debezium_slot_play2path\",
    \"publication.name\": \"debezium_publication\",
    \"publication.autocreate.mode\": \"disabled\",
    \"table.include.list\": \"public.all_jobs,public.companies\",
    \"topic.prefix\": \"pg\",
    \"topic.naming.strategy\": \"io.debezium.schema.SchemaTopicNamingStrategy\",
    \"topic.delimiter\": \"_\",
    \"producer.override.max.request.size\": \"10485760\",
    \"producer.override.buffer.memory\": \"20971520\",
    \"tombstones.on.delete\": \"true\",
    \"snapshot.mode\": \"initial\"
  }"
else
  echo "companiesDebezium PostgreSQL connector not available."
fi

# ========== Elasticsearch Sink Connectors ==========
if echo "$AVAILABLE_PLUGINS" | grep -q "io.confluent.connect.elasticsearch.ElasticsearchSinkConnector"; then
  for table in all_jobs companies; do
    register_connector "es-sink-$table" "{
      \"connector.class\": \"io.confluent.connect.elasticsearch.ElasticsearchSinkConnector\",
      \"tasks.max\": \"1\",
      \"topics\": \"pg_public_${table}\",
      \"connection.url\": \"$ELASTIC_URL\",
      \"connection.username\": \"$ES_USER\",
      \"connection.password\": \"$ES_PASS\",
      \"key.ignore\": \"false\",
      \"schema.ignore\": \"true\",
      \"delete.enabled\": \"true\",
      \"behavior.on.null.values\": \"delete\",
      \"auto.create.indices.at.start\": \"true\",
      \"producer.override.max.request.size\": \"10485760\",
      \"producer.override.buffer.memory\": \"20971520\",
      \"consumer.override.max.partition.fetch.bytes\": \"12582912\",
      \"consumer.override.fetch.max.bytes\": \"12582912\",
      \"flush.synchronously\": \"true\",
      \"transforms\": \"unwrap,addKey,extractId,cleanFields,route\",
      \"transforms.unwrap.type\": \"io.debezium.transforms.ExtractNewRecordState\",
      \"transforms.unwrap.drop.tombstones\": \"true\",
      \"transforms.unwrap.delete.tombstone.handling.mode\": \"rewrite\",
      \"transforms.addKey.type\": \"org.apache.kafka.connect.transforms.ValueToKey\",
      \"transforms.addKey.fields\": \"id\",
      \"transforms.extractId.type\": \"org.apache.kafka.connect.transforms.ExtractField\$Key\",
      \"transforms.extractId.field\": \"id\",
      \"transforms.cleanFields.type\": \"org.apache.kafka.connect.transforms.ReplaceField\$Value\",
      \"transforms.cleanFields.blacklist\": \"job_description\",
      \"transforms.route.type\": \"org.apache.kafka.connect.transforms.RegexRouter\",
      \"transforms.route.regex\": \"pg_public_(.*)\",
      \"transforms.route.replacement\": \"\$1\"
    }"
  done
else
  echo "companiesElasticsearch Sink connector not available."
fi

echo "companiesAll connectors registered for all_jobs and companies."