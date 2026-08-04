
import os, sqlite3, smtplib, ssl
from datetime import datetime, timedelta
from email.message import EmailMessage
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, abort

app = Flask(__name__)
app.secret_key = os.environ["SECRET_KEY"]
DB = os.environ.get("DATABASE_PATH", "bookings.db")

BOOKING_EMAIL = os.environ.get("BOOKING_EMAIL", "maitresselanaftt@gmail.com")
PAYPAL_URL = os.environ.get("PAYPAL_URL", "https://www.paypal.me/msslana")
THRONE_URL = os.environ.get("THRONE_URL", "https://throne.com/lanaftt")
ADMIN_PASSWORD = os.environ["ADMIN_PASSWORD"]
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
    CREATE TABLE IF NOT EXISTS reviews(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      created_at TEXT NOT NULL,
      pseudo TEXT NOT NULL,
      email TEXT,
      rating INTEGER NOT NULL,
      comment TEXT NOT NULL,
      status TEXT NOT NULL DEFAULT 'pending',
      verified INTEGER NOT NULL DEFAULT 0
    );
    """)
    booking_columns = {
        row["name"] for row in con.execute("PRAGMA table_info(bookings)").fetchall()
    }
    if "review_request_sent_at" not in booking_columns:
        con.execute("ALTER TABLE bookings ADD COLUMN review_request_sent_at TEXT")
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

def send_email(to, subject, body, html_body=None):
    try:
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

        if html_body:
            msg.add_alternative(html_body, subtype="html")

        context = ssl.create_default_context()
        with smtplib.SMTP(host, port, timeout=20) as s:
            s.starttls(context=context)
            s.login(user, password)
            s.send_message(msg)
        return True
    except Exception as e:
        print(f"Erreur lors de l’envoi de l’e-mail : {e}")
        return False


def email_layout(title, intro, details_html="", footer=""):
    return f"""<!doctype html>
<html lang="fr">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
</head>
<body style="margin:0;background:#0a0a0d;color:#f6f0e8;font-family:Arial,Helvetica,sans-serif;">
  <div style="padding:28px 14px;">
    <div style="max-width:620px;margin:0 auto;background:#17171c;border:1px solid #3a3136;border-radius:20px;overflow:hidden;">
      <div style="padding:26px 28px;border-bottom:1px solid #332d32;background:linear-gradient(135deg,#1b171b,#111115);">
        <div style="font-family:Georgia,'Times New Roman',serif;font-size:26px;letter-spacing:.08em;color:#e4c47f;">
          MAÎTRESSE LANA
        </div>
        <div style="margin-top:6px;color:#a99fa4;font-size:13px;text-transform:uppercase;letter-spacing:.14em;">
          {title}
        </div>
      </div>

      <div style="padding:28px;">
        <div style="font-size:16px;line-height:1.75;color:#eee6e9;">
          {intro}
        </div>

        {details_html}

        <div style="margin-top:26px;padding-top:18px;border-top:1px solid #332d32;color:#9f959a;font-size:13px;line-height:1.65;">
          {footer}
        </div>
      </div>
    </div>
  </div>
