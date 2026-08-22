# The backend service — docs/08 §3.6.

resource "aws_ecs_task_definition" "backend" {
  family                   = "${local.name}-backend"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 512  # 0.5 vCPU
  memory                   = 1024 # 1 GB
  execution_role_arn       = aws_iam_role.backend_execution.arn
  task_role_arn            = aws_iam_role.backend_task.arn

  runtime_platform {
    cpu_architecture        = "ARM64" # ~20% cheaper for identical work (docs/02 §6)
    operating_system_family = "LINUX"
  }

  container_definitions = jsonencode([{
    name  = "backend"
    image = "${aws_ecr_repository.backend.repository_url}:${var.backend_image_tag}"

    portMappings = [{ containerPort = 8000, protocol = "tcp" }]

    environment = [
      { name = "ENVIRONMENT", value = var.environment },
      { name = "AUTH_MODE", value = "cognito" },
      { name = "COGNITO_USER_POOL_ID", value = aws_cognito_user_pool.main.id },
      { name = "COGNITO_CLIENT_ID", value = aws_cognito_user_pool_client.spa.id },
      { name = "COGNITO_REGION", value = var.region },
      { name = "COGNITO_DOMAIN", value = aws_cognito_user_pool_domain.main.domain },
      # A CVE mitigation, not a tuning flag: without it the SQLite checkpointer
      # deserialises msgpack unsafely (CVE-2026-28277, docs/02 §4.2).
      { name = "LANGGRAPH_STRICT_MSGPACK", value = "true" },
      { name = "LANGSMITH_TRACING", value = tostring(var.enable_langsmith) },
      { name = "LANGSMITH_PROJECT", value = "ccoa-${var.environment}" },
      { name = "LITESTREAM_BUCKET", value = aws_s3_bucket.litestream.id },
      { name = "LITESTREAM_REGION", value = var.region },
    ]

    # `secrets`, never `environment`, for both keys. A value here never appears in the
    # task definition, in `terraform show`, or in the ECS console.
    secrets = [
      { name = "GEMINI_API_KEY", valueFrom = aws_secretsmanager_secret.gemini.arn },
      { name = "LANGSMITH_API_KEY", valueFrom = aws_secretsmanager_secret.langsmith.arn },
    ]

    healthCheck = {
      command  = ["CMD-SHELL", "curl -fsS http://localhost:8000/healthz || exit 1"]
      interval = 30
      timeout  = 5
      retries  = 3
      # Long enough for Litestream's restore and `alembic upgrade head` to finish before
      # the first probe counts against the task (docs/04 §3.7).
      startPeriod = 90
    }

    # Litestream must finish its final sync before SIGKILL. Shorter, and a planned
    # scale-in starts losing writes — which is what makes scale-to-zero safe rather than
    # merely cheap (ADR-007 §1).
    stopTimeout = 60

    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = aws_cloudwatch_log_group.backend.name
        "awslogs-region"        = var.region
        "awslogs-stream-prefix" = "backend"
      }
    }

    essential = true
  }])

  tags = { Name = "${local.name}-backend" }
}

resource "aws_ecs_service" "backend" {
  name            = "${local.name}-backend"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.backend.arn
  launch_type     = "FARGATE"
  desired_count   = 1

  # A rolling deploy would briefly run two tasks, and two backend tasks are two divergent
  # databases (docs/04 §3.5) — worse, two Litestream writers, which corrupts the
  # replica (ADR-007). These two numbers are what force replace-then-start.
  deployment_minimum_healthy_percent = 0
  deployment_maximum_percent         = 100

  network_configuration {
    subnets          = aws_subnet.private[*].id
    security_groups  = [aws_security_group.backend.id]
    assign_public_ip = false # private subnets; egress is via NAT (docs/09 §1)
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.backend.arn
    container_name   = "backend"
    container_port   = 8000
  }

  # Autoscaling owns the count after the first apply. Without this, every plan wants to
  # reset it to `desired_count` and fights the scaling policy.
  lifecycle {
    ignore_changes = [desired_count]
  }

  depends_on = [aws_lb_listener.http]

  tags = { Name = "${local.name}-backend" }
}

