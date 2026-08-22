# Internal load balancer — docs/09 §1.
#
# `internal = true` is the load-bearing line. The ALB holds private IPs only and is
# reachable exclusively as a CloudFront VPC origin, so the listener is not addressable
# from the internet at all — a stronger property than a public ALB with a tight security
# group, where the listener is addressable and the group is the only thing in the way.

resource "aws_lb" "main" {
  name               = local.name
  internal           = true
  load_balancer_type = "application"
  subnets            = aws_subnet.private[*].id
  security_groups    = [aws_security_group.alb.id]

  drop_invalid_header_fields = true
  enable_deletion_protection = false # dev is destroyed routinely (docs/08 §3.1)

  # A graph turn streams for as long as the agent takes. The default 60 s cuts a long
  # investigation off mid-answer, and the browser sees a truncated stream rather than an
  # error (docs/06 §3.4).
  idle_timeout = 120

  tags = { Name = local.name }
}

resource "aws_lb_target_group" "backend" {
  name        = "${local.name}-backend"
  port        = 8000
  protocol    = "HTTP"
  vpc_id      = aws_vpc.main.id
  target_type = "ip" # Fargate awsvpc tasks are addressed by IP, not instance

  health_check {
    path     = "/healthz"
    matcher  = "200"
    interval = 30
    timeout  = 5
    # Liveness only. `/readyz` checks the database and the model binding, and a task that
    # fails those should be visible in the console rather than silently recycled by the
    # load balancer before anyone can read the reason.
    healthy_threshold   = 2
    unhealthy_threshold = 3
  }

  # Long enough for Litestream's final sync (ADR-007), short enough that a deploy is not
  # dominated by draining.
  deregistration_delay = 30

  tags = { Name = "${local.name}-backend" }
}

resource "aws_lb_target_group" "frontend" {
  name        = "${local.name}-frontend"
  port        = 8080
  protocol    = "HTTP"
  vpc_id      = aws_vpc.main.id
  target_type = "ip"

  health_check {
    path                = "/healthz"
    matcher             = "200"
    interval            = 30
    timeout             = 5
    healthy_threshold   = 2
    unhealthy_threshold = 3
  }

  deregistration_delay = 10 # stateless; nothing to flush

  tags = { Name = "${local.name}-frontend" }
}

# HTTP only. TLS terminates at CloudFront, and the hop from there to this listener is
# inside the VPC over a VPC origin — it never crosses the internet (docs/09 §4.3).
resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.main.arn
  port              = 80
  protocol          = "HTTP"

  # Everything that is not the API is the SPA.
  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.frontend.arn
  }
}

resource "aws_lb_listener_rule" "api" {
  listener_arn = aws_lb_listener.http.arn
  priority     = 100

  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.backend.arn
  }

  condition {
    # `/healthz` and `/readyz` are deliberately absent: those belong to the frontend
    # container at the edge, and the backend's own probes are reached by ECS inside the
    # task, not through the load balancer.
    path_pattern {
      values = ["/api/*"]
    }
  }
}
