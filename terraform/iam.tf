# Task and execution roles — docs/10 §3.2.
#
# Four roles, split the way ECS splits responsibility: an *execution* role is used by the
# ECS agent to start the task (pull the image, fetch secrets, write logs); a *task* role
# is used by the code inside the container. Conflating them is the usual mistake, and it
# hands running application code the ability to read every secret it was started with.

data "aws_iam_policy_document" "ecs_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

# --- Execution roles ------------------------------------------------------------------
resource "aws_iam_role" "backend_execution" {
  name               = "${local.name}-backend-execution"
  assume_role_policy = data.aws_iam_policy_document.ecs_assume.json
}

resource "aws_iam_role_policy_attachment" "backend_execution_managed" {
  role       = aws_iam_role.backend_execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

data "aws_iam_policy_document" "backend_execution_secrets" {
  statement {
    actions = ["secretsmanager:GetSecretValue"]
    # Named ARNs, never `*`. This role can read these two secrets and no others — if a
    # third is added to the account, this role cannot see it.
    resources = [
      aws_secretsmanager_secret.gemini.arn,
      aws_secretsmanager_secret.langsmith.arn,
    ]
  }
}

resource "aws_iam_role_policy" "backend_execution_secrets" {
  name   = "secrets"
  role   = aws_iam_role.backend_execution.id
  policy = data.aws_iam_policy_document.backend_execution_secrets.json
}

resource "aws_iam_role" "frontend_execution" {
  name               = "${local.name}-frontend-execution"
  assume_role_policy = data.aws_iam_policy_document.ecs_assume.json
}

resource "aws_iam_role_policy_attachment" "frontend_execution_managed" {
  role       = aws_iam_role.frontend_execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

# The frontend has no secrets at all, so its execution role gets no Secrets Manager
# policy. That absence is the point (docs/10 §3.2).

# --- Task roles -----------------------------------------------------------------------
resource "aws_iam_role" "backend_task" {
  name               = "${local.name}-backend-task"
  assume_role_policy = data.aws_iam_policy_document.ecs_assume.json
}

data "aws_iam_policy_document" "backend_task" {
  # Litestream replicates both databases to this bucket and restores from it on boot
  # (ADR-007). Scoped to the one bucket, and to objects under it.
  statement {
    actions = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject", "s3:ListBucket"]
    resources = [
      aws_s3_bucket.litestream.arn,
      "${aws_s3_bucket.litestream.arn}/*",
    ]
  }
}

resource "aws_iam_role_policy" "backend_task" {
  name   = "litestream"
  role   = aws_iam_role.backend_task.id
  policy = data.aws_iam_policy_document.backend_task.json
}

resource "aws_iam_role" "frontend_task" {
  name               = "${local.name}-frontend-task"
  assume_role_policy = data.aws_iam_policy_document.ecs_assume.json
}

# The frontend task role holds **no policy at all** — it serves static files and needs
# nothing. Creating the role and leaving it empty, rather than omitting it, makes that a
# stated intention instead of an oversight (docs/10 §3.2).

# --- VPC flow logs --------------------------------------------------------------------
data "aws_iam_policy_document" "flow_logs_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["vpc-flow-logs.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "flow_logs" {
  name               = "${local.name}-flow-logs"
  assume_role_policy = data.aws_iam_policy_document.flow_logs_assume.json
}

data "aws_iam_policy_document" "flow_logs" {
  statement {
    actions = [
      "logs:CreateLogStream",
      "logs:PutLogEvents",
      "logs:DescribeLogGroups",
      "logs:DescribeLogStreams",
    ]
    resources = ["${aws_cloudwatch_log_group.flow_logs.arn}:*"]
  }
}

resource "aws_iam_role_policy" "flow_logs" {
  name   = "write"
  role   = aws_iam_role.flow_logs.id
  policy = data.aws_iam_policy_document.flow_logs.json
}