# --- Autoscaling ---------------------------------------------------------------------
resource "aws_appautoscaling_target" "backend" {
  service_namespace  = "ecs"
  resource_id        = "service/${aws_ecs_cluster.main.name}/${aws_ecs_service.backend.name}"
  scalable_dimension = "ecs:service:DesiredCount"

  # 0 costs nothing while idle, and is safe because replication is in place, not despite
  # it: ECS scale-in is graceful and Litestream syncs before exiting (ADR-007 §1).
  min_capacity = 0
  # 1 is a correctness bound. See the variable's description.
  max_capacity = var.backend_max_capacity
}

resource "aws_appautoscaling_policy" "backend_target_tracking" {
  name               = "${local.name}-backend-requests"
  policy_type        = "TargetTrackingScaling"
  service_namespace  = aws_appautoscaling_target.backend.service_namespace
  resource_id        = aws_appautoscaling_target.backend.resource_id
  scalable_dimension = aws_appautoscaling_target.backend.scalable_dimension

  target_tracking_scaling_policy_configuration {
    target_value = 300 # requests per target per minute

    predefined_metric_specification {
      predefined_metric_type = "ALBRequestCountPerTarget"
      resource_label         = "${aws_lb.main.arn_suffix}/${aws_lb_target_group.backend.arn_suffix}"
    }

    scale_in_cooldown  = 300 # a cold start costs 45-75 s; do not thrash
    scale_out_cooldown = 60
  }
}

# --- Waking from zero ------------------------------------------------------------------
#
# Target tracking **cannot** scale out from zero, and this is the subtlety that makes
# scale-to-zero more than a variable. `ALBRequestCountPerTarget` is per *target*; with no
# targets the metric reports no data, the alarm sits in INSUFFICIENT_DATA, and the service
# stays at zero forever. A design that only sets `min_capacity = 0` never comes back up.
#
# `RequestCount` on the target group still increments when a request arrives and finds no
# healthy target, so it is the one signal available at zero. A step policy on it is what
# restores the service.
#
# The consequence is honest and worth stating: **the first request after an idle period
# fails** — CloudFront returns 503 while the task cold-starts (45-75 s). It is a
# demo-environment trade, accepted in docs/08 §3.6, and the reason `prod` would run warm.
resource "aws_appautoscaling_policy" "backend_wake" {
  name               = "${local.name}-backend-wake"
  policy_type        = "StepScaling"
  service_namespace  = aws_appautoscaling_target.backend.service_namespace
  resource_id        = aws_appautoscaling_target.backend.resource_id
  scalable_dimension = aws_appautoscaling_target.backend.scalable_dimension

  step_scaling_policy_configuration {
    adjustment_type = "ExactCapacity"
    cooldown        = 120
    # Only Average/Minimum/Maximum are accepted here; the alarm below is what applies
    # `Sum` to the request count. This value governs how the *breaching datapoints* are
    # aggregated for the step, and with a single step and ExactCapacity it is immaterial.
    metric_aggregation_type = "Maximum"

    step_adjustment {
      metric_interval_lower_bound = 0
      # With `ExactCapacity` this is the absolute count to scale to, not a delta.
      scaling_adjustment = 1
    }
  }
}

resource "aws_cloudwatch_metric_alarm" "backend_wake" {
  alarm_name          = "${local.name}-backend-wake"
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 1
  threshold           = 1
  period              = 60
  namespace           = "AWS/ApplicationELB"
  metric_name         = "RequestCount"
  statistic           = "Sum"
  # Missing data is *not* breaching: an idle service should stay at zero.
  treat_missing_data = "notBreaching"

  dimensions = {
    LoadBalancer = aws_lb.main.arn_suffix
    TargetGroup  = aws_lb_target_group.backend.arn_suffix
  }

  alarm_actions = [aws_appautoscaling_policy.backend_wake.arn]

  tags = { Name = "${local.name}-backend-wake" }
}
