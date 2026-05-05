FROM node:22-alpine AS deps

WORKDIR /app/web

COPY web/package.json web/package-lock.json ./
RUN npm ci

FROM node:22-alpine AS builder

WORKDIR /app/web

COPY --from=deps /app/web/node_modules ./node_modules
COPY web ./

ARG NEXT_PUBLIC_API_BASE_URL
ARG NEXT_PUBLIC_YANDEX_MAPS_API_KEY=""

ENV NEXT_PUBLIC_API_BASE_URL=${NEXT_PUBLIC_API_BASE_URL}
ENV NEXT_PUBLIC_YANDEX_MAPS_API_KEY=${NEXT_PUBLIC_YANDEX_MAPS_API_KEY}

RUN npm run build

FROM node:22-alpine

WORKDIR /app/web
ENV NODE_ENV=production

COPY web/package.json web/package-lock.json ./
RUN npm ci --omit=dev

COPY --from=builder /app/web/.next ./.next
COPY --from=builder /app/web/public ./public
COPY --from=builder /app/web/next.config.mjs ./next.config.mjs

EXPOSE 3001

CMD ["npm", "run", "start"]

