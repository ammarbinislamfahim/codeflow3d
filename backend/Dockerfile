FROM python:3.10-slim

WORKDIR /app

# pycparser needs gcc for C header preprocessing
RUN apt-get update && apt-get install -y --no-install-recommends gcc && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN useradd -m codeflow && chown -R codeflow:codeflow /app
USER codeflow

# Render injects PORT env var; fall back to 8000 locally
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request, os; urllib.request.urlopen('http://localhost:' + os.environ.get('PORT','8000') + '/ping')"

CMD gunicorn main:app --workers 2 --worker-class uvicorn.workers.UvicornWorker --bind "0.0.0.0:${PORT:-8000}" --timeout 120