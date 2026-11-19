# Digital Library: AWS Deployment Runbook

Use this document for an approved, complete deployment of the Digital Library.

**Read-only account inventory on 19 November 2026 found an active EKS cluster,
an EMR cluster in `WAITING`, an available RDS instance, three DynamoDB tables,
and Digital Library ECR repositories in `us-east-1`. No matching resources were
found in `ap-south-1`.** The existing Kubernetes API could not be inspected from
this workstation. Resolve the target region and reconcile Terraform state before
using this fresh-deployment runbook; do not create duplicate infrastructure.

The repository is not a deploy-and-forget application. Before running the documented commands, assign one team lead as the AWS owner and one team member as the Kubernetes/GitOps owner. No command in this document grants deployment approval.

## 0. Completion targets

The deployment is complete only when all of the following are true:

- AWS infrastructure is created through Terraform.
- Seven stateless HTTP microservices run on EKS.
- A public URL reaches the frontend and public APIs.
- REST, gRPC, SQS/Lambda, and Kafka/Flink are exercised.
- RDS, DynamoDB, and S3 are used.
- Catalog and Reservation HPAs scale under sustained k6 traffic.
- Argo CD reconciles Git changes.
- Prometheus and Grafana show service and cluster data.
- Fluent Bit sends application logs to CloudWatch.
- One Flink run publishes results to a results Kafka topic.
- Every deployed image is pinned to an immutable registry digest.
- A cleanup plan removes or retains only explicitly approved resources.

Do not report the deployment as complete after Terraform, EKS, or an Ingress only.

## 1. Team assignments

Before starting, assign one person to each area:

| Owner | Responsibility |
|---|---|
| AWS/IaC owner | Account access, cost approval, Terraform state, plan, apply, and teardown |
| Container/ECR owner | Builds, registries, immutable image digests, and Kubernetes substitutions |
| Database owner | RDS bootstrap, restricted users, schemas, TLS CA, and Kubernetes Secrets |
| GitOps owner | Argo CD, repository access, application sync, and manifest troubleshooting |
| Integration owner | REST/gRPC/Kafka/SQS/Lambda/Flink and end-to-end test evidence |
| Observability/load owner | Prometheus, Grafana, CloudWatch, k6, and HPA evidence |

Every member must still demonstrate their two assigned services and answer questions.

## 2. Account and budget gate

Use an existing non-root IAM identity. Never paste AWS keys, session tokens, or secrets into Git or chat.

```powershell
aws configure list-profiles
$env:AWS_PROFILE = "library-deployer"
aws sts get-caller-identity --no-cli-pager
aws eks describe-cluster-versions `
  --region ap-south-1 `
  --version-status STANDARD_SUPPORT `
  --query 'clusterVersions[].clusterVersion' `
  --output json `
  --no-cli-pager