</body>
</html>"""


def email_details(rows):
    items = []
    for label, value in rows:
        items.append(
            f"""<tr>
              <td style="padding:10px 0;color:#a99fa4;font-size:13px;vertical-align:top;">{label}</td>
              <td style="padding:10px 0 10px 18px;color:#f6f0e8;font-size:14px;font-weight:700;text-align:right;vertical-align:top;">{value}</td>
            </tr>"""
        )
    return (
        '<table role="presentation" style="width:100%;margin-top:22px;padding:8px 18px;'
        'border:1px solid #342f35;border-radius:14px;background:#101014;border-collapse:separate;">'
        + "".join(items)
        + "</table>"
    )
@app.get("/")
def index():
    return render_template("index.html", services=SERVICES)
@app.get("/pratiques")
def pratiques():
    return render_template("pratiques.html")

@app.route("/avis", methods=["GET", "POST"])
def avis():
    con = db()
    if request.method == "POST":
        pseudo = request.form.get("pseudo", "").strip()
        email = request.form.get("email", "").strip()
        comment = request.form.get("comment", "").strip()
        try:
            rating = int(request.form.get("rating", "0"))
        except ValueError:
            rating = 0

        if not pseudo or not comment or rating not in (1, 2, 3, 4, 5):
            con.close()
            flash("Merci de renseigner un pseudo, une note et un avis.")
            return redirect(url_for("avis"))

        con.execute(
            """INSERT INTO reviews(created_at,pseudo,email,rating,comment,status,verified)
               VALUES(?,?,?,?,?,'pending',0)""",
            (dtstr(datetime.now()), pseudo[:80], email[:160], rating, comment[:1500]),
        )
        con.commit()
        con.close()
        send_email(
            BOOKING_EMAIL,
            f"Nouvel avis de {pseudo}",
            f"Nouvel avis en attente\\n\\nPseudo : {pseudo}\\nNote : {rating}/5\\nE-mail : {email or '-'}\\n\\n{comment}",
        )
        flash("Merci. Ton avis a été envoyé et sera publié après validation.")
        return redirect(url_for("avis"))

    reviews = con.execute(
        "SELECT * FROM reviews WHERE status='published' ORDER BY created_at DESC"
    ).fetchall()
    con.close()
    return render_template("avis.html", reviews=reviews)

@app.get("/admin/avis")
def admin_reviews():
    if not session.get("admin"):
        return redirect(url_for("login"))
    con = db()
    reviews = con.execute(
        """SELECT * FROM reviews ORDER BY
           CASE status WHEN 'pending' THEN 0 WHEN 'published' THEN 1 ELSE 2 END,
           created_at DESC"""
    ).fetchall()
    counts = {
        "pending": con.execute("SELECT COUNT(*) FROM reviews WHERE status='pending'").fetchone()[0],
        "published": con.execute("SELECT COUNT(*) FROM reviews WHERE status='published'").fetchone()[0],
        "rejected": con.execute("SELECT COUNT(*) FROM reviews WHERE status='rejected'").fetchone()[0],
    }
    con.close()
    return render_template("admin-avis.html", reviews=reviews, counts=counts)

@app.post("/admin/avis/<int:review_id>/<action>")
def admin_review_action(review_id, action):
    if not session.get("admin"):
        abort(403)
    if action not in ("publish", "reject", "verify", "unverify", "delete"):
        abort(400)

    con = db()
    review = con.execute("SELECT id FROM reviews WHERE id=?", (review_id,)).fetchone()
    if not review:
        con.close()
        abort(404)

    if action == "delete":
        con.execute("DELETE FROM reviews WHERE id=?", (review_id,))
    elif action == "publish":
        con.execute("UPDATE reviews SET status='published' WHERE id=?", (review_id,))
    elif action == "reject":
        con.execute("UPDATE reviews SET status='rejected' WHERE id=?", (review_id,))
    elif action == "verify":
        con.execute("UPDATE reviews SET verified=1 WHERE id=?", (review_id,))
    else:
        con.execute("UPDATE reviews SET verified=0 WHERE id=?", (review_id,))

    con.commit()
    con.close()
    flash("Avis mis à jour.")
    return redirect(url_for("admin_reviews"))

@app.get("/api/reviews")
def public_reviews():
    con = db()
    rows = con.execute(
        """SELECT id,pseudo,rating,comment,verified,created_at
           FROM reviews
           WHERE status='published'
           ORDER BY created_at DESC
           LIMIT 6"""
    ).fetchall()
    con.close()
    return jsonify([
        {
            "id": row["id"],
            "pseudo": row["pseudo"],
            "rating": row["rating"],
            "comment": row["comment"],
            "verified": bool(row["verified"]),
            "created_at": row["created_at"],
        }
        for row in rows
    ])

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
@app.get("/api/month-availability")
def month_availability():
    month_s = request.args.get("month", "")
    service_id = request.args.get("service_id", "")

    if service_id not in SERVICES:
        return jsonify({})

    try:
        year, month = map(int, month_s.split("-"))
    except ValueError:
        return jsonify({})

    duration = SERVICES[service_id]["minutes"]

    if month == 12:
        next_month = datetime(year + 1, 1, 1)
    else:
        next_month = datetime(year, month + 1, 1)

    day = datetime(year, month, 1).date()
    last_day = (next_month - timedelta(days=1)).date()

    result = {}

    while day <= last_day:
        cur = datetime.combine(day, datetime.min.time()).replace(hour=17)
        close = datetime.combine(day + timedelta(days=1), datetime.min.time())

        available = 0

        while cur + timedelta(minutes=duration) <= close:
            end = cur + timedelta(minutes=duration)

            if (
                cur >= datetime.now() + timedelta(hours=24)
                and not booking_conflict(cur, end)
            ):
                available += 1

            cur += timedelta(minutes=30)

        result[day.isoformat()] = available
        day += timedelta(days=1)

    return jsonify(result)
@app.post("/book")
def book():
    if request.form.get("age_confirmed") != "on":
        flash("Tu dois confirmer avoir 18 ans ou plus.")
        return redirect(url_for("index"))
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

    owner_html = email_layout(
        "Nouvelle réservation",
        f"<strong>Nouvelle demande #{booking_id}</strong><br>Une nouvelle réservation vient d’être enregistrée.",
        email_details([
            ("Pseudo", pseudo),
            ("Âge", f"{age} ans"),
            ("E-mail", email),
            ("X / Twitter", twitter or "Non renseigné"),
            ("Séance", service["name"]),
            ("Date", start.strftime("%d/%m/%Y")),
            ("Horaire", f"{start.strftime('%H:%M')} – {end.strftime('%H:%M')}"),
            ("Prix", f"{service['price']} €"),
            ("Acompte", f"{service['deposit']} €"),
            ("Paiement", payment_method),
            ("Message", message or "Aucun message"),
        ]),
        f"Le créneau reste en attente pendant {HOLD_MINUTES} minutes, puis doit être confirmé depuis l’espace admin.",
    )
    send_email(
        BOOKING_EMAIL,
        f"Réservation #{booking_id} - {pseudo}",
        owner_body,
        owner_html,
    )

    client_body = f"""Bonjour {pseudo},

