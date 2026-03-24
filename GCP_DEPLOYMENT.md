# 🌐 Google Cloud Platform 배포 가이드

GCP Compute Engine에 분산 처리 시스템을 배포하는 방법입니다.

## 📋 인스턴스 구성

```
총 11개 인스턴스:
├── 중앙 서버 (Central Server)     1개
│   └── Compute Engine VM (e2-standard-2)
├── 워커 서버 (Worker Servers)     10개
│   └── Compute Engine VM × 10 (e2-standard-2)
└── 데이터베이스 (Database)        1개
    └── Cloud SQL for PostgreSQL (db-f1-micro)
```

## 💰 비용 예상 (월간)

```
기본 구성:
├── Compute Engine
│   ├── 중앙 서버: e2-standard-2 ($30/월)
│   └── 워커 × 10: e2-standard-2 × 10 ($300/월)
├── Cloud SQL PostgreSQL
│   └── db-f1-micro ($13/월)
└── 기타 (스토리지, 네트워크)
    └── ~$20/월

총합: ~$363/월 

최적화 구성 (비용 절감):
├── 중앙 서버: e2-micro ($10/월)
├── 워커 × 10: e2-small × 10 ($150/월)  ← 성능 감소
└── Cloud SQL: db-f1-micro ($13/월)

총합: ~$173/월
```

## 🚀 단계별 배포

### Step 0: GCP 프로젝트 설정

```bash
# 1. GCP 프로젝트 생성
# https://console.cloud.google.com/

# 2. gcloud CLI 설치
# https://cloud.google.com/sdk/docs/install

# 3. 프로젝트 설정
gcloud config set project YOUR_PROJECT_ID

# 4. 필수 API 활성화
gcloud services enable compute.googleapis.com
gcloud services enable sqladmin.googleapis.com
gcloud services enable container.googleapis.com  # Docker 필요

# 5. 기본 영역 설정 (예: 도쿄)
gcloud config set compute/region asia-northeast1
gcloud config set compute/zone asia-northeast1-a
```

### Step 1: Cloud SQL PostgreSQL 생성

```bash
# 1️⃣ PostgreSQL 인스턴스 생성
gcloud sql instances create audit-db \
  --database-version=POSTGRES_15 \
  --tier=db-f1-micro \
  --region=asia-northeast1 \
  --authorized-networks=0.0.0.0/0 \
  --backup-start-time=02:00

# 2️⃣ 데이터베이스 생성
gcloud sql databases create audit_db \
  --instance=audit-db

# 3️⃣ 사용자 생성
gcloud sql users create audit_user \
  --instance=audit-db \
  --password=secure_password_12345

# 4️⃣ 연결 확인
gcloud sql connect audit-db \
  --user=audit_user

# psql 프롬프트에서:
CREATE SCHEMA IF NOT EXISTS audit;
\l  # 데이터베이스 목록 확인
```

**중요:** 비밀번호는 **강력하게** 설정하세요!

### Step 2: VPC 네트워크 설정

```bash
# 1️⃣ VPC 생성 (기존 default 사용 가능)
gcloud compute networks create audit-network \
  --subnet-mode=custom

# 2️⃣ 서브네트 생성
gcloud compute networks subnets create audit-subnet \
  --network=audit-network \
  --region=asia-northeast1 \
  --range=10.0.0.0/20

# 3️⃣ 방화벽 규칙
# 1. 내부 통신 허용
gcloud compute firewall-rules create audit-internal \
  --network=audit-network \
  --allow=tcp,udp \
  --source-ranges=10.0.0.0/20

# 2. SSH 접근 허용 (관리자만)
gcloud compute firewall-rules create audit-ssh \
  --network=audit-network \
  --allow=tcp:22 \
  --source-ranges=YOUR_IP/32  # 본인 공인 IP 입력

# 3. HTTP/HTTPS (선택)
gcloud compute firewall-rules create audit-http \
  --network=audit-network \
  --allow=tcp:80,tcp:443 \
  --source-ranges=0.0.0.0/0
```

### Step 3: 중앙 서버 생성