curl.exe https://checkip.amazonaws.com
```

Stop if the caller is a root identity or an assumed-role STS session. Use an administrator IAM user or role ARN for `cluster_admin_principal_arn`.

Before approval, confirm:

- The account 12-digit ID.
- AWS region and two available AZs.
- Remaining AWS credits and credit expiry.
- Free/Paid plan restrictions.
- EKS service quota.
- EC2 instance availability.
- RDS availability.
- ECR availability.
- SES sandbox status and verified sender.
- NAT gateway, public IPv4, ALB, EKS, RDS, EMR, data transfer, and snapshot costs.
- An explicit cost target under the approved testing budget.
- The time of teardown and who will perform it.
- Remote Terraform state and locking ownership.

Budget for idle time as well as the demo. AWS currently lists the standard EKS
control-plane fee at $0.10 per cluster-hour (about $73 for 730 hours), before
worker EC2, storage, NAT, RDS, load-balancer, and EMR charges. EMR on EC2 adds
EMR charges to EC2 and EBS charges. See [EKS pricing](https://aws.amazon.com/eks/pricing/)
and [EMR pricing](https://aws.amazon.com/emr/pricing/). The existing EMR cluster
is in `WAITING`; keep the analytics cluster windowed and inspect its billing
state before leaving it idle.

The original saved plan reports 48 additions and no changes/deletions. It is not a fresh or account-wide approval and must not be applied.

## 3. Obtain required live prerequisites

### 3.1 AWS values

Create an ignored local variable file at `infra/terraform.tfvars`:

```hcl
aws_account_id               = "REPLACE_WITH_12_DIGIT_ACCOUNT_ID"
aws_region                   = "ap-south-1"
availability_zones           = ["ap-south-1a", "ap-south-1b"]
environment                  = "dev"
kubernetes_version           = "REPLACE_WITH_CONFIRMED_SUPPORTED_VERSION"
cluster_admin_principal_arn  = "arn:aws:iam::ACCOUNT_ID:user/administrator"
eks_public_access_cidrs      = ["ADMINISTRATOR_PUBLIC_IP/32"]
node_instance_type           = "t3.xlarge"
db_instance_class            = "db.t4g.micro"
enable_analytics_cluster     = true
emr_termination_protection   = true
cover_bucket_name            = "globally-unique-library-covers-name"
ses_sender                   = "verified@example.com"
protect_data                 = true
```

Never commit this file or real database passwords.

### 3.2 Repository values

Decide and record:

- GitHub repository URL and branch.
- ECR registry URI.
- EKS cluster name.
- K8s namespace `library`.
- Public DNS name.
- Service-account names.
- RDS application database name.
- One restricted role/user per database-owning service.
- A TLS-verified RDS connection string for each service.
- Kafka/MSK decision.
- SES sender and recipient verification.

The Flink demonstration uses the EMR cluster. Terraform defaults to keeping it
enabled and termination-protected to preserve the existing cluster. To clean it
up, set `emr_termination_protection = false` in a reviewed plan and apply that
change, then set `enable_analytics_cluster = false` in a second reviewed plan to
terminate the cluster.

## 4. Pre-deployment validation

Run local validation before any AWS plan.

```powershell
Set-Location "C:\Nishant\Work\BITS - Engineering\4-1\Cloud Computing\Project\bibiotheca"

docker compose up --build -d --wait --wait-timeout 600
docker compose ps

docker compose exec -T member /venv/bin/python -m pytest -q -p no:cacheprovider
docker compose exec -T catalog /venv/bin/python -m pytest -q -p no:cacheprovider
docker compose exec -T -e S3_PUBLIC_ENDPOINT_URL=http://minio:9000 catalog /venv/bin/python -m pytest -q -p no:cacheprovider

Set-Location infra
terraform fmt -check -recursive
terraform init -backend=false -input=false
terraform validate -no-color
terraform test '-filter=tests\offline.tftest.hcl' -no-color

Set-Location ..
kubectl kustomize k8s -o .local/rendered-app.yaml
kubectl kustomize k8s/platform -o .local/rendered-platform.yaml

