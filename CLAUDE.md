# Claude Code project guide

This is a single-shop computer sales web application. Keep all shop data
private; do not add public signup or tenant access without a separate
authorization and data-isolation design.

## Project map

- `apps/api/`: Python standard-library HTTP API, authentication, and SQLite.
- `apps/web/`: responsive Khmer web interface for desktop and mobile browsers.
- `docs/architecture.md`: architecture and production boundaries.
- `render.yaml`: Render deployment Blueprint. Review cost and secrets in Render
  before creating a service.

## Local development

Requires Python 3.10 or later; there are no third-party packages.

From the repository root in PowerShell:

```powershell
$env:ADMIN_USERNAME = "admin"
$env:ADMIN_PASSWORD = "Use-A-Unique-Local-Password"
python -m apps.api.main
```

Open `http://127.0.0.1:8000` on the same computer. `127.0.0.1` is not reachable
from a phone or another computer. A public URL requires deploying to a hosting
provider; opening or editing the project in Claude Code does not host it.

Run backend tests:

```powershell
python -m unittest discover -s apps/api/tests -v
```

## Safety and verification

- Never commit `.env`, the `data/` directory, SQLite databases, passwords,
  access tokens, or provider credentials.
- Keep account creation admin-only and staff accounts least-privileged.
- Keep password hashes salted; never log submitted passwords.
- Test API behavior with the standard-library unit suite after backend changes.
- Keep the responsive UI usable on narrow phone screens and avoid external
  runtime dependencies without a clear need.
- Do not create paid cloud resources without the owner's confirmation at the
  provider's final cost and creation screen.
