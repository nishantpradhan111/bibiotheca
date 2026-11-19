# Publishes subnet and VPC identifiers for deployment and connection setup.
output "network" {
  value = {
    vpc_id              = aws_vpc.library.id
    public_subnet_ids   = [for subnet in aws_subnet.public : subnet.id]
    private_subnet_ids  = [for subnet in aws_subnet.private : subnet.id]
    database_subnet_ids = [for subnet in aws_subnet.database : subnet.id]
  }
}

# Publishes EKS connection and OIDC values needed by kubectl and IRSA.
output "eks" {
  value = {
    cluster_name              = aws_eks_cluster.library.name
    endpoint                  = aws_eks_cluster.library.endpoint
    certificate_authority     = aws_eks_cluster.library.certificate_authority[0].data
    cluster_security_group_id = aws_eks_cluster.library.vpc_config[0].cluster_security_group_id
    oidc_provider_arn         = aws_iam_openid_connect_provider.eks.arn
  }
}

# Publishes RDS connection metadata while keeping its password in Secrets Manager.
output "member_database" {
  value = {
    address           = aws_db_instance.member.address
    port              = aws_db_instance.member.port
    database_name     = aws_db_instance.member.db_name
    master_secret_arn = aws_db_instance.member.master_user_secret[0].secret_arn
  }
  description = "Connection metadata only. Bootstrap a restricted application user separately; never use the master user in the API."
}

# Publishes Catalog's table, bucket, service-account, and IAM configuration.
output "catalog" {
  value = {
    books_table_name  = aws_dynamodb_table.books.name
    copies_table_name = aws_dynamodb_table.copies.name
    copies_index_name = "book_id-index"
    bucket_name       = aws_s3_bucket.covers.bucket
    role_arn          = aws_iam_role.catalog.arn
    namespace         = "library"
    service_account   = "catalog"
  }
}

# Publishes the SQS, Lambda, and publisher-role values needed by workloads.
output "event_driven_notification" {
  value = {
    queue_url       = aws_sqs_queue.notification.url
    dead_letter_arn = aws_sqs_queue.notification_dlq.arn
    lambda_name     = aws_lambda_function.notification.function_name
    api_role_arn    = aws_iam_role.notification_api.arn
  }
}

# Publishes the EMR ID, Kafka topics, and Flink checkpoint location.
output "analytics" {
  value = {
    emr_cluster_id       = try(aws_emr_cluster.analytics[0].id, null)
    input_topic          = "library.events.v1"
    results_topic        = "library.analytics.results.v1"
    checkpoint_prefix    = "s3://${aws_s3_bucket.covers.bucket}/flink/checkpoints/"
    cloudwatch_log_group = aws_cloudwatch_log_group.analytics.name
  }
}

# Publishes the IAM role annotation used by the Fluent Bit DaemonSet.
output "fluent_bit_role_arn" {
  value = aws_iam_role.fluent_bit.arn
}

# Publishes each ECR image URI for the build-and-publish script.
output "image_repositories" {
  value       = { for name, repo in aws_ecr_repository.service : name => repo.repository_url }
  description = "ECR destinations consumed by scripts/publish-images.ps1."
}
