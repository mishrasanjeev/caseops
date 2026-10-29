# CaseOps web container — Next.js 15, multi-stage build for slim
# production image. Runs `next start` in production mode (NOT
# `next dev`); Cloud Run injects PORT.
#
# Build context is the repository root so the immutable workspace lockfile is
# available. Root .dockerignore/.gcloudignore files admit only package metadata
# and apps/web plus the explicit builder-only unit fixture dependency closure.

# Keep the pinned Node root set except the compromised emSign ECC G3 root.
# This store also applies to npm/build processes, before any package download.
FROM node:22.23.4-alpine AS trusted-base
COPY apps/web/scripts/node-trust.cjs apps/web/scripts/node-trust-start.cjs /opt/caseops/trust/
RUN node /opt/caseops/trust/node-trust.cjs --generate \
  && chmod 0444 /opt/caseops/trust/*.cjs \
  && chmod 0555 /opt/caseops/trust
ENV NODE_OPTIONS=--use-openssl-ca \
    SSL_CERT_FILE=/opt/caseops/trust/ca-bundle.pem \
    SSL_CERT_DIR=/opt/caseops/trust/empty

# ---- deps ---------------------------------------------------------
FROM trusted-base AS deps
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
ENV NEXT_PUBLIC_API_BASE_URL=$NEXT_PUBLIC_API_BASE_URL
ENV NEXT_PUBLIC_APP_URL=$NEXT_PUBLIC_APP_URL

COPY apps/web ./
# One colocated page test imports this canonical fixture during Next's type
# check. Keep it in the builder context only; the runner copies no test files.
COPY tests/fixtures/statutes/structured-schedule-api.json /app/tests/fixtures/statutes/structured-schedule-api.json
COPY tests/fixtures/node-default-tls-probe.cjs /app/tests/fixtures/node-default-tls-probe.cjs
# Colocated diagnostic units require their direct and transitive support imports.
# Admit this explicit closure in both root ignore files; keep it out of the runner.
COPY tests/e2e/support/prod-failure-diagnostics.ts /app/tests/e2e/support/prod-failure-diagnostics.ts
COPY tests/e2e/support/bounded-network-evidence.ts /app/tests/e2e/support/bounded-network-evidence.ts
COPY tests/e2e/support/prod-api-response-evidence.ts /app/tests/e2e/support/prod-api-response-evidence.ts
COPY tests/e2e/support/cost-controls.ts /app/tests/e2e/support/cost-controls.ts
COPY tests/e2e/support/public-release-identity.ts /app/tests/e2e/support/public-release-identity.ts
COPY tests/e2e/support/ip-import-acknowledgements.ts /app/tests/e2e/support/ip-import-acknowledgements.ts
COPY tests/e2e/support/ip-portfolio-export-completion.ts /app/tests/e2e/support/ip-portfolio-export-completion.ts

RUN npm run build

# ---- runner -------------------------------------------------------
FROM trusted-base AS runner
WORKDIR /app/apps/web

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
# Keep distributed font and JavaScript copyright/licence notices reachable.
COPY --from=builder --chown=nextjs:nodejs /app/apps/web/public ./public
# Operator compliance materials are deliberately outside every public asset root.
COPY --chown=nextjs:nodejs license-policy/reviewed-packages.json /app/third-party-compliance/license-policy/reviewed-packages.json
COPY --chown=nextjs:nodejs license-policy/upstream/ /app/third-party-compliance/license-policy/upstream/
COPY --chown=nextjs:nodejs docs/security/js-license-compliance-review-2026-10-12.md /app/third-party-compliance/docs/security/js-license-compliance-review-2026-10-12.md
COPY --from=builder --chown=nextjs:nodejs /app/apps/web/public/third-party-notices /app/third-party-compliance/apps/web/public/third-party-notices
COPY --from=prod-deps --chown=nextjs:nodejs /app/node_modules /app/node_modules
COPY --from=builder --chown=nextjs:nodejs /app/apps/web/package.json ./package.json

ARG CASEOPS_RELEASE_SHA=unavailable
LABEL org.opencontainers.image.revision=$CASEOPS_RELEASE_SHA

USER nextjs

CMD ["sh", "-c", "exec node --use-openssl-ca --require /opt/caseops/trust/node-trust-start.cjs /app/node_modules/next/dist/bin/next start -p ${PORT}"]
