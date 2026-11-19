# Digital Library Architecture Views

This file documents the system in three complementary views: **allocation** (where runtime responsibilities are deployed), **module** (how code is divided), and **component-and-connector** (how requests and events move between runtime components). Reservation and Lending now persist events through transactional outboxes; the AWS Kafka and EMR path still requires live verification.

## 1. Allocation View

This view maps software responsibilities to AWS and Kubernetes resources. Terraform owns the AWS account resources; Argo CD owns application and platform Kubernetes resources after bootstrap. The sample node and database sizes are not cost estimates and must be validated against current account quotas and prices before applying.

<!-- mermaid-checked: no \\n, no em-dash/en-dash, no {} in labels, subgraphs are id["label"], arrows are -->|"label"|, all subgraphs closed by end, ids unique -->
~~~mermaid
flowchart LR
    Reader["Reader Browser"] -->|"HTTPS"| ALB["Public Application Load Balancer"]
    ALB -->|"web and API routes"| Frontend["Frontend Service"]
    Frontend -->|"cluster REST"| APIs

    subgraph Aws["AWS ap-south-1"]
        subgraph Vpc["VPC"]
            subgraph Eks["Managed EKS Cluster"]
                subgraph AppNs["library Namespace"]
                    Frontend
                    APIs["Member Catalog Reservation Lending Availability Fine Notification"]
                    Kafka["Single KRaft Kafka Broker"]
                    Zk["ZooKeeper Ensemble"]
                    Fluent["Fluent Bit DaemonSet"]
                end
                subgraph ObsNs["observability Namespace"]
                    Prom["Prometheus"]
                    Grafana["Grafana"]
                    Ksm["kube-state-metrics"]
                end
                Argo["Argo CD"]
            end
            Rds[("Private RDS PostgreSQL")]
            Emr["EMR Flink Runtime"]
            Nat["NAT Gateway"]
        end
        Ddb[("DynamoDB")]
        S3[("Private S3")]
        Sqs["SQS and DLQ"]
        Lambda["Notification Lambda"]
        Ses["SES"]
        Ecr["ECR Repositories"]
        Cw["CloudWatch Logs"]
    end
    Git["Git Repository"] -->|"manifests"| Argo
    Ecr -->|"immutable image digests"| APIs
    APIs -->|"SQL"| Rds
    APIs -->|"catalog records"| Ddb
    APIs -->|"covers"| S3
    APIs -->|"notification messages"| Sqs
    Sqs -->|"event source mapping"| Lambda
    Lambda -->|"deduplicated email"| Ses
    Lambda -->|"dedupe keys"| Ddb
    Kafka -->|"input events"| Emr
    Emr -->|"aggregate results"| Kafka
    Emr -->|"checkpoints and logs"| S3
    Fluent -->|"container logs"| Cw
    Prom -->|"scrapes and cluster metrics"| Grafana
    Ksm -->|"Kubernetes object metrics"| Prom
    Nat -.->|"private subnet egress"| Eks
~~~

### Allocation Notes

| Allocation | Responsibilities | Owner |
|---|---|---|
| Public subnets | Internet-facing ALB and NAT gateway | Terraform |
| Private worker subnets | EKS node group, application pods, Kafka, ZooKeeper, observability | Terraform + Argo CD |
| Private database subnets | PostgreSQL, without public ingress | Terraform |
| AWS managed data services | DynamoDB, S3, SQS, Lambda, SES, ECR, CloudWatch | Terraform |
| EMR | Flink runtime, Kafka connectivity, checkpoints/logs | Terraform; job submitted separately |
| GitOps control | Reconciles Kustomize manifests and platform applications | Argo CD |

**Availability boundary:** the current IaC is a cost-constrained demonstration shape (one EKS worker, single Kafka broker, one NAT gateway, single EMR primary). A single worker or broker is not a high-availability design. The EKS control plane and the service endpoints are managed by AWS, while pod-level availability is shown by Kubernetes readiness and Prometheus scrape state.

## 2. Module View

This view maps source code into the modules that own user interactions, business rules, external integrations, and persistence. Each API has its own models and data-access code; `contracts/` defines cross-service wire formats.

