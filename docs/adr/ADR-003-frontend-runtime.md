# ADR-003 — React + Vite on ECS rather than Next.js or S3/CloudFront

> **Status:** Accepted
> **Date:** 2026-08-21
> **Related:** [07 — Frontend](../07-frontend.md), [08 — Infrastructure](../08-infrastructure.md)

## Context

The requirements mandate **ECS** and state that both services must be **deployed
independently**. Two questions followed: which frontend framework, and where it runs.

## Decision

**React 19 + Vite + TypeScript, built to static assets, served by nginx in a container,
running as its own ECS Fargate service.**

### Not Next.js

Every view is behind authentication and driven by streaming state. There is no SSR, no
SEO, and no server-component requirement. Next.js would add a Node runtime and a second
server process to operate and patch, for no functional gain.

### Not S3 + CloudFront for the SPA

S3 + CloudFront would be cheaper (~$1/month against ~$9) and operationally simpler. It
was rejected because **the requirements mandate ECS**, and serving the SPA from a
container makes that true of *both* services rather than one — which is also what makes
"deployed independently" concrete: two Dockerfiles, two ECR repositories, two ECS
services, two task definitions, two pipeline jobs.

Choosing the cheaper option here would have meant satisfying a stated requirement for
half the system and explaining why the other half was different.

## Consequences

**Good**
- Both services genuinely satisfy the ECS requirement.
- Independent deployability is structural, not asserted — a frontend failure cannot block
  a backend release.
- nginx image is ~10 MB; ARM64 to match Fargate.
- Runtime configuration is fetched from `/api/v1/meta` rather than baked at build, so one
  image is promotable across environments.

**Bad**
- ~$0.0123/hour for a task that serves static files — CloudFront would do it for cents.
- An nginx configuration to maintain (SPA fallback, security headers, gzip).
- The SPA cold-starts with the task under scale-to-zero
  ([ADR-007](ADR-007-durable-sqlite-via-s3.md) §1).

**Note:** CloudFront is in the design regardless — but as the TLS and WAF edge in front
of the private ALB ([ADR-005](ADR-005-runtime-and-persistence.md) §2), not as an origin
for S3-hosted assets.
