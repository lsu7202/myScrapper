"""
DB 스키마 정의
"""
from sqlalchemy import Column, Integer, String, Text, DateTime, Enum, Boolean, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
import enum
from datetime import datetime

Base = declarative_base()

class TaskStatus(str, enum.Enum):
    """작업 상태"""
    PENDING = "pending"           # 대기 중
    ASSIGNED = "assigned"         # 워커에 할당됨
    IN_PROGRESS = "in_progress"   # 진행 중
    COMPLETED = "completed"       # 완료
    FAILED = "failed"             # 실패


class AuditTask(Base):
    """감사보고서 수집 작업"""
    __tablename__ = "audit_tasks"
    
    id = Column(Integer, primary_key=True)
    page_start = Column(Integer, nullable=False)  # 시작 페이지
    page_end = Column(Integer, nullable=False)    # 종료 페이지
    worker_id = Column(String(50), nullable=True)  # 할당된 워커 ID
    status = Column(Enum(TaskStatus), default=TaskStatus.PENDING)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    
    # 관계
    reports = relationship("AuditReport", back_populates="task", cascade="all, delete-orphan")
    logs = relationship("TaskLog", back_populates="task", cascade="all, delete-orphan")
    
    def __repr__(self):
        return f"<AuditTask(id={self.id}, pages={self.page_start}-{self.page_end}, status={self.status})>"


class AuditReport(Base):
    """수집된 감사보고서"""
    __tablename__ = "audit_reports"
    
    id = Column(Integer, primary_key=True)
    task_id = Column(Integer, ForeignKey("audit_tasks.id"), nullable=False)
    
    company_name = Column(String(255), nullable=False, index=True)  # 공시회사명
    cik_code = Column(String(50), nullable=False)                   # CIK 코드
    ceo_name = Column(String(100), nullable=True)                   # 대표자명
    report_text = Column(Text, nullable=False)                      # 감사보고서 내용
    submitter = Column(String(255), nullable=True)                  # 제출인
    
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # 관계
    task = relationship("AuditTask", back_populates="reports")
    
    def __repr__(self):
        return f"<AuditReport(company={self.company_name}, ceo={self.ceo_name})>"


class TaskLog(Base):
    """작업 로그 (에러 추적)"""
    __tablename__ = "task_logs"
    
    id = Column(Integer, primary_key=True)
    task_id = Column(Integer, ForeignKey("audit_tasks.id"), nullable=False)
    worker_id = Column(String(50), nullable=True)
    
    log_type = Column(String(50), nullable=False)  # "ERROR", "WARNING", "INFO"
    message = Column(Text, nullable=False)
    page_number = Column(Integer, nullable=True)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # 관계
    task = relationship("AuditTask", back_populates="logs")
    
    def __repr__(self):
        return f"<TaskLog(task_id={self.task_id}, type={self.log_type})>"


class ProcessingStatus(Base):
    """전체 처리 상태"""
    __tablename__ = "processing_status"
    
    id = Column(Integer, primary_key=True)
    total_pages = Column(Integer, nullable=False)
    total_tasks = Column(Integer, nullable=False)
    completed_tasks = Column(Integer, default=0)
    failed_tasks = Column(Integer, default=0)
    
    is_initialized = Column(Boolean, default=False)
    is_finalized = Column(Boolean, default=False)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    finalized_at = Column(DateTime, nullable=True)
    
    def __repr__(self):
        return f"<ProcessingStatus(completed={self.completed_tasks}/{self.total_tasks})>"