<!-- mermaid-checked: no \\n, no em-dash/en-dash, no {} in labels, subgraphs are id["label"], arrows are -->|"label"|, all subgraphs closed by end, ids unique -->
~~~mermaid
flowchart LR
    subgraph UiModules["User Interface Modules"]
        Ui["frontend/index.html and app.js"]
        Proxy["frontend/server.js"]
    end
    subgraph ApiModules["Python FastAPI Modules"]
        MemberM["services/member"]
        CatalogM["services/catalog"]
        ReservationM["services/reservation"]
        LendingM["services/lending"]
        AvailabilityM["services/availability"]
        FineM["services/fine"]
        NotificationM["services/notification"]
    end
    subgraph SharedContracts["Shared Contracts"]
        Proto["contracts/proto/member_eligibility.proto"]
        EventSchema["contracts/events/v1/event-envelope.json"]
    end
    subgraph DataAdapters["Data Adapters"]
        SqlA["SQLAlchemy Stores"]
        OutboxA["Per service SQL event outbox"]
        DdbA["DynamoDB Catalog Adapter"]
        S3A["S3 Cover Adapter"]
        SqsA["SQS Queue Adapter"]
    end
    subgraph AsyncModules["Async Modules"]
        LambdaM["services/notification-lambda"]
        AnalyticsM["services/usage-analytics"]
    end

    Ui -->|"browser requests"| Proxy
    Proxy -->|"REST proxy"| ApiModules
    MemberM -->|"member persistence"| SqlA
    ReservationM -->|"reservation persistence"| SqlA
    ReservationM -->|"same transaction"| OutboxA
    LendingM -->|"loan persistence"| SqlA
    LendingM -->|"same transaction"| OutboxA
    AvailabilityM -->|"availability projection reads"| SqlA
    FineM -->|"loan reads"| SqlA
    CatalogM -->|"books and copies"| DdbA
    CatalogM -->|"cover bytes"| S3A
    NotificationM -->|"event publication"| SqsA
    SqsA -->|"queue trigger"| LambdaM
    LendingM -->|"eligibility client"| Proto
    Proto -->|"server contract"| MemberM
    OutboxA -->|"retrying Kafka publisher"| EventSchema
    EventSchema -->|"shared JSON envelope"| AnalyticsM
~~~

### Module Responsibilities

| Module | Important files | Responsibility |
|---|---|---|
| Frontend | `frontend/index.html`, `frontend/app.js`, `frontend/server.js` | Browser screens, API calls and same-origin proxy |
| Member | `services/member/app/` | Member CRUD, PostgreSQL access and gRPC eligibility server |
| Catalog | `services/catalog/app/` | Book/copy routes, DynamoDB access and private cover workflows |
| Reservation | `services/reservation/app/` | FIFO state transitions, SQL store, dependency clients and ZooKeeper lock adapter |
| Lending | `services/lending/app/` | Checkout/return rules, SQL store, REST/gRPC clients and notification publishing |
| Availability | `services/availability/app/` | Derived copy-state response and Catalog client |
| Fine | `services/fine/app/` | Read-only loan lookup and overdue charge calculation |
| Notification | `services/notification/app/` | Event validation, local queue or AWS SQS adapter |
| Notification Lambda | `services/notification-lambda/` | SQS record validation, dedupe and SES delivery |
| Usage Analytics | `services/usage-analytics/src/` | Kafka event parsing, Flink aggregation and Kafka results sink |
| Contracts | `contracts/` | Member gRPC schema and the analytics event envelope |
| Infrastructure | `infra/` and `k8s/` | Terraform AWS resources and Kubernetes workload definitions |

## 3. Component-and-Connector View

This view describes runtime protocols and the business paths. Solid arrows are synchronous request/response or reads; dotted arrows are asynchronous paths. Notification uses SQS/Lambda, and Reservation/Lending use a transactional outbox for Kafka event publication. Live AWS connectivity remains unverified.