Ta demande de réservation #{booking_id} a bien été enregistrée.

Durée : {service['name']}
Date : {start.strftime('%d/%m/%Y')}
Heure : {start.strftime('%H:%M')}
Acompte : {service['deposit']} €

Après paiement, le rendez-vous reste soumis à confirmation personnelle par Maîtresse Lana.
L’adresse exacte n’est pas publiée sur le site et sera communiquée après confirmation.

L’acompte n’est pas remboursable en cas d’annulation du client. Si la demande est refusée par Maîtresse Lana, l’acompte sera remboursé après vérification du paiement. Toute modification du rendez-vous doit être demandée au moins 48 h à l’avance.
Au-delà de 15 minutes de retard, le rendez-vous est annulé.
"""

    client_html = email_layout(
        "Demande reçue",
        f"Bonjour <strong>{pseudo}</strong>,<br>Ta demande de réservation <strong>#{booking_id}</strong> a bien été enregistrée.",
        email_details([
            ("Séance", service["name"]),
            ("Date", start.strftime("%d/%m/%Y")),
            ("Heure", start.strftime("%H:%M")),
            ("Acompte", f"{service['deposit']} €"),
            ("Paiement choisi", payment_method),
            ("Statut", "En attente de confirmation"),
        ]),
        "Le rendez-vous reste soumis à confirmation personnelle. L’adresse exacte sera communiquée uniquement après confirmation. Toute modification doit être demandée au moins 48 h à l’avance. Au-delà de 15 minutes de retard, le rendez-vous est annulé.",
    )
    send_email(
        email,
        f"Demande de réservation #{booking_id}",
        client_body,
        client_html,
    )

    return redirect(url_for("payment", booking_id=booking_id))

@app.get("/payment/<int:booking_id>")
def payment(booking_id):
    con = db()
    b = con.execute("SELECT * FROM bookings WHERE id=?", (booking_id,)).fetchone()
    con.close()
    if not b:
        abort(404)
    return render_template("payment.html", b=b, paypal=PAYPAL_URL, throne=THRONE_URL)

def send_due_review_requests(base_url):
    cutoff = datetime.now() - timedelta(days=3)
    con = db()
    due = con.execute(
        """SELECT * FROM bookings
           WHERE status='confirmed'
             AND end_dt <= ?
             AND review_request_sent_at IS NULL
           ORDER BY end_dt ASC""",
        (dtstr(cutoff),),
    ).fetchall()

    sent = 0
    review_url = base_url.rstrip("/") + "/avis#formulaire"

    for booking in due:
        body = f"""Bonjour {booking['pseudo']},

