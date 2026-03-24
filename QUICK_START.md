# 🚀 빠른 시작 가이드

분산 처리 시스템을 로컬에서 테스트하고 서버에 배포하는 방법을 설명합니다.

## 📋 사전 요구사항

- Docker & Docker Compose
- Python 3.11+
- Git

## 🏠 로컬 테스트 (개발 환경)

### Step 1: 환경 준비

```bash
cd distributed

# 환경 변수 설정
cp .env.example .env

# 필요시 .env 편집 (기본값으로 충분)
# - DATABASE_URL
# - NUM_WORKERS (로컬 테스트용 3-5개 권장)
```

### Step 2: Docker 스택 시작

```bash
# 전체 스택 시작 (DB + 중앙 서버 + 워커)
docker-compose up -d

# 상태 확인
docker-compose ps

# 로그 확인
docker-compose logs -f
```

**시작될 때까지 기다리세요:** ~30초

```
✓ postgres는 5432에서 ready
✓ central-server는 8000에서 ready
✓ worker-1~10은 8001~8010에서 ready
```

### Step 3: 전체 프로세스 자동 실행

```bash
# 호스트 머신에서 실행 (워커는 자동으로 work 수행)
python orchestrator.py --run-all
```

**자동으로 실행되는 단계:**

1. **초기화** (5초)
   - DART에서 총 페이지 수 확인
   - 워커에 작업 분배

2. **워커 작업** (페이지 수집)
   - 각 워커가 할당받은 페이지 처리
   - CEO 정보 조회
   - DB에 저장

3. **최종화** (엑셀 매칭)
   - 기존 엑셀과 DB 데이터 매칭
   - 감사보고서 정보 입력

### Step 4: 수동 단계별 실행 (선택사항)

```bash
# 1️⃣ 초기화만 실행
python orchestrator.py --initialize

# 2️⃣ 진행 상황 모니터링
python orchestrator.py --monitor

# 3️⃣ 현재 상태 조회
python orchestrator.py --status

# 4️⃣ 최종화 실행
python orchestrator.py --finalize
```

### Step 5: 결과 확인

```bash
# 수집된 데이터 확인
docker exec audit_db psql -U audit_user -d audit_db -c \
  "SELECT COUNT(*) FROM audit_reports;"

# 작업 상태 확인
docker exec audit_db psql -U audit_user -d audit_db -c \
  "SELECT 
     (SELECT COUNT(*) FROM audit_tasks WHERE status='completed') as completed,
     (SELECT COUNT(*) FROM audit_tasks WHERE status='failed') as failed,
     (SELECT COUNT(*) FROM audit_tasks) as total;"

# 엑셀 매칭 결과 확인
ls -lh ../기업개황.xlsx
```

### Step 6: 정리

```bash
# 스택 종료
docker-compose down

# 데이터 삭제 (DB 초기화)
docker-compose down -v

# 이미지 정리
docker-compose down --rmi all
```

---

## 🌐 서버 배포 (운영 환경)

### Step 1: 서버 준비

```bash
# 1. 원격 서버(예: AWS EC2) 접속
ssh ubuntu@your-server-ip

# 2. Docker & Docker Compose 설치
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh

sudo curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" \
  -o /usr/local/bin/docker-compose
sudo chmod +x /usr/local/bin/docker-compose

# 3. 코드 배포
git clone <your-repo-url> audit-system
cd audit-system/감사보고서/distributed
```

### Step 2: 환경 설정

```bash
# .env 파일 생성 (서버용)
cat > .env << EOF
# Database
DATABASE_URL=postgresql://audit_user:secure_password@postgres:5432/audit_db

# Server
CENTRAL_SERVER_URL=http://central-server:8000

# Workers
NUM_WORKERS=10

# Logging
LOG_LEVEL=info

# DART API
DART_START_DATE=20250324
DART_END_DATE=20260324
EOF
```

### Step 3: 시작

```bash
# 백그라운드에서 시작
docker-compose up -d

# 로그 확인
docker-compose logs -f central-server
docker-compose logs -f worker-1

# 상태 확인
curl http://localhost:8000/health
curl http://localhost:8000/status
```

### Step 4: 자동 실행 (선택)

**Option 1: 스크린 세션에서 실행**

```bash
screen -S audit-orchestrator
python orchestrator.py --run-all
# Ctrl+A, D로 분리
```

**Option 2: systemd 서비스 (권장)**

```bash
sudo mkdir -p /opt/audit-system

# systemd 서비스 파일 생성
sudo tee /etc/systemd/system/audit-orchestrator.service << EOF
[Unit]
Description=Audit Report Orchestrator
After=docker.service

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/audit-system/감사보고서/distributed
ExecStart=python orchestrator.py --run-all
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

# 서비스 활성화
sudo systemctl daemon-reload
sudo systemctl enable audit-orchestrator
sudo systemctl start audit-orchestrator

# 상태 확인
sudo systemctl status audit-orchestrator
```

**Option 3: Cron으로 주기 실행**

```bash
# 매일 오전 2시에 실행
crontab -e

0 2 * * * cd /audit-system/감사보고서/distributed && python orchestrator.py --run-all >> /tmp/audit.log 2>&1
```

