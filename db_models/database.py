"""
DB 연결 및 세션 관리
"""
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from contextlib import contextmanager
from db_models.models import Base

# DB 연결 문자열
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://audit_user:audit_pass@localhost:5432/audit_db"
)

# 엔진 생성
engine = create_engine(
    DATABASE_URL,
    echo=False,  # SQL 로깅 비활성화 (필요시 True)
    pool_pre_ping=True,  # 연결 상태 확인
    pool_size=10,
    max_overflow=20
)

# 세션 팩토리
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db():
    """DB 테이블 생성"""
    Base.metadata.create_all(bind=engine)
    print("✓ DB 초기화 완료")


def get_db() -> Session:
    """의존성 주입용 세션"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def get_db_context():
    """컨텍스트 매니저용 세션"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
