# 🔧 Terraform으로 자동 배포 (GCP)

gcloud 명령어 대신 Terraform으로 모든 11개 인스턴스를 한 번에 배포할 수 있습니다.

## 🏗️ Terraform 파일 구조

```
terraform/
├── main.tf              # 메인 설정
├── variables.tf         # 변수 정의
├── outputs.tf          # 출력값
├── gcp-auth.tf         # GCP 인증
├── terraform.tfvars    # 변수값 (환경별)
└── scripts/
    ├── startup-central.sh
    └── startup-worker.sh
```

## 📦 설치

```bash
# 1. Terraform 설치
# macOS
brew tap hashicorp/tap
brew install hashicorp/tap/terraform

# 2. 확인
terraform version

# 3. 작업 디렉토리
mkdir -p terraform && cd terraform
```

## 📄 Terraform 파일 작성

### 1. main.tf (메인 리소스)

```hcl
# main.tf
terraform {
  required_version = ">= 1.0"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.0"
    }
  }
}

provider "google" {
  project = var.gcp_project_id
  region  = var.gcp_region
}

# ==================== Cloud SQL ====================
resource "google_sql_database_instance" "audit_db" {
  name             = var.db_instance_name
  database_version = "POSTGRES_15"
  region           = var.gcp_region

  settings {
    tier              = var.db_tier
    availability_type = "REGIONAL"
    backup_configuration {
      enabled                        = true
      start_time                     = "02:00"
      point_in_time_recovery_enabled = true
      backup_retention_settings {
        retained_backups = 30
        retention_unit   = "COUNT"
      }
    }
    ip_configuration {
      ipv4_enabled    = true
      require_ssl     = true
      authorized_networks {
        name  = "allow-gce"
        value = "0.0.0.0/0"
      }
    }
  }

  deletion_protection = false
}

resource "google_sql_database" "audit_database" {
  name     = "audit_db"
  instance = google_sql_database_instance.audit_db.name
}

resource "google_sql_user" "audit_user" {
  name     = var.db_user
  instance = google_sql_database_instance.audit_db.name
  password = random_password.db_password.result
}

resource "random_password" "db_password" {
  length  = 32
  special = true
}

# ==================== VPC 네트워크 ====================
resource "google_compute_network" "audit_network" {
  name                    = var.network_name
  auto_create_subnetworks = false
}

resource "google_compute_subnetwork" "audit_subnet" {
  name          = "${var.network_name}-subnet"
  ip_cidr_range = var.subnet_cidr
  region        = var.gcp_region
  network       = google_compute_network.audit_network.id
}

# ==================== 방화벽 규칙 ====================
resource "google_compute_firewall" "allow_internal" {
  name    = "${var.network_name}-allow-internal"
  network = google_compute_network.audit_network.name

  allow {
    protocol = "tcp"
    ports    = ["0-65535"]
  }
  allow {
    protocol = "udp"
    ports    = ["0-65535"]
  }

  source_ranges = [var.subnet_cidr]
}

resource "google_compute_firewall" "allow_ssh" {
  name    = "${var.network_name}-allow-ssh"
  network = google_compute_network.audit_network.name

  allow {
    protocol = "tcp"
    ports    = ["22"]
  }

  source_ranges = var.allowed_ssh_ips
}

# ==================== 중앙 서버 ====================
resource "google_compute_instance" "central_server" {
  name         = var.central_server_name
  machine_type = var.central_machine_type
  zone         = var.gcp_zone

  boot_disk {
    initialize_params {
      image = data.google_compute_image.ubuntu.self_link
      size  = var.boot_disk_size
    }
  }

  network_interface {
    subnetwork = google_compute_subnetwork.audit_subnet.id
  }

  metadata = {
    enable-oslogin = "TRUE"
  }

  metadata_startup_script = templatefile("${path.module}/scripts/startup-central.sh", {
    db_host   = google_sql_database_instance.audit_db.private_ip_address
    db_user   = var.db_user
    db_pass   = random_password.db_password.result
    repo_url  = var.repo_url
    num_workers = var.num_workers
  })

  service_account {
    scopes = ["cloud-platform"]
  }

  tags = ["central-server", "audit-system"]
}

# ==================== 워커 서버 ====================
resource "google_compute_instance" "workers" {
  count        = var.num_workers
  name         = "${var.worker_name_prefix}-${count.index + 1}"
  machine_type = var.worker_machine_type
  zone         = var.gcp_zone

  boot_disk {
    initialize_params {
      image = data.google_compute_image.ubuntu.self_link
      size  = var.boot_disk_size
    }
  }

  network_interface {
    subnetwork = google_compute_subnetwork.audit_subnet.id
  }

  metadata = {
    enable-oslogin = "TRUE"
    worker-id     = count.index + 1
  }

  metadata_startup_script = templatefile("${path.module}/scripts/startup-worker.sh", {
    worker_id       = count.index + 1
    db_host        = google_sql_database_instance.audit_db.private_ip_address
    db_user        = var.db_user
    db_pass        = random_password.db_password.result
    central_server = google_compute_instance.central_server.network_interface[0].network_ip
    repo_url       = var.repo_url
  })

  service_account {
    scopes = ["cloud-platform"]
  }

  tags = ["worker-server", "audit-system"]

  depends_on = [google_compute_instance.central_server]
}

# ==================== 데이터 소스 ====================
data "google_compute_image" "ubuntu" {
  family  = "ubuntu-2204-lts"
  project = "ubuntu-os-cloud"
}
```

