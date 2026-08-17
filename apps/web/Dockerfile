FROM node:20-alpine AS base

WORKDIR /app

COPY package.json package-lock.json turbo.json /app/
COPY apps /app/apps
COPY packages /app/packages

RUN npm ci

FROM base AS dev

EXPOSE 3000

CMD ["npm", "run", "dev", "--workspace", "@leitesol/web"]

FROM base AS builder

RUN npm run build --workspace @leitesol/contracts \
    && npm run build --workspace @leitesol/web

FROM nginx:1.27-alpine AS prod

ENV PORT=3000
ENV API_PROXY_PASS=http://gateway:3001/api/
ENV HEALTH_PROXY_PASS=http://gateway:3001/health/

COPY apps/web/nginx.conf /etc/nginx/templates/default.conf.template
COPY --from=builder /app/apps/web/dist /usr/share/nginx/html

EXPOSE 3000