```bash
# 1️⃣ 중앙 서버 VM 인스턴스 생성
gcloud compute instances create central-server \
  --zone=asia-northeast1-a \
  --machine-type=e2-standard-2 \
  --image-family=ubuntu-2204-lts \
  --image-project=ubuntu-os-cloud \
  --subnet=audit-subnet \
  --no-address  # 내부 IP만 (또는 필요시 외부 IP 추가)

# 2️⃣ 인스턴스 시작 스크립트 준비
cat > startup-central.sh << 'EOF'
#!/bin/bash
set -e

# Docker 설치
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh
sudo usermod -aG docker $USER

# Docker Compose 설치
sudo curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" \
  -o /usr/local/bin/docker-compose
sudo chmod +x /usr/local/bin/docker-compose

# 코드 다운로드
cd /opt
git clone <YOUR_REPO_URL> audit-system
cd audit-system/감사보고서/distributed

# .env 설정 (Cloud SQL 연결정보)
cat > .env << ENVEOF
DATABASE_URL=postgresql://audit_user:secure_password_12345@10.XX.XX.XX:5432/audit_db
CENTRAL_SERVER_URL=http://10.0.0.2:8000
NUM_WORKERS=10
DART_START_DATE=20250324
DART_END_DATE=20260324
ENVEOF

# 시작
docker-compose up -d
EOF

# 3️⃣ 스크립트로 인스턴스 생성
gcloud compute instances create central-server \
  --zone=asia-northeast1-a \
  --machine-type=e2-standard-2 \
  --image-family=ubuntu-2204-lts \
  --image-project=ubuntu-os-cloud \
  --subnet=audit-subnet \
  --metadata-from-file startup-script=startup-central.sh \
  --scopes=cloud-platform

# 4️⃣ 생성 확인
gcloud compute instances list

# 5️⃣ SSH 접속
gcloud compute ssh central-server --zone=asia-northeast1-a

# 6️⃣ 로그 확인
docker-compose logs -f
```

### Step 4: 워커 서버 생성 (10개)

```bash
# 1️⃣ 워커 시작 스크립트
cat > startup-worker.sh << 'EOF'
#!/bin/bash
set -e

WORKER_ID=$1

# Docker 설치
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh
sudo usermod -aG docker $USER

# Docker Compose 설치
sudo curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" \
  -o /usr/local/bin/docker-compose
sudo chmod +x /usr/local/bin/docker-compose

# 코드 다운로드
cd /opt
git clone <YOUR_REPO_URL> audit-system
cd audit-system/감사보고서/distributed

# .env 설정
cat > .env << ENVEOF
DATABASE_URL=postgresql://audit_user:secure_password_12345@10.XX.XX.XX:5432/audit_db
CENTRAL_SERVER_URL=http://10.0.0.2:8000
WORKER_ID=worker-$WORKER_ID
NUM_WORKERS=10
ENVEOF

# 시작
docker-compose up -d
EOF

# 2️⃣ 루프로 10개 생성
for i in {1..10}; do
  echo "워커 $i 생성 중..."
  gcloud compute instances create worker-$i \
    --zone=asia-northeast1-a \
    --machine-type=e2-standard-2 \
    --image-family=ubuntu-2204-lts \
    --image-project=ubuntu-os-cloud \
    --subnet=audit-subnet \
    --metadata worker-id=$i \
    --metadata-from-file startup-script=startup-worker.sh \
    --scopes=cloud-platform \
    --async
done

# 3️⃣ 생성 대기
gcloud compute instances list --filter="name~'worker-'" --format='table(name,status)'

# 4️⃣ 모든 워커 생성 완료 확인
gcloud compute instances list
```

### Step 5: 초기화 및 실행

```bash
# 1️⃣ 중앙 서버에 SSH 접속
gcloud compute ssh central-server --zone=asia-northeast1-a

# 2️⃣ 중앙 서버 내부에서:
cd /opt/audit-system/감사보고서/distributed

# DB 테이블 생성
python << 'PYEOF'
from db_models import init_db
init_db()
PYEOF

# 3️⃣ 초기화
curl -X GET http://localhost:8000/init

# 4️⃣ 상태 모니터링
python orchestrator.py --run-all
```

---

## 📊 GCP 모니터링

### Cloud Monitoring 설정