Merci pour ta confiance.

Tu peux laisser un avis ici :
{review_url}

Ton avis sera relu avant publication et ton e-mail ne sera jamais affiché.

Maîtresse Lana
"""
        html_body = email_layout(
            "Votre avis compte",
            f"Bonjour <strong>{booking['pseudo']}</strong>,<br>Merci pour ta confiance.",
            (
                '<div style="margin-top:22px;padding:20px;border:1px solid #342f35;'
                'border-radius:14px;background:#101014;text-align:center;">'
                '<p style="margin:0 0 16px;color:#d8cfd3;line-height:1.65;">'
                'Partage ton expérience en quelques mots. Ton avis sera relu avant publication.'
                '</p>'
                f'<a href="{review_url}" style="display:inline-block;padding:12px 20px;'
                'border-radius:999px;background:#e4c47f;color:#171208;'
                'text-decoration:none;font-weight:800;">Laisser un avis</a>'
                '</div>'
            ),
            "Ton adresse e-mail ne sera jamais affichée sur le site.",
        )
        if send_email(
            booking["email"],
            "Partage ton expérience — Maîtresse Lana",
            body,
            html_body,
        ):
            con.execute(
                "UPDATE bookings SET review_request_sent_at=? WHERE id=?",
                (dtstr(datetime.now()), booking["id"]),
            )
            sent += 1

    con.commit()
    con.close()
    return sent


@app.get("/admin")
def admin():
    if not session.get("admin"):
        return redirect(url_for("login"))

    sent_review_requests = send_due_review_requests(request.url_root)
    if sent_review_requests:
        flash(f"{sent_review_requests} demande(s) d’avis envoyée(s) automatiquement.")

    status_filter = request.args.get("status", "active")
    search_query = request.args.get("q", "").strip()
    where, params = [], []

    if status_filter == "pending":
        where.append("status = 'pending'")
    elif status_filter == "confirmed":
        where.append("status = 'confirmed'")
    elif status_filter == "cancelled":
        where.append("status = 'cancelled'")
    elif status_filter == "all":
        pass
    else:
        status_filter = "active"
        where.append("status != 'cancelled'")

    if search_query:
        where.append("(pseudo LIKE ? OR email LIKE ? OR COALESCE(twitter, '') LIKE ?)")
        term = f"%{search_query}%"
        params.extend([term, term, term])

    sql = "SELECT * FROM bookings"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY start_dt DESC"

    now = datetime.now()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    next_month = (
        month_start.replace(year=month_start.year + 1, month=1)
        if month_start.month == 12
        else month_start.replace(month=month_start.month + 1)
    )
    next_week = now + timedelta(days=7)

    con = db()
    bookings = con.execute(sql, params).fetchall()
    blocks = con.execute("SELECT * FROM blocks ORDER BY start_dt DESC").fetchall()

    counts = {
        "pending": con.execute("SELECT COUNT(*) FROM bookings WHERE status='pending'").fetchone()[0],
        "confirmed": con.execute("SELECT COUNT(*) FROM bookings WHERE status='confirmed'").fetchone()[0],
        "cancelled": con.execute("SELECT COUNT(*) FROM bookings WHERE status='cancelled'").fetchone()[0],
        "blocks": con.execute("SELECT COUNT(*) FROM blocks").fetchone()[0],
    }

    dashboard = {
        "month_confirmed": con.execute(
            "SELECT COUNT(*) FROM bookings WHERE status='confirmed' AND start_dt>=? AND start_dt<?",
            (dtstr(month_start), dtstr(next_month)),
        ).fetchone()[0],
        "month_revenue": con.execute(
            "SELECT COALESCE(SUM(price),0) FROM bookings WHERE status='confirmed' AND start_dt>=? AND start_dt<?",
            (dtstr(month_start), dtstr(next_month)),
        ).fetchone()[0],
        "upcoming_week": con.execute(
            "SELECT COUNT(*) FROM bookings WHERE status='confirmed' AND start_dt>=? AND start_dt<=?",
            (dtstr(now), dtstr(next_week)),
        ).fetchone()[0],
        "reviews_pending": con.execute(
            "SELECT COUNT(*) FROM reviews WHERE status='pending'"
        ).fetchone()[0],
        "review_requests_sent": con.execute(
            "SELECT COUNT(*) FROM bookings WHERE review_request_sent_at IS NOT NULL"
        ).fetchone()[0],
    }

    upcoming_bookings = con.execute(
        "SELECT * FROM bookings WHERE status='confirmed' AND start_dt>=? ORDER BY start_dt ASC LIMIT 5",
        (dtstr(now),),
    ).fetchall()

    calendar_bookings = [
        {"id": r["id"], "title": r["pseudo"], "start": r["start_dt"], "end": r["end_dt"], "status": r["status"]}
        for r in con.execute(
            "SELECT id,pseudo,start_dt,end_dt,status FROM bookings WHERE status != 'cancelled'"
        ).fetchall()
    ]
    calendar_blocks = [
        {"id": r["id"], "title": r["note"] or "Indisponible", "start": r["start_dt"], "end": r["end_dt"]}
        for r in blocks
    ]

    con.close()
    return render_template(
        "admin.html",
        bookings=bookings,
        blocks=blocks,
        counts=counts,
        dashboard=dashboard,
        upcoming_bookings=upcoming_bookings,
        status_filter=status_filter,
        search_query=search_query,
        calendar_bookings=calendar_bookings,
        calendar_blocks=calendar_blocks,
    )

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
Toute modification du rendez-vous doit être demandée au moins 48 h à l’avance.
Au-delà de 15 minutes de retard, le rendez-vous est annulé.
"""
        html_body = email_layout(
            "Rendez-vous confirmé",
            f"Bonjour <strong>{b['pseudo']}</strong>,<br>Ton rendez-vous <strong>#{b['id']}</strong> est confirmé.",
            email_details([
                ("Date", parse_dt(b["start_dt"]).strftime("%d/%m/%Y")),
                ("Heure", parse_dt(b["start_dt"]).strftime("%H:%M")),
                ("Durée", f"{b['duration_minutes']} minutes"),
                ("Lieu", "Meaux (77)"),
                ("Statut", "Confirmé"),
            ]),
            "L’adresse exacte sera communiquée séparément. Toute modification doit être demandée au moins 48 h à l’avance. Au-delà de 15 minutes de retard, le rendez-vous est annulé.",
        )
        send_email(
            b["email"],
            f"Rendez-vous confirmé #{b['id']}",
            body,
            html_body,
        )

    if status == "cancelled":
        body = f"""Bonjour {b['pseudo']},

Ta demande de rendez-vous #{b['id']} a été refusée.

Si tu as déjà envoyé l’acompte, celui-ci te sera remboursé après vérification du paiement.

Maîtresse Lana
"""
        html_body = email_layout(
            "Demande refusée",
            f"Bonjour <strong>{b['pseudo']}</strong>,<br>Ta demande de rendez-vous <strong>#{b['id']}</strong> n’a pas été retenue.",
            email_details([
                ("Date demandée", parse_dt(b["start_dt"]).strftime("%d/%m/%Y")),
                ("Heure demandée", parse_dt(b["start_dt"]).strftime("%H:%M")),
                ("Statut", "Refusée"),
            ]),
            "Si l’acompte a déjà été envoyé, il sera remboursé après vérification du paiement.",
        )
        send_email(
            b["email"],
            f"Rendez-vous annulé #{b['id']}",
            body,
            html_body,
        )

    return redirect(url_for("admin"))

@app.post("/admin/booking/<int:booking_id>/delete")
def delete_booking(booking_id):
    if not session.get("admin"):
        abort(403)
    con = db()
    booking = con.execute("SELECT * FROM bookings WHERE id=?", (booking_id,)).fetchone()
    if not booking:
        con.close()
        abort(404)
    con.execute("DELETE FROM bookings WHERE id=?", (booking_id,))
    con.commit()
    con.close()
    flash(f"Réservation #{booking_id} supprimée définitivement.")
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
    con.execute(
        "INSERT INTO blocks(start_dt,end_dt,note) VALUES(?,?,?)",
        (dtstr(start), dtstr(end), request.form.get("note", "").strip())
    )
    con.commit()
    con.close()
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
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT","5000")), debug=False)
