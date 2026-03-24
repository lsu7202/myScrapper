"""
워커 서버 (Worker Server)
역할:
1. 중앙 서버에서 작업 가져오기
2. 할당된 페이지 범위 내에서 감사보고서 수집
3. CEO 정보 조회
4. 결과를 DB에 저장
5. 에러 발생 시 중앙 서버에 보고
"""

import sys
import os
import requests
import re
import time
import socket
from datetime import datetime
from typing import Optional
from bs4 import BeautifulSoup

# 경로 추가
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from db_models import (
    init_db,
    SessionLocal,
    AuditTask,
    AuditReport,
    TaskLog,
    TaskStatus
)

# ==================== 설정 ====================
CENTRAL_SERVER_URL = os.getenv("CENTRAL_SERVER_URL", "http://central-server:8000")
API_BASE = 'https://dart.fss.or.kr/dsab001/searchCorp.ax'
CEO_API = 'https://dart.fss.or.kr/dsae001/selectPopup.ax'
DART_START_DATE = '20250324'
DART_END_DATE = '20260324'

WORKER_ID = os.getenv("WORKER_ID", f"worker-{socket.gethostname()}")
MAX_RETRIES = 3

headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9',
    'Accept-Language': 'ko-KR,ko;q=0.9,en;q=0.8',
}

app = FastAPI(title=f"Audit Report Worker - {WORKER_ID}")

print(f"🤖 워커 서버 시작: {WORKER_ID}")
print(f"📍 중앙 서버: {CENTRAL_SERVER_URL}\n")

# ==================== Pydantic 모델 ====================
class ReportData(BaseModel):
    company_name: str
    cik_code: str
    ceo_name: Optional[str] = None
    report_text: str
    submitter: Optional[str] = None


# ==================== CEO 정보 조회 ====================
def get_ceo_name(cik_code: str) -> Optional[str]:
    """
    CIK 코드로 대표자명 조회
    """
    params = {'selectKey': cik_code}
    
    for attempt in range(MAX_RETRIES):
        try:
            response = requests.post(CEO_API, params=params, headers=headers, timeout=30)
            response.encoding = 'utf-8'
            
            soup = BeautifulSoup(response.text, 'html.parser')
            tbody = soup.find('tbody')
            
            if not tbody:
                return None
            
            rows = tbody.find_all('tr')
            for row in rows:
                th = row.find('th')
                if th and '대표자명' in th.get_text():
                    td = row.find('td')
                    if td:
                        ceo_text = td.get_text(strip=True)
                        ceo_name = ceo_text.split()[0]
                        return ceo_name
            
            return None
            
        except Exception as e:
            if attempt < MAX_RETRIES - 1:
                wait_time = 2 + (attempt * 2)
                time.sleep(wait_time)
            else:
                print(f"    ✗ CEO 조회 실패 ({cik_code}): {str(e)[:50]}")
                return None


# ==================== 페이지 수집 ====================
def collect_page(page_num: int, task_id: int) -> list:
    """
    한 페이지의 감사보고서 수집
    """
    params = {
        'currentPage': page_num,
        'maxResults': 100,
        'maxLinks': 10,
        'sort': 'date',
        'series': 'desc',
        'textCrpCik': '',
        'pageGubun': 'corp',
        'attachDocNmPopYn': '',
        'textCrpNm': '',
        'startDate': DART_START_DATE,
        'endDate': DART_END_DATE,
        'decadeType': '',
        'finalReport': 'recent',
        'attachDocNm': '',
        'publicType': ['F001', 'F002', 'F003', 'F004', 'F005'],
    }
    
    reports = []
    db = SessionLocal()
    
    try:
        response = requests.post(API_BASE, params=params, headers=headers, timeout=30)
        response.encoding = 'utf-8'
        
        soup = BeautifulSoup(response.text, 'html.parser')
        tbody = soup.find('tbody', id='tbody')
        
        if not tbody:
            return reports
        
        rows = tbody.find_all('tr')
        
        for row in rows:
            etc_tag = row.find('span', class_='tagCom_etc')
            if not etc_tag:
                continue
            
            try:
                # 공시회사명 및 CIK 추출
                corp_link = row.find('a', onclick=re.compile(r"openCorpInfoNew"))
                if not corp_link:
                    continue
                
                company_name = corp_link.get_text(strip=True)
                company_name = ' '.join(company_name.split())
                
                onclick = corp_link.get('onclick', '')
                cik_match = re.search(r"openCorpInfoNew\('(\d+)'", onclick)
                if not cik_match:
                    continue
                
                cik_code = cik_match.group(1)
                
                # 감사보고서 링크 추출
                report_links = row.find_all('a', href=re.compile(r'/dsaf001/main.do'))
                if not report_links:
                    continue
                
                for report_link in report_links:
                    report_text = report_link.get_text(strip=True)
                    report_text = ' '.join(report_text.split())
                    
                    # 제출인 추출
                    tds = row.find_all('td')
                    submitter = ''
                    if len(tds) >= 4:
                        submitter = tds[3].get_text(strip=True)
                    
                    # CEO 조회 (실패해도 계속)
                    ceo_name = get_ceo_name(cik_code)
                    
                    reports.append(ReportData(
                        company_name=company_name,
                        cik_code=cik_code,
                        ceo_name=ceo_name,
                        report_text=report_text,
                        submitter=submitter
                    ))
                    
                    time.sleep(0.3)  # CEO 조회 간 대기
            
            except Exception as e:
                # 개별 행 오류는 로깅하고 계속
                log = TaskLog(
                    task_id=task_id,
                    worker_id=WORKER_ID,
                    log_type="WARNING",
                    message=f"Row parse error: {str(e)[:100]}",
                    page_number=page_num
                )
                db.add(log)
                db.commit()
                continue
        
        return reports
        
    except Exception as e:
        # 페이지 전체 오류 로깅
        log = TaskLog(
            task_id=task_id,
            worker_id=WORKER_ID,
            log_type="ERROR",
            message=f"Page fetch error: {str(e)[:100]}",
            page_number=page_num
        )
        db.add(log)
        db.commit()
        return reports
    
    finally:
        db.close()


