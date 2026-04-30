from flask import Flask, render_template, request, redirect, session
import sqlite3
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = "secret-key"


# -----------------------
# DB初期化
# -----------------------
def init_db():
    conn = sqlite3.connect("tasks.db")
    cursor = conn.cursor()

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
        deadline TEXT
    )
    """)

    conn.commit()
    conn.close()

init_db()


# -----------------------
# メイン
# -----------------------
@app.route("/", methods=["GET", "POST"])
def index():
    if "user_id" not in session:
        return redirect("/login")

    user_id = session["user_id"]

    conn = sqlite3.connect("tasks.db")
    cursor = conn.cursor()

    # ユーザー名
    cursor.execute("SELECT username FROM users WHERE id=?", (user_id,))
    user = cursor.fetchone()
    username = user[0] if user else "user"

    # 追加
    if request.method == "POST":
        task = request.form.get("task")
        deadline = request.form.get("deadline")

        if task:
            cursor.execute(
                "INSERT INTO tasks (user_id, title, done, deadline) VALUES (?, ?, ?, ?)",
                (user_id, task, 0, deadline)
            )
            conn.commit()

        return redirect("/")

    # 並び替え
    sort = request.args.get("sort")

    if sort == "new":
        cursor.execute("""
        SELECT * FROM tasks
        WHERE user_id=?
        ORDER BY id DESC
        """, (user_id,))
    else:
        cursor.execute("""
        SELECT * FROM tasks
        WHERE user_id=?
        ORDER BY
            CASE WHEN deadline IS NULL OR deadline='' THEN 1 ELSE 0 END,
            deadline ASC,
            id DESC
        """, (user_id,))

    rows = cursor.fetchall()
    conn.close()

    today = datetime.today().strftime("%Y-%m-%d")

    tasks = []
    for row in rows:
        deadline = row[4]

        tasks.append({
            "id": row[0],
            "title": row[2],
            "done": bool(row[3]),
            "deadline": deadline,
            "overdue": deadline and deadline < today
        })

    return render_template("index.html", tasks=tasks, username=username)


# -----------------------
# 完了切替
# -----------------------
@app.route("/toggle/<int:id>")
def toggle(id):
    if "user_id" not in session:
        return redirect("/login")

    conn = sqlite3.connect("tasks.db")
    cursor = conn.cursor()

    cursor.execute("SELECT done FROM tasks WHERE id=?", (id,))
    row = cursor.fetchone()

    if row:
        cursor.execute(
            "UPDATE tasks SET done=? WHERE id=?",
            (1 - row[0], id)
        )

    conn.commit()
    conn.close()
    return redirect("/")


# -----------------------
# 削除
# -----------------------
@app.route("/delete/<int:id>")
def delete(id):
    if "user_id" not in session:
        return redirect("/login")

    conn = sqlite3.connect("tasks.db")
    cursor = conn.cursor()

    cursor.execute("DELETE FROM tasks WHERE id=?", (id,))

    conn.commit()
    conn.close()
    return redirect("/")


# -----------------------
# 編集
# -----------------------
@app.route("/edit/<int:id>", methods=["GET", "POST"])
def edit(id):
    if "user_id" not in session:
        return redirect("/login")

    conn = sqlite3.connect("tasks.db")
    cursor = conn.cursor()

    if request.method == "POST":
        task = request.form.get("task")
        deadline = request.form.get("deadline")

        cursor.execute(
            "UPDATE tasks SET title=?, deadline=? WHERE id=?",
            (task, deadline, id)
        )

        conn.commit()
        conn.close()
        return redirect("/")

    cursor.execute("SELECT * FROM tasks WHERE id=?", (id,))
    task = cursor.fetchone()
    conn.close()

    return render_template("edit.html", task=task)


# -----------------------
# register
# -----------------------
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username")
        password = generate_password_hash(request.form.get("password"))

        conn = sqlite3.connect("tasks.db")
        cursor = conn.cursor()

        try:
            cursor.execute(
                "INSERT INTO users (username, password) VALUES (?, ?)",
                (username, password)
            )
            conn.commit()
        except:
            pass

        conn.close()
        return redirect("/login")

    return render_template("register.html")


# -----------------------
# login
# -----------------------
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")

        conn = sqlite3.connect("tasks.db")
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM users WHERE username=?", (username,))
        user = cursor.fetchone()
        conn.close()

        if user and check_password_hash(user[2], password):
            session["user_id"] = user[0]
            return redirect("/")

    return render_template("login.html")


# -----------------------
# logout
# -----------------------
@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")


if __name__ == "__main__":
    app.run(debug=True)