node --check frontend/app.js
node --check frontend/server.js
```

Do not proceed after a failing check.

## 5. Fix manifest and topic placeholders

Before deployment, edit Git-tracked files.

### 5.1 Standardize Kafka topics

Choose one pair and update both infrastructure, Kafka jobs, Flink environments, documentation, and analytics publishers.

Recommended names:

- `library.events.v1`
- `library.analytics.results.v1`

Update `UsageAnalyticsJob` defaults and all Kubernetes environment variables. Do not leave both names in the deployment.

### 5.2 Replace placeholder images

The checked-in image digests currently refer to a different ECR registry. Build
and publish images into the target AWS account, then replace every digest before
Argo CD sync. Do not assume an existing account's digest is available.

Build images for:

- Member
- Catalog
- Reservation
- Lending
- Availability
- Notification
- Fine
- Frontend

Remove `imagePullPolicy: IfNotPresent` or set `Always` only with immutable digest references.

Use:

```text
REGISTRY/library-member@sha256:...
```

For a new release, update every image together and commit the substitutions.

### 5.3 Make the frontend publicly deployable

The repository already has a frontend image, Deployment, Service, and ALB
Ingress. The container sets `HOST=0.0.0.0`; the server's loopback default is for
local development. The frontend serves `/` and proxies browser `/api/...`
requests to internal service DNS. Confirm the target account's ALB controller,
public subnet tags, security groups, DNS, and TLS before exposing it publicly.

### 5.4 Replace cloud placeholders

Update or generate substituted manifests for:

- Catalog IAM role ARN.
- AWS region.
- DynamoDB books/copies table names.
- S3 cover bucket.
- Notification SQS URL.
- Fluent Bit role ARN.
- Grafana credentials.
- RDS CA ConfigMap.
- RDS database Secrets.
- Kafka/MSK bootstrap servers.
- Flink jar location and Kafka client properties.

Keep passwords and access keys out of ConfigMaps and source control.

### 5.5 Add required controller resources

Terraform creates the load balancer controller IAM role and policy. The platform
Kustomize tree now defines the controller ServiceAccount and a child Argo CD
Application pinned to the AWS chart. Run `configure-aws.ps1` to fill its role,
cluster, region, and VPC values before syncing the platform application.

Install or provision separately:

- EKS managed add-ons:
  - VPC CNI
  - CoreDNS
  - kube-proxy
  - EBS CSI, if dynamic storage is later added
- Metrics-server.
- Argo CD.
- Argo CD repository credentials or repository trust.

Argo CD installs the AWS Load Balancer Controller chart; Fluent Bit uses its
Terraform-created IRSA role. Do not deploy the controller with a direct
`kubectl apply` command.

## 6. Build and publish container images

This is an AWS image-publishing operation. Require explicit approval first.

```powershell
$env:AWS_PROFILE = "library-deployer"
$AWS_REGION = "ap-south-1"
$AWS_ACCOUNT = "<12-DIGIT-ACCOUNT>"
$REGISTRY = "$AWS_ACCOUNT.dkr.ecr.$AWS_REGION.amazonaws.com"

aws ecr get-login-password --region $AWS_REGION |
  docker login --username AWS --password-stdin $REGISTRY
```

Create an ECR repository for each image. Build from `digital-library`:

```powershell
$services = @(
  "member",
  "catalog",
  "reservation",
  "lending",
  "availability",
  "notification",
  "fine"
)

foreach ($service in $services) {
  $image = "$REGISTRY/library-$service"
  docker build --pull -t $image:latest "services/$service"
  docker push $image:latest
  $digest = docker inspect --format '{{index .RepoDigests 0}}' $image:latest
  Write-Host "$service = $digest"
}
```

Build the frontend separately:

```powershell
docker build -t "$REGISTRY/library-frontend:latest" frontend
docker push "$REGISTRY/library-frontend:latest"
```

Record each immutable `@sha256:...` digest. Replace every manifest `image:` with that digest before Argo CD sync.

## 7. Create a fresh Terraform plan

Explicitly approved real-account planning:

```powershell
Set-Location "C:\Nishant\Work\BITS - Engineering\4-1\Cloud Computing\Project\bibiotheca\infra"
$env:AWS_PROFILE = "library-deployer"

terraform init -backend=false -input=false
terraform plan `
  -input=false `
  "-var-file=terraform.tfvars" `
  "-out=approved-review.tfplan"
```

Review every resource and change count. Stop for unexpected changes, deletions, unrelated resources, or missing account identifiers.

Do not share the raw plan; it may contain sensitive values.

Do not run `apply` until the following are explicitly approved separately:

- AWS account.
- Resource set.
- Region/AZs.
- Cost estimate.
- State location.
- IAM principal.
- EKS version.
- RDS class and protection.
- NAT/ALB/EMR costs.
- Database and secret bootstrap.
- SES mode.
- Kafka choice.
- Cleanup date.

## 8. Approved Terraform apply

Only after separate apply approval:

```powershell
terraform apply -input=false approved-review.tfplan
```

Save the nonsecret output set:

```powershell
terraform output -json > ../.local/terraform-outputs.json
terraform output eks
terraform output member_database
terraform output catalog
terraform output event_driven_notification
terraform output analytics
terraform output fluent_bit_role_arn
```

Never print or commit RDS master password values.

## 9. Configure EKS access

```powershell
$cluster = terraform -chdir=. output -raw eks.cluster_name
aws eks update-kubeconfig `
  --region ap-south-1 `
  --name $cluster `
  --profile library-deployer

