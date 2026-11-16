import os
import re
from rank_bm25 import BM25Okapi

UPLOAD_FOLDER = 'uploads'

def get_project_chunks(folder_path):
    """Читает файлы и нарезает их на логические куски."""
    chunks = []
    full_folder_path = os.path.join(UPLOAD_FOLDER, folder_path)
    
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
                    
                # Нарезаем текст не по абзацам, а по 1000 символов с перекрытием в 200 символов
                # Это гарантирует, что мы не потеряем контекст (например, таблицы или код)
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

def search_context(query, folder_path="", top_k=3):
    """Ищет текст в указанной папке. Если folder_path пустой — ищет везде."""
    search_dir = folder_path if folder_path else UPLOAD_FOLDER
    
    chunks = get_project_chunks(search_dir)
    if not chunks:
        return []

    # Если текста мало (до 20 кусков), отдаем ВСЁ содержимое без поиска
    if len(chunks) <= 20:
        return chunks

    def tokenize(text):
        return re.findall(r'[а-яА-ЯёЁa-zA-Z0-9]+', text.lower())

    tokenized_corpus = [tokenize(c["text"]) for c in chunks]
    
    if not any(tokenized_corpus):
        return chunks[:top_k]

    bm25 = BM25Okapi(tokenized_corpus)
    
    # Убираем стоп-слова (они не помогают поиску)
    stop_words = {"что", "как", "где", "в", "на", "и", "с", "по", "о", "об", "перескажи", "суть", "файл", "файла", "файле", "папка", "папке", "входит", "перечень", "обычно"}
    query_words = [w for w in tokenize(query) if w not in stop_words]
    
    # Если после очистки ничего не осталось, просто возвращаем первые куски
    if not query_words:
        return chunks[:top_k]
        
    # Ищем лучшие куски
    top_chunks_indices = bm25.get_top_n(query_words, range(len(chunks)), n=top_k)
    
    results = []
    for idx in top_chunks_indices:
        # Добавляем только те куски, где есть хоть какое-то совпадение
        if bm25.get_scores(query_words)[idx] > 0:
            results.append(chunks[idx])
        
    # Если поиск по словам не дал результатов, возвращаем первые 3 куска (чтобы ИИ хоть что-то увидел)
    if not results:
        return chunks[:top_k]
        
    return results