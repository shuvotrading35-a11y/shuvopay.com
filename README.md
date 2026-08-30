# ShuvoPay — SMS Payment Verification Gateway

A production-ready platform that listens for incoming payment SMS on Android devices (bKash, Nagad, Rocket, Upay, and more) and automatically matches them to merchant invoices — with real-time WebSocket updates, HMAC-signed webhooks, and a full admin panel.

---

## Quick Start (Docker)

```bash
# 1. Clone and configure
git clone https://github.com/yourorg/shuvopay.git
cd shuvopay
cp .env.example .env
# Edit .env with your values (see .env.example for documentation)

# 2. Generate RSA keys for JWT
openssl genrsa -out private.pem 2048
openssl rsa -in private.pem -pubout -out public.pem
# Paste contents into JWT_PRIVATE_KEY and JWT_PUBLIC_KEY in .env

# 3. Generate AES key for SMS encryption
python3 -c "import secrets; print(secrets.token_hex(32))"
# Paste output into AES_ENCRYPTION_KEY in .env

# 4. Start everything
docker compose up -d

# 5. Run DB migrations + seed data
docker compose exec backend alembic upgrade head
docker compose exec backend python scripts/seed.py

# 6. Verify
curl http://localhost:8000/health
curl http://localhost:8000/health/ready
```

**That's it.** Services available at:
| Service | URL |
|---|---|
| API (FastAPI) | http://localhost:8000 |
| API Docs (Swagger) | http://localhost:8000/docs |
| Merchant Panel | http://localhost:3001 |
| Admin Panel | http://localhost:3002 |
| Grafana | http://localhost:3003 |
| Prometheus | http://localhost:9090 |

Default credentials from seed:
- **Admin:** `admin@shuvopay.com` / `(from ADMIN_PASSWORD in .env)`
- **Merchant 1:** `merchant1@shuvopay.dev` / `merchant123!`
- **Merchant 2:** `merchant2@shuvopay.dev` / `merchant123!`

---

## Architecture

```
Android Device (SMS BroadcastReceiver)
  → AES-256-GCM encrypt → Room DB offline queue
  → WorkManager (exponential backoff) → HTTPS API
  → Match Engine (async) → Invoice status update
  → WebSocket push → Merchant Panel (live)
  → HMAC-signed webhook → Merchant's server
  → Admin Panel (full visibility)
```

See [`docs/architecture/SYSTEM_DESIGN.md`](docs/architecture/SYSTEM_DESIGN.md) for full Mermaid diagrams.

---

## Features

### Android App
- **Kotlin + Jetpack Compose + MVI** — Clean Architecture throughout
- **Runtime SMS permission** — full plain-language explanation screen before request
- **Persistent foreground notification** — always visible when monitoring is active
- **AES-256-GCM** — SMS bodies encrypted on-device via Android Keystore before storage
- **Configurable regex parser** — rules fetched from backend, ETag-cached
- **Offline queue** — Room DB with WorkManager retry (15s→30s→1m→5m→15m, max 6 attempts)
- **OEM guidance** — in-app warnings for Xiaomi/MIUI, Samsung OneUI, Oppo/ColorOS battery kill
- **Built-in patterns** — bKash, Nagad, Rocket, Upay, DBBL, BRAC Bank, City Bank

### Backend (FastAPI)
- **JWT RS256** — asymmetric tokens, 15-min access + 7-day refresh (httpOnly cookie)
- **TOTP 2FA** — RFC 6238 via authenticator app (enforced for admin accounts)
- **Per-device API keys** — PBKDF2-hashed, rotatable, expirable
- **Match engine** — 5-factor weighted scoring (amount, time window, TxnID uniqueness, receiver account)
- **Replay protection** — `X-Request-ID` stored in Redis with 24h TTL
- **Webhook delivery** — HMAC-SHA256 signed, 7-attempt exponential backoff (10s→30s→2m→10m→30m→2h→6h)
- **Rate limiting** — Redis sliding window at app layer + Nginx backup
- **Audit log** — immutable, append-only, every sensitive action recorded
- **GDPR** — hard-delete endpoint, user data export

