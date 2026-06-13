FROM python:3.12-slim AS base
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY src/ ./src/
COPY templates/ ./templates/
COPY static/ ./static/

# test stage — `docker build --target test` runs the unit tests; build fails if they fail
FROM base AS test
COPY pyproject.toml ./
COPY tests/ ./tests/
RUN pip install --no-cache-dir pytest httpx && python -m pytest -q

FROM base AS final
ENV PYTHONUNBUFFERED=1
CMD ["uvicorn", "src.app:app", "--host", "0.0.0.0", "--port", "8080"]