kubectl get nodes
kubectl get storageclass
kubectl cluster-info
```

Do not use `kubectl apply` for application workloads. It is used here only for access verification and separately created operational bootstrap resources.

## 10. Bootstrap RDS safely

The RDS master secret is a secret management source, not an API credential.

Create a restricted application user or role using a separate approved temporary administrator process.

Minimum setup:

- Create `library` or an agreed application database.
- Create `member_app`, `reservation_app`, `lending_app`, `availability_app`, and `fine_app` users.
- Member can read/write `members`.
- Reservation can read/write `reservations`.
- Lending can create/read/update `loans`.
- Fine has read-only access to `loans`.
- Availability has read-only access to `loans` and `reservations`.
- Disable public database access.
- Require TLS.

Create the RDS CA ConfigMap:

```powershell
kubectl create namespace library
kubectl create configmap rds-ca `
  --namespace library `
  --from-file=global-bundle.pem=/approved/path/global-bundle.pem
```

Create Secrets with `kubectl create secret generic`, never source control:

```powershell
kubectl create secret generic member-database `
  --namespace library `
  --from-literal=DATABASE_URL='postgresql+psycopg://member_app:ENCODED_PASSWORD@RDS_HOST:5432/library?sslmode=verify-full&sslrootcert=/etc/rds-ca/global-bundle.pem'

kubectl create secret generic reservation-database `
  --namespace library `
  --from-literal=url='postgresql+psycopg://reservation_app:ENCODED_PASSWORD@RDS_HOST:5432/library?sslmode=verify-full&sslrootcert=/etc/rds-ca/global-bundle.pem'

kubectl create secret generic lending-database `
  --namespace library `
  --from-literal=url='postgresql+psycopg://lending_app:ENCODED_PASSWORD@RDS_HOST:5432/library?sslmode=verify-full&sslrootcert=/etc/rds-ca/global-bundle.pem'

kubectl create secret generic availability-database `
  --namespace library `
  --from-literal=url='postgresql+psycopg://availability_app:ENCODED_PASSWORD@RDS_HOST:5432/library?sslmode=verify-full&sslrootcert=/etc/rds-ca/global-bundle.pem'

kubectl create secret generic fine-database `
  --namespace library `
  --from-literal=url='postgresql+psycopg://fine_app:ENCODED_PASSWORD@RDS_HOST:5432/library?sslmode=verify-full&sslrootcert=/etc/rds-ca/global-bundle.pem'
```

URL-encode special characters in passwords. Never commit the command history or shell transcript if it contains secrets.

## 11. Bootstrap SES and notification delivery

For a sandbox account:

1. Verify the SES sender.
2. Verify every demo recipient.
3. Keep the sender and recipients within approved identities.
4. Test SES only after explicit notification approval.

Test SQS/Lambda:

```powershell
aws sqs send-message `
  --queue-url "<QUEUE_URL>" `
  --message-body '{"notification_id":"deploy-test-1","recipient":"verified@example.com","subject":"Digital Library test","body":"Deployment test","event":{"recipient":"verified@example.com","body":"Deployment test"}}'

aws lambda invoke `
  --function-name "<LAMBDA_NAME>" `
  --payload fileb://test-payload.json `
  .local/lambda-output.json
```

Verify:

- Exactly one email for one notification.
- Duplicate redelivery does not send twice.
- Malformed messages report item failures.
- Invalid messages enter the DLQ after redrive policy counts.
- DynamoDB dedupe records are created and expire.

Update `notification-config` with the real SQS URL.

## 12. Supply catalog IAM values

Update:

- `eks.amazonaws.com/role-arn`
- AWS region
- Books table
- Copies table
- Cover bucket

Confirm:

- Catalog service-account name is `catalog`.
- Namespace is `library`.
- Audience is `sts.amazonaws.com`.
- `AWS_EC2_METADATA_DISABLED=true`.
- EKS OIDC provider exists.
- No static AWS keys are in the manifests.
- The pod can list/Get/Put allowed cover objects.

Test:

```powershell
kubectl run aws-check `
  --namespace library `
  --rm -it `
  --restart=Never `
  --image=amazon/aws-cli `
  --serviceaccount=catalog `
  -- sts get-caller-identity