<!-- mermaid-checked: no \\n, no em-dash/en-dash, no {} in labels, subgraphs are id["label"], arrows are -->|"label"|, all subgraphs closed by end, ids unique -->
~~~mermaid
flowchart LR
    Person["Reader"] -->|"HTTPS"| Web["ALB and Frontend"]
    Web -->|"REST"| Member["Member API"]
    Web -->|"REST"| Catalog["Catalog API"]
    Web -->|"REST"| Reservation["Reservation API"]
    Web -->|"REST"| Lending["Lending API"]
    Web -->|"REST"| Availability["Availability API"]
    Web -->|"REST"| Fine["Fine API"]
    Web -->|"REST"| Notification["Notification API"]

    Reservation -->|"REST validation"| Member
    Reservation -->|"REST copy state"| Availability
    Reservation -->|"per book lock"| ZooKeeper["ZooKeeper"]
    Lending -->|"gRPC eligibility"| Member
    Lending -->|"REST copy lookup"| Catalog
    Lending -->|"REST hold lookup and cancel"| Reservation
    Availability -->|"REST copy pagination"| Catalog

    Member -->|"SQL"| Pg[("PostgreSQL")]
    Reservation -->|"SQL"| Pg
    Lending -->|"SQL"| Pg
    Reservation -->|"same transaction"| Outbox[("Analytics event outbox")]
    Lending -->|"same transaction"| Outbox
    Availability -->|"SQL read"| Pg
    Fine -->|"SQL read"| Pg
    Catalog -->|"AWS SDK"| Ddb[("DynamoDB")]
    Catalog -->|"signed URL and object"| S3[("S3")]

    Lending -.->|"after commit notification event"| Notification
    Notification -.->|"SendMessage"| Sqs["SQS"]
    Sqs -.->|"Lambda event source"| Lambda["Notification Lambda"]
    Lambda -->|"conditional dedupe write"| Ddb
    Lambda -.->|"SendEmail"| Ses["SES"]

    Outbox -.->|"retrying at least once"| Kafka["Kafka input topic"]
    Kafka -->|"flat event JSON"| Flink["Flink event-time windows"]
    Flink -.->|"at least once aggregate"| Results["Kafka results topic"]
~~~

### Connector and Contract Summary

| Connector | Direction | Runtime contract | Failure behavior |
|---|---|---|---|
| Browser REST | Browser to frontend/API | JSON over HTTP; ALB terminates the public route | Frontend proxy returns 503 when an upstream is unavailable |
| Internal REST | Reservation/Lending/Availability to peer APIs | JSON, Kubernetes service DNS, explicit client timeouts | Dependency failures map to service errors; readiness checks dependencies |
| Member gRPC | Lending to Member | `MemberEligibility.CheckoutEligibility` in the protobuf contract | Checkout must fail safely when eligibility cannot be confirmed |
| SQL | Member, Reservation, Lending, Availability, Fine to PostgreSQL | SQLAlchemy and restricted per-service DB credentials | Readiness checks database; application endpoints report unavailable dependencies |
| Catalog storage | Catalog to DynamoDB/S3 | AWS SDK with EKS workload identity | Catalog readiness checks required cloud clients |
| Notification queue | Notification API to SQS to Lambda | JSON SQS envelope with notification ID and nested event | SQS retries; DLQ after configured receive attempts; Lambda reports item failures |
| Analytics stream | Reservation/Lending outboxes to Kafka to Flink to Kafka | Shared camelCase envelope with `eventId`, `eventType`, `occurredAt`, and book/member payload; legacy flat fixtures remain accepted | Outbox retries can redeliver; Flink deduplicates stable event IDs per window and writes results at-least-once |
| Metrics and logs | API pods to Prometheus; Fluent Bit to CloudWatch | Per-service `/metrics`; container stdout/stderr | Prometheus `up`/readiness data and logs show availability and failures |

### End-to-End Checkout and Return

1. The reader requests a book or copy through the frontend and Catalog.
2. Availability combines Catalog copy identities with reservation and loan state.
3. Reservation validates member and availability, acquires a per-book ZooKeeper lock, and creates a `READY` or `WAITLISTED` record.
4. Lending asks Member over gRPC, validates the copy and reservation over REST, then commits a loan in PostgreSQL.
5. Return commits the return timestamp and cancels the active reservation. Lending then queues a stable-ID notification to SQS; Lambda deduplicates and sends through SES.
6. Reservation and Lending publish shared-envelope events from SQL outboxes. Verify delivery, Flink output, and checkpoint recovery on the target AWS network before calling the cloud flow complete.

### Deployment Prerequisites for This View

- Create the VPC, EKS, RDS, DynamoDB, S3, SQS/Lambda/SES permissions, ECR, EMR networking and IAM using the Terraform root.
- Install EKS add-ons and the AWS Load Balancer Controller, then bootstrap Argo CD. After bootstrap, application and platform manifests must be reconciled by Argo CD.
- Supply runtime database Secrets and the RDS CA bundle outside Git. Confirm ECR digests and Argo CD's repository branch before syncing.
- Keep the Kafka broker private and verify the EMR route to the Kafka NodePort before submitting the Flink job.
