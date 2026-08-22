# Remote state in S3, locked by S3 itself — docs/08 §3.4.
#
# The bucket is created by `scripts/aws-bootstrap.sh` before this root is ever
# initialised, because Terraform cannot create its own backend.
#
# The bucket name contains the account id, so it is NOT written here: this repository is
# public (docs/18 §6). Initialise with a partial configuration instead:
#
#   terraform init \
#     -backend-config="bucket=ccoa-tfstate-<AWS_ACCOUNT_ID>" \
#     -backend-config="key=dev/terraform.tfstate" \
#     -backend-config="region=ap-southeast-1"
#
# `scripts/deploy.sh` does this for you from the account it is authenticated to.
terraform {
  backend "s3" {
    # `use_lockfile` writes a `.tflock` object beside the state. No DynamoDB table, and
    # no table to forget to destroy afterwards.
    use_lockfile = true
    encrypt      = true
  }
}