```

## 13. Choose the Kafka implementation

The target manifests use one self-managed KRaft Kafka broker on EKS, with a
private NodePort used by EMR. The Terraform root does not create Amazon MSK.
This matches the assignment's example where Kafka may be self-managed, but it
does not satisfy a requirement for a managed Kafka product. Keep the broker
private and verify its route from EMR before running Flink.

## 14. Prepare EMR and Flink

The new CloudWatch Agent/bootstrap settings may replace an existing EMR cluster.
Review and approve that exact replacement in the Terraform plan; do not apply it
as an incidental change while updating Kubernetes workloads.

Build the shaded job:

```powershell
Set-Location "C:\Nishant\Work\BITS - Engineering\4-1\Cloud Computing\Project\bibiotheca\services\usage-analytics"
mvn -B clean verify
```

Confirm that `target/usage-analytics-1.0.0.jar` exists.

Upload the jar and classpath dependencies to the approved S3 artifact location:

```powershell
aws s3 cp target/usage-analytics-1.0.0.jar `
  s3://<COVER_BUCKET>/flink/jobs/usage-analytics-1.0.0.jar
```

Create topics:

```text
library.events.v1
library.analytics.results.v1
```

Submit only after the Kafka bootstrap server and network route are verified.

Set:

```text
KAFKA_BOOTSTRAP_SERVERS=<BROKER_ADDRESS>
KAFKA_INPUT_TOPIC=library.events.v1
KAFKA_RESULTS_TOPIC=library.analytics.results.v1
KAFKA_CONSUMER_GROUP=library-usage-analytics
KAFKA_CLIENT_PROPERTIES=<APPROVED_KAFKA_PROPERTIES>
```

Publish test events and verify:

- Event-time windows are UTC-aligned.
- One-minute buckets contain the expected counts.
- Unique-member sets are correct.
- Late events up to 30 seconds are handled.
- Results appear in the separate results topic.
- Checkpoints are written to S3.
- Flink/YARN logs appear in CloudWatch Logs group `/digital-library/analytics`.

## 15. Install Argo CD and platform components

Install Argo CD through an approved Helm or documented bootstrap method.

Create a Git repository application only after repository credentials and branch/revision are verified.

Install or bootstrap:

- Metrics-server.
- Prometheus/Grafana.
- Fluent Bit.
- Platform ZooKeeper/Kafka.
- Argo CD Applications.

The platform Argo CD application installs the AWS Load Balancer Controller from
its child Application after the ServiceAccount and IRSA role are configured.

Do not use `kubectl apply` for application resources. Argo CD must own application reconciliation.

## 16. Configure and sync Argo CD

Verify the repository and two Application paths:

- `k8s`
- `k8s/platform`

Confirm `argocd/application.yaml` tracks the team branch.

If a branch is temporarily fixed, commit the branch change and let Argo CD sync it.

Required sync order:

1. Namespace, Secrets, and ConfigMaps.
2. RDS CA and database bootstrap.
3. Platform metrics and ZooKeeper/Kafka.
4. Member and Catalog.
5. Reservation.
6. Lending, Availability, and Fine.
7. Notification adapter.
8. Frontend.
9. Ingress.

Argo CD can be used for platform and application workloads after the prerequisites exist.

## 17. Public endpoint setup

Sync the platform Argo CD application and wait for the controller:

```powershell
kubectl -n kube-system rollout status deployment/aws-load-balancer-controller --timeout=5m
kubectl -n kube-system get deployment aws-load-balancer-controller
```

Change the Ingress to public only with approval:

```yaml
alb.ingress.kubernetes.io/scheme: internet-facing
```

Keep public access constrained to the frontend and only approved API routes.

Use HTTPS with a DNS name and ACM certificate for the best demo. A plain HTTP ALB DNS is acceptable only if the team has explicitly accepted it.

Verify:

```powershell
kubectl get ingress -n library
kubectl describe ingress library-public -n library
kubectl get svc,pods -n library
```

Wait until the ALB address and DNS are resolvable.

## 18. Cloud service verification

Check every pod and dependency.

```powershell
kubectl get pods -n library
kubectl get deploy -n library
kubectl get hpa -n library
kubectl get ingress -n library

kubectl get pods -n observability
kubectl get pods -n argocd
```

For each service:

