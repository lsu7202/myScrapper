"""
중앙 서버 (Central Server)
역할: 
1. 초기화: 총 페이지 수 확인 -> 작업 분배
2. 모니터링: 워커 상태 확인
3. 최종화: 모든 워커 완료 후 엑셀 매칭
"""

import sys
import os
import requests
import re
import math
from datetime import datetime
from typing import List

# 경로 추가
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import FastAPI, HTTPException, Depends
from sqlalchemy.orm import Session
from pydantic import BaseModel

from db_models import (
    init_db, 
    get_db_context, 
    SessionLocal,
    AuditTask, 
    AuditReport, 
    ProcessingStatus,
    TaskStatus
)

# ==================== 설정 ====================
API_BASE = 'https://dart.fss.or.kr/dsab001/searchCorp.ax'
EXCEL_FILE = '../기업개황.xlsx'
NUM_WORKERS = 10
DART_START_DATE = '20250324'
DART_END_DATE = '20260324'

headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9',
    'Accept-Language': 'ko-KR,ko;q=0.9,en;q=0.8',
}

app = FastAPI(title="Audit Report Central Server")

# ==================== Pydantic 모델 ====================
class TaskResponse(BaseModel):
    id: int
    page_start: int
    page_end: int
    status: str
    worker_id: str = None
    
    class Config:
        from_attributes = True


class StatusResponse(BaseModel):
    total_pages: int
    total_tasks: int
    completed_tasks: int
    failed_tasks: int
    in_progress_tasks: int
    pending_tasks: int
    is_initialized: bool


