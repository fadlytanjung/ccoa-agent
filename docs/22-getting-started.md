# 22 — Getting started: clone to deployment

> **Status:** Living
> **Audience:** anyone who has just cloned this repository
> **Depends on:** [14 — Local development](14-local-dev.md), [18 — AWS access](18-aws-access-and-manual-steps.md), [20 — Implementation status](20-implementation-status.md)

## 1. Purpose

One path from `git clone` to a running application, and as far towards a deployed one as
this repository can currently take you.

Every other document explains *why* something is the way it is. This one only tells you
what to type, in order, and what should happen when you do.

**Read [20 — Implementation status](20-implementation-status.md) before you plan anything
around this.** The application runs; the AWS deployment does not exist yet, and §5 below is
honest about exactly where the path stops.

---

## 2. What you need

| Tool | Version | For |
|---|---|---|
| [uv](https://docs.astral.sh/uv/) | ≥ 0.5 | Python dependencies — replaces pip and venv |
| [Node](https://nodejs.org) | ≥ 22 | The frontend |
| Python | ≥ 3.12 | The repository checks |
| [Docker](https://docs.docker.com/get-docker/) | any recent | Container checks (optional locally) |
| A [Gemini API key](https://aistudio.google.com/apikey) | — | The agent. Free tier is enough |

Only for deploying:

| Tool | Version | For |
|---|---|---|
| [AWS CLI](https://aws.amazon.com/cli/) | v2 | Everything AWS |
| [Terraform](https://developer.hashicorp.com/terraform/install) | **≥ 1.11** | Infrastructure. 1.11 is a floor, not a preference — [§5.1](#51-what-does-not-exist-yet) |
| [jq](https://jqlang.github.io/jq/) | ≥ 1.6 | The bootstrap scripts |
| [gh](https://cli.github.com/) | any | Setting repository secrets |

Check all of it at once:

```bash
./scripts/preflight.sh            # local development
./scripts/preflight.sh --deploy   # ...plus the deployment tools
```

It reports everything missing in one pass, rather than failing on one tool at a time.

---

## 3. Run it locally

### 3.1 The short version

```bash
git clone <this repository>
cd ccoa-agent

cp backend/.env.example backend/.env
# Put your key in it:  GEMINI_API_KEY=...

./scripts/preflight.sh
./scripts/dev.sh
```

Open **<http://localhost:5173>**.

`dev.sh` installs dependencies, seeds the database on first run, starts the API on `:8000`
and the SPA on `:5173`, and stops both on Ctrl-C. First run takes a couple of minutes;
after that it is seconds.

### 3.2 What you should see

A conversation view with an empty thread list. Try:

> Why did John Tan's claim submission fail? Check his policies and open cases.

Two customers are named John Tan in the seeded corpus — deliberately
([12](12-seed-data.md) §3.4) — so the agent stops and asks which one. Answer in the message
box, or click an option if it offers them. It then investigates and answers with citations
you can click, and the right-hand panel fills in with that customer's real records.

That single exchange exercises the whole system: routing, tools, grounding, the
human-in-the-loop checkpoint, streaming, and the context panel.

### 3.3 Signing in

By default the local stack runs with `AUTH_MODE=dev`: no identity provider, a fixed
`dev@localhost` user in the `agent` and `supervisor` groups. This is not a shortcut bolted
on for convenience — without it you would need a Cognito pool to render a single screen —
and **the backend refuses to start with it outside `ENVIRONMENT=local`**
([14](14-local-dev.md) §3.7).

To use a real Cognito sign-in, from your own machine, see [§4](#4-real-sign-in-from-your-machine).

### 3.4 A clean slate

Testing leaves the sidebar full of half-finished conversations. To clear them without
touching the seeded records:

```bash
cd backend && uv run python tools/reset_conversations.py --tickets
```

To regenerate the corpus itself — a different job — `uv run python -m app.seed --reset`.

### 3.5 Running the checks

```bash
./scripts/verify.sh                # everything CI runs
./scripts/verify.sh --fast         # skip the browser tests
./scripts/verify.sh --containers   # also build and verify both images
```

A green run here means a green run on GitHub: the script and `ci.yml` run the same checks
in the same order, and are meant to stay in step.

---

## 4. Real sign-in, from your machine

This is the part that surprises people, so it is worth stating plainly: **the full Cognito
flow works against `http://localhost:5173`.** You do not need a deployed environment to
test sign-in. Cognito permits `http://localhost` callback URLs specifically so a SPA can be
developed against real identities — the same way a Google sign-in works against an app
running on a laptop.

```bash
./scripts/aws-cognito.sh --region ap-southeast-1
```

It creates the user pool, the `agent` and `supervisor` groups, a **public** app client
(no secret — a browser cannot keep one), and the hosted UI domain. It writes the pool id,
client id, domain, and region into `backend/.env`, because copying an id by hand is the
step that goes wrong. Re-running it is safe: it finds what already exists rather than
creating a second pool.

**Nobody can sign themselves up.** `AllowAdminCreateUserOnly=true` is set explicitly —
Cognito's default is the opposite, and a pool left at its defaults lets anyone who finds
the hosted UI create a working account, which in this application means anyone can spend
your model quota ([10](10-security.md) §3.1a, [ADR-008](adr/ADR-008-provisioned-identity.md)).

Add the people who should have access, one at a time:

```bash
./scripts/aws-cognito.sh --add-user someone@example.test
./scripts/aws-cognito.sh --add-user lead@example.test --group supervisor
./scripts/aws-cognito.sh --status        # what the pool allows, and who exists
```

The password is typed at a prompt, never passed as an argument — a command line is visible
in shell history and in the process list.

Then:

```bash
./scripts/dev.sh --cognito
```

Open **<http://localhost:5173>** — `localhost`, not `127.0.0.1`. Cognito compares the
redirect URI as a string, and to it those are two different values.

The console click-path for all of this is [18](18-aws-access-and-manual-steps.md) §7.3, for
when a terminal is not available. Nothing about Cognito genuinely requires a console.

### 4.1 When sign-in does not work

| Symptom | Cause | Fix |
|---|---|---|
| The button does nothing at all | You are on a LAN address like `http://192.168.1.5:5173` | PKCE needs `crypto.subtle`, which browsers withhold outside a secure context. Use `localhost` or https. The app now says this instead of failing silently |
| `redirect_mismatch` | The callback URL is not registered, or differs by a character | Compare byte for byte: scheme, host, port, trailing slash |
| Sign-in works, then the token exchange 400s | The app client has a secret | Recreate it public. `aws-cognito.sh` passes `--no-generate-secret` |
| Signed in, but every API call is 403 | The user is in no group | `admin-add-user-to-group ... --group-name agent` |
| "The assistant could not start" | `COGNITO_DOMAIN` unset, or the pool does not exist | Run `./scripts/aws-cognito.sh` |

The full table, including the deployed-environment cases, is
[18](18-aws-access-and-manual-steps.md) §7.6.

---

## 5. Deployment

### 5.1 What does not exist yet

**Read this before planning around it.** `terraform/` is an empty directory. There is no
`deploy.yml`, and nothing is deployed. The only AWS resources this project has created are
the Cognito pool from [§4](#4-real-sign-in-from-your-machine) and whatever
`aws-bootstrap.sh` has made — recorded in [`ops-log.md`](ops-log.md). The infrastructure is
fully specified — [08](08-infrastructure.md), [09](09-networking.md) — and entirely
unbuilt, and a specification reads exactly the same either way.

What *is* built and ready for it:

| Piece | State |
|---|---|
| `scripts/aws-bootstrap.sh` | Creates the state bucket, the GitHub OIDC provider, the permission boundary, and the deploy role. Written and logic-tested; the AWS calls have not run |
| `scripts/aws-cognito.sh` | **Run.** The user pool exists, self-registration is off, sign-in works from localhost |
| `.github/workflows/ci.yml` | Validate, test, browser, containers, repository checks. Real, and never yet executed on GitHub |
| Both container images | Built and verified locally, including a Litestream round trip and 30 assertions on what nginx serves |

### 5.2 Bootstrap: what Terraform cannot create for itself

Terraform's own state backend has to exist before `terraform init` can run, and the
pipeline needs an identity before it can do anything. That is the whole of the bootstrap,
and it is the one place a human runs `aws` directly.

```bash
# Never as the account root — the script refuses, and checks before anything else.
aws sts get-caller-identity

./scripts/aws-bootstrap.sh --repo <ORG>/<REPO> --region ap-southeast-1
```

It creates:

1. **`ccoa-tfstate-<AWS_ACCOUNT_ID>`** — versioned, encrypted, private. Versioning first,
   because it is what makes a corrupted state recoverable and it cannot be applied
   retroactively. State locking is **native to S3** (`use_lockfile`), so there is no
   DynamoDB anywhere in this project ([08](08-infrastructure.md) §3.4).
2. **The GitHub OIDC provider** — so the pipeline authenticates with a short-lived token
   and this repository holds no AWS keys, ever.
3. **A permission boundary and the `ccoa-deploy` role**, with the trust policy scoped by a
   `sub` condition to your repository. Without that condition **any repository on GitHub
   could assume the role** — the single most common way this pattern is misconfigured.

It prints the two commands to finish the wiring:

```bash
gh secret set AWS_DEPLOY_ROLE_ARN --repo <ORG>/<REPO> --body "arn:aws:iam::…"
gh variable set AWS_REGION --repo <ORG>/<REPO> --body "ap-southeast-1"
```

The role ARN contains the account id, so it is a **secret**, not a variable — this
repository is public ([18](18-aws-access-and-manual-steps.md) §6).

### 5.1a "Not secure" in the browser

The deployed environment currently serves a **self-signed** certificate, so every visitor
is asked to override a warning. The traffic is encrypted; what is missing is any attestation
of *who* is on the other end.

**There is no way to fix this without a domain.** A load balancer's own
`*.elb.amazonaws.com` name cannot have a trusted certificate: a certificate authority
issues for domains the requester can prove they control, and that one is Amazon's.

Why a self-signed certificate at all, rather than plain HTTP: **Cognito rejects `http://`
callback URLs** for anything but `localhost`. An unencrypted edge cannot sign anyone in, so
the choice was never HTTPS-or-HTTP — it was HTTPS or no authentication.

To fix it properly:

1. **Register a domain.** Route 53 → *Registered domains* → *Register*. A `.click` or
   `.link` is a few dollars a year, and registering there creates the hosted zone for you.
   A domain from elsewhere works too — point its nameservers at a Route 53 zone first.
2. **Set one variable** in `terraform/envs/dev.tfvars`:
   ```hcl
   domain_name = "ccoa.example.com"
   ```
3. **Deploy.** Terraform requests an ACM certificate, writes the DNS record that proves
   ownership, waits for validation, attaches the certificate to the listener, and points
   the domain at the load balancer. The self-signed certificate is dropped automatically —
   `self_signed_certificate` is ignored once a domain is set.

Cognito's callback URLs follow the same variable, so sign-in keeps working at the new
address with no further change.

### 5.2a If CloudFront is refused on a new account

The first deploy of this project hit it, so expect it:

```
Error: creating CloudFront Distribution: AccessDenied: Your account must be
verified before you can add new CloudFront resources.
```

**This is not an IAM problem**, which is the trap — it reads exactly like one, and no
amount of widening the deploy role fixes it. AWS restricts CloudFront on unverified
accounts and the only route through is a Support case: console → Support → *Create case*
→ **Account and billing** → *Account verification*, quoting the error. It is usually
cleared within a day.

Everything else applies cleanly meanwhile — 89 of 97 resources. The eight that do not are
all downstream of the distribution: the Cognito app client needs its domain for a callback
URL, and the backend service needs the client id. When verification lands, one
`./scripts/deploy.sh` finishes them with no configuration change.

While you wait, `./scripts/destroy.sh` stops the meter; the NAT gateway and ALB are the
only things still costing anything, at roughly $0.07/hour.

### 5.3 What is left to build

In order, and none of it is started:

1. **`terraform/`** — VPC, ECS Fargate (ARM64, scale-to-zero), an **internal** ALB reached
   only as a CloudFront VPC origin, ECR, S3 for Litestream, Cognito, WAF, and the S3
   backend with `use_lockfile = true`. Specified in [08](08-infrastructure.md) and
   [09](09-networking.md).
2. **`.github/workflows/deploy.yml`** — the same validate and test jobs, then build and
   push both images to ECR, `terraform apply` to `dev`, a smoke test, and a gated `prod`
   job that is configuration only and never approved ([11](11-cicd.md) §3.6).
3. **The first deploy**, and the list of things that only a first deploy finds.

Until step 1 exists, a CD pipeline would have nothing to apply, which is why there is no
`deploy.yml` rather than a stub that fails helpfully.

### 5.4 Costs, and turning it off

`dev` is ephemeral by design. It scales to zero when idle, and `terraform destroy` when you
are not using it is the intended workflow rather than a cost-saving afterthought
([16](16-cost-model.md), [ADR-004](adr/ADR-004-ephemeral-infrastructure.md)).

`prod` is configuration plus a pipeline job that is never approved. There is deliberately
no way to deploy it.

---

## 6. Working on it

| Task | Command |
|---|---|
| Run everything | `./scripts/dev.sh` |
| Run the checks | `./scripts/verify.sh` |
| Backend tests only | `cd backend && uv run pytest` |
| Frontend unit tests | `cd frontend && npx vitest` |
| Browser tests | `cd frontend && npx playwright test` |
| Inspect the graph | `cd backend && uv run langgraph dev` — Studio on `:2024` |
| Measure agent quality | `cd backend && uv run deepeval test run evals/test_agent.py` — real model calls |
| Clear conversations | `cd backend && uv run python tools/reset_conversations.py` |

Two rules worth knowing before your first change:

- **The specs are the source of truth.** If code must diverge from `docs/`, change the
  document in the same commit ([00](00-constitution.md)).
- **`docs/20` is the checkpoint.** Anything that adds, removes, or completes a component
  updates it in the same change — `/checkpoint`, or
  `python3 tools/check_implementation_status.py --update-counts`. CI fails if it drifts.

`langgraph dev` and the FastAPI server are **not** meant to run together; they answer
different questions and each supplies its own checkpointer ([14](14-local-dev.md) §3.4).

---

## 7. If something is wrong

| Symptom | Likely cause |
|---|---|
| `Address already in use` | A previous run still holds the port: `lsof -ti tcp:8000 \| xargs kill -9` |
| The agent answers nothing, no error | No `GEMINI_API_KEY` in `backend/.env` |
| Browser tests fail against correct-looking code | A stale backend on `:8000`. `ci.yml` and `playwright.config.ts` both start their own; kill any others |
| `alembic check` reports a diff | A model changed with no migration ([04](04-data-model.md) §3.7) |
| The status checker fails | `docs/20` no longer matches the tree. Fix the rows, not the checker |
| Tests pass locally, CI fails on formatting | `cd backend && uv run ruff format .` |
