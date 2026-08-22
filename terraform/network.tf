# VPC, subnets, and routing — docs/09 §1.
#
# Two properties define this topology, and both are worth stating because a later change
# can erase them without looking like it did:
#
#   1. Nothing has a public IP except the NAT gateways. Not the load balancer, not either
#      service. The public subnets exist only to give NAT a route to the internet.
#   2. All compute is in private subnets, which means a widened security group is not on
#      its own enough to expose anything — there is no route from the internet either.

resource "aws_vpc" "main" {
  cidr_block           = var.vpc_cidr
  enable_dns_support   = true
  enable_dns_hostnames = true # interface endpoints resolve by DNS name

  tags = { Name = local.name }
}

resource "aws_internet_gateway" "main" {
  vpc_id = aws_vpc.main.id
  tags   = { Name = local.name }
}

resource "aws_subnet" "public" {
  count = length(local.azs)

  vpc_id            = aws_vpc.main.id
  cidr_block        = local.public_subnet_cidrs[count.index]
  availability_zone = local.azs[count.index]

  # Explicitly false. The default is false too, but "no public IPs" is the point of the
  # design and a stated intention is harder to undo by accident than an omitted one.
  map_public_ip_on_launch = false

  tags = { Name = "${local.name}-public-${local.azs[count.index]}", Tier = "public" }
}

resource "aws_subnet" "private" {
  count = length(local.azs)

  vpc_id            = aws_vpc.main.id
  cidr_block        = local.private_subnet_cidrs[count.index]
  availability_zone = local.azs[count.index]

  tags = { Name = "${local.name}-private-${local.azs[count.index]}", Tier = "private" }
}

# One NAT per AZ by default; one in total when `single_nat_gateway` is set. The trade is
# spelled out on the variable — a second NAT is 23% of the idle bill, and what it buys is
# that one AZ's NAT failing does not take the other AZ's egress with it. dev takes the
# cheap option because it is ephemeral and single-purpose (docs/09 §6.3).
resource "aws_eip" "nat" {
  count      = local.nat_count
  domain     = "vpc"
  depends_on = [aws_internet_gateway.main]

  tags = { Name = "${local.name}-nat-${local.azs[count.index]}" }
}

resource "aws_nat_gateway" "main" {
  count = local.nat_count

  allocation_id = aws_eip.nat[count.index].id
  subnet_id     = aws_subnet.public[count.index].id
  depends_on    = [aws_internet_gateway.main]

  tags = { Name = "${local.name}-${local.azs[count.index]}" }
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.main.id
  tags   = { Name = "${local.name}-public" }
}

resource "aws_route" "public_internet" {
  route_table_id         = aws_route_table.public.id
  destination_cidr_block = "0.0.0.0/0"
  gateway_id             = aws_internet_gateway.main.id
}

resource "aws_route_table_association" "public" {
  count = length(local.azs)

  subnet_id      = aws_subnet.public[count.index].id
  route_table_id = aws_route_table.public.id
}

# One route table per private subnet, because each points at its own AZ's NAT.
resource "aws_route_table" "private" {
  count = length(local.azs)

  vpc_id = aws_vpc.main.id
  tags   = { Name = "${local.name}-private-${local.azs[count.index]}" }
}

resource "aws_route" "private_nat" {
  count = length(local.azs)

  route_table_id         = aws_route_table.private[count.index].id
  destination_cidr_block = "0.0.0.0/0"
  # With one NAT, both private subnets point at it — which is precisely the cross-AZ
  # dependency the variable's description describes.
  nat_gateway_id = aws_nat_gateway.main[var.single_nat_gateway ? 0 : count.index].id
}

resource "aws_route_table_association" "private" {
  count = length(local.azs)

  subnet_id      = aws_subnet.private[count.index].id
  route_table_id = aws_route_table.private[count.index].id
}