# ==================== 1. 총 페이지 수 조회 ====================
def get_total_pages() -> int:
    """DART에서 총 페이지 수 조회"""
    params = {
        'currentPage': 1,
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
    
    try:
        print(f"🔍 DART 총 페이지 수 조회 중...")
        response = requests.post(API_BASE, params=params, headers=headers, timeout=30)
        response.encoding = 'utf-8'
        
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(response.text, 'html.parser')
        page_info = soup.find('div', class_='pageInfo')
        
        if page_info:
            text = page_info.get_text(strip=True)
            match = re.search(r'\[1/(\d+)\]', text)
            if match:
                total_pages = int(match.group(1))
                print(f"✓ 총 페이지: {total_pages}페이지\n")
                return total_pages
        
        print("⚠️ 페이지 정보 조회 실패, 기본값 1페이지")
        return 1
        
    except Exception as e:
        print(f"✗ 페이지 정보 조회 실패: {e}")
        return 1


# ==================== 2. 작업 분배 ====================
def distribute_tasks(total_pages: int, num_workers: int):
    """작업을 워커에 분배"""
    db = SessionLocal()
    try:
        # 기존 작업 제거
        db.query(AuditTask).delete()
        db.commit()
        
        pages_per_worker = math.ceil(total_pages / num_workers)
        
        print(f"📊 작업 분배:")
        print(f"  - 총 페이지: {total_pages}")
        print(f"  - 워커 개수: {num_workers}")
        print(f"  - 워커당 페이지: {pages_per_worker}\n")
        
        for worker_idx in range(num_workers):
            page_start = worker_idx * pages_per_worker + 1
            page_end = min((worker_idx + 1) * pages_per_worker, total_pages)
            
            if page_start > total_pages:
                break
            
            task = AuditTask(
                page_start=page_start,
                page_end=page_end,
                status=TaskStatus.PENDING
            )
            db.add(task)
            print(f"  ✓ Task {worker_idx + 1}: 페이지 {page_start}-{page_end}")
        
        db.commit()
        
        # 처리 상태 업데이트
        status = db.query(ProcessingStatus).first()
        if not status:
            status = ProcessingStatus(
                total_pages=total_pages,
                total_tasks=num_workers,
                is_initialized=True
            )
            db.add(status)
        else:
            status.total_pages = total_pages
            status.total_tasks = num_workers
            status.is_initialized = True
        
        db.commit()
        print(f"\n✓ 작업 분배 완료\n")
        
    finally:
        db.close()


# ==================== API 엔드포인트 ====================

@app.get("/init")
async def initialize():
    """
    초기화: DART 조회 -> 총 페이지 수 -> 작업 분배
    """
    try:
        total_pages = get_total_pages()
        distribute_tasks(total_pages, NUM_WORKERS)
        
        return {
            "status": "success",
            "total_pages": total_pages,
            "num_workers": NUM_WORKERS,
            "timestamp": datetime.utcnow().isoformat()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/tasks/pending", response_model=List[TaskResponse])
async def get_pending_tasks():
    """
    대기 중인 작업 목록 조회
    """
    db = SessionLocal()
    try:
        tasks = db.query(AuditTask).filter(
            AuditTask.status == TaskStatus.PENDING
        ).all()
        
        return tasks
    finally:
        db.close()


@app.get("/status", response_model=StatusResponse)
async def get_status():
    """
    전체 처리 상태 조회
    """
    db = SessionLocal()
    try:
        status = db.query(ProcessingStatus).first()
        
        if not status:
            return {
                "total_pages": 0,
                "total_tasks": 0,
                "completed_tasks": 0,
                "failed_tasks": 0,
                "in_progress_tasks": 0,
                "pending_tasks": 0,
                "is_initialized": False
            }
        
        completed = db.query(AuditTask).filter(
            AuditTask.status == TaskStatus.COMPLETED
        ).count()
        
        in_progress = db.query(AuditTask).filter(
            AuditTask.status == TaskStatus.IN_PROGRESS
        ).count()
        
        pending = db.query(AuditTask).filter(
            AuditTask.status == TaskStatus.PENDING
        ).count()
        
        failed = db.query(AuditTask).filter(
            AuditTask.status == TaskStatus.FAILED
        ).count()
        
        return {
            "total_pages": status.total_pages,
            "total_tasks": status.total_tasks,
            "completed_tasks": completed,
            "failed_tasks": failed,
            "in_progress_tasks": in_progress,
            "pending_tasks": pending,
            "is_initialized": status.is_initialized
        }
    finally:
        db.close()


@app.post("/tasks/{task_id}/assign/{worker_id}")
async def assign_task(task_id: int, worker_id: str):
    """
    워커에게 작업 할당
    """
    db = SessionLocal()
    try:
        task = db.query(AuditTask).filter(AuditTask.id == task_id).first()
        
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        
        task.worker_id = worker_id
        task.status = TaskStatus.ASSIGNED
        task.started_at = datetime.utcnow()
        
        db.commit()
        
        return {"status": "success", "task_id": task_id, "worker_id": worker_id}
    finally:
        db.close()


@app.post("/tasks/{task_id}/complete")
async def complete_task(task_id: int):
    """
    작업 완료 보고
    """
    db = SessionLocal()
    try:
        task = db.query(AuditTask).filter(AuditTask.id == task_id).first()
        
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        
        task.status = TaskStatus.COMPLETED
        task.completed_at = datetime.utcnow()
        
        # 전체 진행 상황 업데이트
        status = db.query(ProcessingStatus).first()
        if status:
            completed = db.query(AuditTask).filter(
                AuditTask.status == TaskStatus.COMPLETED
            ).count()
            status.completed_tasks = completed
        
        db.commit()
        
        return {"status": "success", "task_id": task_id}
    finally:
        db.close()


@app.post("/tasks/{task_id}/fail")
async def fail_task(task_id: int, reason: str = None):
    """
    작업 실패 보고
    """
    db = SessionLocal()
    try:
        task = db.query(AuditTask).filter(AuditTask.id == task_id).first()
        
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        
        task.status = TaskStatus.FAILED
        
        from db_models import TaskLog
        log = TaskLog(
            task_id=task_id,
            worker_id=task.worker_id,
            log_type="ERROR",
            message=reason or "Unknown error"
        )
        db.add(log)
        
        # 전체 진행 상황 업데이트
        status = db.query(ProcessingStatus).first()
        if status:
            failed = db.query(AuditTask).filter(
                AuditTask.status == TaskStatus.FAILED
            ).count()
            status.failed_tasks = failed
        
        db.commit()
        
        return {"status": "success", "task_id": task_id}
    finally:
        db.close()


@app.post("/finalize")
async def finalize():
    """
    최종화: 모든 작업 완료 후 엑셀 매칭
    """
    db = SessionLocal()
    try:
        # 완료되지 않은 작업 확인
        pending = db.query(AuditTask).filter(
            AuditTask.status.in_([TaskStatus.PENDING, TaskStatus.IN_PROGRESS])
        ).count()
        
        if pending > 0:
            raise HTTPException(
                status_code=400,
                detail=f"Still {pending} pending tasks"
            )
        
        status = db.query(ProcessingStatus).first()
        if status:
            status.is_finalized = True
            status.finalized_at = datetime.utcnow()
        
        db.commit()
        
        # 엑셀 매칭 로직 실행
        try:
            from excel_matcher import match_excel
            excel_path = os.getenv("EXCEL_FILE", "../기업개황.xlsx")
            match_result = match_excel(excel_path)
            
            return {
                "status": "success",
                "message": "Excel matching completed",
                "matched_rows": match_result['matched_rows'],
                "total_rows": match_result['total_rows'],
                "timestamp": datetime.utcnow().isoformat()
            }
        except Exception as e:
            return {
                "status": "partial",
                "message": f"Excel matching error: {str(e)[:100]}",
                "timestamp": datetime.utcnow().isoformat()
            }
    finally:
        db.close()


@app.get("/health")
async def health_check():
    """헬스 체크"""
    return {"status": "healthy", "timestamp": datetime.utcnow().isoformat()}


# ==================== Main ====================
if __name__ == "__main__":
    import uvicorn
    
    # DB 초기화
    init_db()
    
    # 서버 시작
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
        log_level="info"
    )
