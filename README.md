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
- Customer storefront with email accounts, product search and filters, product
  details, cart and checkout, order tracking, and verified-purchase reviews.
- Demo payment choices for COD, ABA PayWay, KHQR, and cards; no real payment
  processing or third-party identity provider is configured.
- Animated responsive storefront with 3D product-card interactions and reduced
  motion support.
- Responsive interface, SQLite persistence, and a standard-library Python API.

## Run locally

Requires Python 3.10 or later; no third-party packages are needed.

```powershell
cd computer-sales-system
$env:ADMIN_USERNAME = "admin"
$env:ADMIN_PASSWORD = "ChangeThisLocalPassword!"
python -m apps.api.main
```

Open <http://127.0.0.1:8000>. The initial catalog is seeded on first run. Set
`DATA_DIR` to change the SQLite database location and `PORT` to change the
listening port. Local-development defaults are `admin` / `ChangeMe123!`; set
your own password before using the app with real data.

The local server binds to loopback by default. Do not expose it directly to the
internet. For a real deployment, place it behind an HTTPS reverse proxy, use a
managed identity provider and a production-grade database, and set
`APP_ENV=production` with a non-default `ADMIN_PASSWORD`.

## Security alerts

The administrator dashboard records failed sign-ins, unauthorized requests,
server errors, and health-check/database failures. It refreshes its event list
every 15 seconds while the dashboard is open. Telegram delivery runs in a
background worker and coalesces repeated events by category for 60 seconds by
default; adjust `SECURITY_ALERT_COOLDOWN_SECONDS` if needed.

To enable Telegram delivery, create a bot with Telegram's official BotFather,
obtain the destination chat ID, and configure both values as environment
variables on the server. Never paste the bot token into source code, a browser,
or chat:

```powershell
$env:TELEGRAM_BOT_TOKEN = "your-bot-token"
$env:TELEGRAM_CHAT_ID = "your-chat-id"
$env:SECURITY_ALERT_COOLDOWN_SECONDS = "60"
python -m apps.api.main
```

The dashboard indicates whether Telegram settings are present. Alert messages
contain a generic event summary and API route only; passwords, request bodies,
and IP addresses are not included. Test delivery with a failed sign-in after
the server starts. Telegram delivery requires outbound HTTPS access. If the
entire host or server process is offline, it cannot send its own alert; use an
external uptime monitor against `/api/health` for that failure mode.

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

## Customer storefront

Open the site and choose **ចូលទៅកាន់ហាងអនឡាញ** to browse the public product
catalog. Customers can register with email and a password, save a delivery
address, place orders, and review products after a purchase. Google and
Facebook sign-in are not configured. Payment method options are demonstrations
only; connect a provider's hosted checkout and configure its credentials
separately before accepting payments.

The storefront UI includes 3D hover effects and entrance animations. Animations
are disabled for users who enable reduced motion in their operating system.

## API overview

Private API routes require the HTTP-only session cookie with the appropriate
administrator or customer role. The catalog and customer sign-in/registration
routes are public.

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/health` | Liveness check |
| GET | `/api/session` | Current session role |
| GET | `/api/security/events` | Administrator security event log |
| POST | `/api/login` | Sign in |
| POST | `/api/logout` | Sign out |
| GET | `/api/dashboard` | Dashboard metrics |
| GET, POST | `/api/products` | List or create products |
| PUT, DELETE | `/api/products/{id}` | Update or archive a product |
| GET, POST | `/api/orders` | List orders or create a sale |
| GET | `/api/storefront/products` | Search and filter the public catalog |
| GET | `/api/storefront/products/{id}` | View product details and reviews |
| POST | `/api/customer/register` | Create a customer account |
| POST | `/api/customer/login` | Sign in to a customer account |
| GET, PUT | `/api/customer/profile` | View or update customer profile |
| GET, POST | `/api/customer/orders` | List or place customer orders |
| GET | `/api/customer/orders/{order_number}` | Track an order |
| GET, POST | `/api/products/{id}/reviews` | List or add verified-purchase reviews |

Run the API test suite from this directory:

```powershell
python -m unittest discover -s apps/api/tests -v
```
