# CodeFlow3D — 3D Control Flow Visualization

Analyze source code and generate interactive 3D control flow graphs. Supports **C, C++, Python, Java, and JavaScript**.

![License](https://img.shields.io/badge/license-MIT-blue)

---

## Features

- **Multi-language** — C, C++, Python, Java, JavaScript parsers (tree-sitter + javalang)
- **3D Visualization** — Interactive Three.js scene with orbit controls, zoom, and SVG export
- **Async Processing** — Celery workers for heavy analyses
- **Caching** — Redis-powered result caching
- **Auth & Rate Limiting** — API-key authentication, per-user rate limits, admin panel
- **Subscription Tiers** — Free / Pro / Enterprise plan support
- **Monitoring** — Prometheus metrics + Grafana dashboards
- **Production-ready** — Dockerized, health checks, CORS, security headers

---

## Tech Stack

| Layer | Tech |
|-------|------|
| Frontend | Vite, Three.js, Monaco Editor |
| Backend | Python, FastAPI, tree-sitter, javalang |
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

# Configure environment
cp .env.example .env
# Edit .env with your database password and secret key

# Start everything
docker-compose up -d

# Seed admin user
docker-compose exec backend python seed_admin.py
```

- **Frontend** → http://localhost:5500
- **Backend API** → http://localhost:8000
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
   - `VITE_API_URL` = your Render backend URL (e.g. `https://codeflow3d-backend.onrender.com`)
5. Deploy.

### Backend → Render

1. In [Render](https://render.com), click **New → Blueprint**.
2. Connect your GitHub repo — Render auto-detects `render.yaml`.
3. This creates:
   - **Web Service** — FastAPI backend
   - **Worker** — Celery worker
   - **Redis** — Cache + message broker
   - **PostgreSQL** — Database
4. Set `ALLOWED_ORIGINS` env var on the web service to your Netlify URL.
5. After deploy, run the seed script via Render Shell:
   ```bash
   python seed_admin.py
   ```

---

## Environment Variables

| Variable | Description | Example |
|----------|-------------|---------|
| `DATABASE_URL` | PostgreSQL connection string | `postgresql://user:pass@host/db` |
| `REDIS_URL` | Redis connection string | `redis://host:6379/0` |
| `SECRET_KEY` | JWT signing key | *(random string)* |
| `ALLOWED_ORIGINS` | CORS allowed origins | `https://your-site.netlify.app` |
| `VITE_API_URL` | Backend URL (frontend build) | `https://codeflow3d-backend.onrender.com` |

---

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/ping` | Health check |
| `POST` | `/analyze` | Parse code → CFG JSON |
| `POST` | `/auth/register` | Create account |
| `POST` | `/auth/login` | Get JWT + API key |
| `GET` | `/auth/me` | Current user info |
| `GET` | `/admin/*` | Admin endpoints (JWT required) |

---

## Running Tests

```bash
# Parser unit tests
python test_parsers.py

# Website integration tests
python test_website.py
```

---

## License

MIT