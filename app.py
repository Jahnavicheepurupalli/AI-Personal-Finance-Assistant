import os
import json
import re
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
from database import get_db_connection, init_db
from dotenv import load_dotenv
from groq import Groq

# ---------------- ENV ----------------
load_dotenv()

groq_api_key = os.getenv("GROQ_API_KEY")
client = Groq(api_key=groq_api_key) if groq_api_key else None

# ---------------- APP ----------------
app = Flask(__name__)
app.secret_key = "super_secret_finance_key"

# ---------------- DATABASE INIT ----------------
if not os.path.exists("finance.db"):
    init_db()

# ---------------- PASSWORD VALIDATION ----------------
def validate_password(password):
    if len(password) < 8:
        return False, "Password must be at least 8 characters long."
    if not re.search(r"[!@#$%^&*()]", password):
        return False, "Password must contain at least one special character."
    return True, ""

# ---------------- HOME ----------------
@app.route("/")
def index():
    if "user_id" in session:
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))

# ---------------- LOGIN ----------------
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        login_id = request.form["login_id"]
        password = request.form["password"]

        conn = get_db_connection()
        user = conn.execute(
            "SELECT * FROM users WHERE email=? OR name=?",
            (login_id, login_id),
        ).fetchone()
        conn.close()

        if user and check_password_hash(user["password"], password):
            session["user_id"] = user["id"]
            session["user_name"] = user["name"]
            return redirect(url_for("dashboard"))
        else:
            flash("Invalid email or password", "error")

    return render_template("login.html")

# ---------------- SIGNUP ----------------
@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":

        name = request.form["name"]
        email = request.form["email"]
        password = request.form["password"]

        valid, msg = validate_password(password)
        if not valid:
            flash(msg, "error")
            return render_template("signup.html")

        hashed_pw = generate_password_hash(password)

        conn = get_db_connection()
        try:
            conn.execute(
                "INSERT INTO users (name,email,password) VALUES (?,?,?)",
                (name, email, hashed_pw),
            )
            conn.commit()
            flash("Account created successfully", "success")
            return redirect(url_for("login"))

        except Exception as e:
            print(e)
            flash("Email already exists", "error")

        finally:
            conn.close()

    return render_template("signup.html")

# ---------------- FORGOT PASSWORD ----------------
@app.route("/forgot-password", methods=["GET","POST"])
def forgot_password():

    if request.method == "POST":

        email = request.form["email"]

        conn = get_db_connection()
        user = conn.execute(
            "SELECT * FROM users WHERE email=?",
            (email,)
        ).fetchone()
        conn.close()

        if user:
            session["reset_email"] = email
            return redirect(url_for("reset_password"))
        else:
            flash("Email not found", "error")

    return render_template("forgot_password.html")

# ---------------- RESET PASSWORD ----------------
@app.route("/reset-password", methods=["GET","POST"])
def reset_password():

    if "reset_email" not in session:
        return redirect(url_for("forgot_password"))

    if request.method == "POST":

        password = request.form["password"]
        confirm_password = request.form["confirm_password"]

        if password != confirm_password:
            flash("Passwords do not match", "error")
            return render_template("reset_password.html")

        valid, msg = validate_password(password)
        if not valid:
            flash(msg, "error")
            return render_template("reset_password.html")

        hashed_pw = generate_password_hash(password)
        email = session["reset_email"]

        conn = get_db_connection()
        conn.execute("UPDATE users SET password=? WHERE email=?", (hashed_pw,email))
        conn.commit()
        conn.close()

        session.pop("reset_email", None)

        flash("Password reset successful", "success")

        return redirect(url_for("login"))

    return render_template("reset_password.html")

# ---------------- LOGOUT ----------------
@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

# ---------------- PROFILE UPDATE ----------------
@app.route("/update-profile", methods=["GET", "POST"])
def update_profile():

    if "user_id" not in session:
        return redirect(url_for("login"))

    if request.method == "POST":
        name = request.form.get("name")
        new_password = request.form.get("new_password")

        conn = get_db_connection()

        if name:
            conn.execute(
                "UPDATE users SET name=? WHERE id=?",
                (name, session["user_id"])
            )
            session["user_name"] = name

        if new_password:

            valid, msg = validate_password(new_password)

            if not valid:
                flash(msg, "error")
                conn.close()
                return redirect(url_for("update_profile"))

            hashed_pw = generate_password_hash(new_password)

            conn.execute(
                "UPDATE users SET password=? WHERE id=?",
                (hashed_pw, session["user_id"])
            )

        conn.commit()
        conn.close()

        flash("Profile updated successfully", "success")

        return redirect(url_for("update_profile"))

    return render_template("update_profile.html")

