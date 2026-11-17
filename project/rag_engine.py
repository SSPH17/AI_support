import os
import re
from rank_bm25 import BM25Okapi

UPLOAD_FOLDER = 'uploads'

def get_project_chunks(folder_path):
    """Читает все файлы папки (или всей папки uploads, если пусто)."""
    chunks = []
    full_folder_path = os.path.join(UPLOAD_FOLDER, folder_path) if folder_path else UPLOAD_FOLDER
    
    if not os.path.exists(full_folder_path):
        return chunks

    for root, _, files in os.walk(full_folder_path):
        for file in files:
            if file.endswith(('.md', '.markdown', '.txt')):
                file_path = os.path.join(root, file)
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        text = f.read()
                except UnicodeDecodeError:
                    with open(file_path, 'r', encoding='cp1251', errors='replace') as f:
                        text = f.read()
                    
                chunk_size = 1000
                overlap = 200
                for i in range(0, len(text), chunk_size - overlap):
                    chunk_text = text[i:i + chunk_size].strip()
                    if len(chunk_text) > 20:
                        chunks.append({
                            "text": chunk_text,
                            "source": os.path.relpath(file_path, full_folder_path)
                        })
    return chunks

def get_file_chunks(file_rel_path):
    """Читает ОДИН файл и нарезает его на куски."""
    chunks = []
    full_path = os.path.join(UPLOAD_FOLDER, file_rel_path)
    if not os.path.exists(full_path) or not os.path.isfile(full_path):
        return chunks

    try:
        with open(full_path, 'r', encoding='utf-8') as f:
            text = f.read()
    except UnicodeDecodeError:
        with open(full_path, 'r', encoding='cp1251', errors='replace') as f:
            text = f.read()

    chunk_size = 1000
    overlap = 200
    for i in range(0, len(text), chunk_size - overlap):
        chunk_text = text[i:i + chunk_size].strip()
        if len(chunk_text) > 20:
            chunks.append({
                "text": chunk_text,
                "source": file_rel_path
            })
    return chunks

def _rank_chunks(query, chunks, top_k):
    """Общая логика ранжирования BM25."""
    if not chunks:
        return []

    # Защита от общих вопросов (чтобы не искать в файлах то, чего там нет)
    short_query = query.lower().strip()
    general_keywords = ["привет", "как дела", "сколько времени", "который час", "посчитай", "рассчитай", "оцени", "как ты", "кто ты"]
    if len(short_query) < 5 or any(kw in short_query for kw in general_keywords):
        return [] 

    # Если текста мало — отдаём всё
    if len(chunks) <= 20:
        return chunks

    def tokenize(text):
        return re.findall(r'[а-яА-ЯёЁa-zA-Z0-9]+', text.lower())

    tokenized_corpus = [tokenize(c["text"]) for c in chunks]
    if not any(tokenized_corpus):
        return chunks[:top_k]

    bm25 = BM25Okapi(tokenized_corpus)

    stop_words = {
        "что", "как", "где", "в", "на", "и", "с", "по", "о", "об",
        "перескажи", "расскажи", "суть", "файл", "файла", "файле",
        "папка", "папке", "входит", "перечень", "обычно",
        "пункт", "пункта", "раздел", "раздела", "общие", "сведения",
        "цель", "состав", "проект", "проекта", "какой", "какая", "какие",
        "мне", "пожалуйста"
    }
    query_words = [w for w in tokenize(query) if w not in stop_words and len(w) >= 3]
    if not query_words:
        return chunks[:top_k]

    scores = bm25.get_scores(query_words)
    top_indices = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:top_k]

    results = [chunks[i] for i in top_indices if scores[i] > 0]
    return results if results else chunks[:top_k]

def search_context(query, folder_path="", top_k=3):
    """Поиск по папке (folder_path) или по всем файлам (если пусто)."""
    chunks = get_project_chunks(folder_path)
    return _rank_chunks(query, chunks, top_k)

def search_in_file(query, file_rel_path, top_k=3):
    """Поиск ТОЛЬКО по одному файлу."""
    chunks = get_file_chunks(file_rel_path)
    return _rank_chunks(query, chunks, top_k)