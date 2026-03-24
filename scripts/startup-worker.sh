#!/bin/bash
set -e

# 워커 서버 시작 스크립트
# Terraform 변수로 주입됨

WORKER_ID=${worker_id}
DB_HOST=${db_host}
DB_USER=${db_user}
DB_PASS=${db_pass}
CENTRAL_IP=${central_ip}
REPO_URL=${repo_url}
WORKER_IP=$(hostname -I | awk '{print $1}')

echo "==================== Worker $WORKER_ID Startup ===================="
echo "Worker ID: $WORKER_ID"
echo "DB Host: $DB_HOST"
echo "Central Server: $CENTRAL_IP"
echo "Worker IP: $WORKER_IP"
echo ""

# ==================== 1. Docker 설치 ====================
echo "[1/6] Installing Docker..."
if ! command -v docker &> /dev/null; then
    curl -fsSL https://get.docker.com -o get-docker.sh
    sudo sh get-docker.sh
    sudo usermod -aG docker ubuntu
    rm get-docker.sh
    echo "✓ Docker installed"
else
    echo "✓ Docker already installed"
fi

# ==================== 2. Docker Compose 설치 ====================
echo "[2/6] Installing Docker Compose..."
if ! command -v docker-compose &> /dev/null; then
    sudo curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" \
      -o /usr/local/bin/docker-compose
    sudo chmod +x /usr/local/bin/docker-compose
    echo "✓ Docker Compose installed"
else
    echo "✓ Docker Compose already installed"
fi

# ==================== 3. 코드 다운로드 ====================
echo "[3/6] Cloning repository..."
cd /opt
if [ -d "audit-system" ]; then
    echo "✓ Repository already cloned"
    cd audit-system
    git pull origin main || true
else
    sudo git clone $REPO_URL audit-system
    cd audit-system
fi
sudo chown -R ubuntu:ubuntu /opt/audit-system
cd 감사보고서/distributed
echo "✓ Repository ready"

# ==================== 4. 환경 변수 설정 ====================
echo "[4/6] Setting up environment..."
cat > .env << EOF
DATABASE_URL=postgresql://$DB_USER:$DB_PASS@$DB_HOST:5432/audit_db
CENTRAL_SERVER_URL=http://$CENTRAL_IP:8000
WORKER_ID=worker-$WORKER_ID
NUM_WORKERS=10
DART_START_DATE=20250324
DART_END_DATE=20260324
LOG_LEVEL=info
EOF

echo "✓ Environment configured"

# ==================== 5. 대기 (중앙 서버가 DB 초기화할 때까지) ====================
echo "[5/6] Waiting for central server and database..."
sleep 30

# ==================== 6. Docker 서비스 시작 ====================
echo "[6/6] Starting worker services..."
docker-compose up -d

# 헬스 체크
sleep 10
echo ""
echo "Checking worker health..."

max_retries=10
retry_count=0

while [ $retry_count -lt $max_retries ]; do
    if curl -f http://localhost:8001/health > /dev/null 2>&1; then
        echo "✓ Worker $WORKER_ID is ready"
        break
    fi
    retry_count=$((retry_count + 1))
    if [ $retry_count -lt $max_retries ]; then
        echo "⏳ Waiting for worker... (attempt $retry_count/$max_retries)"
        sleep 3
    fi
done

if [ $retry_count -eq $max_retries ]; then
    echo "⚠️ Worker not responding after $max_retries attempts"
    echo "Check logs: docker-compose logs -f"
fi

echo ""
echo "==================== ✅ Worker $WORKER_ID Ready ===================="
echo ""
echo "Worker will automatically poll central server for work"
echo ""
