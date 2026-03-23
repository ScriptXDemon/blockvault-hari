FROM node:20-bookworm-slim AS build

WORKDIR /app

COPY package.json package-lock.json tsconfig.base.json /app/
COPY apps/web /app/apps/web
COPY packages/contracts /app/packages/contracts
COPY packages/ui /app/packages/ui

RUN npm ci --no-audit --fetch-retries=5 --fetch-retry-mintimeout=20000 --fetch-retry-maxtimeout=120000

ARG VITE_API_BASE_URL=http://127.0.0.1:8000
ENV VITE_API_BASE_URL=${VITE_API_BASE_URL}

RUN npm run build:web


FROM nginx:1.27-alpine

COPY infra/nginx.web.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/apps/web/dist /usr/share/nginx/html

EXPOSE 80