# ---------------- DASHBOARD ----------------
@app.route("/dashboard")
def dashboard():

    if "user_id" not in session:
        return redirect(url_for("login"))

    conn = get_db_connection()

    transactions = conn.execute(
        "SELECT * FROM transactions WHERE user_id=? ORDER BY date DESC",
        (session["user_id"],)
    ).fetchall()

    # Check budgets
    budgets = conn.execute(
        "SELECT category, amount FROM budgets WHERE user_id=?",
        (session["user_id"],)
    ).fetchall()

    conn.close()

    budget_dict = {b["category"]: b["amount"] for b in budgets}
    
    import datetime
    current_month = datetime.datetime.now().strftime("%Y-%m")
    
    category_spending = {}
    for t in transactions:
        if t["type"] == "Expense" and t["date"].startswith(current_month):
            category_spending[t["category"]] = category_spending.get(t["category"], 0) + t["amount"]
            
    budget_alerts = []
    for category, limit in budget_dict.items():
        spent = category_spending.get(category, 0)
        if spent > limit:
            budget_alerts.append({"category": category, "limit": limit, "spent": spent})

    income = sum(t["amount"] for t in transactions if t["type"] == "Income")
    expenses = sum(t["amount"] for t in transactions if t["type"] == "Expense")

    balance = income - expenses

    return render_template(
        "dashboard.html",
        balance=balance,
        income=income,
        expenses=expenses,
        transactions=transactions[:5],
        budget_alerts=budget_alerts,
        budgets=budget_dict
    )

# ---------------- ADD TRANSACTION ----------------
@app.route("/add-transaction", methods=["GET","POST"])
def add_transaction():

    if "user_id" not in session:
        return redirect(url_for("login"))

    if request.method == "POST":

        type_ = request.form["type"]
        category = request.form["category"]
        amount = float(request.form["amount"])
        date = request.form["date"]

        conn = get_db_connection()

        conn.execute(
            "INSERT INTO transactions (user_id,type,category,amount,date) VALUES (?,?,?,?,?)",
            (session["user_id"], type_, category, amount, date)
        )

        conn.commit()
        conn.close()

        flash("Transaction added", "success")

        return redirect(url_for("dashboard"))

    return render_template("add_transaction.html")

# ---------------- HISTORY ----------------
@app.route("/history")
def history():

    if "user_id" not in session:
        return redirect(url_for("login"))

    conn = get_db_connection()

    transactions = conn.execute(
        "SELECT * FROM transactions WHERE user_id=? ORDER BY date DESC",
        (session["user_id"],)
    ).fetchall()

    conn.close()

    return render_template("history.html", transactions=transactions)

# ---------------- EDIT TRANSACTION ----------------
@app.route("/edit-transaction/<int:id>", methods=["GET", "POST"])
def edit_transaction(id):
    if "user_id" not in session:
        return redirect(url_for("login"))

    conn = get_db_connection()
    transaction = conn.execute(
        "SELECT * FROM transactions WHERE id=? AND user_id=?",
        (id, session["user_id"])
    ).fetchone()

    if not transaction:
        flash("Transaction not found", "error")
        conn.close()
        return redirect(url_for("history"))

    if request.method == "POST":
        type_ = request.form["type"]
        category = request.form["category"]
        amount = float(request.form["amount"])
        date = request.form["date"]

        conn.execute(
            "UPDATE transactions SET type=?, category=?, amount=?, date=? WHERE id=? AND user_id=?",
            (type_, category, amount, date, id, session["user_id"])
        )
        conn.commit()
        conn.close()
        flash("Transaction updated successfully", "success")
        return redirect(url_for("history"))

    conn.close()
    return render_template("edit_transaction.html", transaction=transaction)

# ---------------- DELETE TRANSACTION ----------------
@app.route("/delete-transaction/<int:id>", methods=["POST"])
def delete_transaction(id):

    if "user_id" not in session:
        return redirect(url_for("login"))

    conn = get_db_connection()

    conn.execute(
        "DELETE FROM transactions WHERE id=? AND user_id=?",
        (id, session["user_id"])
    )

    conn.commit()
    conn.close()

    return redirect(url_for("history"))

# ---------------- SET BUDGET ----------------
@app.route("/set-budget", methods=["POST"])
def set_budget():
    if "user_id" not in session:
        return redirect(url_for("login"))

    category = request.form.get("category")
    amount = request.form.get("amount")

    if category and amount:
        try:
            amount = float(amount)
            conn = get_db_connection()
            conn.execute(
                """INSERT INTO budgets (user_id, category, amount) 
                   VALUES (?, ?, ?) 
                   ON CONFLICT(user_id, category) 
                   DO UPDATE SET amount=excluded.amount""",
                (session["user_id"], category, amount)
            )
            conn.commit()
            conn.close()
            flash(f"Budget set for {category}", "success")
        except ValueError:
            flash("Invalid amount", "error")

    return redirect(request.referrer or url_for("dashboard"))

