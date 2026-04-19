# CaseOps web container — Next.js 15, multi-stage build for slim
# production image. Runs `next start` in production mode (NOT
# `next dev`); Cloud Run injects PORT.
#
# Build context is apps/web/ — the root .dockerignore already
# excludes node_modules/, .next/, etc., so the COPY layers stay lean.

# ---- deps ---------------------------------------------------------
FROM node:22.14.0-alpine AS deps
WORKDIR /app

# In this monorepo the package-lock.json lives at the repo root
# (npm workspaces). `gcloud builds submit apps/web` uses apps/web
# as the build context, so the lockfile isn't present here — hence
# `npm install` (not `npm ci`). A future refactor could submit the
# repo root as build context and keep `npm ci` for determinism.
#
# Installing *all* deps (including dev) is intentional here: tailwind,
# postcss, typescript, and next's build plugins are in devDependencies
# but are REQUIRED by the builder stage below. The final runtime
# stage prunes back to prod-only via `npm prune --omit=dev`.
COPY package.json ./
RUN npm install --no-audit --no-fund

# ---- builder ------------------------------------------------------
FROM node:22.14.0-alpine AS builder
WORKDIR /app

ENV NEXT_TELEMETRY_DISABLED=1

# Next.js inlines NEXT_PUBLIC_* env vars at BUILD time. The Cloud Run
# runtime env never gets to override them — so we set them here via
# build args. Defaults target the custom domain; Cloud Build passes
# the current .run.app URLs via --substitutions during a first-boot
# deploy before the domain mapping is live.
ARG NEXT_PUBLIC_API_BASE_URL=https://api.caseops.ai
ARG NEXT_PUBLIC_APP_URL=https://caseops.ai
ARG NEXT_PUBLIC_GA_MEASUREMENT_ID=
ENV NEXT_PUBLIC_API_BASE_URL=$NEXT_PUBLIC_API_BASE_URL
ENV NEXT_PUBLIC_APP_URL=$NEXT_PUBLIC_APP_URL
ENV NEXT_PUBLIC_GA_MEASUREMENT_ID=$NEXT_PUBLIC_GA_MEASUREMENT_ID

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
# This project has no /public directory — Next.js serves assets via
# app/icon.tsx, app/opengraph-image.tsx, app/robots.txt, app/sitemap.xml
# (file-based conventions). Nothing to copy.
COPY --from=builder --chown=nextjs:nodejs /app/node_modules ./node_modules
COPY --from=builder --chown=nextjs:nodejs /app/package.json ./package.json

# Prune devDependencies in the runtime layer — they were needed by
# the builder stage (tailwind, postcss, typescript, next plugins)
# but not at runtime. Drops the final image by ~200 MB.
RUN npm prune --omit=dev --no-audit --no-fund 2>/dev/null || true

USER nextjs

CMD ["sh", "-c", "npx next start -p ${PORT}"]
