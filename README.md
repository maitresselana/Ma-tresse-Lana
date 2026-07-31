
# Maîtresse Lana — vrai système de réservation

Cette version est un vrai petit site full-stack en Flask.

## Ce qui fonctionne
- choix de durée : 30 min / 1 h / 1 h 30 / 2 h
- disponibilités toutes les 30 minutes de 17:00 à 00:00
- réservation minimum 24 h à l'avance
- blocage automatique des créneaux qui se chevauchent
- maintien temporaire d'un créneau pendant 30 minutes après la demande
- espace admin privé pour confirmer / annuler les demandes
- espace admin pour bloquer manuellement des journées ou créneaux
- e-mails au client et à maitresselanaftt@gmail.com si SMTP est configuré
- PayPal + Throne
- photos intégrées
- règles : acompte non remboursable, déplacement 48 h avant, retard > 15 min = annulation

## Limite importante du paiement
Les liens PayPal.me et Throne ne permettent pas à ce site de vérifier automatiquement que le paiement a été effectué.
La demande reste donc "pending" jusqu'à ce que tu vérifies le paiement et cliques "Confirmer" dans l'admin.

## Lancer sur ordinateur
1. Installer Python 3.11+
2. `pip install -r requirements.txt`
3. Copier `.env.example` vers tes variables d'environnement
4. `python app.py`
5. Ouvrir http://127.0.0.1:5000
6. Espace privé : http://127.0.0.1:5000/admin

## E-mails avec Gmail
Utilise un mot de passe d'application Gmail, jamais ton mot de passe Gmail normal.
Variables :
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=maitresselanaftt@gmail.com
SMTP_PASSWORD=<mot de passe d'application>

## Mise en ligne
Le projet est prêt pour un hébergeur Python (Render, Railway, Fly.io, VPS, etc.).
Pour une vraie production durable, remplace SQLite par PostgreSQL ou utilise un disque persistant.
