
import os, sqlite3, smtplib, ssl
from datetime import datetime, timedelta
from email.message import EmailMessage
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, abort

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "change-me-in-production")
DB = os.environ.get("DATABASE_PATH", "bookings.db")

BOOKING_EMAIL = os.environ.get("BOOKING_EMAIL", "maitresselanaftt@gmail.com")
PAYPAL_URL = os.environ.get("PAYPAL_URL", "https://www.paypal.me/msslana")
THRONE_URL = os.environ.get("THRONE_URL", "https://throne.com/lanaftt")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "change-this-password")
HOLD_MINUTES = int(os.environ.get("HOLD_MINUTES", "30"))

SERVICES = {
    "30min": {"name":"30 minutes","minutes":30,"price":120,"deposit":20},
    "1h": {"name":"1 heure","minutes":60,"price":220,"deposit":30},
    "1h30": {"name":"1 h 30","minutes":90,"price":300,"deposit":50},
    "2h": {"name":"2 heures","minutes":120,"price":400,"deposit":70},
}

def db():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    return con

def init_db():
    con = db()
    con.executescript("""
    CREATE TABLE IF NOT EXISTS bookings(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      created_at TEXT NOT NULL,
      pseudo TEXT NOT NULL,
      email TEXT NOT NULL,
      age INTEGER NOT NULL,
      twitter TEXT,
      message TEXT,
      service_id TEXT NOT NULL,
      duration_minutes INTEGER NOT NULL,
      price INTEGER NOT NULL,
      deposit INTEGER NOT NULL,
      start_dt TEXT NOT NULL,
      end_dt TEXT NOT NULL,
      status TEXT NOT NULL DEFAULT 'pending',
      hold_expires_at TEXT,
      payment_method TEXT
    );
    CREATE TABLE IF NOT EXISTS blocks(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      start_dt TEXT NOT NULL,
      end_dt TEXT NOT NULL,
      note TEXT
    );
    """)
    con.commit()
    con.close()

init_db()

def parse_dt(s):
    return datetime.fromisoformat(s)

def dtstr(d):
    return d.isoformat(timespec="minutes")

def booking_conflict(start, end, ignore_id=None):
    now = datetime.now()
    con = db()
    params = [dtstr(end), dtstr(start), dtstr(now)]
    sql = """
      SELECT * FROM bookings
      WHERE start_dt < ? AND end_dt > ?
      AND (
        status='confirmed'
        OR (status='pending' AND hold_expires_at IS NOT NULL AND hold_expires_at > ?)
      )
    """
    if ignore_id:
        sql += " AND id != ?"
        params.append(ignore_id)
    booking = con.execute(sql, params).fetchone()
    block = con.execute(
        "SELECT * FROM blocks WHERE start_dt < ? AND end_dt > ?",
        (dtstr(end), dtstr(start))
    ).fetchone()
    con.close()
    return booking is not None or block is not None

def within_open_hours(start, end):
    # Each operating day runs 17:00 through 00:00 next day.
    day = start.date()
    open_dt = datetime.combine(day, datetime.min.time()).replace(hour=17)
    close_dt = datetime.combine(day + timedelta(days=1), datetime.min.time())
    return start >= open_dt and end <= close_dt

def send_email(to, subject, body):
    host = os.environ.get("SMTP_HOST")
    port = int(os.environ.get("SMTP_PORT", "587"))
    user = os.environ.get("SMTP_USER")
    password = os.environ.get("SMTP_PASSWORD")
    if not (host and user and password):
        return False
    msg = EmailMessage()
    msg["From"] = user
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    context = ssl.create_default_context()
    with smtplib.SMTP(host, port, timeout=20) as s:
        s.starttls(context=context)
        s.login(user, password)
        s.send_message(msg)
    return True

@app.get("/")
def index():
    return render_template("index.html", services=SERVICES)