### Step 5: 모니터링

```bash
# 실시간 로그 모니터링
docker-compose logs -f

# 중앙 서버 상태 API
curl http://localhost:8000/status

# 워커 상태
for i in {1..10}; do
  echo "Worker $i:"
  curl http://localhost:800$i/health
done

# 데이터베이스 상태
docker exec audit_db psql -U audit_user -d audit_db -c \
  "SELECT id, status, worker_id, completed_at FROM audit_tasks ORDER BY id;"
```

---

## 🔧 문제 해결

### Q1: 컨테이너가 시작 안 됨

```bash
# 로그 확인
docker-compose logs

# 문제 해결:
# 1. 포트 충돌 확인
lsof -i :8000
lsof -i :5432

# 2. DB 초기화
docker-compose down -v
docker-compose up -d
```

### Q2: 워커가 작업을 못 찾음

```bash
# 1. 초기화 확인
curl http://localhost:8000/status

# 응답에 pending_tasks가 있는지 확인

# 2. 초기화 재실행
curl -X GET http://localhost:8000/init

# 3. 워커 로그 확인
docker logs audit_worker_1
```

### Q3: CEO 정보 조회 실패율 높음

```bash
# 1. 타임아웃 증가 (network 느릴 때)
# worker_server/main.py 수정:
timeout=30  # → 60으로 변경

# 2. 재시도 횟수 증가
MAX_RETRIES = 3  # → 5로 변경

# 3. 재배포
docker-compose up -d --build
```

### Q4: 엑셀 매칭이 안 됨

```bash
# 1. 엑셀 파일 경로 확인
ls -la ../기업개황.xlsx

# 2. 엑셀 컬럼 확인
# "공시회사명", "대표자명" 컬럼이 있는지 확인

# 3. 매칭 함수 테스트
python
>>> from excel_matcher import match_excel
>>> match_excel("../기업개황.xlsx")

# 4. 수동 실행
python orchestrator.py --finalize
```

---

## 📊 성능 최적화

### 1. 워커 수 조정

```yaml
# docker-compose.yml
# 성능 테스트 결과에 따라 조정

# 낮은 성능:
NUM_WORKERS=5

# 중간 성능 (기본):
NUM_WORKERS=10

# 높은 성능:
NUM_WORKERS=20
```

### 2. 동시성 제어

```python
# worker_server/main.py
# CEO 조회 간 대기 시간 조정
time.sleep(0.3)  # → 0.1로 감소 (빠름) / 0.5로 증가 (안정적)

# 페이지 간 대기 시간
time.sleep(2)    # → 0.5로 감소 (빠름) / 5로 증가 (안정적)
```

### 3. DB 최적화

```sql
-- 인덱스 추가
CREATE INDEX idx_audit_reports_company ON audit_reports(company_name);
CREATE INDEX idx_audit_reports_cik ON audit_reports(cik_code);
CREATE INDEX idx_audit_tasks_status ON audit_tasks(status);

-- 통계 업데이트
VACUUM ANALYZE;
```

---

## 📈 모니터링 대시보드 (선택)

Grafana + Prometheus로 실시간 모니터링 구성:

```yaml
# docker-compose.yml에 추가

  prometheus:
    image: prom/prometheus
    ports:
      - "9090:9090"
    volumes:
      - ./prometheus.yml:/etc/prometheus/prometheus.yml

  grafana:
    image: grafana/grafana
    ports:
      - "3000:3000"
    environment:
      GF_SECURITY_ADMIN_PASSWORD: admin
```

---

## 📝 주요 엔드포인트 요약

| 메서드 | URL | 설명 |
|--------|-----|------|
| GET | `http://localhost:8000/init` | 초기화 |
| GET | `http://localhost:8000/status` | 상태 조회 |
| POST | `http://localhost:8000/finalize` | 최종화 |
| GET | `http://localhost:8000/health` | 중앙 서버 헬스 |
| GET | `http://localhost:8001/health` | 워커 헬스 |

---

## ❓ 자주 묻는 질문

### Q: 얼마나 걸려요?

페이지 수 = 50개, 워커 = 10개 기준:
- 초기화: ~5초
- 수집: ~20분 (페이지당 30초, CEO 조회 포함)
- 엑셀 매칭: ~1분
- **총량: ~25분**

### Q: 중간에 실패하면?

- 실패한 작업만 재실행 가능
- 성공한 데이터는 DB에 저장됨
- 엑셀 매칭 가능

### Q: 비용은?

- 로컬: 무료 (Docker만 있으면 됨)
- AWS EC2: t3.medium (약 $30/월) 권장
- RDS PostgreSQL: db.t3.small (약 $20/월) 권장

### Q: 확장성은?

- 최대 100개 워커까지 수평 확장 가능
- 성능 = 워커 수 × 페이지처리속도
- 네트워크 대역폭이 제약 요소

---

## 📚 추가 자료

- [중앙 서버 API 문서](./central_server/main.py)
- [워커 서버 소스](./worker_server/main.py)
- [DB 스키마](./db_models/models.py)
- [전체 구조 README](./README.md)

---

**문제 발생시:** GitHub Issue 생성 또는 관리자 연락
