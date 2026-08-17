FROM node:20-alpine AS base

WORKDIR /app

COPY package.json package-lock.json turbo.json /app/
COPY apps /app/apps
COPY packages /app/packages

RUN npm ci

FROM base AS dev

ENV PORT=3001
ENV BACKEND_URL=http://api:5000
ENV CORS_ORIGINS=http://localhost:3000

EXPOSE 3001

CMD ["npm", "run", "dev", "--workspace", "@leitesol/gateway"]

FROM base AS builder

RUN npm run build --workspace @leitesol/contracts \
    && npm run build --workspace @leitesol/gateway

FROM node:20-alpine AS prod

WORKDIR /app

ENV NODE_ENV=production
ENV PORT=3001
ENV BACKEND_URL=http://api:5000

COPY --from=base /app/node_modules /app/node_modules
COPY --from=builder /app/apps/gateway/dist /app/apps/gateway/dist
COPY --from=builder /app/apps/gateway/package.json /app/apps/gateway/package.json
COPY --from=builder /app/packages /app/packages

WORKDIR /app/apps/gateway

EXPOSE 3001

CMD ["npm", "run", "start"]
