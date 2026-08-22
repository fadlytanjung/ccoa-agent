# Internal load balancer — docs/09 §1.
#
# `internal = true` is the load-bearing line. The ALB holds private IPs only and is
# reachable exclusively as a CloudFront VPC origin, so the listener is not addressable
# from the internet at all — a stronger property than a public ALB with a tight security
# group, where the listener is addressable and the group is the only thing in the way.

resource "aws_lb" "main" {
  name = local.name
  # Internal behind CloudFront; internet-facing when it *is* the edge. This one boolean is
  # the whole difference between the two topologies — see docs/09 §6.6 for what it costs.
  internal           = local.use_cloudfront
  load_balancer_type = "application"
  # Internet-facing load balancers must sit in subnets with a route to the internet
  # gateway. The tasks stay in the private subnets either way, which is the property that
  # matters: the ALB moving does not move the compute.
  subnets         = local.use_cloudfront ? aws_subnet.private[*].id : aws_subnet.public[*].id
  security_groups = [aws_security_group.alb.id]

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

# Port 80.
#
# Behind CloudFront this carries no viewer traffic: TLS terminates at the edge and this
# hop runs inside the VPC over a VPC origin (docs/09 §4.3).
#
# As the edge with a certificate, it redirects to 443. As the edge without one, it *is*
# the listener — unencrypted, and said plainly rather than hidden behind an https:// URL
# that would not resolve.
resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.main.arn
  port              = 80
  protocol          = "HTTP"

  dynamic "default_action" {
    for_each = local.alb_https ? [1] : []
    content {
      type = "redirect"
      redirect {
        port        = "443"
        protocol    = "HTTPS"
        status_code = "HTTP_301"
      }
    }
  }

  # Everything that is not the API is the SPA.
  dynamic "default_action" {
    for_each = local.alb_https ? [] : [1]
    content {
      type             = "forward"
      target_group_arn = aws_lb_target_group.frontend.arn
    }
  }
}

resource "aws_lb_listener" "https" {
  count = local.alb_https ? 1 : 0

  load_balancer_arn = aws_lb.main.arn
  port              = 443
  protocol          = "HTTPS"
  ssl_policy        = "ELBSecurityPolicy-TLS13-1-2-2021-06"
  certificate_arn   = local.certificate_arn

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.frontend.arn
  }
}

# The API rule has to exist on whichever listener actually serves traffic, so it is
# duplicated onto the HTTPS one rather than assumed to be inherited — listener rules are
# per listener, and a missing rule here sends every /api/* call to the SPA, which answers
# 200 with index.html and makes the failure look like a frontend bug.
resource "aws_lb_listener_rule" "api_https" {
  count = local.alb_https ? 1 : 0

  listener_arn = aws_lb_listener.https[0].arn
  priority     = 100

  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.backend.arn
  }

  condition {
    path_pattern {
      values = ["/api/*"]
    }
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
