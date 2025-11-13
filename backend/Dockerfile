# ================================
# Build stage
# ================================
FROM node:22-slim AS builder

WORKDIR /app

# Copy dependency files first for better caching
COPY package*.json ./

# Install all dependencies
RUN npm ci

COPY . .

# Build the TypeScript app
RUN npm run build

# Copy non-TypeScript assets explicitly
RUN mkdir -p dist/src dist/db && \
    # Copy DB assets
    cp -r db/connect dist/db/ && \
    mkdir -p dist/db/drizzle && \
    cp -r db/drizzle/migrations dist/db/drizzle/ && \
    cp db/.env dist/db/.env || true && \
    # Copy src/locales for translations
    cp -r src/locales dist/src/locales
    
# ================================
# Production stage
# ================================
FROM node:22-slim AS runner

WORKDIR /app

COPY package*.json ./
RUN npm ci --omit=dev

# Copy compiled files and any required assets
COPY --from=builder /app/dist ./dist

EXPOSE 4000

# Start Fastify
CMD ["node", "dist/src/app.js"]
