terraform {
  # 1.11 is a floor, not a preference: native S3 state locking (`use_lockfile`) landed in
  # 1.10 and `dynamodb_table` was deprecated in 1.11. That is what lets this project have
  # no DynamoDB anywhere (docs/08 §3.4).
  required_version = ">= 1.11"

  required_providers {
    tls = {
      source  = "hashicorp/tls"
      version = "~> 4.0"
    }
    aws = {
      source = "hashicorp/aws"
      # docs/08 §3.3 specified `~> 5.70`; 6.x is current and is what this is written
      # against. The pin was updated in the same change, per the working agreement.
      version = "~> 6.0"
    }
  }
}
