# Lets the EKS control plane call the AWS APIs needed to operate the cluster.
resource "aws_iam_role" "cluster" {
  name = "${local.name}-cluster"
  assume_role_policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Effect = "Allow", Action = "sts:AssumeRole", Principal = { Service = "eks.amazonaws.com" } }]
  })
}

# Grants the EKS service its required control-plane policy.
resource "aws_iam_role_policy_attachment" "cluster" {
  role       = aws_iam_role.cluster.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonEKSClusterPolicy"
}

# Creates the managed Kubernetes control plane with restricted public API access.
resource "aws_eks_cluster" "library" {
  name     = local.name
  role_arn = aws_iam_role.cluster.arn
  version  = var.kubernetes_version
  access_config {
    authentication_mode                         = "API"
    bootstrap_cluster_creator_admin_permissions = false
  }
  vpc_config {
    subnet_ids              = [for subnet in aws_subnet.private : subnet.id]
    endpoint_private_access = true
    endpoint_public_access  = true
    public_access_cidrs     = var.eks_public_access_cidrs
  }
  depends_on = [aws_iam_role_policy_attachment.cluster]
}

# Registers the named IAM principal as a cluster administrator.
resource "aws_eks_access_entry" "administrator" {
  cluster_name  = aws_eks_cluster.library.name
  principal_arn = var.cluster_admin_principal_arn
  type          = "STANDARD"
}

# Associates cluster-wide administrative permissions with that access entry.
resource "aws_eks_access_policy_association" "administrator" {
  cluster_name  = aws_eks_cluster.library.name
  principal_arn = aws_eks_access_entry.administrator.principal_arn
  policy_arn    = "arn:aws:eks::aws:cluster-access-policy/AmazonEKSClusterAdminPolicy"
  access_scope {
    type = "cluster"
  }
}

# Lets EC2 workers join EKS and pull container images.
resource "aws_iam_role" "nodes" {
  name = "${local.name}-nodes"
  assume_role_policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Effect = "Allow", Action = "sts:AssumeRole", Principal = { Service = "ec2.amazonaws.com" } }]
  })
}

# Attaches the minimum standard EKS worker, ECR pull, and CNI policies.
resource "aws_iam_role_policy_attachment" "nodes" {
  for_each   = toset(["AmazonEKSWorkerNodePolicy", "AmazonEC2ContainerRegistryPullOnly", "AmazonEKS_CNI_Policy"])
  role       = aws_iam_role.nodes.name
  policy_arn = "arn:aws:iam::aws:policy/${each.key}"
}

# Enforces encrypted node disks and IMDSv2 for worker instances.
resource "aws_launch_template" "nodes" {
  name_prefix            = "${local.name}-"
  vpc_security_group_ids = [aws_eks_cluster.library.vpc_config[0].cluster_security_group_id]
  metadata_options {
    http_endpoint               = "enabled"
    http_tokens                 = "required"
    http_put_response_hop_limit = 1
  }
  block_device_mappings {
    device_name = "/dev/xvda"
    ebs {
      volume_size           = 20
      volume_type           = "gp3"
      encrypted             = true
      delete_on_termination = true
    }
  }
  credit_specification {
    cpu_credits = "standard"
  }
}

# Runs the application on one fixed-size managed worker group for the demo.
resource "aws_eks_node_group" "library" {
  cluster_name    = aws_eks_cluster.library.name
  node_group_name = "${local.name}-workers"
  node_role_arn   = aws_iam_role.nodes.arn
  subnet_ids      = [for subnet in aws_subnet.private : subnet.id]
  instance_types  = [var.node_instance_type]
  ami_type        = "AL2023_x86_64_STANDARD"
  capacity_type   = "ON_DEMAND"
  launch_template {
    id      = aws_launch_template.nodes.id
    version = aws_launch_template.nodes.latest_version
  }
  scaling_config {
    desired_size = 1
    min_size     = 1
    max_size     = 1
  }
  # Wait for EMR replacement to release its old capacity before launching EKS.
  depends_on = [aws_iam_role_policy_attachment.nodes, aws_route.private_internet, aws_emr_cluster.analytics]
}
