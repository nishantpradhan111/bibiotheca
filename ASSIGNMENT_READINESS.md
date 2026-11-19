# Assignment Requirements Readiness

This matrix maps the Cloud Computing assignment requirements to the repository.
It separates source implementation from live AWS verification; a checked-in
manifest is not proof that a workload is running.

| Requirement | Repository implementation | Current verification |
|---|---|---|
| a. Provision infrastructure with IaC | [Terraform](./infra/) defines VPC, EKS, RDS, DynamoDB, S3, SQS, Lambda, ECR, IAM, and optional EMR. [Kubernetes resources](./k8s/) are reconciled by Argo CD. | Terraform formatting passes. `validate` and offline tests are blocked because provider plugins do not answer Terraform's schema handshake. The AWS account already has infrastructure in `us-east-1`; state and live resources must be reconciled before any apply. |
| b. Eight services and REST, gRPC, and event messaging | Seven REST APIs, the frontend, and Notification Lambda are separate runtimes. Member serves gRPC; Reservation/Lending use REST and transactional Kafka outboxes; Notification uses SQS/Lambda/SES. | Python service tests pass except Catalog's emulator-backed tests. The new outbox rows and event envelope have unit coverage. No end-to-end AWS call has been confirmed. |
| c. Managed Kubernetes, two HPAs, and load testing | EKS manifests define Catalog and Reservation HPAs; [k6 script](./scripts/k6/reservation-load.js) uses existing records and read-only requests. | k6 syntax inspection passes. No load was run because Docker and Kubernetes API access are unavailable. Existing EKS has one `t3.small` worker, which needs a capacity review. |
| d. GitOps deployment | [Argo CD Applications](./argocd/) watch the app and platform Kustomize trees. The platform tree installs the AWS Load Balancer Controller through an Argo CD child Application. | Manifests render and built-in schemas validate. Current Argo sync and repository branch were not inspected because kubectl TLS validation fails. |
| e. Flink windowed analytics | [Usage Analytics](./services/usage-analytics/) reads the shared event envelope, aggregates one-minute event-time windows, deduplicates event IDs in a window, and writes a results topic. | Maven `clean verify` passes: 3 tests. The Kafka/EMR live path still needs target-account verification. |
| f. ZooKeeper concept | Reservation coordinates per-book allocation with ZooKeeper in Kubernetes and an in-memory lock locally. | Reservation API tests pass; the live ZooKeeper path was not exercised from this workstation. |
| g. Three storage products | Services use PostgreSQL, DynamoDB, and S3; Terraform and runtime adapters are in [infra](./infra/) and the service folders. | AWS inventory found an available RDS instance and three DynamoDB tables in `us-east-1`. S3 access and cover upload/download are not currently verified. |
| h. Prometheus, Grafana, and centralized logs | [Observability manifests](./k8s/platform/) define service scrape health, pod readiness, RPS, 5xx rate, success rate, p95 latency, replicas, HPA state, restarts, memory, and CPU. Fluent Bit forwards app logs; the optional EMR bootstrap forwards Flink/YARN logs to CloudWatch. | App and platform Kustomize output validates. Four custom resources need their CRD schemas; no live Grafana queries or CloudWatch streams were checked. |

## Local checks completed

- Python tests in the `deeplearning` Anaconda environment: root demo controls 10 passed; Member 21 passed and 1 skipped; Catalog config 5 passed; Reservation 6 passed; Lending 11 passed; Availability 5 passed; Fine 5 passed; Notification 4 passed.
- Catalog's full integration suite needs DynamoDB Local and MinIO. Docker Desktop's Linux engine remains in `starting` state and returns an API error.
- Compose configuration, frontend syntax, Kustomize app/platform rendering, and k6 script inspection pass.
- Terraform `fmt -check` passes. `terraform validate` and `terraform test` cannot load the AWS and archive provider schemas.

## AWS inventory and deployment gate

The `library-deployer` profile identifies the account configured in the ignored
Terraform variables file. A read-only inventory on 19 November 2026 found an
ACTIVE EKS 1.35 cluster, one ACTIVE `t3.small` node group, an EMR cluster in
`WAITING`, an available `db.t4g.micro` RDS instance, three DynamoDB tables,
Digital Library ECR repositories, a Notification Lambda, and SQS/DLQ in
`us-east-1`. No ALB was found. The same inventory found no matching EKS, EMR,
RDS, DynamoDB, or ECR resources in `ap-south-1`.

The ignored Terraform variables file says `us-east-1`, while the assignment
design documents say `ap-south-1`. No apply, image push, or workload mutation has
been run. Use [CLOUD_DEPLOYMENT_RUNBOOK.md](./CLOUD_DEPLOYMENT_RUNBOOK.md) after
the region and budget are confirmed. Kubernetes API calls still fail TLS
verification on this workstation, so application pods and Argo CD health remain
unknown. Adding the EMR CloudWatch agent/bootstrap configuration may require a
cluster replacement; review the exact Terraform plan before allowing that
change.
