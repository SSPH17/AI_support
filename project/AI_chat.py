import uuid
import requests 
import os
import json
from flask import Blueprint, render_template, request, jsonify
from openai import OpenAI
from settings import get_config
from rag_engine import search_context, search_in_file

# Отключаем предупреждения SSL для GigaChat
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

ai_chat_bp = Blueprint('ai_chat', __name__, template_folder='templates')

GIGACHAT_AUTH_KEY = "MDFhMWUzZDctYWU1ZS03YTYyLWI5MzAtYzIzMTk4OGMwNTc5OmEyMTQ4Yzg4LWFkNjQtNDA4OC1iNjRmLWY2MzFhNDVmZTgzMA=="
DEEPSEEK_API_KEY = "ВАШ_DEEPSEEK_КЛЮЧ" # Не забудьте вставить ключ

UPLOAD_FOLDER = 'uploads'

# --- Вспомогательные функции ---
def get_all_folders():
    folders = []
    if os.path.exists(UPLOAD_FOLDER):
        for root, dirs, files in os.walk(UPLOAD_FOLDER):
            for d in dirs:
                rel_path = os.path.relpath(os.path.join(root, d), UPLOAD_FOLDER).replace("\\", "/")
                folders.append(rel_path)
    return folders

def get_all_files():
    files = []
    if os.path.exists(UPLOAD_FOLDER):
        for root, dirs, file_names in os.walk(UPLOAD_FOLDER):
            for f in file_names:
                if f.endswith(('.md', '.markdown', '.txt')):
                    full_path = os.path.join(root, f)
                    rel = os.path.relpath(full_path, UPLOAD_FOLDER).replace("\\", "/")
                    
                    size_bytes = os.path.getsize(full_path)
                    if size_bytes < 1024:
                        size_str = f"{size_bytes} Б"
                    else:
                        size_str = f"{size_bytes / 1024:.1f} КБ"

                    if "/" not in rel:
                        files.append(f"{rel} (в корне, без папок, размер: {size_str})")
                    else:
                        files.append(f"{rel} (размер: {size_str})")
    return sorted(files)

# --- Единый системный промпт ---
def build_system_prompt(context: str, folder_list_str: str = "", file_list_str: str = "", files_count: int = 0) -> str:
    ctx = context if context else "(Контекст из файлов не предоставлен или файлы пусты)."
    files_info = f"В системе загружено файлов: {files_count}.\nСписок файлов:\n{file_list_str}" if file_list_str else "Файлов нет."
    
    folders_info = f"СПИСОК РЕАЛЬНЫХ ПАПОК (ПРОЕКТОВ) В СИСТЕМЕ:\n{folder_list_str}" if folder_list_str else "Папок нет."

    return (
        "Ты — умный и дружелюбный ИИ-ассистент системы TeamDocs AI. Твоя задача — помогать пользователю.\n\n"
        "ПРАВИЛА ОБЩЕНИЯ:\n"
        "1. Ты можешь свободно общаться, здороваться, отвечать на общие вопросы и делать логические выводы.\n"
        "2. Если пользователь задаёт вопрос ФАКТИЧЕСКОГО характера (что написано в документе, какие есть функции и т.д.), ты ОБЯЗАН отвечать ТОЛЬКО на основе предоставленного КОНТЕКСТА. Не придумывай факты о проекте.\n"
        "3. ВАЖНО: Если пользователь спрашивает о структуре (какие есть папки, проекты, сколько файлов), используй блок «СПИСОК РЕАЛЬНЫХ ПАПОК» и «ИНФОРМАЦИЯ О ФАЙЛАХ». В этом случае НЕ НУЖНО цитировать содержимое файлов и ставить теги [[SOURCE]], если только пользователь не просил найти упоминание об этом в документах.\n"
        "4. Если в документах нет ответа на фактический вопрос, так и скажи: «В загруженных документах этой информации нет, но...» и можешь дать общий совет.\n"
        "5. ОБЯЗАТЕЛЬНОЕ ПРАВИЛО ДЛЯ ИСТОЧНИКОВ: Если ты берешь информацию из конкретного файла (из блока КОНТЕКСТ), ты должен в конце ответа указать источник в строго определенном формате:\n"
        "[[SOURCE: название_файла_с_расширением]]\n"
        "Например: [[SOURCE: README.md]] или [[SOURCE: тест/Стехтин.txt]]\n"
        "Не пиши слово 'Источник' просто текстом, используй только этот тег.\n\n"
        f"--- ИНФОРМАЦИЯ О ФАЙЛАХ ---\n{files_info}\n\n"
        f"--- {folders_info} ---\n\n"
        f"--- ТЕКСТОВЫЙ КОНТЕКСТ ИЗ ФАЙЛОВ ---\n{ctx}\n--- КОНЕЦ КОНТЕКСТА ---"
    )