### 2. variables.tf (변수)

```hcl
# variables.tf
variable "gcp_project_id" {
  description = "GCP Project ID"
  type        = string
}

variable "gcp_region" {
  description = "GCP Region"
  type        = string
  default     = "asia-northeast1"
}

variable "gcp_zone" {
  description = "GCP Zone"
  type        = string
  default     = "asia-northeast1-a"
}

# Database
variable "db_instance_name" {
  description = "Cloud SQL Instance Name"
  type        = string
  default     = "audit-db"
}

variable "db_tier" {
  description = "Cloud SQL Tier"
  type        = string
  default     = "db-f1-micro"
}

variable "db_user" {
  description = "DB Username"
  type        = string
  default     = "audit_user"
  sensitive   = true
}

# Network
variable "network_name" {
  description = "VPC Network Name"
  type        = string
  default     = "audit-network"
}

variable "subnet_cidr" {
  description = "Subnet CIDR"
  type        = string
  default     = "10.0.0.0/20"
}

variable "allowed_ssh_ips" {
  description = "Allowed SSH IPs"
  type        = list(string)
  default     = ["0.0.0.0/0"]  # ⚠️ 운영시 제한하세요
}

# Instances
variable "central_server_name" {
  description = "Central Server Name"
  type        = string
  default     = "central-server"
}

variable "central_machine_type" {
  description = "Central Server Machine Type"
  type        = string
  default     = "e2-standard-2"
}

variable "worker_name_prefix" {
  description = "Worker Name Prefix"
  type        = string
  default     = "worker"
}

variable "worker_machine_type" {
  description = "Worker Machine Type"
  type        = string
  default     = "e2-standard-2"
}

variable "num_workers" {
  description = "Number of Workers"
  type        = number
  default     = 10
}

variable "boot_disk_size" {
  description = "Boot Disk Size (GB)"
  type        = number
  default     = 50
}

# Repository
variable "repo_url" {
  description = "GitHub Repository URL"
  type        = string
}
```

### 3. outputs.tf (출력)

```hcl
# outputs.tf
output "db_connection_name" {
  description = "Cloud SQL Connection Name"
  value       = google_sql_database_instance.audit_db.connection_name
}

output "db_private_ip" {
  description = "Cloud SQL Private IP"
  value       = google_sql_database_instance.audit_db.private_ip_address
}

output "db_password" {
  description = "Database Password"
  value       = random_password.db_password.result
  sensitive   = true
}

output "central_server_ip" {
  description = "Central Server Internal IP"
  value       = google_compute_instance.central_server.network_interface[0].network_ip
}

output "worker_ips" {
  description = "Worker Servers Internal IPs"
  value       = [for worker in google_compute_instance.workers : worker.network_interface[0].network_ip]
}

output "central_server_name" {
  description = "Central Server Instance Name"
  value       = google_compute_instance.central_server.name
}

output "worker_names" {
  description = "Worker Instance Names"
  value       = [for worker in google_compute_instance.workers : worker.name]
}
```

### 4. terraform.tfvars (환경 설정)

```hcl
# terraform.tfvars
gcp_project_id      = "your-gcp-project-id"
gcp_region          = "asia-northeast1"
gcp_zone            = "asia-northeast1-a"

# Database
db_instance_name    = "audit-db"
db_tier             = "db-f1-micro"
db_user             = "audit_user"

# Network
network_name        = "audit-network"
subnet_cidr         = "10.0.0.0/20"
allowed_ssh_ips     = ["YOUR_IP/32"]  # 본인 공인 IP 입력

# Instances
central_server_name = "central-server"
central_machine_type = "e2-standard-2"
worker_name_prefix  = "worker"
worker_machine_type = "e2-standard-2"
num_workers         = 10

# Storage
boot_disk_size      = 50

# Repository
repo_url            = "https://github.com/YOUR_USERNAME/audit-system.git"
```

### 5. 시작 스크립트 (startup-central.sh)