```bash
# 1️⃣ Cloud Monitoring 활성화
gcloud services enable monitoring.googleapis.com

# 2️⃣ 메트릭 확인 (웹 콘솔)
# https://console.cloud.google.com/monitoring

# 주요 메트릭:
# - compute.googleapis.com/instance/cpu/utilization
# - compute.googleapis.com/instance/memory/percent_used
# - cloudsql.googleapis.com/database/cpu/utilization
```

### 로그 조회

```bash
# 1️⃣ Cloud Logging 활성화
gcloud services enable logging.googleapis.com

# 2️⃣ 인스턴스 로그
gcloud logging read "resource.type=gce_instance" \
  --limit=50 \
  --format=json

# 3️⃣ Cloud SQL 로그
gcloud logging read "resource.type=cloudsql_database" \
  --limit=50
```

---

## 🛠️ 관리 작업

### 인스턴스 관리

```bash
# 1️⃣ 모든 인스턴스 나열
gcloud compute instances list

# 2️⃣ 인스턴스 상태 확인
gcloud compute instances describe central-server \
  --zone=asia-northeast1-a

# 3️⃣ 인스턴스 재부팅
gcloud compute instances reboot central-server \
  --zone=asia-northeast1-a

# 4️⃣ 인스턴스 중단 (비용 절감)
gcloud compute instances stop worker-1 \
  --zone=asia-northeast1-a

# 5️⃣ 인스턴스 삭제
gcloud compute instances delete worker-1 \
  --zone=asia-northeast1-a
```

### 데이터베이스 백업

```bash
# 1️⃣ 자동 백업 설정 (이미 설정됨)
gcloud sql backups describe BACKUP_ID \
  --instance=audit-db

# 2️⃣ 수동 백업
gcloud sql backups create \
  --instance=audit-db

# 3️⃣ 백업 복원
gcloud sql backups restore BACKUP_ID \
  --backup-instance=audit-db \
  --backup-configuration=backup

# 4️⃣ DB 내보내기 (Cloud Storage)
gcloud sql export sql audit-db \
  gs://audit-backup/audit_db_backup.sql \
  --database=audit_db
```

---

## 🔒 보안 설정

### 1. 방화벽 규칙 강화

```bash
# SSH는 특정 IP만 허용
gcloud compute firewall-rules update audit-ssh \
  --source-ranges=YOUR_PUBLIC_IP/32

# Cloud SQL 외부 접근 차단
gcloud sql instances patch audit-db \
  --no-assign-ip
```

### 2. 비밀번호 관리

```bash
# Secret Manager 사용 (권장)
gcloud services enable secretmanager.googleapis.com

# 비밀번호 저장
echo -n "secure_password_12345" | \
  gcloud secrets create db-password --data-file=-

# 인스턴스에서 비밀번호 조회
gcloud secrets versions access latest --secret=db-password
```

### 3. VPC Service Controls (선택)

```bash
# 내부 통신만 허용하는 보안 경계 생성
gcloud access-context-manager policies create \
  --title="Audit System"
```

---

## ⚡ 성능 최적화

### CPU/메모리 조정

```bash
# 중앙 서버는 e2-standard-2 (권장)
gcloud compute machine-types list --filter="name~'e2-standard'"

# 워커도 e2-standard-2 권장
# 코어: 2, 메모리: 8GB

# 성능 부족시:
# n1-standard-2 (고성능, 비용 높음)
# n2-standard-2 (중간)
```

### 디스크 확장

```bash
# 디스크 크기 확인
gcloud compute disks list

# 디스크 확장 (100GB → 200GB)
gcloud compute disks resize central-server-disk \
  --size=200 \
  --zone=asia-northeast1-a
```

---

## 📱 스마트폰으로 모니터링

### GCP 모바일 앱

```
1. Google Cloud 앱 설치
2. 프로젝트 선택
3. 메트릭 확인
4. 알람 설정

주요 화면:
- 인스턴스 상태
- CPU/메모리 사용률
- 비용 현황
```

---

## 🔄 스케일링 (확장)

### 워커 추가 (15개로 확장)

```bash
# 기존: 10개 워커
# 새로운: 15개 워커

# 1️⃣ 추가 워커 5개 생성
for i in {11..15}; do
  gcloud compute instances create worker-$i \
    --zone=asia-northeast1-a \
    --machine-type=e2-standard-2 \
    ...
done

# 2️⃣ docker-compose.yml 업데이트
# NUM_WORKERS=15로 변경

# 3️⃣ 중앙 서버 재시작
gcloud compute ssh central-server
docker-compose restart
```

