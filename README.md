# 감사보고서 분산 수집 시스템

분산 처리를 통해 DART 감사보고서를 효율적으로 수집하는 시스템입니다.

## 아키텍처

```
┌─────────────────────────────────────────────────────┐
│         중앙 서버 (Central Server)                  │
│  - 총 페이지 수 확인                                │
│  - 작업 분배 (페이지 범위 할당)                     │
│  - 진행 상황 모니터링                               │
│  - 최종 매칭 (엑셀)                                 │
└────────────────────┬────────────────────────────────┘
                     │
        ┌────────────┼────────────┐
        │            │            │
    ┌───▼──┐    ┌───▼──┐    ┌───▼──┐
    │Worker│    │Worker│ ...│Worker│ (10개)
    │  1   │    │  2   │    │  10  │
    └───┬──┘    └───┬──┘    └───┬──┘
        │            │            │
        └────────────┼────────────┘
                     │
           ┌─────────▼──────────┐
           │  PostgreSQL DB    │
           │  - 작업 관리      │
           │  - 수집된 데이터  │
           │  - 에러 로그      │
           └───────────────────┘
```

## 주요 특징

✅ **분산 처리**: 10개의 워커가 동시에 페이지 수집  
✅ **신뢰성**: 에러 발생해도 계속 진행, DB에 정확히 기록  
✅ **재귀성**: 실패한 작업만 재시도 가능  
✅ **모니터링**: 실시간 진행 상황 확인  

## 시작하기

### 1. 환경 설정

```bash
cd distributed
cp .env.example .env
```

### 2. Docker 스택 시작

```bash
docker-compose up -d
```

**확인:**
- 중앙 서버: http://localhost:8000
- 워커 1: http://localhost:8001
- DB: localhost:5432

### 3. 초기화 및 작업 시작

```bash
# 1️⃣ 초기화 (총 페이지 수 확인 + 작업 분배)
curl -X GET http://localhost:8000/init

# 2️⃣ 진행 상황 확인
curl -X GET http://localhost:8000/status

# 3️⃣ 워커에서 작업 수행
# 각 워커가 자동으로 work endpoint 호출

# 4️⃣ 모든 작업 완료 후 최종 매칭
curl -X POST http://localhost:8000/finalize
```

## API 엔드포인트

### 중앙 서버 (포트 8000)

| 메서드 | 엔드포인트 | 설명 |
|--------|-----------|------|
| GET | `/init` | 초기화: 페이지 수 확인 + 작업 분배 |
| GET | `/status` | 전체 진행 상황 조회 |
| GET | `/tasks/pending` | 대기 중인 작업 목록 |
| POST | `/tasks/{id}/assign/{worker}` | 작업 할당 |
| POST | `/tasks/{id}/complete` | 작업 완료 보고 |
| POST | `/tasks/{id}/fail` | 작업 실패 보고 |
| POST | `/finalize` | 최종화 (엑셀 매칭) |
| GET | `/health` | 헬스 체크 |

### 워커 서버 (포트 8001-8010)

| 메서드 | 엔드포인트 | 설명 |
|--------|-----------|------|
| GET | `/work` | 작업 가져오기 + 수행 + 완료 보고 |
| GET | `/status` | 워커 상태 |
| GET | `/health` | 헬스 체크 |

## 단계별 실행 흐름

### ✨ Step 1: 초기화

```bash
curl -X GET http://localhost:8000/init
```

**응답:**
```json
{
  "status": "success",
  "total_pages": 50,
  "num_workers": 10,
  "timestamp": "2024-01-01T12:00:00"
}
```

**내부 동작:**
- DART API에서 총 페이지 수 조회
- 50페이지 ÷ 10 워커 = 각 워커 5페이지씩
- DB에 작업 분배: Task 1 (1-5페이지), Task 2 (6-10페이지), ...

### ✨ Step 2: 진행 상황 확인

```bash
curl -X GET http://localhost:8000/status
```

**응답:**
```json
{
  "total_pages": 50,
  "total_tasks": 10,
  "completed_tasks": 2,
  "failed_tasks": 0,
  "in_progress_tasks": 3,
  "pending_tasks": 5,
  "is_initialized": true
}
```

### ✨ Step 3: 워커 작업 수행

각 워커는 자유도 있게 주기적으로 `/work` 엔드포인트 호출:

```python
# 워커에서 (자동 또는 스크립트)
while True:
    response = requests.get(f"{CENTRAL_SERVER_URL}/work")
    if response.json()["status"] == "no_work":
        break
    time.sleep(300)  # 5분마다 확인
```