```bash
#!/bin/bash
set -e

DB_HOST=${db_host}
DB_USER=${db_user}
DB_PASS=${db_pass}
REPO_URL=${repo_url}
NUM_WORKERS=${num_workers}
CENTRAL_IP=$(hostname -I | awk '{print $1}')

echo "==================== Central Server Startup ===================="
echo "DB Host: $DB_HOST"
echo "Central IP: $CENTRAL_IP"
echo "Repo: $REPO_URL"

# Docker 설치
echo "[1/5] Installing Docker..."
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh
sudo usermod -aG docker ubuntu

# Docker Compose 설치
echo "[2/5] Installing Docker Compose..."
sudo curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" \
  -o /usr/local/bin/docker-compose
sudo chmod +x /usr/local/bin/docker-compose

# 코드 다운로드
echo "[3/5] Cloning repository..."
cd /opt
sudo git clone $REPO_URL audit-system
cd audit-system/감사보고서/distributed
sudo chown -R ubuntu:ubuntu /opt/audit-system

# .env 설정
echo "[4/5] Setting up environment..."
cat > .env << EOF
DATABASE_URL=postgresql://$DB_USER:$DB_PASS@$DB_HOST:5432/audit_db
CENTRAL_SERVER_URL=http://$CENTRAL_IP:8000
NUM_WORKERS=$NUM_WORKERS
DART_START_DATE=20250324
DART_END_DATE=20260324
LOG_LEVEL=info
EOF

# 서비스 시작
echo "[5/5] Starting services..."
docker-compose up -d

# 헬스 체크
sleep 10
curl -f http://localhost:8000/health || echo "⚠️ Central server not ready yet"

echo "==================== Startup Complete ===================="
```

### 6. 시작 스크립트 (startup-worker.sh)

```bash
#!/bin/bash
set -e

WORKER_ID=${worker_id}
DB_HOST=${db_host}
DB_USER=${db_user}
DB_PASS=${db_pass}
CENTRAL_SERVER=${central_server}
REPO_URL=${repo_url}
WORKER_IP=$(hostname -I | awk '{print $1}')

echo "==================== Worker $WORKER_ID Startup ===================="
echo "DB Host: $DB_HOST"
echo "Central Server: $CENTRAL_SERVER"
echo "Worker IP: $WORKER_IP"

# Docker 설치
echo "[1/5] Installing Docker..."
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh
sudo usermod -aG docker ubuntu

# Docker Compose 설치
echo "[2/5] Installing Docker Compose..."
sudo curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" \
  -o /usr/local/bin/docker-compose
sudo chmod +x /usr/local/bin/docker-compose

# 코드 다운로드
echo "[3/5] Cloning repository..."
cd /opt
sudo git clone $REPO_URL audit-system
cd audit-system/감사보고서/distributed
sudo chown -R ubuntu:ubuntu /opt/audit-system

# .env 설정
echo "[4/5] Setting up environment..."
cat > .env << EOF
DATABASE_URL=postgresql://$DB_USER:$DB_PASS@$DB_HOST:5432/audit_db
CENTRAL_SERVER_URL=http://$CENTRAL_SERVER:8000
WORKER_ID=worker-$WORKER_ID
NUM_WORKERS=10
DART_START_DATE=20250324
DART_END_DATE=20260324
LOG_LEVEL=info
EOF

# 서비스 시작
echo "[5/5] Starting worker..."
docker-compose up -d

# 헬스 체크
sleep 10
curl -f http://localhost:8001/health || echo "⚠️ Worker not ready yet"

echo "==================== Worker $WORKER_ID Startup Complete ===================="
```

## 🚀 배포

```bash
# 1. 디렉토리 이동
cd terraform

# 2. Terraform 초기화
terraform init

# 3. 설정 확인
terraform plan

# 4. 배포 (11개 인스턴스 + DB)
terraform apply

# 5. 출력값 확인
terraform output

# 예상 출력:
# db_connection_name = "audit-project:asia-northeast1:audit-db"
# db_private_ip = "10.20.0.2"
# central_server_ip = "10.0.0.2"
# worker_ips = ["10.0.0.3", "10.0.0.4", ...]
```

## 🔄 상태 관리

```bash
# 상태 확인
terraform show

# 특정 리소스만 적용
terraform apply -target=google_compute_instance.central_server

# 워커 수 변경 (5개 → 15개)
terraform apply -var="num_workers=15"

# 리소스 삭제
terraform destroy
```

## 📊 비용 추정

```bash
# Terraform Cloud 이용시 자동 비용 추정
# 또는 GCP 가격 계산기
# https://cloud.google.com/products/calculator

# 수동 계산:
# - Central: e2-standard-2 ($30/월)
# - Workers: e2-standard-2 × 10 ($300/월)
# - DB: db-f1-micro ($13/월)
# - 기타: ~$20/월
# = ~$363/월
```

## 🛠️ 관리 명령어

```bash
# 모든 인스턴스 제거 후 재생성
terraform taint google_compute_instance.central_server
terraform apply

# 워커 일부만 재생성
terraform taint google_compute_instance.workers[0]
terraform apply

# 상태 파일 백업
cp terraform.tfstate terraform.tfstate.backup

# 원격 상태 저장 (Terraform Cloud)
terraform cloud login
git add main.tf
git push
```

## 🔒 보안

```hcl
# 비밀번호는 Secret Manager에 저장
resource "google_secret_manager_secret" "db_password" {
  secret_id = "audit-db-password"
}

resource "google_secret_manager_secret_version" "db_password" {
  secret      = google_secret_manager_secret.db_password.id
  secret_data = random_password.db_password.result
}
```

---

**Terraform으로 모든 11개 인스턴스를 3분 내에 배포할 수 있습니다! ⚡**
