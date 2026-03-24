#!/usr/bin/env python3
"""
오케스트레이터 (Orchestrator)
전체 흐름을 자동화하는 스크립트

사용 방법:
  python orchestrator.py --run-all
  python orchestrator.py --initialize
  python orchestrator.py --status
  python orchestrator.py --finalize
"""

import sys
import os
import requests
import time
import argparse
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ==================== 설정 ====================
CENTRAL_SERVER_URL = os.getenv("CENTRAL_SERVER_URL", "http://localhost:8000")
NUM_WORKERS = int(os.getenv("NUM_WORKERS", 10))
POLL_INTERVAL = 5  # 상태 확인 간격 (초)
WORKER_TIMEOUT = 600  # 워커 최대 작업 시간 (초)

# ==================== 색상 ====================
class Colors:
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'

def print_header(text):
    print(f"\n{Colors.BOLD}{Colors.BLUE}{'='*70}")
    print(f"  {text}")
    print(f"{'='*70}{Colors.ENDC}\n")

def print_success(text):
    print(f"{Colors.GREEN}✓ {text}{Colors.ENDC}")

def print_error(text):
    print(f"{Colors.RED}✗ {text}{Colors.ENDC}")

def print_info(text):
    print(f"{Colors.CYAN}ℹ {text}{Colors.ENDC}")

def print_warning(text):
    print(f"{Colors.YELLOW}⚠ {text}{Colors.ENDC}")

# ==================== 1. 초기화 ====================
def initialize():
    """초기화: 페이지 수 확인 + 작업 분배"""
    print_header("1️⃣  초기화 단계")
    
    try:
        print_info("중앙 서버에 초기화 요청 중...")
        response = requests.get(f"{CENTRAL_SERVER_URL}/init", timeout=30)
        response.raise_for_status()
        
        data = response.json()
        
        print_success(f"초기화 완료")
        print(f"  - 총 페이지: {data['total_pages']}")
        print(f"  - 워커 개수: {data['num_workers']}")
        print(f"  - 워커당 페이지: {data['total_pages'] // data['num_workers']}")
        
        return data
        
    except requests.exceptions.ConnectionError:
        print_error(f"중앙 서버에 연결할 수 없습니다: {CENTRAL_SERVER_URL}")
        return None
    except Exception as e:
        print_error(f"초기화 실패: {str(e)[:100]}")
        return None

# ==================== 2. 상태 모니터링 ====================
def get_status():
    """진행 상황 조회"""
    try:
        response = requests.get(f"{CENTRAL_SERVER_URL}/status", timeout=10)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print_error(f"상태 조회 실패: {str(e)[:50]}")
        return None

def print_status(status):
    """상태를 시각화"""
    if not status:
        return
    
    total = status['total_tasks']
    completed = status['completed_tasks']
    failed = status['failed_tasks']
    in_progress = status['in_progress_tasks']
    pending = status['pending_tasks']
    
    # 진행률
    progress = (completed / total * 100) if total > 0 else 0
    
    # 진행바
    bar_length = 40
    filled = int(bar_length * completed / total) if total > 0 else 0
    bar = '█' * filled + '░' * (bar_length - filled)
    
    print(f"\n📊 진행 현황")
    print(f"  {bar} {progress:.1f}%")
    print(f"\n  📋 작업:")
    print(f"    - 완료: {Colors.GREEN}{completed}{Colors.ENDC}/{total}")
    print(f"    - 진행 중: {Colors.CYAN}{in_progress}{Colors.ENDC}")
    print(f"    - 대기 중: {Colors.YELLOW}{pending}{Colors.ENDC}")
    print(f"    - 실패: {Colors.RED}{failed}{Colors.ENDC}")
    
    # 예상 시간
    if in_progress > 0 or pending > 0:
        est_remaining = max(pending, 2)  # 최소 2개 작업 예상
        print(f"\n  ⏱️  예상 남은 시간: ~{est_remaining * 2}분 (워커당 2분 기준)")

def monitor_progress():
    """진행 상황을 실시간 모니터링"""
    print_header("2️⃣  진행 모니터링")
    
    prev_status = None
    start_time = time.time()
    
    while True:
        status = get_status()
        
        if not status:
            print_error("상태 조회 실패, 재시도 중...")
            time.sleep(POLL_INTERVAL)
            continue
        
        # 상태 변경 시에만 출력
        if status != prev_status:
            print(f"\n[{datetime.now().strftime('%H:%M:%S')}]")
            print_status(status)
            prev_status = status
        
        # 완료 조건
        if status['completed_tasks'] == status['total_tasks']:
            print_success(f"\n모든 작업 완료! (소요 시간: {(time.time() - start_time) / 60:.1f}분)")
            return True
        
        # 모든 작업 실패
        if status['failed_tasks'] == status['total_tasks']:
            print_error(f"\n모든 작업 실패")
            return False
        
        time.sleep(POLL_INTERVAL)

