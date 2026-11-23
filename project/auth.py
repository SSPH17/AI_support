import os
import json
import functools
from flask import (
    Blueprint, session, redirect, url_for, flash,
    request, jsonify, render_template
)

# ============================================================
#  КОНСТАНТЫ
# ============================================================
USERS_FILE = 'users.json'
ACL_FILE = 'folder_acl.json'

auth_bp = Blueprint('auth', __name__, template_folder='templates')

# ============================================================
#  ПОЛЬЗОВАТЕЛИ
# ============================================================
def get_users():
    if os.path.exists(USERS_FILE):
        with open(USERS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    default = {"admin": {"role": "admin", "password": "admin"}}
    with open(USERS_FILE, 'w', encoding='utf-8') as f:
        json.dump(default, f, ensure_ascii=False, indent=2)
    return default

def save_users(users):
    with open(USERS_FILE, 'w', encoding='utf-8') as f:
        json.dump(users, f, ensure_ascii=False, indent=2)

# ============================================================
#  ACL НА ПАПКИ
# ============================================================
# {"folder/rel/path": {"owner": "admin", "editors": [], "viewers": []}}
def get_acl():
    if os.path.exists(ACL_FILE):
        with open(ACL_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}

def save_acl(acl):
    with open(ACL_FILE, 'w', encoding='utf-8') as f:
        json.dump(acl, f, ensure_ascii=False, indent=2)

def set_folder_owner(folder_rel_path, username):
    acl = get_acl()
    acl.setdefault(folder_rel_path, {})
    acl[folder_rel_path]["owner"] = username
    acl[folder_rel_path].setdefault("editors", [])
    acl[folder_rel_path].setdefault("viewers", [])
    save_acl(acl)

def grant_access(folder_rel_path, username, level="viewer"):
    acl = get_acl()
    entry = acl.setdefault(folder_rel_path, {"owner": None, "editors": [], "viewers": []})
    if level == "editor" and username not in entry["editors"]:
        entry["editors"].append(username)
        if username in entry["viewers"]:
            entry["viewers"].remove(username)
    elif level == "viewer" and username not in entry["viewers"] and username not in entry["editors"]:
        entry["viewers"].append(username)
    save_acl(acl)

def revoke_access(folder_rel_path, username):
    acl = get_acl()
    entry = acl.get(folder_rel_path)
    if not entry:
        return
    for key in ("editors", "viewers"):
        if username in entry.get(key, []):
            entry[key].remove(username)
    save_acl(acl)

def delete_folder_acl(folder_rel_path):
    prefix = folder_rel_path.rstrip("/") + "/"
    acl = get_acl()
    updated = {k: v for k, v in acl.items() if k != folder_rel_path and not k.startswith(prefix)}
    if len(updated) != len(acl):
        save_acl(updated)

# ============================================================
#  ПРОВЕРКА ПРАВ
# ============================================================
def get_user_role(username):
    users = get_users()
    return users.get(username, {}).get("role", "viewer")

def get_folder_permission(username, folder_rel_path):
    """Возвращает 'owner' | 'editor' | 'viewer' | None, наследуя от предков."""
    if not username:
        return None
    if get_user_role(username) == "admin":
        return "owner"

    acl = get_acl()
    parts = folder_rel_path.strip("/").split("/") if folder_rel_path else []
    candidates = ["/".join(parts[:i]) for i in range(len(parts), -1, -1)]
    for path in candidates:
        entry = acl.get(path)
        if not entry:
            continue
        if entry.get("owner") == username:
            return "owner"
        if username in entry.get("editors", []):
            return "editor"
        if username in entry.get("viewers", []):
            return "viewer"
    return None

def can_read(username, folder_rel_path):
    return get_folder_permission(username, folder_rel_path) in ("owner", "editor", "viewer")

def can_write(username, folder_rel_path):
    return get_folder_permission(username, folder_rel_path) in ("owner", "editor")

def can_delete(username, folder_rel_path):
    return get_folder_permission(username, folder_rel_path) == "owner"

# ============================================================
#  ТЕКУЩИЙ ПОЛЬЗОВАТЕЛЬ + ДЕКОРАТОР
# ============================================================
def current_user():
    return session.get("user")

def login_required(view):
    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        if not current_user():
            if request.is_json or request.path.startswith("/api/"):
                return jsonify({"error": "Требуется вход"}), 401
            return redirect(url_for("auth.login", next=request.path))
        return view(*args, **kwargs)
    return wrapped

# ============================================================
#  МАРШРУТЫ (Blueprint)
# ============================================================
@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        users = get_users()
        if username in users and users[username].get("password") == password:
            session["user"] = username
            flash(f"Добро пожаловать, {username}!", "success")
            return redirect(request.args.get("next") or url_for("home"))
        flash("Неверный логин или пароль.", "error")
    return render_template("index.html", title="Вход", login_page=True)

@auth_bp.route("/logout")
def logout():
    session.pop("user", None)
    flash("Вы вышли из системы.", "success")
    return redirect(url_for("home"))