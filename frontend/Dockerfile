# --------------------------------------------------
# Build Stage — compile Vite app
# --------------------------------------------------
FROM node:22-alpine AS builder

WORKDIR /app

# Copy package files first for caching
COPY package*.json ./

RUN npm ci

# Copy all project files
COPY . .

# Build the production-ready static files
RUN npm run build

# --------------------------------------------------
# Run Stage — serve static files with Node
# --------------------------------------------------
FROM node:22-alpine AS runner

WORKDIR /app

# Copy only the built files
COPY --from=builder /app/dist ./dist

RUN npm install -g serve

EXPOSE 3000

CMD ["serve", "-s", "dist", "-l", "3000"]