```powershell
$publicUrl = "https://<PUBLIC-DNS>"

Invoke-RestMethod "$publicUrl/api/member/health"
Invoke-RestMethod "$publicUrl/api/catalog/health"
Invoke-RestMethod "$publicUrl/api/reservations/health"
Invoke-RestMethod "$publicUrl/api/lending/health"
Invoke-RestMethod "$publicUrl/api/availability/health"
Invoke-RestMethod "$publicUrl/api/fine/health"
Invoke-RestMethod "$publicUrl/api/notifications/health"
```

Check readiness, not only `/health`.

```powershell
kubectl logs -n library deployment/member --tail=100
kubectl logs -n library deployment/catalog --tail=100
kubectl logs -n library deployment/reservation --tail=100
kubectl logs -n library deployment/lending --tail=100
kubectl logs -n library deployment/availability --tail=100
kubectl logs -n library deployment/fine --tail=100
kubectl logs -n library deployment/notification --tail=100
```

## 19. End-to-end application test

Test the following real flow:

1. Open the public frontend.
2. Create or retrieve a Member.
3. Create a Book.
4. Add at least two physical Copies.
5. Verify Availability.
6. Create a READY reservation.
7. Confirm the reservation and copy allocation.
8. Checkout the allocated copy through Lending.
9. Confirm Member eligibility through gRPC.
10. Confirm only one active loan exists for the copy.
11. Verify Availability decrements.
12. Calculate Fine for an overdue loan.
13. Return the loan.
14. Confirm the reservation is cancelled/promoted correctly.
15. Confirm notification delivery.
16. Confirm Reservation/Lending events reach Kafka.
17. Confirm Flink publishes a result.

The backend must expose:

- Member, Catalog, Reservation, Lending, Availability, Fine, and Notification.
- `/health`, `/ready`, and `/metrics` where documented.

## 20. HPA and k6 load test

First verify metrics-server:

```powershell
kubectl get deployment metrics-server -n kube-system
kubectl top nodes
kubectl top pods -n library
```

Run k6 only against the approved public endpoint:

```powershell
$env:BASE_URL = "https://<PUBLIC-DNS>"
$env:BOOK_ID = "<BOOK_ID>"
$env:MEMBER_ID = "<MEMBER_ID>"
$env:TOKEN = "<ONLY_IF_AUTH_IS_IMPLEMENTED>"

k6 run scripts/k6/reservation-load.js
```

Capture:

```powershell
kubectl get hpa -n library -w
kubectl get pods -n library -w
kubectl get hpa catalog reservation -n library -o yaml
```

Evidence required:

- k6 start time.
- k6 summary.
- HPA target CPU.
- HPA current CPU.
- Replica counts before, during, and after.
- Grafana CPU/RPS/latency/error panel.
- Pod scaling back down.

The k6 reservation traffic must not create invalid reservations. The script should use existing member/book IDs and stop if reservation copy logic rejects work unexpectedly.

## 21. Observability verification

### Prometheus

Verify `/metrics` is scraped:

```text
sum(rate(member_http_requests_total[1m]))
sum(rate(catalog_http_requests_total[1m]))
sum(rate(reservation_http_requests_total[1m]))
sum(rate(lending_http_requests_total[1m]))
sum(rate(availability_http_requests_total[1m]))
sum(rate(fine_http_requests_total[1m]))
```

Create Grafana panels for:

- RPS per service.
- Error rate per service.
- P95 latency per service.
- Catalog replicas and CPU.
- Reservation replicas and CPU.
- EKS node CPU.
- EKS node memory.
- Pod restarts.
- HPA desired/current replicas.

Do not leave a dashboard querying generic names that the services do not export.

### Central logs

Verify:

- Fluent Bit has the correct IRSA role.
- CloudWatch log group `/digital-library/eks` exists.
- Member/Catalog/Reservation/Lending/Availability/Fine/Notification logs appear.
- Lambda logs appear in the Lambda log group.
- EMR logs appear in S3 and CloudWatch as configured.
- Flink/EMR logs can be located for the demo.

## 22. Argo CD and direct-deployment verification

Verify no application resources were deployed with direct `kubectl apply`.

Capture:

- Argo CD application status.
- Synced/out-of-sync state.
- Health status.
- Repository revision.
- Resource graph.
- A Git commit followed by one observed reconciliation.

