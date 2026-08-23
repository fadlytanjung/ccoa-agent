# Operations log

Every AWS action performed by hand — outside Terraform and outside the pipeline — is
recorded here. See [18 — AWS access and manual steps](18-aws-access-and-manual-steps.md)
§3.5 for why.

The reason is practical, not bureaucratic: Terraform cannot see a manual change, so on
the next `apply` it will either revert it, conflict with it, or fail because of it. An
entry here is the difference between "someone changed this deliberately" and an hour of
confusion.

**Nothing in this file names the account.** Placeholders only — the same rule as
everywhere else, and the same check enforces it
([18](18-aws-access-and-manual-steps.md) §6).

## Open — needs bringing back under IaC

| Date | Identity | Action | Why not the pipeline | Follow-up |
|---|---|---|---|---|
| 2026-08-23 | admin IAM user | Created the Route 53 public hosted zone for the application's domain, via `scripts/enable-domain.sh` | **Deliberately outside Terraform.** A zone recreated by `terraform destroy` gets new nameservers, which would mean editing the registrar again after every teardown of an ephemeral environment | **None — this is correct as it stands.** Like the state bucket, the zone outlives any single environment. Terraform reads it with a `data` source and owns only the records inside it |
| 2026-08-23 | admin IAM user | **Blocked:** `terraform apply` cannot create the CloudFront distribution — `AccessDenied: Your account must be verified before you can add new CloudFront resources` | Not a permissions problem and not fixable in IaC: it is an account-level restriction on new AWS accounts | **Open a Support case** ("Account and billing" → "Account verification") quoting that message. Once cleared, `./scripts/deploy.sh` finishes the remaining 8 resources with no changes to the configuration |
| 2026-08-23 | admin IAM user | Imported four resources a killed `terraform apply` had created without recording: the internet-facing ALB, the regional WAF ACL, an ALB ingress rule, and the CloudFront VPC origin | A 10-minute command timeout SIGKILLs an apply after the API calls succeed and before the state is written. The lesson is about how the apply was run, not about the configuration | Closed by `terraform import` in each case. Long applies now run detached |
| 2026-08-23 | admin IAM user | Imported the CloudFront VPC origin `vo_…` that a killed `terraform apply` had created but not recorded | A 10-minute command timeout SIGKILLed the apply after the API call succeeded and before the state was written | Closed by `terraform import`; nothing further needed |
| 2026-08-23 | admin IAM user | Created the Cognito user pool `ccoa-dev`, the `agent` and `supervisor` groups, the hosted UI domain, and the public SPA app client `ccoa-spa`, in `ap-southeast-1`, via `scripts/aws-cognito.sh` | There is no pipeline yet — `terraform/` is empty ([20](20-implementation-status.md) §4.4). Sign-in had to work before there was anywhere to deploy it | **`terraform import` all four** when [08](08-infrastructure.md) is built. The script is idempotent, so it is also the reference for what the Terraform must produce |

## Closed

| Date | Identity | Action | Why not the pipeline | How it was resolved |
|---|---|---|---|---|
| — | — | — | — | — |

---

## Template

Copy this when adding an entry. Be specific enough that someone else could repeat it.

```markdown
| 2026-01-01 | ccoa-bootstrap | Created the S3 state bucket for Terraform state | Terraform cannot create its own backend | Permanent by nature — documented in 18 §4 Step 1 |
```

If a manual action can later be expressed in Terraform, `terraform import` it, move the
row to **Closed**, and say how. Manual state that stays manual is how an environment
stops being reproducible.

## Notes on the open entries

**The Cognito pool.** Four resources, and the one setting that matters most is the least
obvious: `AllowAdminCreateUserOnly=true`. Cognito's default is `false`, which means a pool
left at its defaults lets **anyone who reaches the hosted UI create an account** — and in
this application every account can spend the project's model quota. The Terraform that
replaces this must set it explicitly:

```hcl
resource "aws_cognito_user_pool" "main" {
  admin_create_user_config { allow_admin_create_user_only = true }
}
```

`./scripts/aws-cognito.sh --status` reports it, and re-running the script re-applies it to
a pool that has drifted.
