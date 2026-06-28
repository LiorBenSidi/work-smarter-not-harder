# Web container — the ONLY user-facing service. OWNER: Lior.
FROM python:3.12-slim
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 5000
# wsgi:app configures logging (console + rotating file) before building the app — see web/wsgi.py.
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "2", "wsgi:app"]
