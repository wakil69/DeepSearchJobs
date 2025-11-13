#!/bin/bash

ENV_FILE="./backend/db/.env"
if [[ -f "$ENV_FILE" ]]; then
  echo "Loading environment from $ENV_FILE"
  set -a
  source "$ENV_FILE"
  set +a
else
  echo "ERROR: $ENV_FILE not found (expected from repo root)."
  exit 1
fi

ELASTIC_USER="${ELASTIC_USER:-elastic}"
ES_PASS="${ELASTIC_PASSWORD:-admin}"

curl -u $ES_USER:$ES_PASS -X POST "http://localhost:9200/all_jobs/_delete_by_query" \
  -H 'Content-Type: application/json' \
  -d '{
    "query": {
      "term": {
        "__deleted": "true"
      }
    }
  }'

curl -u $ES_USER:$ES_PASS -X POST "http://localhost:9200/all_jobs/_delete_by_query" \
  -H 'Content-Type: application/json' \
  -d '{
    "query": {
      "term": {
        "is_existing": false
      }
    }
  }'

curl -u $ES_USER:$ES_PASS -X POST "http://localhost:9200/companies/_delete_by_query" \
  -H 'Content-Type: application/json' \
  -d '{
    "query": {
      "term": {
        "__deleted": "true"
      }
    }
  }'