# ==================== 작업 처리 ====================
def process_task(task_id: int, page_start: int, page_end: int):
    """
    할당된 작업 처리 (페이지 수집 + DB 저장)
    """
    db = SessionLocal()
    
    try:
        print(f"\n🚀 작업 처리 시작: Task {task_id}")
        print(f"   워커: {WORKER_ID}")
        print(f"   페이지: {page_start}-{page_end}")
        
        # 작업 상태를 IN_PROGRESS로 변경
        task = db.query(AuditTask).filter(AuditTask.id == task_id).first()
        if task:
            task.status = TaskStatus.IN_PROGRESS
            task.worker_id = WORKER_ID
            db.commit()
        
        total_reports = 0
        
        # 페이지별 수집
        for page_num in range(page_start, page_end + 1):
            print(f"  📄 페이지 {page_num} 수집 중...")
            
            reports = collect_page(page_num, task_id)
            
            # DB에 저장
            for report in reports:
                audit_report = AuditReport(
                    task_id=task_id,
                    company_name=report.company_name,
                    cik_code=report.cik_code,
                    ceo_name=report.ceo_name,
                    report_text=report.report_text,
                    submitter=report.submitter
                )
                db.add(audit_report)
            
            db.commit()
            total_reports += len(reports)
            
            print(f"    ✓ {len(reports)}건 저장")
            time.sleep(2)  # 페이지 간 대기
        
        print(f"\n✓ 작업 완료: Task {task_id}")
        print(f"  - 총 {total_reports}건 수집")
        
        # 작업 상태를 COMPLETED로 변경
        task = db.query(AuditTask).filter(AuditTask.id == task_id).first()
        if task:
            task.status = TaskStatus.COMPLETED
            task.completed_at = datetime.utcnow()
            db.commit()
        
        return {"status": "success", "reports": total_reports}
        
    except Exception as e:
        print(f"\n✗ 작업 실패: Task {task_id}")
        print(f"  - 오류: {str(e)[:100]}")
        
        # 작업 상태를 FAILED로 변경
        task = db.query(AuditTask).filter(AuditTask.id == task_id).first()
        if task:
            task.status = TaskStatus.FAILED
            db.commit()
        
        # 에러 로그 기록
        log = TaskLog(
            task_id=task_id,
            worker_id=WORKER_ID,
            log_type="ERROR",
            message=str(e)[:200]
        )
        db.add(log)
        db.commit()
        
        raise
    
    finally:
        db.close()


# ==================== API 엔드포인트 ====================

@app.get("/work")
async def get_work():
    """
    중앙 서버에서 다음 작업 가져오기
    """
    try:
        # 중앙 서버에서 대기 중인 작업 조회
        response = requests.get(f"{CENTRAL_SERVER_URL}/tasks/pending", timeout=10)
        response.raise_for_status()
        
        tasks = response.json()
        
        if not tasks:
            return {"status": "no_work", "message": "No pending tasks"}
        
        # 첫 번째 작업 선택
        task = tasks[0]
        task_id = task['id']
        
        # 중앙 서버에 작업 할당 보고
        assign_response = requests.post(
            f"{CENTRAL_SERVER_URL}/tasks/{task_id}/assign/{WORKER_ID}",
            timeout=10
        )
        assign_response.raise_for_status()
        
        # 작업 처리
        result = process_task(
            task_id=task_id,
            page_start=task['page_start'],
            page_end=task['page_end']
        )
        
        # 중앙 서버에 완료 보고
        complete_response = requests.post(
            f"{CENTRAL_SERVER_URL}/tasks/{task_id}/complete",
            timeout=10
        )
        complete_response.raise_for_status()
        
        return result
        
    except Exception as e:
        print(f"✗ 작업 처리 오류: {str(e)[:100]}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/status")
async def status():
    """워커 상태"""
    return {
        "worker_id": WORKER_ID,
        "status": "ready",
        "timestamp": datetime.utcnow().isoformat()
    }


@app.get("/health")
async def health_check():
    """헬스 체크"""
    return {"status": "healthy", "worker_id": WORKER_ID}


# ==================== Main ====================
if __name__ == "__main__":
    import uvicorn
    
    # DB 초기화
    init_db()
    
    # 서버 시작
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8001,
        log_level="info"
    )
