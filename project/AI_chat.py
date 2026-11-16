import uuid
import requests 
import os
from flask import Blueprint, render_template, request, jsonify
from gigachat import GigaChat
from gigachat.models import Chat, Messages, MessagesRole
from openai import OpenAI
from settings import get_config
from rag_engine import search_context # Импортируем наш поисковик

ai_chat_bp = Blueprint('ai_chat', __name__, template_folder='templates')

GIGACHAT_AUTH_KEY = "MDFhMWUzZDctYWU1ZS03YTYyLWI5MzAtYzIzMTk4OGMwNTc5OmEyMTQ4Yzg4LWFkNjQtNDA4OC1iNjRmLWY2MzFhNDVmZTgzMA=="
DEEPSEEK_API_KEY = "ВАШ_DEEPSEEK_КЛЮЧ"

UPLOAD_FOLDER = 'uploads'

# --- Функция для получения списка папок (для выпадающего списка) ---
def get_all_folders():
    folders = []
    if os.path.exists(UPLOAD_FOLDER):
        for root, dirs, files in os.walk(UPLOAD_FOLDER):
            for d in dirs:
                rel_path = os.path.relpath(os.path.join(root, d), UPLOAD_FOLDER).replace("\\", "/")
                folders.append(rel_path)
    return folders

# --- Генераторы ответов ---
def generate_gigachat_response(user_message: str, history: list, context: str) -> str:
    try:
        # 1. Получаем токен авторизации
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

        # 2. Узнаем, какие модели доступны
        chat_headers = {
            'Accept': 'application/json',
            'Authorization': f'Bearer {access_token}'
        }
        
        # Запрашиваем список моделей
        models_response = requests.get("https://gigachat.devices.sberbank.ru/api/v1/models", headers=chat_headers, verify=False)
        models_response.raise_for_status()
        available_models = models_response.json()
        
        # Берем первую доступную модель (обычно это GigaChat или GigaChat-Pro)
        # Или можно поискать конкретную, но для надежности возьмем первую
        model_id = available_models['data'][0]['id']

        # 3. Формируем запрос к чату
        chat_url = "https://gigachat.devices.sberbank.ru/api/v1/chat/completions"
        chat_headers['Content-Type'] = 'application/json'
        
        system_prompt = """Ты — полезный ИИ-ассистент системы TeamDocs AI. 
Твоя задача — отвечать на вопросы пользователя, опираясь ТОЛЬКО на предоставленный контекст из файлов.
КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНО использовать общие знания, если их нет в контексте. Не пиши "обычно", "как правило" и т.д.
Если в контексте нет прямого ответа, напиши: "В загруженных документах я не нашел ответа на этот вопрос".
СТРОГО ЗАПРЕЩЕНО придумывать имена файлов или папок. Отвечай только тем, что видишь."""

        if context:
            system_prompt += f"\n\n--- НАЧАЛО КОНТЕКСТА ИЗ ФАЙЛОВ ---\n{context}\n--- КОНЕЦ КОНТЕКСТА ---"
        else:
            system_prompt += "\n\n(Контекст из файлов не предоставлен или файлы пусты)."

        messages = [{"role": "system", "content": system_prompt}]
        
        if history:
            for msg in history:
                messages.append({"role": msg["role"], "content": msg["content"]})

        messages.append({"role": "user", "content": user_message})

        chat_payload = {
            "model": model_id, # Используем динамически полученное имя модели
            "messages": messages,
            "temperature": 0.7,
            "max_tokens": 1024
        }

        chat_response = requests.post(chat_url, headers=chat_headers, json=chat_payload, verify=False)
        chat_response.raise_for_status()
        
        result = chat_response.json()
        return result['choices'][0]['message']['content']

    except Exception as e:
        return f"Ошибка GigaChat: {str(e)}"

def generate_deepseek_response(user_message: str, history: list, context: str) -> str:
    try:
        client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url="https://api.deepseek.com")
        
        system_prompt = "Ты — полезный ИИ-ассистент системы TeamDocs AI."
        if context:
            system_prompt += f"\n\nИспользуй следующий контекст из документов пользователя для ответа:\n{context}\n\nЕсли ответа нет в контексте, скажи об этом."
            
        messages = [{"role": "system", "content": system_prompt}]
        if history:
            for msg in history:
                messages.append({"role": msg["role"], "content": msg["content"]})
        
        messages.append({"role": "user", "content": user_message})
        
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=messages,
            temperature=0.7,
            max_tokens=1024
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"Ошибка DeepSeek: {str(e)}"