@app.get("/api/availability")
def availability():
    date_s = request.args.get("date","")
    service_id = request.args.get("service_id","")
    if service_id not in SERVICES:
        return jsonify([])
    try:
        day = datetime.strptime(date_s, "%Y-%m-%d").date()
    except ValueError:
        return jsonify([])
    duration = SERVICES[service_id]["minutes"]
    result = []
    cur = datetime.combine(day, datetime.min.time()).replace(hour=17)
    close = datetime.combine(day + timedelta(days=1), datetime.min.time())
    while cur + timedelta(minutes=duration) <= close:
        end = cur + timedelta(minutes=duration)
        if cur >= datetime.now() + timedelta(hours=24) and not booking_conflict(cur, end):
            result.append(cur.strftime("%H:%M"))
        cur += timedelta(minutes=30)
    return jsonify(result)

@app.post("/book")
def book():
    service_id = request.form.get("service_id","")
    if service_id not in SERVICES:
        abort(400)
    pseudo = request.form.get("pseudo","").strip()
    email = request.form.get("email","").strip()
    twitter = request.form.get("twitter","").strip()
    message = request.form.get("message","").strip()
    date_s = request.form.get("date","")
    time_s = request.form.get("time","")
    payment_method = request.form.get("payment_method","paypal")
    try:
        age = int(request.form.get("age","0"))
    except ValueError:
        age = 0
    if not pseudo or not email or age < 18:
        flash("Merci de compléter les informations obligatoires. Réservations 18+.")
        return redirect(url_for("index"))
    try:
        start = datetime.strptime(f"{date_s} {time_s}", "%Y-%m-%d %H:%M")
    except ValueError:
        flash("Date ou heure invalide.")
        return redirect(url_for("index"))
    service = SERVICES[service_id]
    end = start + timedelta(minutes=service["minutes"])
    if start < datetime.now() + timedelta(hours=24):
        flash("La réservation doit être faite au minimum 24 h à l’avance.")
        return redirect(url_for("index"))
    if not within_open_hours(start, end):
        flash("Ce créneau n’est pas compatible avec les horaires disponibles.")
        return redirect(url_for("index"))
    if booking_conflict(start, end):
        flash("Ce créneau vient d’être pris. Choisis-en un autre.")
        return redirect(url_for("index"))

    hold_expires = datetime.now() + timedelta(minutes=HOLD_MINUTES)
    con = db()
    cur = con.execute("""
      INSERT INTO bookings(
        created_at,pseudo,email,age,twitter,message,service_id,duration_minutes,
        price,deposit,start_dt,end_dt,status,hold_expires_at,payment_method
      ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        dtstr(datetime.now()), pseudo, email, age, twitter, message, service_id,
        service["minutes"], service["price"], service["deposit"], dtstr(start), dtstr(end),
        "pending", dtstr(hold_expires), payment_method
    ))
    booking_id = cur.lastrowid
    con.commit()
    con.close()

    owner_body = f"""Nouvelle demande de réservation #{booking_id}

Pseudo : {pseudo}
Âge : {age}
Email : {email}
X/Twitter : {twitter or '-'}
Durée : {service['name']}
Date : {start.strftime('%d/%m/%Y')}
Heure : {start.strftime('%H:%M')}
Fin : {end.strftime('%H:%M')}
Prix : {service['price']} €
Acompte : {service['deposit']} €
Paiement choisi : {payment_method}
Message : {message or '-'}

Le créneau est placé en attente pendant {HOLD_MINUTES} minutes.
"""
    send_email(BOOKING_EMAIL, f"Réservation #{booking_id} - {pseudo}", owner_body)

    client_body = f"""Bonjour {pseudo},

Ta demande de réservation #{booking_id} a bien été enregistrée.

Durée : {service['name']}
Date : {start.strftime('%d/%m/%Y')}
Heure : {start.strftime('%H:%M')}
Acompte : {service['deposit']} €

Après paiement, le rendez-vous reste soumis à confirmation personnelle par Maîtresse Lana.
L’adresse exacte n’est pas publiée sur le site et sera communiquée après confirmation.

Acompte non remboursable. Déplacement possible si la demande est faite au moins 48 h à l’avance.
Au-delà de 15 minutes de retard, le rendez-vous est annulé.
"""
    send_email(email, f"Demande de réservation #{booking_id}", client_body)

    return redirect(url_for("payment", booking_id=booking_id))

@app.get("/payment/<int:booking_id>")
def payment(booking_id):
    con = db()
    b = con.execute("SELECT * FROM bookings WHERE id=?", (booking_id,)).fetchone()
    con.close()
    if not b:
        abort(404)
    return render_template("payment.html", b=b, paypal=PAYPAL_URL, throne=THRONE_URL)

@app.get("/admin")
def admin():
    if not session.get("admin"):
        return redirect(url_for("login"))
    con = db()
    bookings = con.execute("SELECT * FROM bookings ORDER BY start_dt DESC").fetchall()
    blocks = con.execute("SELECT * FROM blocks ORDER BY start_dt DESC").fetchall()
    con.close()
    return render_template("admin.html", bookings=bookings, blocks=blocks)

@app.route("/login", methods=["GET","POST"])
def login():
    if request.method == "POST":
        if request.form.get("password") == ADMIN_PASSWORD:
            session["admin"] = True
            return redirect(url_for("admin"))
        flash("Mot de passe incorrect.")
    return render_template("login.html")

@app.get("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))

@app.post("/admin/booking/<int:booking_id>/<action>")
def admin_booking_action(booking_id, action):
    if not session.get("admin"):
        abort(403)
    if action not in ("confirm","cancel"):
        abort(400)
    con = db()
    b = con.execute("SELECT * FROM bookings WHERE id=?", (booking_id,)).fetchone()
    if not b:
        con.close(); abort(404)
    status = "confirmed" if action == "confirm" else "cancelled"
    con.execute("UPDATE bookings SET status=?, hold_expires_at=NULL WHERE id=?", (status, booking_id))
    con.commit()
    con.close()
    if status == "confirmed":
        body = f"""Bonjour {b['pseudo']},

Ton rendez-vous #{b['id']} est confirmé.

Date : {parse_dt(b['start_dt']).strftime('%d/%m/%Y')}
Heure : {parse_dt(b['start_dt']).strftime('%H:%M')}
Durée : {b['duration_minutes']} minutes
Lieu : Meaux (77)

L’adresse exacte te sera communiquée séparément.
Déplacement possible uniquement avec au moins 48 h de préavis.
Au-delà de 15 minutes de retard, le rendez-vous est annulé.
"""
        send_email(b["email"], f"Rendez-vous confirmé #{b['id']}", body)
    return redirect(url_for("admin"))

@app.post("/admin/block")
def admin_block():
    if not session.get("admin"):
        abort(403)
    try:
        start = datetime.fromisoformat(request.form.get("start_dt"))
        end = datetime.fromisoformat(request.form.get("end_dt"))
    except Exception:
        flash("Dates invalides.")
        return redirect(url_for("admin"))
    if end <= start:
        flash("La fin doit être après le début.")
        return redirect(url_for("admin"))
    con = db()
    con.execute("INSERT INTO blocks(start_dt,end_dt,note) VALUES(?,?,?)",
                (dtstr(start), dtstr(end), request.form.get("note","").strip()))
    con.commit(); con.close()
    return redirect(url_for("admin"))

@app.post("/admin/block/<int:block_id>/delete")
def delete_block(block_id):
    if not session.get("admin"):
        abort(403)
    con = db()
    con.execute("DELETE FROM blocks WHERE id=?", (block_id,))
    con.commit(); con.close()
    return redirect(url_for("admin"))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT","5000")), debug=True)
