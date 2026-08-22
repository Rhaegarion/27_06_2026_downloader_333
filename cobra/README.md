# COBRA — setup

## 1. Environment
```bash
python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # Linux/Mac (dev only)
pip install -r requirements.txt
```

## 2. Database
1. Create the DB on this office's MySQL server, e.g. `CREATE DATABASE cobra_db;`
2. Run `schema/name_details.sql` against it.
3. Copy `.env.example` to `.env` and fill in `DB_HOST`, `DB_USER`, `DB_PASSWORD`, `DB_NAME`, and a random `SECRET_KEY`.

## 3. Run (dev)
```bash
python run.py
```
Visit http://127.0.0.1:5000 — it redirects to the login page.
There's no seeded user yet: use "Create an account" on the login screen to make the first one.

## 4. What's built so far
- Login (`/login`) and account creation (`/register`) against `name_details`, bcrypt-hashed passwords.
- A placeholder dashboard (`/dashboard`) with a module grid for the pages still to come
  (New Report, VOIP/IP tables, OSINT, WAN allocation & utilization).
- Design system lives in `app/static/css/main.css` — colors/fonts are CSS variables at the top,
  reuse those rather than hardcoding new values as new pages get built.
- Fonts (Space Grotesk / IBM Plex Sans / IBM Plex Mono) are self-hosted under
  `app/static/fonts/` since offices run offline — no Google Fonts dependency.

## Not built yet (flagged so nothing's assumed silently)
- Report generation page (JSON/XML extraction → Word doc, file copy by msg no)
- VOIP / IP table search & edit
- OSINT injection + view
- WAN allocation & utilization
- PyInstaller/Waitress packaging into a distributable .exe
