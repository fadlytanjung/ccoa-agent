# Secrets and the Litestream bucket — docs/10 §4, ADR-007.

# Containers only. **No `aws_secretsmanager_secret_version` here on purpose**: a value
# written by Terraform lands in the state file, and the state file is an S3 object that
# more people can read than should ever read an API key. The values are set out of band
# by `scripts/deploy.sh` (docs/18 §4 Step 6).
resource "aws_secretsmanager_secret" "gemini" {
  name = "${local.name}/gemini-api-key"

  # `dev` is created and destroyed repeatedly, and Secrets Manager keeps deleted secrets
  # for a recovery window by default — during which the name cannot be reused, so the
  # next apply fails with "already scheduled for deletion".
  recovery_window_in_days = 0

  tags = { Name = "${local.name}-gemini" }
}

resource "aws_secretsmanager_secret" "langsmith" {
  name                    = "${local.name}/langsmith-api-key"
  recovery_window_in_days = 0

  tags = { Name = "${local.name}-langsmith" }
}

resource "aws_s3_bucket" "litestream" {
  bucket = "${local.name}-litestream-${data.aws_caller_identity.current.account_id}"

  # The database is disposable — it ships in the image — so nothing here needs to survive
  # a destroy, and a bucket with objects in it would block one.
  force_destroy = true

  tags = { Name = "${local.name}-litestream" }
}

data "aws_caller_identity" "current" {}

resource "aws_s3_bucket_versioning" "litestream" {
  bucket = aws_s3_bucket.litestream.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "litestream" {
  bucket = aws_s3_bucket.litestream.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_public_access_block" "litestream" {
  bucket = aws_s3_bucket.litestream.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# Litestream keeps generations indefinitely otherwise, and this bucket holds a database
# that is rebuilt from the image on every deploy.
resource "aws_s3_bucket_lifecycle_configuration" "litestream" {
  bucket = aws_s3_bucket.litestream.id

  rule {
    id     = "expire-old-generations"
    status = "Enabled"

    filter {}

    noncurrent_version_expiration {
      noncurrent_days = 7
    }
  }
}
