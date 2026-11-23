import os
import re
import numpy as np
from rank_bm25 import BM25Okapi
from sentence_transformers import SentenceTransformer

UPLOAD_FOLDER = 'uploads'

# Глобальная переменная для ленивой загрузки модели (чтобы не грузить её при каждом импорте)
_model = None

def get_embedding_model():
    """Ленивая загрузка модели эмбеддингов."""
    global _model
    if _model is None:
        print("🔄 Загрузка модели семантического поиска (rubert-tiny2)... Это займет несколько секунд при первом запуске.")
        # Модель легкая (~100 МБ), отлично понимает русский и английский смысл
        _model = SentenceTransformer('cointegrated/rubert-tiny2')
    return _model

def cosine_similarity(a, b):
    """Вычисление косинусного сходства между двумя векторами."""
    return np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b))

def min_max_normalize(scores):
    """Нормализация оценок в диапазон [0, 1]."""
    min_s = np.min(scores)
    max_s = np.max(scores)
    if max_s == min_s:
        return np.zeros_like(scores)
    return (scores - min_s) / (max_s - min_s)

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
    """ГИБРИДНОЕ ранжирование: BM25 (ключевые слова) + Эмбеддинги (смысл)."""
    if not chunks:
        return []
        
    # Защита от общих вопросов
    short_query = query.lower().strip()
    general_keywords = [
        "привет", "как дела", "сколько времени", "который час", "посчитай", "рассчитай", "оцени", "как ты", "кто ты",
        "какие папки", "есть ли папка", "список папок", "какие проекты", "список проектов", "какие файлы", "список файлов", "структура"
    ]
    if len(short_query) < 5 or any(kw in short_query for kw in general_keywords):
        return [] 
    
    # Если текста мало — отдаём всё
    if len(chunks) <= 20:
        return chunks

    def tokenize(text):
        return re.findall(r'[а-яА-ЯёЁa-zA-Z0-9]+', text.lower())

    # --- 1. ПОИСК ПО КЛЮЧЕВЫМ СЛОВАМ (BM25) ---
    tokenized_corpus = [tokenize(c["text"]) for c in chunks]
    bm25 = BM25Okapi(tokenized_corpus)
    
    stop_words = {
        "что", "как", "где", "в", "на", "и", "с", "по", "о", "об", "перескажи", "расскажи", "суть", 
        "файл", "файла", "файле", "папка", "папке", "входит", "перечень", "обычно", "пункт", "пункта", 
        "раздел", "раздела", "общие", "сведения", "цель", "состав", "проект", "проекта", "какой", "какая", "какие", "мне", "пожалуйста"
    }
    query_words = [w for w in tokenize(query) if w not in stop_words and len(w) >= 3]
    
    bm25_scores = bm25.get_scores(query_words) if query_words else np.zeros(len(chunks))

    # --- 2. СЕМАНТИЧЕСКИЙ ПОИСК (ЭМБЕДДИНГИ) ---
    model = get_embedding_model()
    
    # Кодируем чанки и запрос в векторы
    chunk_embeddings = model.encode([c["text"] for c in chunks], convert_to_numpy=True, show_progress_bar=False)
    query_embedding = model.encode(query, convert_to_numpy=True, show_progress_bar=False)
    
    # Считаем косинусное сходство запроса с каждым чанком
    emb_scores = np.array([cosine_similarity(query_embedding, c_emb) for c_emb in chunk_embeddings])

    # --- 3. ГИБРИДНОЕ ОБЪЕДИНЕНИЕ ---
    # Нормализуем обе оценки от 0 до 1, чтобы их можно было честно сложить
    bm25_norm = min_max_normalize(bm25_scores)
    emb_norm = min_max_normalize(emb_scores)
    
    # Веса: 0.4 для ключевых слов, 0.6 для смысла (можно настроить под себя)
    alpha = 0.4 
    final_scores = alpha * bm25_norm + (1 - alpha) * emb_norm

    # Сортируем и берем top_k
    top_indices = np.argsort(final_scores)[::-1][:top_k]
    
    # Отсекаем мусор (если итоговая оценка слишком низкая)
    results = [chunks[i] for i in top_indices if final_scores[i] > 0.15] 
    
    return results if results else chunks[:top_k]

def search_context(query, folder_path="", top_k=3):
    """Поиск по папке (folder_path) или по всем файлам (если пусто)."""
    chunks = get_project_chunks(folder_path)
    return _rank_chunks(query, chunks, top_k)

def search_in_file(query, file_rel_path, top_k=3):
    """Поиск ТОЛЬКО по одному файлу."""
    chunks = get_file_chunks(file_rel_path)
    return _rank_chunks(query, chunks, top_k)