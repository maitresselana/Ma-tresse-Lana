
import os, sqlite3, smtplib, ssl, json, secrets
from datetime import datetime, timedelta
from email.message import EmailMessage
from pywebpush import webpush, WebPushException
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, abort, send_from_directory

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
    CREATE TABLE IF NOT EXISTS customer_notes(
      email TEXT PRIMARY KEY,
      note TEXT NOT NULL DEFAULT '',
      updated_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS push_subscriptions(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      endpoint TEXT NOT NULL UNIQUE,
      p256dh TEXT NOT NULL,
      auth TEXT NOT NULL,
      created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS reschedule_proposals(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      token TEXT NOT NULL UNIQUE,
      booking_id INTEGER NOT NULL,
      slot1_start TEXT NOT NULL,
      slot2_start TEXT NOT NULL,
      expires_at TEXT NOT NULL,
      chosen_slot INTEGER,
      chosen_at TEXT,
      created_at TEXT NOT NULL
    );
    """)
    booking_columns = {
        row["name"] for row in con.execute("PRAGMA table_info(bookings)").fetchall()
    }
    if "review_request_sent_at" not in booking_columns:
        con.execute("ALTER TABLE bookings ADD COLUMN review_request_sent_at TEXT")
    if "practices" not in booking_columns:
        con.execute("ALTER TABLE bookings ADD COLUMN practices TEXT")
    if "private_notes" not in booking_columns:
        con.execute("ALTER TABLE bookings ADD COLUMN private_notes TEXT")
    if "completed_at" not in booking_columns:
        con.execute("ALTER TABLE bookings ADD COLUMN completed_at TEXT")
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
@app.get("/admin-sw.js")
def admin_service_worker():
    response = send_from_directory(
        app.static_folder,
        "admin-sw.js",
        mimetype="application/javascript",
    )
    response.headers["Service-Worker-Allowed"] = "/"
    response.headers["Cache-Control"] = "no-cache"
    return response



def send_push_notification(title, body, url="/admin"):
    public_key = os.environ.get("VAPID_PUBLIC_KEY", "").strip()
    private_key = os.environ.get("VAPID_PRIVATE_KEY", "").replace("\\n", "\n").strip()
    subject = os.environ.get("VAPID_SUBJECT", "mailto:maitresselanaftt@gmail.com").strip()

    if not public_key or not private_key:
        return 0

    con = db()
    subscriptions = con.execute("SELECT * FROM push_subscriptions").fetchall()
    sent = 0

    pending_bookings = con.execute(
        "SELECT COUNT(*) FROM bookings WHERE status='pending'"
    ).fetchone()[0]
    pending_reviews = con.execute(
        "SELECT COUNT(*) FROM reviews WHERE status='pending'"
    ).fetchone()[0]
    action_count = pending_bookings + pending_reviews

    payload = json.dumps({
        "title": title,
        "body": body,
        "url": url,
        "icon": "/static/admin-icon-192.png",
        "badge": "/static/admin-icon-192.png",
        "badgeCount": max(1, action_count),
    }, ensure_ascii=False)

    for subscription in subscriptions:
        subscription_info = {
            "endpoint": subscription["endpoint"],
            "keys": {
                "p256dh": subscription["p256dh"],
                "auth": subscription["auth"],
            },
        }
        try:
            webpush(
                subscription_info=subscription_info,
                data=payload,
                vapid_private_key=private_key,
                vapid_claims={"sub": subject},
            )
            sent += 1
        except WebPushException as exc:
            status = getattr(exc.response, "status_code", None)
            if status in (404, 410):
                con.execute(
                    "DELETE FROM push_subscriptions WHERE endpoint=?",
                    (subscription["endpoint"],),
                )
            else:
                print(f"Erreur notification push : {exc}")

    con.commit()
    con.close()
    return sent


@app.get("/api/push/public-key")
def push_public_key():
    if not session.get("admin"):
        abort(403)
    return jsonify({"publicKey": os.environ.get("VAPID_PUBLIC_KEY", "")})


@app.post("/api/push/subscribe")
def push_subscribe():
    if not session.get("admin"):
        abort(403)

    data = request.get_json(silent=True) or {}
    endpoint = data.get("endpoint", "")
    keys = data.get("keys") or {}
    p256dh = keys.get("p256dh", "")
    auth = keys.get("auth", "")

    if not endpoint or not p256dh or not auth:
        abort(400)

    con = db()
    con.execute(
        """INSERT INTO push_subscriptions(endpoint,p256dh,auth,created_at)
           VALUES(?,?,?,?)
           ON CONFLICT(endpoint) DO UPDATE SET
             p256dh=excluded.p256dh,
             auth=excluded.auth""",
        (endpoint, p256dh, auth, dtstr(datetime.now())),
    )
    con.commit()
    con.close()
    return jsonify({"ok": True})


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

    send_push_notification(
        "Nouvelle réservation",
        f"{pseudo} · {start.strftime('%d/%m à %H:%M')} · {service['price']} €",
        f"/admin?booking={booking_id}",
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
           WHERE status IN ('confirmed','completed')
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
        "confirmed": con.execute("SELECT COUNT(*) FROM bookings WHERE status IN ('confirmed','completed')").fetchone()[0],
        "cancelled": con.execute("SELECT COUNT(*) FROM bookings WHERE status='cancelled'").fetchone()[0],
        "blocks": con.execute("SELECT COUNT(*) FROM blocks").fetchone()[0],
    }

    monthly_chart = []
    for offset in range(5, -1, -1):
        year = now.year
        month = now.month - offset
        while month <= 0:
            month += 12
            year -= 1
        start_month = datetime(year, month, 1)
        end_month = (
            datetime(year + 1, 1, 1)
            if month == 12
            else datetime(year, month + 1, 1)
        )
        row = con.execute(
            """SELECT
                 COUNT(*) AS bookings_count,
                 COALESCE(SUM(price),0) AS revenue
               FROM bookings
               WHERE status IN ('confirmed','completed')
                 AND start_dt>=? AND start_dt<?""",
            (dtstr(start_month), dtstr(end_month)),
        ).fetchone()
        monthly_chart.append({
            "label": start_month.strftime("%m/%Y"),
            "bookings": row["bookings_count"],
            "revenue": row["revenue"],
        })

    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    today_end = today_start + timedelta(days=1)

    week_start = today_start - timedelta(days=today_start.weekday())
    week_end = week_start + timedelta(days=7)
    year_start = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
    next_year = year_start.replace(year=year_start.year + 1)

    dashboard = {
        "today_confirmed": con.execute(
            "SELECT COUNT(*) FROM bookings WHERE status IN ('confirmed','completed') AND start_dt>=? AND start_dt<?",
            (dtstr(today_start), dtstr(today_end)),
        ).fetchone()[0],
        "today_revenue": con.execute(
            "SELECT COALESCE(SUM(price),0) FROM bookings WHERE status IN ('confirmed','completed') AND start_dt>=? AND start_dt<?",
            (dtstr(today_start), dtstr(today_end)),
        ).fetchone()[0],
        "total_revenue": con.execute(
            "SELECT COALESCE(SUM(price),0) FROM bookings WHERE status IN ('confirmed','completed')"
        ).fetchone()[0],
        "month_confirmed": con.execute(
            "SELECT COUNT(*) FROM bookings WHERE status IN ('confirmed','completed') AND start_dt>=? AND start_dt<?",
            (dtstr(month_start), dtstr(next_month)),
        ).fetchone()[0],
        "month_revenue": con.execute(
            "SELECT COALESCE(SUM(price),0) FROM bookings WHERE status IN ('confirmed','completed') AND start_dt>=? AND start_dt<?",
            (dtstr(month_start), dtstr(next_month)),
        ).fetchone()[0],
        "upcoming_week": con.execute(
            "SELECT COUNT(*) FROM bookings WHERE status IN ('confirmed','completed') AND start_dt>=? AND start_dt<=?",
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
        "SELECT * FROM bookings WHERE status IN ('confirmed','completed') AND start_dt>=? ORDER BY start_dt ASC LIMIT 5",
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

    dashboard["year_revenue"] = con.execute(
        "SELECT COALESCE(SUM(price),0) FROM bookings WHERE status IN ('confirmed','completed') AND start_dt>=? AND start_dt<?",
        (dtstr(year_start), dtstr(next_year)),
    ).fetchone()[0]
    dashboard["week_revenue"] = con.execute(
        "SELECT COALESCE(SUM(price),0) FROM bookings WHERE status IN ('confirmed','completed') AND start_dt>=? AND start_dt<?",
        (dtstr(week_start), dtstr(week_end)),
    ).fetchone()[0]
    dashboard["average_booking"] = round(con.execute(
        "SELECT COALESCE(AVG(price),0) FROM bookings WHERE status IN ('confirmed','completed')"
    ).fetchone()[0])
    dashboard["confirmed_total"] = con.execute(
        "SELECT COUNT(*) FROM bookings WHERE status IN ('confirmed','completed')"
    ).fetchone()[0]
    dashboard["confirmation_rate"] = round(
        100 * dashboard["confirmed_total"] /
        max(1, dashboard["confirmed_total"] + counts["cancelled"])
    )
    dashboard["action_count"] = counts["pending"] + dashboard["reviews_pending"]

    soon_end = today_start + timedelta(days=4)

    today_bookings = con.execute(
        "SELECT * FROM bookings WHERE status!='cancelled' AND start_dt>=? AND start_dt<? ORDER BY start_dt ASC",
        (dtstr(today_start), dtstr(today_end)),
    ).fetchall()
    soon_bookings = con.execute(
        """SELECT * FROM bookings
           WHERE status!='cancelled' AND start_dt>=? AND start_dt<?
           ORDER BY start_dt ASC""",
        (dtstr(today_start), dtstr(soon_end)),
    ).fetchall()
    later_bookings = con.execute(
        """SELECT * FROM bookings
           WHERE status!='cancelled' AND start_dt>=?
           ORDER BY start_dt ASC""",
        (dtstr(soon_end),),
    ).fetchall()
    past_bookings = con.execute(
        """SELECT * FROM bookings
           WHERE start_dt<?
           ORDER BY start_dt DESC
           LIMIT 100""",
        (dtstr(today_start),),
    ).fetchall()

    pending_bookings = con.execute(
        "SELECT * FROM bookings WHERE status='pending' ORDER BY created_at DESC LIMIT 10"
    ).fetchall()
    clients_preview = con.execute(
        """SELECT email, MAX(pseudo) AS pseudo,
                  MAX(COALESCE(twitter,'')) AS twitter,
                  COUNT(*) AS total_bookings,
                  SUM(CASE WHEN status IN ('confirmed','completed') THEN 1 ELSE 0 END) AS confirmed_bookings,
                  COALESCE(SUM(CASE WHEN status IN ('confirmed','completed') THEN price ELSE 0 END),0) AS total_spent,
                  MAX(start_dt) AS last_booking
           FROM bookings GROUP BY email ORDER BY last_booking DESC LIMIT 40"""
    ).fetchall()

    con.close()
    return render_template(
        "admin.html",
        bookings=bookings,
        blocks=blocks,
        counts=counts,
        dashboard=dashboard,
        monthly_chart=monthly_chart,
        upcoming_bookings=upcoming_bookings,
        status_filter=status_filter,
        search_query=search_query,
        calendar_bookings=calendar_bookings,
        calendar_blocks=calendar_blocks,
        today_bookings=today_bookings,
        soon_bookings=soon_bookings,
        later_bookings=later_bookings,
        past_bookings=past_bookings,
        pending_bookings=pending_bookings,
        clients_preview=clients_preview,
        focus_booking=request.args.get("booking", ""),
    )


@app.get("/admin/clients")
def admin_clients():
    if not session.get("admin"):
        return redirect(url_for("login"))

    query = request.args.get("q", "").strip()
    params = []
    where = ""

    if query:
        where = "WHERE b.email LIKE ? OR b.pseudo LIKE ? OR COALESCE(b.twitter,'') LIKE ?"
        term = f"%{query}%"
        params = [term, term, term]

    con = db()
    clients = con.execute(
        f"""
        SELECT
          b.email,
          MAX(b.pseudo) AS pseudo,
          MAX(COALESCE(b.twitter,'')) AS twitter,
          COUNT(*) AS total_bookings,
          SUM(CASE WHEN b.status IN ('confirmed','completed') THEN 1 ELSE 0 END) AS confirmed_bookings,
          COALESCE(SUM(CASE WHEN b.status IN ('confirmed','completed') THEN b.price ELSE 0 END),0) AS total_spent,
          MAX(b.start_dt) AS last_booking,
          MIN(b.created_at) AS first_seen,
          COALESCE(n.note,'') AS note
        FROM bookings b
        LEFT JOIN customer_notes n ON n.email=b.email
        {where}
        GROUP BY b.email
        ORDER BY last_booking DESC
        """,
        params,
    ).fetchall()

    stats = {
        "total_clients": con.execute(
            "SELECT COUNT(DISTINCT email) FROM bookings"
        ).fetchone()[0],
        "returning_clients": con.execute(
            """SELECT COUNT(*) FROM (
                 SELECT email FROM bookings
                 WHERE status IN ('confirmed','completed')
                 GROUP BY email HAVING COUNT(*) >= 2
               )"""
        ).fetchone()[0],
        "vip_clients": con.execute(
            """SELECT COUNT(*) FROM (
                 SELECT email FROM bookings
                 WHERE status IN ('confirmed','completed')
                 GROUP BY email HAVING SUM(price) >= 500
               )"""
        ).fetchone()[0],
    }

    con.close()
    return render_template(
        "admin-clients.html",
        clients=clients,
        stats=stats,
        search_query=query,
    )


@app.get("/admin/clients/<path:email>")
def admin_client_detail(email):
    if not session.get("admin"):
        return redirect(url_for("login"))

    con = db()
    bookings = con.execute(
        "SELECT * FROM bookings WHERE email=? ORDER BY start_dt DESC",
        (email,),
    ).fetchall()
    reviews = con.execute(
        "SELECT * FROM reviews WHERE email=? ORDER BY created_at DESC",
        (email,),
    ).fetchall()
    note_row = con.execute(
        "SELECT note FROM customer_notes WHERE email=?",
        (email,),
    ).fetchone()

    if not bookings:
        con.close()
        abort(404)

    summary = {
        "pseudo": bookings[0]["pseudo"],
        "email": email,
        "twitter": next((b["twitter"] for b in bookings if b["twitter"]), ""),
        "total_bookings": len(bookings),
        "confirmed_bookings": sum(1 for b in bookings if b["status"] == "confirmed"),
        "total_spent": sum(b["price"] for b in bookings if b["status"] == "confirmed"),
        "first_seen": bookings[-1]["created_at"],
        "last_booking": bookings[0]["start_dt"],
    }
    con.close()

    return render_template(
        "admin-client.html",
        client=summary,
        bookings=bookings,
        reviews=reviews,
        note=note_row["note"] if note_row else "",
    )


@app.post("/admin/clients/<path:email>/note")
def admin_client_note(email):
    if not session.get("admin"):
        abort(403)

    note = request.form.get("note", "").strip()[:3000]
    con = db()
    con.execute(
        """INSERT INTO customer_notes(email,note,updated_at)
           VALUES(?,?,?)
           ON CONFLICT(email) DO UPDATE SET
             note=excluded.note,
             updated_at=excluded.updated_at""",
        (email, note, dtstr(datetime.now())),
    )
    con.commit()
    con.close()
    flash("Note client enregistrée.")
    return redirect(url_for("admin_client_detail", email=email))




@app.post("/admin/client/delete")
def admin_delete_client():
    if not session.get("admin"):
        abort(403)

    email = request.form.get("email", "").strip()
    if not email:
        abort(400)

    con = db()
    future_confirmed = con.execute(
        """SELECT COUNT(*) FROM bookings
           WHERE email=? AND status='confirmed' AND start_dt>=?""",
        (email, dtstr(datetime.now())),
    ).fetchone()[0]

    if future_confirmed:
        con.close()
        flash("Impossible de supprimer ce client : un rendez-vous futur est confirmé.")
        return redirect(url_for("admin"))

    con.execute("DELETE FROM customer_notes WHERE email=?", (email,))
    con.execute("DELETE FROM reviews WHERE email=?", (email,))
    con.execute("DELETE FROM bookings WHERE email=?", (email,))
    con.commit()
    con.close()
    flash("Fiche client supprimée définitivement.")
    return redirect(url_for("admin"))


@app.post("/admin/assistant")
def admin_assistant():
    if not session.get("admin"):
        abort(403)

    data = request.get_json(silent=True) or {}
    question = (data.get("question") or "").strip().lower()
    if not question:
        return jsonify({"answer": "Écris une question sur tes revenus, tes rendez-vous ou tes clients."})

    now = datetime.now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    today_end = today_start + timedelta(days=1)
    tomorrow_start = today_end
    tomorrow_end = tomorrow_start + timedelta(days=1)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    next_month = (
        month_start.replace(year=month_start.year + 1, month=1)
        if month_start.month == 12
        else month_start.replace(month=month_start.month + 1)
    )

    con = db()
    answer = None

    if any(word in question for word in ("demain", "rendez-vous demain", "rdv demain")):
        rows = con.execute(
            """SELECT pseudo,start_dt,price,status FROM bookings
               WHERE status!='cancelled' AND start_dt>=? AND start_dt<?
               ORDER BY start_dt""",
            (dtstr(tomorrow_start), dtstr(tomorrow_end)),
        ).fetchall()
        if rows:
            details = ", ".join(
                f"{r['pseudo']} à {r['start_dt'][11:16]} ({r['price']} €, {r['status']})"
                for r in rows
            )
            answer = f"Demain : {details}."
        else:
            answer = "Tu n’as aucun rendez-vous prévu demain."

    elif any(word in question for word in ("ce mois", "mois-ci", "gagné ce mois", "revenu mois")):
        amount = con.execute(
            """SELECT COALESCE(SUM(price),0) FROM bookings
               WHERE status IN ('confirmed','completed') AND start_dt>=? AND start_dt<?""",
            (dtstr(month_start), dtstr(next_month)),
        ).fetchone()[0]
        answer = f"Ton chiffre d’affaires confirmé ce mois-ci est de {amount} €."

    elif any(word in question for word in ("aujourd'hui", "aujourd’hui", "rdv aujourd", "rendez-vous aujourd")):
        rows = con.execute(
            """SELECT pseudo,start_dt,price,status FROM bookings
               WHERE status!='cancelled' AND start_dt>=? AND start_dt<?
               ORDER BY start_dt""",
            (dtstr(today_start), dtstr(today_end)),
        ).fetchall()
        if rows:
            details = ", ".join(
                f"{r['pseudo']} à {r['start_dt'][11:16]} ({r['price']} €, {r['status']})"
                for r in rows
            )
            answer = f"Aujourd’hui : {details}."
        else:
            answer = "Tu n’as aucun rendez-vous aujourd’hui."

    elif any(word in question for word in ("meilleur client", "client vip", "plus dépensé")):
        row = con.execute(
            """SELECT MAX(pseudo) AS pseudo, email,
                      SUM(price) AS total_spent,
                      COUNT(*) AS visits
               FROM bookings
               WHERE status IN ('confirmed','completed')
               GROUP BY email
               ORDER BY total_spent DESC
               LIMIT 1"""
        ).fetchone()
        if row:
            answer = (
                f"Ton meilleur client est {row['pseudo']} avec "
                f"{row['total_spent']} € confirmés sur {row['visits']} séance(s)."
            )
        else:
            answer = "Aucun client confirmé pour le moment."

    elif any(word in question for word in ("en attente", "à confirmer", "a traiter", "à traiter")):
        count = con.execute(
            "SELECT COUNT(*) FROM bookings WHERE status='pending'"
        ).fetchone()[0]
        answer = f"Tu as {count} réservation(s) en attente de traitement."

    elif any(word in question for word in ("total", "depuis le début", "tout gagné")):
        amount = con.execute(
            "SELECT COALESCE(SUM(price),0) FROM bookings WHERE status IN ('confirmed','completed')"
        ).fetchone()[0]
        answer = f"Ton chiffre d’affaires confirmé total est de {amount} €."

    else:
        answer = (
            "Je peux répondre à : « combien ce mois-ci ? », « mes rendez-vous demain », "
            "« qui est mon meilleur client ? », « combien en attente ? » ou « total depuis le début ? »."
        )

    con.close()
    return jsonify({"answer": answer})


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
    if action not in ("confirm","cancel","complete"):
        abort(400)
    con = db()
    b = con.execute("SELECT * FROM bookings WHERE id=?", (booking_id,)).fetchone()
    if not b:
        con.close(); abort(404)

    if action == "confirm":
        status = "confirmed"
        con.execute(
            "UPDATE bookings SET status=?, hold_expires_at=NULL WHERE id=?",
            (status, booking_id),
        )
    elif action == "complete":
        status = "completed"
        con.execute(
            "UPDATE bookings SET status=?, completed_at=?, hold_expires_at=NULL WHERE id=?",
            (status, dtstr(datetime.now()), booking_id),
        )
    else:
        status = "cancelled"
        con.execute(
            "UPDATE bookings SET status=?, hold_expires_at=NULL WHERE id=?",
            (status, booking_id),
        )
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



@app.post("/admin/booking/<int:booking_id>/move")
def admin_move_booking(booking_id):
    if not session.get("admin"):
        abort(403)

    start_raw = request.form.get("start_dt", "").strip()
    send_confirmation = request.form.get("send_confirmation") == "1"

    try:
        new_start = parse_dt(start_raw)
    except (ValueError, TypeError):
        flash("Date ou heure invalide.")
        return redirect(url_for("admin", booking=booking_id))

    con = db()
    booking = con.execute("SELECT * FROM bookings WHERE id=?", (booking_id,)).fetchone()
    con.close()
    if not booking:
        abort(404)

    duration = int(booking["duration_minutes"])
    new_end = new_start + timedelta(minutes=duration)

    if booking_conflict(new_start, new_end, ignore_id=booking_id):
        flash("Ce nouveau créneau est déjà occupé ou bloqué.")
        return redirect(url_for("admin", booking=booking_id))

    con = db()
    con.execute(
        "UPDATE bookings SET start_dt=?, end_dt=? WHERE id=?",
        (dtstr(new_start), dtstr(new_end), booking_id),
    )
    con.commit()
    con.close()

    if send_confirmation and booking["email"]:
        details = email_details([
            ("Nouvelle date", new_start.strftime("%d/%m/%Y à %H:%M")),
            ("Durée", f"{duration} minutes"),
            ("Montant", f"{booking['price']} €"),
        ])
        send_email(
            booking["email"],
            "Votre rendez-vous a été déplacé — Maîtresse Lana",
            f"Votre rendez-vous a été déplacé au {new_start.strftime('%d/%m/%Y à %H:%M')}.",
            email_layout(
                "Rendez-vous déplacé",
                "Votre rendez-vous a été reprogrammé.",
                details,
                "Merci de prendre note de cette nouvelle date.",
            ),
        )

    send_push_notification(
        "Rendez-vous déplacé",
        f"{booking['pseudo']} · {new_start.strftime('%d/%m à %H:%M')}",
        f"/admin?booking={booking_id}",
    )
    flash("Rendez-vous déplacé.")
    return redirect(url_for("admin", booking=booking_id))


@app.post("/admin/booking/<int:booking_id>/propose")
def admin_propose_slots(booking_id):
    if not session.get("admin"):
        abort(403)

    try:
        slot1 = parse_dt(request.form.get("slot1_start", "").strip())
        slot2 = parse_dt(request.form.get("slot2_start", "").strip())
        expires_hours = int(request.form.get("expires_hours", "48"))
    except (ValueError, TypeError):
        flash("Vérifie les deux créneaux proposés.")
        return redirect(url_for("admin", booking=booking_id))

    if slot1 == slot2:
        flash("Les deux propositions doivent être différentes.")
        return redirect(url_for("admin", booking=booking_id))

    con = db()
    booking = con.execute("SELECT * FROM bookings WHERE id=?", (booking_id,)).fetchone()
    con.close()
    if not booking:
        abort(404)
    if not booking["email"]:
        flash("Ce client n’a pas d’adresse e-mail.")
        return redirect(url_for("admin", booking=booking_id))

    duration = int(booking["duration_minutes"])
    for slot in (slot1, slot2):
        if booking_conflict(slot, slot + timedelta(minutes=duration), ignore_id=booking_id):
            flash("Un des deux créneaux est déjà occupé ou bloqué.")
            return redirect(url_for("admin", booking=booking_id))

    token = secrets.token_urlsafe(32)
    expires_at = datetime.now() + timedelta(hours=max(1, min(expires_hours, 168)))

    con = db()
    con.execute(
        "DELETE FROM reschedule_proposals WHERE booking_id=? AND chosen_slot IS NULL",
        (booking_id,),
    )
    con.execute(
        """INSERT INTO reschedule_proposals(
             token,booking_id,slot1_start,slot2_start,expires_at,created_at
           ) VALUES(?,?,?,?,?,?)""",
        (
            token, booking_id, dtstr(slot1), dtstr(slot2),
            dtstr(expires_at), dtstr(datetime.now()),
        ),
    )
    con.commit()
    con.close()

    choice_url = url_for("choose_reschedule", token=token, _external=True)
    details = email_details([
        ("Proposition 1", slot1.strftime("%d/%m/%Y à %H:%M")),
        ("Proposition 2", slot2.strftime("%d/%m/%Y à %H:%M")),
        ("Lien de choix", f'<a href="{choice_url}" style="color:#e4c47f;">Choisir mon créneau</a>'),
    ])
    send_email(
        booking["email"],
        "Choisissez un nouveau créneau — Maîtresse Lana",
        (
            "Votre rendez-vous doit être reprogrammé.\n\n"
            f"Choix 1 : {slot1.strftime('%d/%m/%Y à %H:%M')}\n"
            f"Choix 2 : {slot2.strftime('%d/%m/%Y à %H:%M')}\n\n"
            f"Choisissez ici : {choice_url}"
        ),
        email_layout(
            "Reprogrammation",
            "Merci de choisir l’un des deux nouveaux créneaux proposés.",
            details,
            f"Ce lien expire le {expires_at.strftime('%d/%m/%Y à %H:%M')}.",
        ),
    )
    flash("Les deux créneaux ont été envoyés au client.")
    return redirect(url_for("admin", booking=booking_id))


@app.route("/reprogrammer/<token>", methods=["GET", "POST"])
def choose_reschedule(token):
    con = db()
    proposal = con.execute(
        """SELECT p.*, b.pseudo, b.email, b.duration_minutes, b.price
           FROM reschedule_proposals p
           JOIN bookings b ON b.id=p.booking_id
           WHERE p.token=?""",
        (token,),
    ).fetchone()
    con.close()

    if not proposal:
        return render_template("reprogrammer.html", error="Ce lien est invalide."), 404

    expired = parse_dt(proposal["expires_at"]) < datetime.now()
    already_chosen = proposal["chosen_slot"] is not None

    if request.method == "POST":
        if expired or already_chosen:
            return render_template(
                "reprogrammer.html",
                proposal=proposal,
                error="Cette proposition a expiré ou a déjà été utilisée.",
            ), 400

        try:
            choice = int(request.form.get("choice", "0"))
        except ValueError:
            choice = 0
        if choice not in (1, 2):
            abort(400)

        chosen_start = parse_dt(proposal[f"slot{choice}_start"])
        chosen_end = chosen_start + timedelta(minutes=int(proposal["duration_minutes"]))

        if booking_conflict(chosen_start, chosen_end, ignore_id=proposal["booking_id"]):
            return render_template(
                "reprogrammer.html",
                proposal=proposal,
                error="Ce créneau vient d’être pris. Merci de choisir l’autre proposition.",
            ), 409

        con = db()
        con.execute(
            """UPDATE bookings
               SET start_dt=?, end_dt=?, status='confirmed', hold_expires_at=NULL
               WHERE id=?""",
            (dtstr(chosen_start), dtstr(chosen_end), proposal["booking_id"]),
        )
        con.execute(
            """UPDATE reschedule_proposals
               SET chosen_slot=?, chosen_at=?
               WHERE id=?""",
            (choice, dtstr(datetime.now()), proposal["id"]),
        )
        con.commit()
        con.close()

        details = email_details([
            ("Date choisie", chosen_start.strftime("%d/%m/%Y à %H:%M")),
            ("Durée", f"{proposal['duration_minutes']} minutes"),
            ("Montant", f"{proposal['price']} €"),
        ])
        send_email(
            proposal["email"],
            "Nouveau rendez-vous confirmé — Maîtresse Lana",
            f"Votre nouveau rendez-vous est confirmé le {chosen_start.strftime('%d/%m/%Y à %H:%M')}.",
            email_layout(
                "Nouveau créneau confirmé",
                "Votre choix a bien été enregistré.",
                details,
                "À bientôt.",
            ),
        )
        send_email(
            BOOKING_EMAIL,
            f"Nouveau créneau choisi par {proposal['pseudo']}",
            f"{proposal['pseudo']} a choisi le {chosen_start.strftime('%d/%m/%Y à %H:%M')}.",
        )
        send_push_notification(
            "Créneau choisi",
            f"{proposal['pseudo']} · {chosen_start.strftime('%d/%m à %H:%M')}",
            f"/admin?booking={proposal['booking_id']}",
        )
        return render_template(
            "reprogrammer.html",
            proposal=proposal,
            success=True,
            chosen_start=chosen_start,
        )

    return render_template(
        "reprogrammer.html",
        proposal=proposal,
        expired=expired,
        already_chosen=already_chosen,
    )


@app.post("/admin/booking/create")
def admin_create_booking():
    if not session.get("admin"):
        abort(403)

    pseudo = request.form.get("pseudo", "").strip()
    email = request.form.get("email", "").strip()
    twitter = request.form.get("twitter", "").strip()
    start_raw = request.form.get("start_dt", "").strip()
    practices = request.form.get("practices", "").strip()
    private_notes = request.form.get("private_notes", "").strip()
    payment_method = request.form.get("payment_method", "").strip()
    send_confirmation = request.form.get("send_confirmation") == "1"
    status = request.form.get("status", "confirmed").strip()

    try:
        duration_minutes = int(request.form.get("duration_minutes", "0"))
        price = int(request.form.get("price", "0"))
        deposit = int(request.form.get("deposit", "0") or 0)
        start = parse_dt(start_raw)
    except (ValueError, TypeError):
        flash("Vérifie la date, la durée et les montants.")
        return redirect(url_for("admin"))

    if status not in ("pending", "confirmed", "completed"):
        status = "confirmed"
    if not pseudo or duration_minutes <= 0 or price < 0:
        flash("Pseudo, durée et prix sont obligatoires.")
        return redirect(url_for("admin"))

    end = start + timedelta(minutes=duration_minutes)
    if booking_conflict(start, end):
        flash("Ce créneau est déjà occupé ou bloqué.")
        return redirect(url_for("admin"))

    con = db()
    con.execute(
        """INSERT INTO bookings(
             created_at,pseudo,email,age,twitter,message,service_id,
             duration_minutes,price,deposit,start_dt,end_dt,status,
             hold_expires_at,payment_method,practices,private_notes,completed_at
           ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            dtstr(datetime.now()), pseudo[:80], email[:160], 18,
            twitter[:120], "", "custom", duration_minutes, price, deposit,
            dtstr(start), dtstr(end), status, None, payment_method[:80],
            practices[:3000], private_notes[:3000],
            dtstr(datetime.now()) if status == "completed" else None,
        ),
    )
    booking_id = con.execute("SELECT last_insert_rowid()").fetchone()[0]
    con.commit()
    con.close()

    if send_confirmation and email:
        details = email_details([
            ("Date", start.strftime("%d/%m/%Y à %H:%M")),
            ("Durée", f"{duration_minutes} minutes"),
            ("Montant", f"{price} €"),
        ])
        send_email(
            email,
            "Votre rendez-vous — Maîtresse Lana",
            f"Votre rendez-vous est prévu le {start.strftime('%d/%m/%Y à %H:%M')}.",
            email_layout(
                "Rendez-vous créé",
                "Votre rendez-vous a bien été ajouté au planning.",
                details,
                "Conservez cet e-mail comme confirmation.",
            ),
        )

    flash(f"Rendez-vous #{booking_id} créé.")
    return redirect(url_for("admin", booking=booking_id))



@app.route("/admin/booking/<int:booking_id>/edit", methods=["GET", "POST"])
def admin_booking_edit(booking_id):
    if not session.get("admin"):
        return redirect(url_for("login"))

    con = db()
    booking = con.execute("SELECT * FROM bookings WHERE id=?", (booking_id,)).fetchone()
    con.close()
    if not booking:
        abort(404)

    if request.method == "POST":
        try:
            start = parse_dt(request.form.get("start_dt", "").strip())
            duration_minutes = int(request.form.get("duration_minutes", "0"))
            price = int(request.form.get("price", "0"))
            deposit = int(request.form.get("deposit", "0") or 0)
        except (ValueError, TypeError):
            flash("Vérifie la date, la durée, le prix et l’acompte.")
            return redirect(url_for("admin_booking_edit", booking_id=booking_id))

        payment_method = request.form.get("payment_method", "").strip()[:80]
        status = request.form.get("status", booking["status"]).strip()
        if status not in ("pending", "confirmed", "completed", "cancelled"):
            status = booking["status"]

        if duration_minutes <= 0 or price < 0 or deposit < 0:
            flash("La durée doit être positive et les montants ne peuvent pas être négatifs.")
            return redirect(url_for("admin_booking_edit", booking_id=booking_id))

        end = start + timedelta(minutes=duration_minutes)
        if booking_conflict(start, end, ignore_id=booking_id):
            flash("Cette modification crée un conflit avec un autre rendez-vous ou un blocage.")
            return redirect(url_for("admin_booking_edit", booking_id=booking_id))

        completed_at = booking["completed_at"]
        if status == "completed" and not completed_at:
            completed_at = dtstr(datetime.now())
        elif status != "completed":
            completed_at = None

        con = db()
        con.execute(
            """UPDATE bookings
               SET start_dt=?, end_dt=?, duration_minutes=?, price=?, deposit=?,
                   payment_method=?, status=?, completed_at=?, hold_expires_at=NULL
               WHERE id=?""",
            (
                dtstr(start), dtstr(end), duration_minutes, price, deposit,
                payment_method, status, completed_at, booking_id,
            ),
        )
        con.commit()
        con.close()

        flash("Rendez-vous modifié.")
        return redirect(
            url_for("admin_client_detail", email=booking["email"], booking=booking_id)
        )

    return render_template("admin-booking-edit.html", booking=booking)


@app.route("/admin/booking/<int:booking_id>/notes-page", methods=["GET", "POST"])
def admin_booking_notes_page(booking_id):
    if not session.get("admin"):
        return redirect(url_for("login"))

    con = db()
    booking = con.execute("SELECT * FROM bookings WHERE id=?", (booking_id,)).fetchone()
    if not booking:
        con.close()
        abort(404)

    note_row = con.execute(
        "SELECT note FROM customer_notes WHERE email=?",
        (booking["email"],),
    ).fetchone()

    if request.method == "POST":
        practices = request.form.get("practices", "").strip()[:3000]
        private_notes = request.form.get("private_notes", "").strip()[:3000]
        client_note = request.form.get("client_note", "").strip()[:3000]

        con.execute(
            "UPDATE bookings SET practices=?, private_notes=? WHERE id=?",
            (practices, private_notes, booking_id),
        )
        con.execute(
            """INSERT INTO customer_notes(email,note,updated_at)
               VALUES(?,?,?)
               ON CONFLICT(email) DO UPDATE SET
                 note=excluded.note,
                 updated_at=excluded.updated_at""",
            (booking["email"], client_note, dtstr(datetime.now())),
        )
        con.commit()
        con.close()

        flash("Notes enregistrées.")
        return redirect(
            url_for("admin_client_detail", email=booking["email"], booking=booking_id)
        )

    con.close()
    return render_template(
        "admin-booking-notes.html",
        booking=booking,
        client_note=note_row["note"] if note_row else "",
    )


@app.post("/admin/booking/<int:booking_id>/notes")
def admin_booking_notes(booking_id):
    if not session.get("admin"):
        abort(403)
    practices = request.form.get("practices", "").strip()
    private_notes = request.form.get("private_notes", "").strip()
    con = db()
    con.execute(
        "UPDATE bookings SET practices=?, private_notes=? WHERE id=?",
        (practices[:3000], private_notes[:3000], booking_id),
    )
    con.commit()
    con.close()
    flash("Notes enregistrées.")
    return redirect(url_for("admin", booking=booking_id))


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
@app.post("/admin/block-day")
def admin_block_day():
    if not session.get("admin"):
        abort(403)
    try:
        day = datetime.strptime(request.form.get("date", ""), "%Y-%m-%d").date()
    except ValueError:
        flash("Date invalide.")
        return redirect(url_for("admin") + "#planning")
    start = datetime.combine(day, datetime.min.time()).replace(hour=17)
    end = datetime.combine(day + timedelta(days=1), datetime.min.time())
    note = request.form.get("note", "").strip() or "Journée bloquée"
    con = db()
    con.execute("INSERT INTO blocks(start_dt,end_dt,note) VALUES(?,?,?)", (dtstr(start), dtstr(end), note))
    con.commit(); con.close()
    flash("Journée complète bloquée.")
    return redirect(url_for("admin") + "#planning")


@app.post("/admin/block-range")
def admin_block_range():
    if not session.get("admin"):
        abort(403)
    try:
        start_day = datetime.strptime(request.form.get("start_date", ""), "%Y-%m-%d").date()
        end_day = datetime.strptime(request.form.get("end_date", ""), "%Y-%m-%d").date()
    except ValueError:
        flash("Dates invalides.")
        return redirect(url_for("admin") + "#planning")
    if end_day < start_day:
        flash("La date de fin doit être après la date de début.")
        return redirect(url_for("admin") + "#planning")
    start = datetime.combine(start_day, datetime.min.time()).replace(hour=17)
    end = datetime.combine(end_day + timedelta(days=1), datetime.min.time())
    note = request.form.get("note", "").strip() or "Indisponibilité prolongée"
    con = db()
    con.execute("INSERT INTO blocks(start_dt,end_dt,note) VALUES(?,?,?)", (dtstr(start), dtstr(end), note))
    con.commit(); con.close()
    flash("Période bloquée.")
    return redirect(url_for("admin") + "#planning")


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
