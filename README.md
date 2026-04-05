# CodeFlow3D — 3D Control Flow Visualization

Analyze source code and generate interactive 3D control flow graphs. Supports **C, C++, Python, Java, JavaScript, and TypeScript**.

![License](https://img.shields.io/badge/license-MIT-blue)

---

## Features

- **Multi-language** — C, C++, Python, Java, JavaScript, TypeScript parsers (tree-sitter + javalang + pycparser)
- **3D Visualization** — Interactive Three.js scene with orbit controls, zoom, and SVG export
- **Smart Analysis** — Loop detection with metadata, recursion detection (direct & mutual), break/continue tracking
- **Async Processing** — Celery workers for heavy analyses (paid tier)
- **Caching** — Redis-powered result caching
- **Auth & Security** — API-key auth, JWT login (email or username), password strength enforcement, rate limiting
- **Subscription Tiers** — Free / Pro / Enterprise plan support
- **Admin Panel** — Full user management, subscription control, site settings (mobile-responsive)
- **Monitoring** — Prometheus metrics + Grafana dashboards
- **Production-ready** — Dockerized, health checks, CORS, security headers, input validation

---

## Tech Stack

| Layer | Tech |
|-------|------|
| Frontend | Vite, Three.js, Monaco Editor |
| Backend | Python, FastAPI, tree-sitter, pycparser, javalang |
| Queue | Celery + Redis |
| Database | PostgreSQL |
| Monitoring | Prometheus, Grafana |
| Hosting | Netlify (frontend) + Render (backend) |

---

## Project Structure

```
├── frontend/          # Vite + Three.js SPA
│   ├── src/           # JS modules, CSS
│   ├── index.html     # Main app
│   ├── admin.html     # Admin panel
│   └── vite.config.js
├── backend/           # FastAPI service
│   ├── main.py        # API endpoints
│   ├── parsers/       # Language parsers (C, C++, Java, JS, Python)
│   ├── auth/          # Auth & security
│   ├── migrations/    # SQL migrations
│   ├── celery_tasks.py
│   ├── cache.py
│   └── database.py
├── docker-compose.yml # Local dev (all services)
├── render.yaml        # Render Blueprint (backend deploy)
├── netlify.toml       # Netlify config (frontend deploy)
└── prometheus.yml     # Metrics config
```

---

## Quick Start (Local with Docker)

```bash
# Clone
git clone https://github.com/fahim2089/CodeFlow3D.git
cd CodeFlow3D

# Create .env file (required)
cat > .env << 'EOF'
DB_PASSWORD=MySecureDbPass123!
JWT_SECRET=my-super-secret-jwt-key-min-32-chars!!
ADMIN_EMAIL=admin@yourdomain.com
ADMIN_USERNAME=admin
ADMIN_PASSWORD=Admin@1234
EOF

# Start everything
docker-compose up -d

# The admin user is created automatically on first startup.
# Check logs for the admin API key:
docker-compose logs backend | grep "API Key"
```

> **Password requirements:** Minimum 8 characters, at least one uppercase letter, one lowercase letter, one number, and one special character.

- **Frontend** → http://localhost:5500
- **Backend API** → http://localhost:8000
- **API Docs** → http://localhost:8000/docs
- **Prometheus** → http://localhost:9090
- **Grafana** → http://localhost:3000

---

## Deployment

### Frontend → Netlify

1. Push this repo to GitHub.
2. In [Netlify](https://app.netlify.com), create a new site → Import from GitHub.
3. **Build settings** are auto-detected from `netlify.toml`:
   - Base directory: `frontend`
   - Build command: `npm install && npm run build`
   - Publish directory: `frontend/dist`
4. Add environment variable:
   - `BACKEND_URL` = your Render backend URL (e.g. `https://codeflow3d-backend.onrender.com`)
5. Deploy.

> **How it works:** Netlify proxies all `/api/*` requests to your Render backend (configured in `netlify.toml`).
> The frontend talks to `/api/ping`, `/api/analyze`, etc. on the same origin — **no CORS issues**.
> You do **NOT** need to set `VITE_API_URL` on Netlify. Only set `BACKEND_URL`.

### Backend → Render (Free Tier — Default)

The default `render.yaml` is configured for **Render's free tier**. It deploys:

- **Web Service** — FastAPI backend (handles code parsing synchronously)
- **Redis** — Cache
- **PostgreSQL** — Database

> **Note:** No Celery worker is deployed on the free tier. Code analysis runs synchronously
> inside the web process. For large codebases (>10K characters), this may be slower but works
> without a separate worker service.
>
> **Cold starts:** Render free tier sleeps after 15 min of inactivity. Use a free service like
> [UptimeRobot](https://uptimerobot.com) to ping `https://your-backend.onrender.com/ping` every 14 min to prevent this.

1. In [Render](https://render.com), click **New → Blueprint**.
2. Connect your GitHub repo — Render auto-detects `render.yaml`.
3. Set these environment variables on the **codeflow3d-backend** web service:
   - `ALLOWED_ORIGINS` = `*` (or your Netlify URL, e.g. `https://your-site.netlify.app`)
   - `ADMIN_EMAIL` = your admin email
   - `ADMIN_USERNAME` = your admin username
   - `ADMIN_PASSWORD` = a strong password (min 8 chars, uppercase, lowercase, number, special character)
4. Deploy. The admin user is **created automatically** on first startup — no shell access needed.

### Backend → Render (Paid Tier)

If you're on a **paid Render plan**, you can enable Celery workers for async processing:

1. Open `render.yaml` and follow the comments inside — uncomment the **Celery Worker**
   service section and switch all `plan: free` entries to your desired plan (e.g. `starter`, `standard`).
2. Deploy via Render Blueprint as above.
3. With the worker enabled, large code analysis runs asynchronously via Celery + Redis,
   keeping the web process responsive.

---

## Environment Variables

| Variable | Description | Required | Example |
|----------|-------------|----------|---------|
| `DB_PASSWORD` | PostgreSQL password (Docker) | Yes (Docker) | `MySecureDbPass123!` |
| `DATABASE_URL` | PostgreSQL connection string (Render) | Auto (Render) | `postgresql://user:pass@host/db` |
| `REDIS_URL` | Redis connection string | Auto (Render) | `redis://host:6379/0` |
| `JWT_SECRET` / `SECRET_KEY` | JWT signing key (min 32 chars) | Yes | *(random string)* |
| `ALLOWED_ORIGINS` | CORS allowed origins | Yes | `*` or `https://your-site.netlify.app` |
| `BACKEND_URL` | Backend URL (Netlify proxy) | Yes (Netlify) | `https://codeflow3d-backend.onrender.com` |
| `VITE_API_URL` | Override API base URL (dev only) | No | `http://localhost:8000` |
| `ADMIN_EMAIL` | Auto-create admin on startup | Optional | `admin@yourdomain.com` |
| `ADMIN_USERNAME` | Admin username | Optional | `admin` |
| `ADMIN_PASSWORD` | Admin password (must meet strength rules) | Optional | `Admin@1234` |

---

## API Endpoints

### Public

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/ping` | Health check |
| `GET` | `/docs` | Interactive API documentation |
| `GET` | `/settings/public` | Public site settings (plan prices, contact) |

### Authentication

| Method | Path | Rate Limit | Description |
|--------|------|------------|-------------|
| `POST` | `/register` | 5/min | Create account |
| `POST` | `/login` | 10/min | Login with email or username → JWT |
| `POST` | `/auth/api-key` | 10/min | Exchange JWT for API key |

### Authenticated (API key required)

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/analyze` | Parse code → control flow graph JSON (30/min) |
| `GET` | `/task/{id}` | Poll async analysis task status |
| `GET` | `/history` | Analysis history |
| `GET` | `/me` | Current user profile |
| `GET` | `/me/subscription` | Subscription info & usage |
| `GET` | `/graphs` | List saved graphs |
| `POST` | `/graphs` | Save a graph |
| `GET` | `/graphs/{id}` | Load a saved graph |
| `DELETE` | `/graphs/{id}` | Delete a saved graph |
| `GET` | `/api-keys` | List API keys |
| `POST` | `/api-keys` | Create a new API key |
| `DELETE` | `/api-keys/{id}` | Revoke an API key |

### Admin (admin API key or JWT required)

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/admin/me` | Verify admin access |
| `GET` | `/admin/stats` | Dashboard statistics |
| `GET` | `/admin/users` | List users (paginated, searchable) |
| `GET` | `/admin/users/{id}` | User detail |
| `PATCH` | `/admin/users/{id}` | Update user (username, email, active, admin) |
| `DELETE` | `/admin/users/{id}` | Delete user |
| `PUT` | `/admin/users/{id}/subscription` | Change user plan |
| `GET` | `/admin/users/{id}/api-keys` | List user's API keys |
| `POST` | `/admin/users/{id}/api-keys/reset` | Reset user's API keys |
| `DELETE` | `/admin/api-keys/{id}` | Revoke specific API key |
| `GET` | `/admin/settings` | Get site settings |
| `PUT` | `/admin/settings` | Update site settings |

---

## Running Tests

```bash
# Activate the virtual environment first
source .venv/bin/activate

# Parser unit tests (60 tests across all languages)
python test_parsers.py

# Website integration tests
python test_website.py
```

---

## Security

- Passwords hashed with **bcrypt** (12 rounds) and enforced strength rules
- API keys hashed with **SHA-256** — never stored in plaintext
- JWT tokens (HS256) with 24-hour expiry
- Rate limiting on all auth endpoints (`/register`, `/login`, `/auth/api-key`)
- Input validation on all user-facing fields (email, username, code size, graph title)
- Security headers configured in nginx and Netlify (`X-Frame-Options`, `CSP`, `X-Content-Type-Options`)
- CORS restricted to configured origins

---

## License

MIT