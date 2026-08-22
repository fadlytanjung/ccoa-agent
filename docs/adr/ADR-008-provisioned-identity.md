# ADR-008 — Provisioned identity in Cognito, not application-managed users

> **Status:** Accepted — 2026-08-23
> **Supersedes:** nothing. Refines the identity half of
> [ADR-005](ADR-005-runtime-and-persistence.md).
> **Related:** [10 — Security](10-security.md) §3.1a, [18](18-aws-access-and-manual-steps.md) §7

## Context

The requirement is narrow and worth stating exactly, because it is not "authentication":

> Testers must not be able to create their own accounts. Access is granted deliberately
> when the system is deployed, so that the public cannot use the application — which would
> spend the project's model quota.

Two designs were on the table.

**A — Cognito, with self-registration disabled.** The design already specified
([ADR-005](ADR-005-runtime-and-persistence.md)), already implemented on both sides: JWT
verification with a JWKS cache that fails closed, and Authorization Code + PKCE in the SPA.

**B — Application-managed users.** Drop Cognito. Seed an admin account on first run, add an
admin-only endpoint to create users, store password hashes in the project's SQLite
database, and issue the application's own tokens.

B was raised for a good reason: Cognito *looked* hard. Sign-in did not work, and the path
from nothing to a working pool was a console runbook rather than a command.

## Decision

**Keep Cognito, and disable self-registration explicitly.**

The premise that made B attractive turned out to be false. Cognito was not hard; it was
*undone*. `scripts/aws-cognito.sh` now provisions the pool, the groups, the domain, and a
public app client in one command, and adds users with
`--add-user someone@example.test`. The pool exists, and the first sign-in works.

The requirement is met by one setting, `AllowAdminCreateUserOnly = true`, applied on create
and re-applied on every run so a drifted pool is corrected rather than reported.

## Why not application-managed users

Not effort — B is perhaps a day. The objection is what that day *buys*: ownership of
security-critical machinery that has to be right forever, in exchange for removing a
dependency the project already has.

| Concern | Cognito | Owned by this project under B |
|---|---|---|
| Password hashing and parameters | Managed, and updated without a deploy | A choice that quietly ages; today's parameters are next year's weakness |
| Credential storage | Never in our database | Hashes in SQLite, replicated to S3 by Litestream ([ADR-007](ADR-007-durable-sqlite-via-s3.md)) — a credential store in an object store |
| Brute force and lockout | Built in | To be written, and to be tested, and to be got right |
| Password reset | Hosted flow | Email delivery, single-use tokens, expiry |
| Session revocation | Token revocation endpoint | To be designed |
| Token verification | **Already implemented and tested** | Replaced with something new |

The database row is the decisive one. This project replicates its SQLite file to S3 for
durability. Under B that file contains password hashes, which turns a durability mechanism
into credential distribution and pulls every bucket policy into the blast radius of a
credential breach. That is a real change in what an S3 misconfiguration would cost, taken
on to avoid a dependency that is free at this scale and already built.

There is also a smaller, more embarrassing risk: B ends with a **default admin password
seeded on first run**. Every such password is a permanent invitation until someone
remembers to change it, and this repository is public, so the default would be published
alongside the deployment that uses it.

## Consequences

**Good**

- No new security-critical code. The verification path was already implemented and tested.
- The requirement is one flag, and `--status` reports whether it is set.
- Group-based authorisation is unchanged; `agent` and `supervisor` still come from
  `cognito:groups` ([10](10-security.md) §3.1).
- No credential material in the project's database, and therefore none in S3.

**Bad**

- A hard dependency on AWS for sign-in. Local development sidesteps it with
  `AUTH_MODE=dev`, which the backend refuses to start with outside `ENVIRONMENT=local`
  ([14](14-local-dev.md) §3.7).
- Adding a user is an operator action, not a self-service flow. That is the requirement,
  but it does mean someone has to run a command per tester.
- The pool was created by hand and is not yet in Terraform. Recorded in
  [`ops-log.md`](../ops-log.md) with `terraform import` as the follow-up.

**Revisit if** the project needs to run with no AWS account at all — a fully offline
demo — or if identity needs to federate somewhere Cognito cannot reach.

## What would have changed the decision

Had the account been unable to create a user pool, B would have been correct. It was
checked rather than assumed:

```
cognito-idp:CreateUserPool        allowed
cognito-idp:CreateUserPoolClient  allowed
```
