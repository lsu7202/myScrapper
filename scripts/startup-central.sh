#!/bin/bash
set -e

# 중앙 서버 시작 스크립트
# Terraform 변수로 주입됨

DB_HOST=${db_host}
DB_USER=${db_user}
DB_PASS=${db_pass}
REPO_URL=${repo_url}
NUM_WORKERS=${num_workers}
CENTRAL_IP=$(hostname -I | awk '{print $1}')

echo "==================== Central Server Startup ===================="
echo "DB Host: $DB_HOST"
echo "DB User: $DB_USER"
echo "Central IP: $CENTRAL_IP"
echo "Repo: $REPO_URL"
echo "Num Workers: $NUM_WORKERS"
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
    echo "⚠️ Directory exists, pulling latest changes..."
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
NUM_WORKERS=$NUM_WORKERS
DART_START_DATE=20250324
DART_END_DATE=20260324
LOG_LEVEL=info
EXCEL_FILE=../기업개황.xlsx
EOF

echo "✓ Environment configured"

# ==================== 5. DB 테이블 초기화 ====================
echo "[5/6] Initializing database tables..."
sleep 10  # DB가 준비될 때까지 대기

# Python으로 DB 초기화
python3 << 'PYEOF'
import os
import sys
sys.path.insert(0, '.')

try:
    from db_models import init_db
    init_db()
    print("✓ Database tables created")
except Exception as e:
    print(f"⚠️ DB initialization warning: {e}")
    print("Will retry on first run...")
PYEOF

# ==================== 6. Docker 서비스 시작 ====================
echo "[6/6] Starting services..."
docker-compose up -d

# 헬스 체크
sleep 15
echo ""
echo "Checking services..."

max_retries=10
retry_count=0

while [ $retry_count -lt $max_retries ]; do
    if curl -f http://localhost:8000/health > /dev/null 2>&1; then
        echo "✓ Central server is ready"
        break
    fi
    retry_count=$((retry_count + 1))
    if [ $retry_count -lt $max_retries ]; then
        echo "⏳ Waiting for central server... (attempt $retry_count/$max_retries)"
        sleep 5
    fi
done

if [ $retry_count -eq $max_retries ]; then
    echo "⚠️ Central server not responding after $max_retries attempts"
    echo "Check logs: docker-compose logs -f"
fi

echo ""
echo "==================== ✅ Central Server Ready ===================="
echo ""
echo "📊 Next steps:"
echo "1. Wait for all workers to start"
echo "2. SSH to central server"
echo "3. Run: python orchestrator.py --run-all"
echo ""
