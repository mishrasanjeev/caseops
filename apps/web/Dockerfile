# CaseOps web container — Next.js 15, multi-stage build for slim
# production image. Runs `next start` in production mode (NOT
# `next dev`); Cloud Run injects PORT.
#
# Build context is the repository root so the immutable workspace lockfile is
# available. Root .dockerignore/.gcloudignore files admit only package metadata
# and apps/web, keeping both the Docker context and Cloud Build upload narrow.

# ---- deps ---------------------------------------------------------
FROM node:22.14.0-alpine AS deps
WORKDIR /app

# Installing *all* deps (including dev) is intentional here: tailwind,
# postcss, typescript, and next's build plugins are in devDependencies
# but are REQUIRED by the builder stage below. The final runtime
# stage copies a separately pruned dependency tree.
COPY package.json package-lock.json ./
COPY apps/web/package.json ./apps/web/package.json
RUN npm ci --no-audit --no-fund

FROM deps AS prod-deps
RUN npm prune --omit=dev --no-audit --no-fund

# ---- builder ------------------------------------------------------
FROM deps AS builder
WORKDIR /app/apps/web

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

COPY apps/web ./

RUN npm run build

# ---- runner -------------------------------------------------------
FROM node:22.14.0-alpine AS runner
WORKDIR /app/apps/web

ARG CASEOPS_RELEASE_SHA=unavailable
LABEL org.opencontainers.image.revision=$CASEOPS_RELEASE_SHA

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
COPY --from=builder --chown=nextjs:nodejs /app/apps/web/.next ./.next
# This project has no /public directory — Next.js serves assets via
# app/icon.tsx, app/opengraph-image.tsx, app/robots.txt, app/sitemap.xml
# (file-based conventions). Nothing to copy.
COPY --from=prod-deps --chown=nextjs:nodejs /app/node_modules /app/node_modules
COPY --from=prod-deps --chown=nextjs:nodejs /app/apps/web/node_modules ./node_modules
COPY --from=builder --chown=nextjs:nodejs /app/apps/web/package.json ./package.json

USER nextjs

CMD ["sh", "-c", "node /app/node_modules/next/dist/bin/next start -p ${PORT}"]