# --- Генераторы ответов ---

def generate_gigachat_response(user_message: str, history: list, context: str, file_list_str: str, files_count: int, folder_list_str: str) -> str:
    try:
        auth_url = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"
        headers = {
            'Content-Type': 'application/x-www-form-urlencoded',
            'Accept': 'application/json',
            'RqUID': str(uuid.uuid4()),
            'Authorization': f'Basic {GIGACHAT_AUTH_KEY}'
        }
        payload = {'scope': 'GIGACHAT_API_PERS'}
        
        auth_response = requests.post(auth_url, headers=headers, data=payload, verify=False)
        auth_response.raise_for_status()
        access_token = auth_response.json()['access_token']

        chat_headers = {'Accept': 'application/json', 'Authorization': f'Bearer {access_token}'}
        models_response = requests.get("https://gigachat.devices.sberbank.ru/api/v1/models", headers=chat_headers, verify=False)
        model_id = models_response.json()['data'][0]['id']

        chat_url = "https://gigachat.devices.sberbank.ru/api/v1/chat/completions"
        chat_headers['Content-Type'] = 'application/json'
        
        system_prompt = build_system_prompt(context, folder_list_str, file_list_str, files_count)
        messages = [{"role": "system", "content": system_prompt}]
        
        if history:
            for msg in history:
                messages.append({"role": msg["role"], "content": msg["content"]})

        messages.append({"role": "user", "content": user_message})

        chat_payload = {
            "model": model_id,
            "messages": messages,
            "temperature": 0.6,
            "max_tokens": 1500
        }

        chat_response = requests.post(chat_url, headers=chat_headers, json=chat_payload, verify=False)
        chat_response.raise_for_status()
        return chat_response.json()['choices'][0]['message']['content']

    except Exception as e:
        return f"Ошибка GigaChat: {str(e)}"

def generate_deepseek_response(user_message: str, history: list, context: str, file_list_str: str, files_count: int, folder_list_str: str) -> str:
    try:
        client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url="https://api.deepseek.com")
        system_prompt = build_system_prompt(context, folder_list_str, file_list_str, files_count)
        
        messages = [{"role": "system", "content": system_prompt}]
        if history:
            for msg in history:
                messages.append({"role": msg["role"], "content": msg["content"]})
        
        messages.append({"role": "user", "content": user_message})
        
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=messages,
            temperature=0.6,
            max_tokens=1500
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"Ошибка DeepSeek: {str(e)}"


