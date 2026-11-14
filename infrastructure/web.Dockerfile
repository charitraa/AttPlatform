# syntax=docker/dockerfile:1
# Production edge image: the built SPA + Nginx (TLS, security headers, reverse proxy to the backend).
# Build from the repository root:  docker build -f infrastructure/web.Dockerfile -t att-web .

FROM node:24-alpine AS build
RUN corepack enable
WORKDIR /app
COPY frontend/package.json frontend/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile
COPY frontend/ .
ARG VITE_API_BASE_URL=/api/v1
ARG VITE_WS_URL=
# Shown as "Request a demo" on the landing page (hidden when empty)
ARG VITE_CONTACT_EMAIL=
RUN pnpm build

FROM nginx:1.27-alpine
RUN rm /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
COPY infrastructure/nginx-prod/att.conf /etc/nginx/conf.d/att.conf
COPY infrastructure/nginx-prod/snippets/ /etc/nginx/snippets/
EXPOSE 80 443
HEALTHCHECK --interval=30s --timeout=5s --retries=3 CMD wget -q --spider --no-check-certificate https://localhost/ || exit 1