### Merchant Panel (Next.js)
- Live WebSocket dashboard with payment confirmation feed
- Invoice creation, cancellation, status tracking
- Webhook configuration, delivery logs, manual retry
- API key management
- Parser rule customization (JSON upload)
- CSV export

### Admin Panel (Next.js)
- System health: device count, SMS rate, queue depth, error rate
- Manual approve/reject for `REVIEW_REQUIRED` matches (with reason field)
- Full cross-merchant SMS logs + audit trail
- Global parser rule management
- User and merchant lifecycle management

---

## Project Structure

```
shuvopay/
├── android/                    # Kotlin Android App (MVI + Clean Architecture)
├── backend/                    # FastAPI backend (Python 3.12)
│   ├── app/
│   │   ├── api/v1/             # Routers: auth, device, sms, invoice, webhook, merchant, admin
│   │   ├── core/               # Security, config, middleware, deps, Redis client
│   │   ├── db/                 # SQLAlchemy models, session
│   │   └── workers/            # Match engine, webhook worker
│   └── alembic/versions/       # DB migrations
├── merchant-panel/             # Next.js 14 Merchant Dashboard
├── admin-panel/                # Next.js 14 Admin Dashboard
├── infrastructure/
│   ├── nginx/                  # TLS 1.3, HSTS, WebSocket upgrade, rate limiting
│   ├── prometheus/             # Metrics scraping config
│   └── grafana/                # Auto-provisioned dashboards
├── tests/
│   ├── unit/                   # Parser regex × 5 samples each, HMAC, AES, scoring
│   └── integration/            # Full API flow tests (httpx + pytest-asyncio)
├── docs/
│   ├── architecture/           # Mermaid system design, ERD, processing pipeline
│   ├── deployment/             # INSTALL.md, UPGRADE.md
│   └── sdk/                    # Webhook consumer guide (Python, PHP, Node.js)
├── scripts/seed.py             # Dev seed: 2 merchants, 5 devices, 50 SMS, 30 invoices
├── docker-compose.yml
└── .env.example
```

---

## Security

- TLS 1.3 only — HSTS with preload
- Certificate pinning in Android (OkHttp `CertificatePinner`)
- SMS raw text encrypted AES-256-GCM at rest (Android Keystore + backend DB)
- Webhook secrets bcrypt-hashed, revealed only once
- Rate limiting: per-IP + per-device + Nginx backup layer
- Audit log: immutable, append-only — no DELETE endpoint
- OWASP Top 10 mitigations throughout

See [`SECURITY.md`](SECURITY.md) for responsible disclosure policy.

---

## Monitoring

Prometheus metrics at `/metrics`:
- `sms_received_total` — labeled by provider
- `sms_matched_total` — labeled by status
- `webhook_delivery_duration_seconds` — histogram
- `match_engine_duration_seconds` — histogram
- `api_request_duration_seconds` — histogram by endpoint

Grafana dashboards (auto-provisioned):
- **System Overview** — request rate, error rate, latency
- **SMS Processing Pipeline** — received/matched/failed over time
- **Webhook Delivery Health** — delivery rate, dead webhooks

---

## Legal & Privacy

- The Android app reads **only SMS delivered to the device's own SIM**
- **No cross-device access**, no screen scraping, no unofficial APIs
- All SMS data is **encrypted at rest** (AES-256-GCM) on both device and server
- Users can permanently delete all their data via app Settings → Data & Privacy
- GDPR/PDPA compliant — hard-delete endpoint for SMS logs and user data
- Audit logs record every access to SMS data with actor, IP, and timestamp

---

## Development

```bash
# Backend dev server
cd backend
uvicorn app.main:app --reload --port 8000

# Run backend tests
pytest tests/ -v

# Merchant panel dev
cd merchant-panel && npm run dev

# Admin panel dev
cd admin-panel && npm run dev
```

---

## Deployment

See [`docs/deployment/INSTALL.md`](docs/deployment/INSTALL.md) for a step-by-step fresh VPS setup guide.
See [`docs/deployment/UPGRADE.md`](docs/deployment/UPGRADE.md) for zero-downtime upgrade procedure.