# --- Маршрут ---
@ai_chat_bp.route("/AI-Chat", methods=["GET", "POST"])
def chat():
    if request.method == "POST":
        try:
            data = request.get_json()
            if not data:
                return jsonify({"error": "Неверный формат запроса"}), 400
                
            user_message = data.get("message", "")
            history = data.get("history", [])
            
            selected_folder = data.get("folder", "") 
            selected_file = data.get("file", "")   
            
            if not user_message:
                return jsonify({"error": "Пустое сообщение"}), 400
                
            # --- Сбор контекста (RAG) ---
            context = ""
            
            if selected_file:
                # Режим 1: Выбран конкретный файл
                file_abs = os.path.join(UPLOAD_FOLDER, selected_file)
                if os.path.isfile(file_abs):
                    try:
                        with open(file_abs, 'r', encoding='utf-8') as f:
                            full_text = f.read()
                    except UnicodeDecodeError:
                        with open(file_abs, 'r', encoding='cp1251', errors='replace') as f:
                            full_text = f.read()
                    
                    if len(full_text) <= 15000 or any(w in user_message.lower() for w in ["прочти", "прочитай", "покажи", "выведи", "содержимое"]):
                        context = f"Источник: файл «{selected_file}»\n\n--- ПОЛНОЕ СОДЕРЖИМОЕ ---\n{full_text}\n--- КОНЕЦ ---"
                    else:
                        chunks = search_in_file(user_message, selected_file, top_k=5)
                        content_text = "\n\n".join([f"[Фрагмент]:\n{c['text']}" for c in chunks])
                        context = f"Источник: файл «{selected_file}»\n\n--- РЕЛЕВАНТНЫЕ ФРАГМЕНТЫ ---\n{content_text}\n--- КОНЕЦ ---"
            
            elif selected_folder:
                # Режим 2: Выбрана папка
                folder_abs_path = os.path.join(UPLOAD_FOLDER, selected_folder)
                files_in_folder = []
                if os.path.exists(folder_abs_path):
                    for root, _, files in os.walk(folder_abs_path):
                        for f in files:
                            if f.endswith(('.md', '.markdown', '.txt')):
                                files_in_folder.append(f)

                folder_structure = f"Файлы в папке '{selected_folder}':\n" + "\n".join([f"- {f}" for f in files_in_folder]) + "\n\n"
                relevant_chunks = search_context(user_message, selected_folder, top_k=5)
                content_text = ""
                if relevant_chunks:
                    content_text = "\n\nСодержимое файлов:\n" + "\n\n".join([f"[Из файла {c['source']}]:\n{c['text']}" for c in relevant_chunks])
                context = folder_structure + content_text
            
            else:
                # Режим 3: Поиск по всем файлам
                all_items = []
                found_file_path = None
                found_file_name = None
                
                if os.path.exists(UPLOAD_FOLDER):
                    for root, dirs, files in os.walk(UPLOAD_FOLDER):
                        if root == UPLOAD_FOLDER:
                            for d in dirs:
                                all_items.append(f"📁 Папка: {d}")
                        for f in files:
                            if f.endswith(('.md', '.markdown', '.txt')):
                                rel_path = os.path.relpath(os.path.join(root, f), UPLOAD_FOLDER).replace("\\", "/")
                                all_items.append(f"📄 Файл: {rel_path}")
                                
                                file_stem = os.path.splitext(f)[0].lower()
                                if len(file_stem) >= 4 and file_stem in user_message.lower():
                                    found_file_path = os.path.join(root, f)
                                    found_file_name = f
                
                folder_structure = "Структура всех проектов:\n" + "\n".join(all_items) + "\n\n"
                content_text = ""
                
                if found_file_path:
                    try:
                        with open(found_file_path, 'r', encoding='utf-8') as f:
                            full_text = f.read()
                        content_text = f"\n\n--- ПОЛНОЕ СОДЕРЖИМОЕ ФАЙЛА {found_file_name} ---\n{full_text}\n--- КОНЕЦ ---"
                    except Exception as e:
                        content_text = f"\n\n(Ошибка чтения файла: {e})"
                else:
                    relevant_chunks = search_context(user_message, "", top_k=6)
                    if relevant_chunks:
                        content_text = "\n\nНаиболее релевантные фрагменты:\n" + "\n\n".join([f"[Из файла {c['source']}]:\n{c['text']}" for c in relevant_chunks])
                
                context = folder_structure + content_text

            # Формируем списки для промпта
            all_files_list = get_all_files()
            file_list_str = "\n".join([f"- {f}" for f in all_files_list])
            files_count = len(all_files_list)

            all_folders = get_all_folders()
            folder_list_str = "\n".join([f"- {f}" for f in all_folders]) if all_folders else ""

            # --- Генерация ---
            config = get_config()
            current_model = config.get("ai_model", "gigachat")
            
            if current_model == "deepseek":
                answer = generate_deepseek_response(user_message, history, context, file_list_str, files_count, folder_list_str)
            else:
                answer = generate_gigachat_response(user_message, history, context, file_list_str, files_count, folder_list_str)
                
            return jsonify({"response": answer, "model": current_model})
            
        except Exception as e:
            print(f"КРИТИЧЕСКАЯ ОШИБКА В ЧАТЕ: {e}")
            return jsonify({"error": str(e)}), 500

    # --- GET-запрос (Отрисовка страницы) ---
    config = get_config()
    
    load_chat_id = request.args.get("load")
    loaded_chat_messages = None
    loaded_chat_id = None
    
    if load_chat_id:
        history_file = os.path.join('chat_history', f"{load_chat_id}.json")
        if os.path.exists(history_file):
            try:
                with open(history_file, 'r', encoding='utf-8') as f:
                    chat_data = json.load(f)
                    loaded_chat_messages = chat_data.get("messages", [])
                    loaded_chat_id = chat_data.get("id") or load_chat_id
            except Exception as e:
                print(f"Ошибка загрузки истории: {e}")

    return render_template(
        "index.html", 
        title="AI-чат", 
        current_model=config.get("ai_model", "gigachat"),
        project_folders=get_all_folders(),
        project_files=get_all_files(),
        loaded_chat_messages=loaded_chat_messages,
        loaded_chat_id=loaded_chat_id
    )