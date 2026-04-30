from flask import Flask, render_template, request, redirect, session, g
import sqlite3
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = "secret-key"


# =======================
# DB管理（重要改善）
# =======================
DATABASE = "tasks.db"

def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DATABASE)
        g.db.row_factory = sqlite3.Row  # ← dictみたいに扱える
    return g.db

@app.teardown_appcontext
def close_db(exception):
    db = g.pop("db", None)
    if db:
        db.close()


# =======================
# DB初期化
# =======================
def init_db():
    db = get_db()
    cursor = db.cursor()

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE,
        password TEXT
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS tasks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        title TEXT,
        done INTEGER,
        deadline TEXT,
        position INTEGER
    )
    """)

    db.commit()

with app.app_context():
    init_db()


# =======================
# ログインチェック
# =======================
def require_login():
    if "user_id" not in session:
        return False
    return True


# =======================
# メイン
# =======================
@app.route("/", methods=["GET", "POST"])
def index():
    if not require_login():
        return redirect("/login")

    db = get_db()
    user_id = session["user_id"]

    # ユーザー名
    user = db.execute(
        "SELECT username FROM users WHERE id=?",
        (user_id,)
    ).fetchone()

    username = user["username"] if user else "user"

    # 追加
    if request.method == "POST":
        task = request.form.get("task", "").strip()
        deadline = request.form.get("deadline")

        if task:
            # 最大position取得
            row = db.execute(
                "SELECT MAX(position) as max_pos FROM tasks WHERE user_id=?",
                (user_id,)
            ).fetchone()

            new_pos = (row["max_pos"] + 1) if row["max_pos"] is not None else 0

            db.execute(
                "INSERT INTO tasks (user_id, title, done, deadline, position) VALUES (?, ?, ?, ?, ?)",
                (user_id, task, 0, deadline, new_pos)
            )
            db.commit()

        return redirect("/")

    # 並び替え
    sort = request.args.get("sort")

    if sort == "new":
        rows = db.execute("""
            SELECT id, title, done, deadline
            FROM tasks
            WHERE user_id=?
            ORDER BY position ASC
        """, (user_id,)).fetchall()
    else:
        rows = db.execute("""
            SELECT id, title, done, deadline
            FROM tasks
            WHERE user_id=?
            ORDER BY
                CASE WHEN deadline IS NULL OR deadline='' THEN 1 ELSE 0 END,
                deadline ASC,
                id DESC
        """, (user_id,)).fetchall()

    today = datetime.today().strftime("%Y-%m-%d")

    tasks = []
    for r in rows:
        tasks.append({
            "id": r["id"],
            "title": r["title"],
            "done": bool(r["done"]),
            "deadline": r["deadline"],
            "overdue": r["deadline"] and r["deadline"] < today
        })

    return render_template("index.html", tasks=tasks, username=username)


# =======================
# 完了切替
# =======================
@app.route("/toggle/<int:id>")
def toggle(id):
    if not require_login():
        return redirect("/login")

    db = get_db()
    user_id = session["user_id"]

    row = db.execute(
        "SELECT done FROM tasks WHERE id=? AND user_id=?",
        (id, user_id)
    ).fetchone()

    if row:
        db.execute(
            "UPDATE tasks SET done=? WHERE id=? AND user_id=?",
            (1 - row["done"], id, user_id)
        )
        db.commit()

    return redirect("/")


# =======================
# 削除
# =======================
@app.route("/delete/<int:id>")
def delete(id):
    if not require_login():
        return redirect("/login")

    db = get_db()
    user_id = session["user_id"]

    db.execute(
        "DELETE FROM tasks WHERE id=? AND user_id=?",
        (id, user_id)
    )
    db.commit()

    return redirect("/")


# =======================
# 編集
# =======================
@app.route("/edit/<int:id>", methods=["POST"])
def edit(id):
    if not require_login():
        return redirect("/login")

    db = get_db()
    user_id = session["user_id"]

    task = request.form.get("task", "").strip()
    deadline = request.form.get("deadline")

    if task:
        db.execute("""
            UPDATE tasks
            SET title=?, deadline=?
            WHERE id=? AND user_id=?
        """, (task, deadline, id, user_id))
        db.commit()

    return redirect("/")


# =======================
# register
# =======================
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        if not username or not password:
            return redirect("/register")

        hashed = generate_password_hash(password)

        db = get_db()

        try:
            db.execute(
                "INSERT INTO users (username, password) VALUES (?, ?)",
                (username, hashed)
            )
            db.commit()
        except:
            return redirect("/register")

        return redirect("/login")

    return render_template("register.html")


# =======================
# login
# =======================
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")

        db = get_db()

        user = db.execute(
            "SELECT * FROM users WHERE username=?",
            (username,)
        ).fetchone()

        if user and check_password_hash(user["password"], password):
            session["user_id"] = user["id"]
            return redirect("/")

    return render_template("login.html")


# =======================
# logout
# =======================
@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")


# =======================
# 起動
# =======================
if __name__ == "__main__":
    app.run(debug=True)


with app.app_context():
    db = get_db()
    try:
        db.execute("ALTER TABLE tasks ADD COLUMN position INTEGER")
        db.commit()
    except:
        pass
    
from flask import jsonify

@app.route("/reorder", methods=["POST"])
def reorder():
    if not require_login():
        return jsonify({"status": "error"})

    db = get_db()
    user_id = session["user_id"]

    data = request.get_json()
    order = data.get("order", [])

    for index, task_id in enumerate(order):
        db.execute(
            "UPDATE tasks SET position=? WHERE id=? AND user_id=?",
            (index, task_id, user_id)
        )

    db.commit()

    return jsonify({"status": "ok"})