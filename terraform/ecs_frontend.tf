# The frontend service — docs/08 §3.6.
#
# Stateless in a way the backend is not: no database, no secrets, no task-role
# permissions, and no correctness ceiling on the task count.

resource "aws_ecs_task_definition" "frontend" {
  family                   = "${local.name}-frontend"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 256 # 0.25 vCPU
  memory                   = 512
  execution_role_arn       = aws_iam_role.frontend_execution.arn
  task_role_arn            = aws_iam_role.frontend_task.arn

  runtime_platform {
    cpu_architecture        = "ARM64"
    operating_system_family = "LINUX"
  }

  container_definitions = jsonencode([{
    name  = "frontend"
    image = "${aws_ecr_repository.frontend.repository_url}:${var.frontend_image_tag}"

    portMappings = [{ containerPort = 8080, protocol = "tcp" }]

    # One variable, and only because CSP is enforced by nginx rather than by the SPA, so
    # it cannot come from `/api/v1/config` like everything else does.
    #
    # These are the exact hosts the PKCE flow contacts from the browser: `/oauth2/token`
    # and `/oauth2/revoke` on the hosted UI domain, and the pool's JWKS on the identity
    # host. Named individually rather than wildcarded — `https://*.amazonaws.com` would
    # let an injected script reach every AWS service endpoint there is.
    environment = [{
      name = "CSP_CONNECT_SRC"
      value = join(" ", [
        "'self'",
        "https://${aws_cognito_user_pool_domain.main.domain}.auth.${var.region}.amazoncognito.com",
        "https://cognito-idp.${var.region}.amazonaws.com",
      ])
    }]

    # No secrets. The SPA learns everything else at runtime from the backend's public
    # `/api/v1/config`, which is what lets one image serve every environment without a
    # rebuild (docs/07 §3.9).

    healthCheck = {
      command     = ["CMD-SHELL", "wget -qO- http://localhost:8080/healthz || exit 1"]
      interval    = 30
      timeout     = 5
      retries     = 3
      startPeriod = 10 # nginx serves immediately; nothing to migrate or restore
    }

    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = aws_cloudwatch_log_group.frontend.name
        "awslogs-region"        = var.region
        "awslogs-stream-prefix" = "frontend"
      }
    }

    essential = true
  }])

  tags = { Name = "${local.name}-frontend" }
}

resource "aws_ecs_service" "frontend" {
  name            = "${local.name}-frontend"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.frontend.arn
  launch_type     = "FARGATE"
  desired_count   = 1

  # An ordinary rolling deploy, unlike the backend: two frontend tasks are two identical
  # copies of a static site, so overlapping them is free.
  deployment_minimum_healthy_percent = 100
  deployment_maximum_percent         = 200

  network_configuration {
    subnets          = aws_subnet.private[*].id
    security_groups  = [aws_security_group.frontend.id]
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.frontend.arn
    container_name   = "frontend"
    container_port   = 8080
  }

  lifecycle {
    ignore_changes = [desired_count]
  }

  depends_on = [aws_lb_listener.http]

  tags = { Name = "${local.name}-frontend" }
}

resource "aws_appautoscaling_target" "frontend" {
  service_namespace  = "ecs"
  resource_id        = "service/${aws_ecs_cluster.main.name}/${aws_ecs_service.frontend.name}"
  scalable_dimension = "ecs:service:DesiredCount"
  min_capacity       = var.min_capacity
  max_capacity       = var.frontend_max_capacity
}

resource "aws_appautoscaling_policy" "frontend_target_tracking" {
  name               = "${local.name}-frontend-requests"
  policy_type        = "TargetTrackingScaling"
  service_namespace  = aws_appautoscaling_target.frontend.service_namespace
  resource_id        = aws_appautoscaling_target.frontend.resource_id
  scalable_dimension = aws_appautoscaling_target.frontend.scalable_dimension

  target_tracking_scaling_policy_configuration {
    target_value = 1000

    predefined_metric_specification {
      predefined_metric_type = "ALBRequestCountPerTarget"
      resource_label         = "${aws_lb.main.arn_suffix}/${aws_lb_target_group.frontend.arn_suffix}"
    }

    scale_in_cooldown  = 300
    scale_out_cooldown = 60
  }
}

# Same scale-from-zero problem as the backend, same shape of answer — see the long comment
# in ecs_backend.tf. It matters more here: the frontend is the first thing a browser asks
# for, so if it cannot wake, nothing else is reachable either.
resource "aws_appautoscaling_policy" "frontend_wake" {
  name               = "${local.name}-frontend-wake"
  policy_type        = "StepScaling"
  service_namespace  = aws_appautoscaling_target.frontend.service_namespace
  resource_id        = aws_appautoscaling_target.frontend.resource_id
  scalable_dimension = aws_appautoscaling_target.frontend.scalable_dimension

  step_scaling_policy_configuration {
    adjustment_type = "ExactCapacity"
    cooldown        = 60
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

resource "aws_cloudwatch_metric_alarm" "frontend_wake" {
  alarm_name          = "${local.name}-frontend-wake"
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 1
  threshold           = 1
  period              = 60
  namespace           = "AWS/ApplicationELB"
  metric_name         = "RequestCount"
  statistic           = "Sum"
  treat_missing_data  = "notBreaching"

  # **LoadBalancer only.** `RequestCount` broken down by TargetGroup counts requests that
  # reached a target — so with zero targets it reports nothing, the alarm sits in
  # INSUFFICIENT_DATA, and the service that was supposed to wake on traffic never sees
  # any. The wake policy was watching a metric that cannot fire in the one state it
  # exists to escape. At the load-balancer level the request is counted whether or not
  # anything was there to serve it.
  dimensions = {
    LoadBalancer = aws_lb.main.arn_suffix
  }

  alarm_actions = [aws_appautoscaling_policy.frontend_wake.arn]

  tags = { Name = "${local.name}-frontend-wake" }
}
