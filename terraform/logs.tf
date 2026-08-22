# Log groups and flow logs — docs/08 §3.2.
#
# Every group has finite retention. Not for cost: an indefinite log group is a resource
# `terraform destroy` leaves behind, and "destroy leaves nothing" is a requirement of an
# ephemeral environment (docs/08 §3.1).

resource "aws_cloudwatch_log_group" "backend" {
  name              = "/ecs/${local.name}/backend"
  retention_in_days = var.log_retention_days
}

resource "aws_cloudwatch_log_group" "frontend" {
  name              = "/ecs/${local.name}/frontend"
  retention_in_days = var.log_retention_days
}

resource "aws_cloudwatch_log_group" "flow_logs" {
  name              = "/vpc/${local.name}/flow-logs"
  retention_in_days = var.log_retention_days
}

# Flow logs record what actually crossed the network, which is the only way to check the
# claims in docs/09 §5 rather than assert them.
resource "aws_flow_log" "vpc" {
  vpc_id               = aws_vpc.main.id
  traffic_type         = "ALL"
  iam_role_arn         = aws_iam_role.flow_logs.arn
  log_destination      = aws_cloudwatch_log_group.flow_logs.arn
  log_destination_type = "cloud-watch-logs"

  tags = { Name = local.name }
}
