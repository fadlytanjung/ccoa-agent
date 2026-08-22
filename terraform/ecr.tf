# Image repositories — docs/08 §3.2.

resource "aws_ecr_repository" "backend" {
  name                 = "${local.name}-backend"
  image_tag_mutability = "IMMUTABLE" # a SHA tag must never point at different bytes

  image_scanning_configuration {
    scan_on_push = true
  }

  # `dev` is destroyed routinely, and a repository with images in it blocks the destroy.
  # "Destroy leaves nothing behind" is a requirement here (docs/08 §3.1).
  force_delete = true

  tags = { Name = "${local.name}-backend" }
}

resource "aws_ecr_repository" "frontend" {
  name                 = "${local.name}-frontend"
  image_tag_mutability = "IMMUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  force_delete = true

  tags = { Name = "${local.name}-frontend" }
}

locals {
  # Keep the last ten. Enough to roll back several deploys, few enough that storage stays
  # negligible.
  ecr_lifecycle = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep the 10 most recent images"
      selection = {
        tagStatus   = "any"
        countType   = "imageCountMoreThan"
        countNumber = 10
      }
      action = { type = "expire" }
    }]
  })
}

resource "aws_ecr_lifecycle_policy" "backend" {
  repository = aws_ecr_repository.backend.name
  policy     = local.ecr_lifecycle
}

resource "aws_ecr_lifecycle_policy" "frontend" {
  repository = aws_ecr_repository.frontend.name
  policy     = local.ecr_lifecycle
}
