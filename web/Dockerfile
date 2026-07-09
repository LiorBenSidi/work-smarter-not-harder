# Web container — the ONLY user-facing service. OWNER: Lior.
FROM python:3.12-slim
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 5000
# wsgi:app configures logging (console + rotating file) before building the app — see web/wsgi.py.
# gthread workers (course L7): the web tier is I/O-bound (waits on Mongo + the AI service, and those
# socket waits release the GIL), so 2 workers x 4 threads serve up to 8 concurrent requests without the
# memory of 8 processes — sync workers would head-of-line-block at 2. --max-requests recycles workers to
# bound memory + the per-PID log growth wsgi.py notes. CPU-bound parallelism stays in the AI container.
# --timeout 45 must exceed AI_CLIENT_TIMEOUT (config.py, 33s) so a slow /predict hits the graceful
# ai_client degrade (returns None -> DESIGN §5) instead of gunicorn SIGKILL-ing the worker mid-request.
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--worker-class", "gthread", "--workers", "2", \
     "--threads", "4", "--timeout", "45", "--max-requests", "1000", "--max-requests-jitter", "100", "wsgi:app"]
