# Web container — the ONLY user-facing service. OWNER: Lior.
FROM python:3.12-slim
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 5000
# wsgi:app configures logging (console + rotating file) before building the app — see web/wsgi.py.
# gthread workers (course L7): the web tier is I/O-bound (waits on Mongo + the AI service, and those
# socket waits release the GIL), so 1 worker x 16 threads serves concurrent requests as threads — not
# processes — with no per-process memory duplication. scrypt hashing also releases the GIL, so ONE worker
# already spreads it across the cores; ONE worker also keeps ratelimit.py's memory:// caps EXACT (N workers
# would loosen every anti-abuse cap N×). 16 threads is the measured knee (#324: 8->16 = +56% throughput /
# -36% p95 under load; 16->32 flat). --max-requests recycles the worker to bound memory + the per-PID log
# growth wsgi.py notes. CPU-bound parallelism stays in the AI container. --timeout 45 must exceed
# AI_CLIENT_TIMEOUT (config.py, 33s) so a slow /predict hits the graceful ai_client degrade (returns None ->
# DESIGN §5) instead of gunicorn SIGKILL-ing the worker mid-request. This is the image DEFAULT; both compose
# files override it with an identical WEB_WORKERS/WEB_THREADS-tunable command (dev mirrors prod — see
# docker-compose.yml / docker-compose.prod.yml), so local and the VM run the same.
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--worker-class", "gthread", "--workers", "1", \
     "--threads", "16", "--timeout", "45", "--max-requests", "1000", "--max-requests-jitter", "100", "wsgi:app"]
