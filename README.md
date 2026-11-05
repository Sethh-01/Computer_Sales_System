# Computer Sales System

A small, local-first computer shop management web app. The UI is in Khmer and
the default currency is USD. The original C++ lesson files in the workspace
are kept separate and unchanged.

## Features

- Sign-in protected shop dashboard with daily sales, active products, and low
  stock indicators.
- Product search, creation, editing, stock updates, and archiving.
- Multi-item checkout that validates stock and records the sale atomically.
- Order history with item and total details.
- Admin-only staff account creation with individually salted password hashes.
- Responsive background color themes saved in the current browser.
- Responsive interface, SQLite persistence, and a standard-library Python API.

## Run locally

Requires Python 3.10 or later; no third-party packages are needed.

```powershell
cd computer-sales-system
$env:ADMIN_USERNAME = "admin"
$env:ADMIN_PASSWORD = "ChangeThisLocalPassword!"
python -m apps.api.main
```

Open <http://127.0.0.1:8000>. The initial catalog and administrator account
are seeded on first run. Set `DATA_DIR` to change the SQLite database location
and `PORT` to change the listening port. Local-development defaults are
`admin` / `ChangeMe123!`; set your own password before using the app with real
data. The administrator credentials seed the account only once; changing the
environment variables later does not reset its stored password.

After signing in as the administrator, open **គ្រប់គ្រងគណនី** and choose
**បង្កើតគណនីថ្មី** to add staff accounts. Usernames are 3-40 letters, numbers,
dots, dashes, or underscores. Passwords must be at least 12 characters.
Accounts are stored in the local database with a per-account random salt and
PBKDF2 password hash. Staff can use the shop features but cannot manage
accounts. On mobile, use the bottom navigation to open account management; the
administrator can also start account creation from the dashboard. Public
sign-up is intentionally disabled.

Use the **ពណ៌ផ្ទៃ** button on the sign-in screen or the palette button in the
top bar to choose a background color. The selected theme is saved in that
browser and remains available before and after signing in.

The local server binds to loopback by default. Do not expose it directly to the
internet. For a real deployment, place it behind an HTTPS reverse proxy, use a
managed identity provider and a production-grade database, and set
`APP_ENV=production` with a non-default `ADMIN_PASSWORD`.

## Public deployment on Render

This repository includes a Render Blueprint in `render.yaml`. The configuration
uses a paid single-instance web service and a 1 GB persistent disk for SQLite.
Render's free service filesystem is ephemeral and cannot keep this shop's
database safely across restarts. A disk-backed service cannot be scaled to
multiple instances; use PostgreSQL and shared session storage before scaling.

To publish it:

1. Put this project folder in a GitHub repository and push the code. Keep the
   repository private if it contains business information.
2. Sign in to Render, choose **New → Blueprint**, and connect that repository.
3. Review the service plan and disk cost shown by Render before creating
   anything. The Blueprint does not create resources or incur charges until
   you approve the creation in your Render account.
4. When prompted, set `ADMIN_USERNAME` and a unique `ADMIN_PASSWORD` with at
   least 14 characters. Enter secrets only in Render's dashboard; never commit
   them or send them in chat.
5. After the first deploy is healthy, open the generated `*.onrender.com` URL,
   sign in as the admin, and create staff accounts. Do not enable public
   registration. Keep the admin password in a password manager.
6. Configure a custom domain later in Render if desired. Render provides HTTPS
   for its service hostname and for domains configured through its dashboard.
7. Test a sale and confirm it remains after a redeploy. Keep separate database
   backups for important sales records; a persistent disk is not a substitute
   for an independently stored backup.

If you already created a Render web service with the native Python runtime
instead of using the Blueprint, set its root directory to the repository root,
build command to `pip install -r requirements.txt`, and start command to
`python main.py`. The root launcher binds to `0.0.0.0` and uses Render's
`PORT`. Set `DATA_DIR` to the mount path of a persistent disk (for example
`/var/lib/computer-sales`) and set the admin credentials in Render's
environment settings. Configure `/api/health` as the health check path.

The app stays a single-shop, admin-managed system. Login has an in-process
limit of five failed attempts per username per 15 minutes. Sessions are
process-local and will expire on service restart. Before handling sensitive
customer data or substantial real sales, migrate to a supported production
identity/session service and a managed database with monitored backups.

## Project layout

```text
computer-sales-system/
├── apps/
│   ├── api/             Python HTTP API, auth, SQLite data access
│   └── web/             Static responsive frontend
├── data/                Generated SQLite database (not committed)
├── docs/                Architecture and operational notes
├── infra/               Container image and local compose setup
└── .github/workflows/   Automated API tests
```

## API overview

All API routes except `/api/health` and `POST /api/login` require the
HTTP-only session cookie.

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/health` | Liveness check |
| POST | `/api/login` | Sign in |
| POST | `/api/logout` | Sign out |
| GET | `/api/me` | Current signed-in user and role |
| GET | `/api/dashboard` | Dashboard metrics |
| GET, POST | `/api/accounts` | List accounts or create a staff account (admin only) |
| GET, POST | `/api/products` | List or create products |
| PUT, DELETE | `/api/products/{id}` | Update or archive a product |
| GET, POST | `/api/orders` | List orders or create a sale |

Run the API test suite from this directory:

```powershell
python -m unittest discover -s apps/api/tests -v
```