@ai_chat_bp.route("/AI-Chat", methods=["GET", "POST"])
def chat():
    if request.method == "POST":
        data = request.get_json()
        user_message = data.get("message", "")
        history = data.get("history", [])
        selected_folder = data.get("folder", "") 
        
        if not user_message:
            return jsonify({"error": "Пустое сообщение"}), 400
            
        # --- RAG: Поиск контекста ---
        context = ""
        import os
        if selected_folder:
            folder_abs_path = os.path.join(UPLOAD_FOLDER, selected_folder)
            files_in_folder = []
            if os.path.exists(folder_abs_path):
                for root, _, files in os.walk(folder_abs_path):
                    for f in files:
                        if f.endswith(('.md', '.markdown', '.txt')):
                            files_in_folder.append(f)
            
            folder_structure = f"Список файлов в папке '{selected_folder}':\n" + "\n".join([f"- {f}" for f in files_in_folder]) + "\n\n"

            relevant_chunks = search_context(user_message, selected_folder, top_k=3)
            content_text = ""
            if relevant_chunks:
                content_text = "\n\nСодержимое файлов:\n" + "\n\n".join([f"[Из файла {c['source']}]:\n{c['text']}" for c in relevant_chunks])
            
            context = folder_structure + content_text
        else:
            # Если папка НЕ выбрана, формируем структуру всех проектов
            all_items = []
            if os.path.exists(UPLOAD_FOLDER):
                for root, dirs, files in os.walk(UPLOAD_FOLDER):
                    if root == UPLOAD_FOLDER:
                        for d in dirs:
                            all_items.append(f"📁 Папка: {d}")
                    for f in files:
                        if f.endswith(('.md', '.markdown', '.txt')):
                            rel_path = os.path.relpath(os.path.join(root, f), UPLOAD_FOLDER)
                            all_items.append(f"📄 Файл: {rel_path}")
            
            folder_structure = "Структура всех проектов:\n" + "\n".join(all_items) + "\n\n"
            content_text = ""
            
            # --- ПОИСК ФАЙЛА ПО ИМЕНИ В ВОПРОСЕ ---
            # Ищем, не упомянул ли пользователь конкретный файл (например, README)
            found_file_path = None
            for root, dirs, files in os.walk(UPLOAD_FOLDER):
                for f in files:
                    file_stem = os.path.splitext(f)[0].lower() # Например, "readme"
                    if file_stem and file_stem in user_message.lower():
                        found_file_path = os.path.join(root, f)
                        break
                if found_file_path: break
            
            # Если файл найден, читаем его ЦЕЛИКОМ
            if found_file_path:
                try:
                    with open(found_file_path, 'r', encoding='utf-8') as file:
                        file_content = file.read()
                    content_text = f"\n\n--- ПОЛНОЕ СОДЕРЖИМОЕ ФАЙЛА {os.path.basename(found_file_path)} ---\n{file_content}\n--- КОНЕЦ ФАЙЛА ---"
                except Exception as e:
                    content_text = f"\n\n(Ошибка чтения файла: {e})"
            
            # Если файл не нашли, отдаем первые 3000 символов каждого файла
            if not content_text:
                for root, dirs, files in os.walk(UPLOAD_FOLDER):
                    for f in files:
                        if f.endswith(('.md', '.markdown', '.txt')):
                            file_path = os.path.join(root, f)
                            try:
                                with open(file_path, 'r', encoding='utf-8') as file:
                                    file_content = file.read()
                                content_text += f"\n\n--- НАЧАЛО ФАЙЛА {f} ---\n{file_content[:3000]}\n--- КОНЕЦ ФАЙЛА {f} ---"
                            except: pass
            
            context = folder_structure + content_text

        # --- ГЕНЕРАЦИЯ ОТВЕТА (ВОТ ЭТОГО НЕ ХВАТАЛО) ---
        config = get_config()
        current_model = config.get("ai_model", "gigachat")
        
        if current_model == "deepseek":
            answer = generate_deepseek_response(user_message, history, context)
        else:
            answer = generate_gigachat_response(user_message, history, context)
            
        return jsonify({"response": answer, "model": current_model})

    # GET-запрос: показываем страницу
    config = get_config()
    
    # --- ЗАГРУЗКА ИСТОРИИ ЧАТА ---
    load_chat_id = request.args.get("load")
    loaded_chat_messages = None
    loaded_chat_id = None
    
    if load_chat_id:
        import json
        history_file = os.path.join('chat_history', f"{load_chat_id}.json")
        if os.path.exists(history_file):
            try:
                with open(history_file, 'r', encoding='utf-8') as f:
                    chat_data = json.load(f)
                    loaded_chat_messages = chat_data.get("messages", [])
                    loaded_chat_id = load_chat_id
            except Exception as e:
                print(f"Ошибка загрузки истории: {e}")

    return render_template(
        "index.html", 
        title="AI-чат", 
        current_model=config.get("ai_model", "gigachat"),
        project_folders=get_all_folders(),
        loaded_chat_messages=loaded_chat_messages, # Передаем сообщения
        loaded_chat_id=loaded_chat_id              # Передаем ID
    )