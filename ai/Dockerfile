# AI container (internal). OWNER: Shiri.
FROM python:3.12-slim
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
# The trained model is BAKED into the image: train offline -> model/model.pkl, which `COPY . .`
# bundles. Pin scikit-learn (requirements.txt) to the version you trained with so the pickle loads.

EXPOSE 5000
# ONE gunicorn worker on purpose: the job store is in-memory, so a second worker would own a second
# store and `GET /jobs/<id>` would 404 whenever it landed on the wrong one. Threads accept concurrent
# requests; the PARALLELISM comes from the queue's process pool (ai/jobqueue.py), which — unlike
# threads — actually overlaps CPU-bound inference across cores. Size the pool with AI_QUEUE_WORKERS.
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "1", "--threads", "8", "app:create_app()"]
