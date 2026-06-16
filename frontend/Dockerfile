# Materia frontend image. Two stages:
#   1) "build"  — Node compiles the React app into static files (dist/).
#   2) final    — Caddy serves those files AND reverse-proxies /api to the backend,
#                 giving us one front door with automatic HTTPS in production.

# ── Stage 1: build the static site ───────────────────────────────────────────
FROM node:20-alpine AS build
WORKDIR /app

# Install deps first (cached unless package files change).
COPY package.json package-lock.json ./
RUN npm ci

# Build. VITE_API_BASE_URL is empty by default → the app calls relative "/api",
# which Caddy proxies to the backend on the same origin.
COPY . .
RUN npm run build

# ── Stage 2: serve with Caddy ────────────────────────────────────────────────
FROM caddy:2-alpine
# Static files Caddy will serve.
COPY --from=build /app/dist /srv
# Front-door config (static files + /api reverse proxy + optional HTTPS).
COPY Caddyfile /etc/caddy/Caddyfile

EXPOSE 80 443
