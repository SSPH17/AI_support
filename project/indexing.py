import hashlib
from datetime import datetime
from sqlalchemy import delete
from database.db import get_db
from database.models import Document, Chunk
from rag_engine import embed_text, get_embedding_model


def parse_markdown_chunks(text: str, target_chars: int = 1200, overlap: int = 200) -> list[dict]:
    """Разбиение на куски. Маленькие файлы — один чанк."""
    if not text or not text.strip():
        return []
    chunks = []
    step = max(target_chars - overlap, 1)
    for start in range(0, len(text), step):
        piece = text[start:start + target_chars].strip()
        if piece:  # берём любой непустой кусок, даже короткий
            chunks.append({"content": piece, "section_title": "Фрагмент"})
    return chunks


def index_document(document_id: int, full_path: str):
    with get_db() as db:
        doc = db.get(Document, document_id)
        if not doc:
            return

        doc.status = "processing"
        db.commit()

        try:
            try:
                with open(full_path, "r", encoding="utf-8") as f:
                    raw = f.read()
            except UnicodeDecodeError:
                with open(full_path, "r", encoding="cp1251", errors="replace") as f:
                    raw = f.read()

            # 1. Удаляем старые чанки
            db.execute(delete(Chunk).where(Chunk.document_id == document_id))

            # 2. Нарезаем
            parsed = parse_markdown_chunks(raw)

            # 3. Пустой/крошечный файл — не ошибка, просто нет чанков
            if not parsed:
                doc.status = "ready"
                doc.processed_at = datetime.utcnow()
                doc.content_hash = hashlib.sha256(raw.encode("utf-8", errors="replace")).hexdigest()
                db.commit()
                print(f"ℹ️ Файл {full_path} пуст — проиндексирован без чанков")
                return

            # 4. Эмбеддинги
            texts = [p["content"] for p in parsed]
            model = get_embedding_model()
            embeddings = model.encode(texts, convert_to_numpy=True, show_progress_bar=False)

            # 5. Сохраняем
            for i, (p, vec) in enumerate(zip(parsed, embeddings)):
                db.add(Chunk(
                    document_id=document_id,
                    project_id=doc.project_id,
                    filename=doc.filename, # <--- ДОБАВЬ ЭТУ СТРОКУ!
                    chunk_index=i,
                    section_title=p["section_title"],
                    content=p["content"],
                    embedding=vec.tolist(),
                ))

            doc.status = "ready"
            doc.processed_at = datetime.utcnow()
            doc.content_hash = hashlib.sha256(raw.encode("utf-8", errors="replace")).hexdigest()
            db.commit()
            print(f"✅ Файл {full_path} успешно проиндексирован")

        except Exception as e:
            print(f"❌ Ошибка индексации {full_path}: {e}")
            doc.status = "error"
            doc.error_message = str(e)[:500]
            db.commit()