**워커 동작:**
1. 대기 중인 작업 조회 (페이지 범위 할당)
2. 할당받은 페이지 수집
3. CEO 정보 조회
4. DB에 저장
5. 중앙 서버에 완료 보고

### ✨ Step 4: 최종 매칭

```bash
curl -X POST http://localhost:8000/finalize
```

**동작:**
- DB의 모든 수집 데이터 조회
- 기존 엑셀과 매칭 (공시회사명 + 대표자명)
- 엑셀에 감사보고서 정보 입력
- 엑셀 저장

## 에러 처리

### 🔴 사례 1: 대표자명 조회 실패

```
상황: 워커가 CEO 정보를 못 찾음
결과: ceo_name = None으로 DB 저장
영향: 엑셀 매칭에서 이 항목은 매칭되지 않음
```

### 🔴 사례 2: 페이지 수집 실패

```
상황: DART 서버 에러로 페이지 수집 실패
결과: 해당 워커 작업은 FAILED, 로그에 기록
영향: 재시도 가능 (작업 재할당)
```

### 🔴 사례 3: 워커 중단

```
상황: 워커 컨테이너 중지
결과: 작업은 IN_PROGRESS 상태로 남음
해결: 다른 워커가 같은 작업 재수행 (보고 전)
```

## 로그 확인

```bash
# 중앙 서버 로그
docker logs audit_central

# 워커 로그
docker logs audit_worker_1
docker logs audit_worker_2

# 데이터베이스 상태 확인
docker exec audit_db psql -U audit_user -d audit_db -c \
  "SELECT id, page_start, page_end, status, worker_id FROM audit_tasks;"
```

## 데이터베이스 스키마

### audit_tasks (작업 관리)
```sql
id              | 작업 ID
page_start      | 시작 페이지
page_end        | 종료 페이지
worker_id       | 할당된 워커
status          | pending/assigned/in_progress/completed/failed
created_at      | 생성 시간
completed_at    | 완료 시간
```

### audit_reports (수집 데이터)
```sql
id              | 감사보고서 ID
task_id         | 작업 ID (외래키)
company_name    | 공시회사명
cik_code        | CIK 코드
ceo_name        | 대표자명
report_text     | 감사보고서 내용
submitter       | 제출인
```

### task_logs (에러 추적)
```sql
id              | 로그 ID
task_id         | 작업 ID
worker_id       | 워커 ID
log_type        | ERROR/WARNING/INFO
message         | 로그 메시지
page_number     | 해당 페이지
```

## 성능 최적화 팁

### 1️⃣ 워커 수조정

```yaml
# docker-compose.yml
# worker-11, worker-12 추가로 성능 향상
```

### 2️⃣ 타임아웃 조정

```python
# worker_server/main.py
timeout=30  # → 60으로 증가 (느린 네트워크)
```

### 3️⃣ 재시도 로직

```python
# worker_server/main.py
MAX_RETRIES = 3  # → 5로 증가 (불안정한 네트워크)
```

## 문제 해결

### ❌ 연결 실패: Connection refused

**원인:** 컨테이너 미시작 또는 DB 준비 미완료

```bash
# 1. 컨테이너 상태 확인
docker-compose ps

# 2. DB 헬스 확인
docker exec audit_db pg_isready -U audit_user

# 3. 재시작
docker-compose restart
```

### ❌ 워커가 작업을 못 찾음

**원인:** 초기화가 안 됨 또는 모든 작업 완료

```bash
# 초기화 확인
curl -X GET http://localhost:8000/status

# 필요시 재초기화 (DB 초기화 필수)
# docker-compose down -v
# docker-compose up -d
```

### ❌ 엑셀 매칭 실패 (재실행 필요)

```bash
# 1. 매칭 함수 구현 (최종 단계)
# 2. finalize endpoint 재호출
```

## 다음 단계

### 📝 TODO

1. **엑셀 매칭 로직 구현**
   - [x] DB 설계
   - [x] 중앙/워커 서버
   - [ ] 최종 매칭 함수 (finalize endpoint)

2. **모니터링 대시보드** (선택)
   - Grafana + Prometheus
   - Real-time 진행률 표시

3. **자동 재시도**
   - 실패한 작업 자동 재할당

4. **스케줄링**
   - APScheduler로 주기적 실행

## 라이선스

MIT

## 지원

문제 발생 시 로그를 확인하세요:
```bash
docker-compose logs -f
```
