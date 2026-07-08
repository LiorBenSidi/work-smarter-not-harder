# Test-runner container — OWNER: Elad. Used ONLY by docker-compose.test.yml.
#
# It runs the cross-container suites against the RUNNING stack (web/ai/db), which is what the
# in-process pytest run on the host cannot prove: real HTTP, real gunicorn, real Mongo, real network.
#   - tests/System_Tests            -> E2E_BASE_URL=http://web:5000  (the whole web->ai->db journey)
#   - tests/Integration_Tests/test_db_mongo.py -> TEST_MONGO_URI (the real data layer, throwaway DB)
#
# It never publishes a port and it never writes to the dev/prod database.
FROM python:3.12-slim
WORKDIR /app

COPY tests/requirements.txt tests/requirements.txt
RUN pip install --no-cache-dir -r tests/requirements.txt

# web/ is copied because the real-Mongo integration test loads web/services/db.py off disk (the data
# layer under test). tests/ carries the suites + conftest. Nothing else from the repo is needed.
COPY web/ web/
COPY tests/ tests/

# Overridden by docker-compose.test.yml; this default makes `docker run` on the image do the right thing.
CMD ["python", "-m", "pytest", "tests/System_Tests", "tests/Integration_Tests/test_db_mongo.py", "-q"]