---

## 💾 비용 절감 팁

### 1. 스팟 인스턴스 사용

```bash
# 스팟 인스턴스 (70% 할인, 언제든 중단 가능)
gcloud compute instances create worker-spot-1 \
  --provisioning-model=SPOT \
  --zone=asia-northeast1-a \
  --machine-type=e2-standard-2 \
  ...
```

### 2. 예약 인스턴스

```bash
# 1년 예약 계약 (30-40% 할인)
gcloud compute reservations create audit-reserved \
  --machine-type=e2-standard-2 \
  --zone=asia-northeast1-a \
  --vm-count=11
```

### 3. 인스턴스 크기 최적화

```
원본: e2-standard-2 × 11 = $330/월
최적화 옵션:

옵션 A (성능 중시):
- 중앙: e2-standard-4
- 워커: e2-standard-2 × 10
→ $350/월

옵션 B (비용 중시):
- 중앙: e2-small (2vCPU, 2GB)
- 워커: e2-small × 10 (2vCPU, 2GB)
→ $120/월 (성능은 50% 감소)

추천: 옵션 A (적정 밸런스)
```

### 4. 자동 스케일링 (Advanced)

```bash
# CPU > 80% → 인스턴스 추가
# CPU < 20% → 인스턴스 제거

# Instance Group 생성
gcloud compute instance-groups managed create worker-group \
  --size=10 \
  --template=worker-template \
  --zone=asia-northeast1-a

# 자동 스케일링 정책
gcloud compute instance-groups managed set-autoscaling worker-group \
  --max-num-replicas=20 \
  --min-num-replicas=5 \
  --target-cpu-utilization=0.8
```

---

## 🚨 문제 해결

### Q1: 인스턴스 생성 실패

```bash
# 1. 할당량 확인
gcloud compute project-info describe --project=YOUR_PROJECT

# 2. 다른 영역 시도
gcloud compute instances create worker-1 \
  --zone=asia-northeast1-b  # 다른 존 사용

# 3. 머신 타입 변경
gcloud compute instances create worker-1 \
  --machine-type=e2-small  # 더 작은 머신
```

### Q2: Cloud SQL 연결 실패

```bash
# 1. 비밀번호 확인
gcloud sql users describe audit_user \
  --instance=audit-db

# 2. 인스턴스 공인 IP 추가
gcloud sql instances patch audit-db \
  --assign-ip

# 3. 승인된 네트워크 확인
gcloud sql instances describe audit-db \
  --format='value(settings.ipConfiguration.authorizedNetworks)'
```

### Q3: 인스턴스 SSH 접속 불가

```bash
# 1. 방화벽 규칙 확인
gcloud compute firewall-rules list

# 2. IAM 권한 확인
gcloud projects get-iam-policy YOUR_PROJECT

# 3. 공인 IP 할당
gcloud compute instances add-access-config central-server \
  --zone=asia-northeast1-a
```

---

## 📋 체크리스트

### 초기 설정

- [ ] GCP 프로젝트 생성
- [ ] gcloud CLI 설치 및 인증
- [ ] 필수 API 활성화 (Compute, Cloud SQL)
- [ ] VPC 네트워크 생성
- [ ] 방화벽 규칙 설정

### 배포

- [ ] Cloud SQL PostgreSQL 생성
- [ ] 중앙 서버 VM 생성
- [ ] 워커 10개 VM 생성
- [ ] Docker 및 코드 설치 확인
- [ ] .env 파일 설정
- [ ] 초기화 및 테스트 실행

### 운영

- [ ] Cloud Monitoring 대시보드 설정
- [ ] 자동 백업 확인
- [ ] 알람 설정
- [ ] 정기적인 로그 확인
- [ ] 비용 모니터링

---

## 📞 GCP 기술 지원

```
모든 GCP 리소스:
https://console.cloud.google.com/

공식 문서:
- Compute Engine: https://cloud.google.com/compute/docs
- Cloud SQL: https://cloud.google.com/sql/docs
- gcloud CLI: https://cloud.google.com/sdk/docs
```

---

**Created:** 2024-01-01  
**Version:** 1.0  
**Status:** Ready for Deployment ✓