# ==================== 3. 최종화 ====================
def finalize():
    """최종화: 엑셀 매칭"""
    print_header("3️⃣  최종화 단계")
    
    try:
        print_info("중앙 서버에 최종화 요청 중...")
        response = requests.post(f"{CENTRAL_SERVER_URL}/finalize", timeout=60)
        response.raise_for_status()
        
        data = response.json()
        
        if data.get('status') == 'success':
            print_success("엑셀 매칭 완료")
            print(f"  - {data.get('message', 'N/A')}")
        else:
            print_warning("최종화 요청은 전달되었으나 처리 중입니다")
        
        return True
        
    except Exception as e:
        print_error(f"최종화 실패: {str(e)[:100]}")
        return False

# ==================== 4. 전체 실행 ====================
def run_all():
    """전체 흐름 자동 실행"""
    print_header("🚀 전체 프로세스 시작")
    
    # Step 1: 초기화
    init_data = initialize()
    if not init_data:
        print_error("초기화 실패, 종료")
        return False
    
    time.sleep(2)
    
    # Step 2: 모니터링
    success = monitor_progress()
    if not success:
        print_error("진행 중 오류, 종료")
        return False
    
    time.sleep(2)
    
    # Step 3: 최종화
    finalize()
    
    print_header("✅ 전체 프로세스 완료")
    return True

# ==================== 5. CLI ====================
def main():
    parser = argparse.ArgumentParser(
        description="감사보고서 분산 수집 시스템 오케스트레이터"
    )
    
    parser.add_argument(
        "--run-all",
        action="store_true",
        help="전체 프로세스 자동 실행 (초기화 → 모니터링 → 최종화)"
    )
    
    parser.add_argument(
        "--initialize",
        action="store_true",
        help="초기화 단계만 실행"
    )
    
    parser.add_argument(
        "--status",
        action="store_true",
        help="현재 상태 조회"
    )
    
    parser.add_argument(
        "--monitor",
        action="store_true",
        help="진행 상황 모니터링 (실시간)"
    )
    
    parser.add_argument(
        "--finalize",
        action="store_true",
        help="최종화 단계 실행 (엑셀 매칭)"
    )
    
    parser.add_argument(
        "--server",
        default="http://localhost:8000",
        help="중앙 서버 URL (기본값: http://localhost:8000)"
    )
    
    args = parser.parse_args()
    
    global CENTRAL_SERVER_URL
    CENTRAL_SERVER_URL = args.server
    
    print(f"{Colors.BOLD}{Colors.CYAN}")
    print("╔════════════════════════════════════════════════╗")
    print("║  감사보고서 분산 수집 시스템 - 오케스트레이터  ║")
    print("╚════════════════════════════════════════════════╝")
    print(f"{Colors.ENDC}\n")
    
    if args.run_all:
        run_all()
    elif args.initialize:
        initialize()
    elif args.status:
        status = get_status()
        if status:
            print_status(status)
    elif args.monitor:
        monitor_progress()
    elif args.finalize:
        finalize()
    else:
        # 기본: 상태 조회 및 권장사항
        print_info("아무 옵션도 주지 않았습니다.\n")
        print("사용 가능한 옵션:")
        print(f"  {Colors.CYAN}python orchestrator.py --run-all{Colors.ENDC}")
        print(f"    → 전체 프로세스 자동 실행\n")
        print(f"  {Colors.CYAN}python orchestrator.py --initialize{Colors.ENDC}")
        print(f"    → 초기화만 실행\n")
        print(f"  {Colors.CYAN}python orchestrator.py --monitor{Colors.ENDC}")
        print(f"    → 진행 상황 실시간 모니터링\n")
        print(f"  {Colors.CYAN}python orchestrator.py --status{Colors.ENDC}")
        print(f"    → 현재 상태 조회\n")
        print(f"  {Colors.CYAN}python orchestrator.py --finalize{Colors.ENDC}")
        print(f"    → 최종화 (엑셀 매칭)\n")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(f"\n{Colors.YELLOW}사용자 중단{Colors.ENDC}")
        sys.exit(0)
    except Exception as e:
        print_error(f"예기치 않은 오류: {str(e)}")
        sys.exit(1)