Then revert or accept the change through Git only.

## 23. Security verification

Before demo:

- RDS is private.
- S3 blocks public access.
- DynamoDB tables are not public.
- SQS/DLQ encryption is enabled.
- Lambda has least privilege.
- Catalog IRSA has least privilege.
- EKS public API CIDRs are restricted.
- Secrets contain no source-control values.
- Container images do not run as root.
- Pods drop Linux capabilities and disable privilege escalation.
- Only required ports are public.
- ALB has the correct public/internal scheme.
- TLS is enabled where available.
- Public DNS is documented.

## 24. Deadline evidence capture

Before submitting, save:

- Terraform plan summary and apply summary.
- Terraform outputs.
- ECR image URIs/digests.
- EKS `kubectl get nodes` and pod status.
- Argo CD screenshot.
- Public URL.
- Frontend screenshot.
- Swagger/OpenAPI screenshot.
- REST integration evidence.
- gRPC call evidence.
- SQS/Lambda event evidence.
- DynamoDB dedupe evidence.
- Kafka input/results evidence.
- Flink window/result evidence.
- HPA before/during/after screenshot.
- k6 summary.
- Grafana dashboard.
- CloudWatch logs.
- EMR logs/checkpoint evidence.
- RDS/DynamoDB/S3 evidence.
- Security group and IAM evidence.
- ZooKeeper/fencing evidence.

Do not capture credentials or secrets in screenshots.

## 25. Submission updates

Before uploading:

- Commit every source and manifest change.
- Update `task_divison.txt` with names, IDs, services, and assigned work.
- Update the design document with observed cloud architecture.
- Add deployed public URL and resource names.
- Mark live-verified requirements separately from unverified requirements.
- Update the runtime report from `PASS` to include:
  - Cloud account and region.
  - EKS version.
  - Public URL.
  - Live RDS/DynamoDB/S3 evidence.
  - HPA/k6 evidence.
  - GitOps revision.
  - Lambda/SQS/SES evidence.
  - Kafka/Flink evidence.
  - Prometheus/Grafana evidence.
  - CloudWatch/EMR logs.

Submit:

- Design PDF.
- GitHub repository URL.
- Public web URL.
- Kubernetes manifest and GitOps configuration.
- Terraform source and offline test evidence.
- HPA/load test evidence.
- Microservice test evidence.
- `task_divison.txt`.

## 26. Demo rehearsal

Prepare a 10-minute flow:

1. State the domain and architecture.
2. Open the public frontend.
3. Create/retrieve a member.
4. Show a book and copies.
5. Show availability.
6. Create a reservation.
7. Checkout and return.
8. Show Kafka/Flink result.
9. Show notification.
10. Run k6 briefly.
11. Show replicas scale.
12. Show Grafana and CloudWatch.
13. Show Argo CD sync.
14. Show Terraform and explain storage/IAM choices.

Each student should own and demonstrate their assigned services.

## 27. Cleanup gate

Do not destroy resources merely because the demo finished.

Before cleanup, confirm:

- Who owns each resource.
- Retained RDS snapshots, S3 objects, DynamoDB data, secrets, IP addresses, and logs.
- Deletion-protection settings.
- SQS, Lambda, EMR, EKS, ALB, NAT, and public IP charges.
- Final snapshots and whether they are to be retained.
- Whether an explicit cleanup or retain operation is required.

After approval, stop or destroy only the resources listed by the team.

```powershell
terraform destroy "-var-file=terraform.tfvars"
```

Only run this after:

- The demo is complete.
- Every team member agrees.
- Retained evidence is downloaded.
- The exact cost impact is understood.
- Snapshot/object/IP cleanup has separate approval.

## 28. Immediate no-credit-fallback

If AWS approval or SES/Kafka/MSK prerequisites are not available before the deadline:

- Keep the Docker Compose demo running.
- Demonstrate Terraform and Kubernetes statically.
- Demonstrate HPA manifests and k6 script.
- Demonstrate the public frontend locally.
- Demonstrate REST/gRPC/Kafka/Flink source code and tests.
- Clearly label live AWS components as not deployed.
- Do not fabricate AWS screenshots or status.

For the final submission, static code and IaC are better evidence than spending credits on an incomplete deployment.
