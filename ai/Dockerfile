# AI container (internal). OWNER: Lior.
FROM python:3.12-slim
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
# The trained model is BAKED into the image: train offline -> model/model.pkl, which `COPY . .`
# bundles. Pin scikit-learn (requirements.txt) to the version you trained with so the pickle loads.

EXPOSE 5000
# gunicorn workers = the parallel/scaling story (CPU-bound inference across processes).
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "2", "app:create_app()"]
