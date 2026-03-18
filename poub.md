docker compose -f docker-compose-dev.yml exec -T -e NODE_ENV=development connect bash ./backend/db/connect/scripts/set_connectors.sh
