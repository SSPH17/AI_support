import os
from contextlib import contextmanager
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import QueuePool

# ВАЖНО: Замените "ИМЯ_ПОЛЬЗОВАТЕЛЯ" и "ПАРОЛЬ" на те, 
# которые вы вводили при установке PostgreSQL!
# Например: "postgresql+psycopg2://admin:mypassword@localhost:5432/teamdocs"
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg2://SSPH:194500194500Aa@localhost:5432/AI_support"
)

engine = create_engine(
    DATABASE_URL,
    poolclass=QueuePool,
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,
    echo=False,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

@contextmanager
def get_db():
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

def init_db():
    """Создает таблицы и включает pgvector. Вызывать один раз при старте."""
    # 1. Включаем расширение vector
    with engine.connect() as conn:
        try:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector;"))
            conn.commit()
        except Exception as e:
            print(f"⚠️ Предупреждение: не удалось создать расширение vector (возможно, оно уже есть). {e}")

    # 2. Создаем таблицы
    from .models import Base
    Base.metadata.create_all(bind=engine)
    print("✅ База данных успешно инициализирована.")

def create_default_admin():
    from .models import User, Project
    # Используем готовую сессию, которая объявлена в начале файла!
    with SessionLocal() as db: 
        if not db.query(User).filter_by(username='admin').first():
            admin = User(username='admin', password_hash='admin', role='admin')
            db.add(admin)
            db.commit()
            print("✅ Создан пользователь admin (пароль: admin)")