# ---------------- ANALYTICS PAGE ----------------
@app.route("/analytics")
def analytics():

    if "user_id" not in session:
        return redirect(url_for("login"))

    conn = get_db_connection()

    transactions = conn.execute(
        "SELECT type,amount,category,date FROM transactions WHERE user_id=? ORDER BY date DESC",
        (session["user_id"],)
    ).fetchall()

    # Check budgets
    budgets = conn.execute(
        "SELECT category, amount FROM budgets WHERE user_id=?",
        (session["user_id"],)
    ).fetchall()

    conn.close()

    budget_dict = {b["category"]: b["amount"] for b in budgets}
    import datetime
    current_month = datetime.datetime.now().strftime("%Y-%m")
    
    category_spending = {}
    for t in transactions:
        if t["type"] == "Expense" and t["date"].startswith(current_month):
            category_spending[t["category"]] = category_spending.get(t["category"], 0) + t["amount"]
            
    budget_alerts = []
    for category, limit in budget_dict.items():
        spent = category_spending.get(category, 0)
        if spent > limit:
            budget_alerts.append({"category": category, "limit": limit, "spent": spent})

    income = sum(t["amount"] for t in transactions if t["type"] == "Income")
    expenses = sum(t["amount"] for t in transactions if t["type"] == "Expense")

    balance = income - expenses

    # Monthly Summary Logic
    monthly_summary = {}
    for t in transactions:
        month = t["date"][:7] # YYYY-MM
        if month not in monthly_summary:
            monthly_summary[month] = {"income": 0, "expense": 0}
        if t["type"] == "Income":
            monthly_summary[month]["income"] += t["amount"]
        else:
            monthly_summary[month]["expense"] += t["amount"]

    for m in monthly_summary:
        monthly_summary[m]["balance"] = monthly_summary[m]["income"] - monthly_summary[m]["expense"]

    # Sort descending
    sorted_months = sorted(monthly_summary.keys(), reverse=True)
    monthly_data = [{"month": m, **monthly_summary[m]} for m in sorted_months]

    return render_template(
        "analytics.html",
        income=income,
        expenses=expenses,
        balance=balance,
        budget_alerts=budget_alerts,
        monthly_data=monthly_data
    )

# ---------------- CHART DATA ----------------
@app.route("/api/chart-data")
def chart_data():

    if "user_id" not in session:
        return jsonify({"error":"Unauthorized"}),401

    conn = get_db_connection()

    data = conn.execute("""
        SELECT category,SUM(amount) as total
        FROM transactions
        WHERE user_id=? AND type='Expense'
        GROUP BY category
    """,(session["user_id"],)).fetchall()

    conn.close()

    labels=[row["category"] for row in data]
    values=[row["total"] for row in data]

    return jsonify({"labels":labels,"values":values})

@app.route("/api/monthly-chart-data")
def monthly_chart_data():
    if "user_id" not in session:
        return jsonify({"error":"Unauthorized"}),401

    conn = get_db_connection()
    data = conn.execute("""
        SELECT substr(date, 1, 7) as month, SUM(amount) as total
        FROM transactions
        WHERE user_id=? AND type='Expense'
        GROUP BY month
        ORDER BY month ASC
    """, (session["user_id"],)).fetchall()
    conn.close()

    labels = [row["month"] for row in data]
    values = [row["total"] for row in data]

    return jsonify({"labels":labels, "values":values})

# ---------------- AI INSIGHTS ----------------
@app.route("/api/ai-insights")
def ai_insights():

    if "user_id" not in session:
        return jsonify({"error":"Unauthorized"}),401

    if client is None:
        return jsonify({
            "suggestions":"Groq API not configured",
            "warnings":"AI disabled",
            "savings_tips":"Add GROQ_API_KEY in .env"
        })

    conn=get_db_connection()

    transactions=conn.execute(
        "SELECT type,category,amount FROM transactions WHERE user_id=?",
        (session["user_id"],)
    ).fetchall()

    conn.close()

    if not transactions:
        return jsonify({
            "suggestions":"Add transactions first",
            "warnings":"No financial data",
            "savings_tips":"Track your expenses"
        })

    expenses={}
    income=0

    for t in transactions:

        if t["type"]=="Expense":
            expenses[t["category"]]=expenses.get(t["category"],0)+t["amount"]

        else:
            income+=t["amount"]

    prompt=f"""
Analyze user finances.

Income: {income}
Expenses: {expenses}

Return JSON:

{{
"suggestions":"financial advice",
"warnings":"risk alerts",
"savings_tips":"saving ideas"
}}
"""

    try:

        response=client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[
                {"role":"system","content":"You are a financial advisor AI. Ensure your response is a valid JSON object with EXACTLY keys 'suggestions', 'warnings', and 'savings_tips' as strings."},
                {"role":"user","content":prompt}
            ],
            temperature=0.3,
            response_format={"type": "json_object"}
        )

        result=json.loads(response.choices[0].message.content)

        # Ensure values are strings for the frontend
        for key in ["suggestions", "warnings", "savings_tips"]:
            if key in result and isinstance(result[key], list):
                result[key] = " ".join(str(item) for item in result[key])
            elif key not in result:
                result[key] = "No specific data provided."
            else:
                result[key] = str(result[key])

        return jsonify(result)

    except Exception as e:

        print(e)

        return jsonify({
            "suggestions":"AI error",
            "warnings":"Try later",
            "savings_tips":"Continue tracking spending"
        })

# ---------------- RUN ----------------
if __name__=="__main__":
    app.run(debug=True,port=5001)