# CaseOps web container — Next.js 15, multi-stage build for slim
# production image. Runs `next start` in production mode (NOT
# `next dev`); Cloud Run injects PORT.
#
# Build context is apps/web/ — the root .dockerignore already
# excludes node_modules/, .next/, etc., so the COPY layers stay lean.

# ---- deps ---------------------------------------------------------
FROM node:22.14.0-alpine AS deps
WORKDIR /app

# Use the lockfile for deterministic installs. npm ci is faster +
# stricter than `npm install` in CI/CD because it errors on lockfile
# drift instead of silently rewriting it.
COPY package.json package-lock.json* ./
RUN npm ci

# ---- builder ------------------------------------------------------
FROM node:22.14.0-alpine AS builder
WORKDIR /app

ENV NEXT_TELEMETRY_DISABLED=1

COPY --from=deps /app/node_modules ./node_modules
COPY . .

RUN npm run build

# ---- runner -------------------------------------------------------
FROM node:22.14.0-alpine AS runner
WORKDIR /app

ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000

# Drop root for the running container.
RUN addgroup -g 1001 -S nodejs \
  && adduser -S nextjs -u 1001

# Next.js standalone output (when configured) drops a self-contained
# server. We're not on standalone yet — copy the full build + node_
# modules. Switch to standalone in `next.config.js` later for a
# smaller image.
COPY --from=builder --chown=nextjs:nodejs /app/.next ./.next
COPY --from=builder --chown=nextjs:nodejs /app/public ./public
COPY --from=builder --chown=nextjs:nodejs /app/node_modules ./node_modules
COPY --from=builder --chown=nextjs:nodejs /app/package.json ./package.json

USER nextjs

CMD ["sh", "-c", "npx next start -p ${PORT}"]
