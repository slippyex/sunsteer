# Base image is intentionally a floating tag (not digest-pinned): each release
# rebuild picks up the latest base security patches. Released images are
# themselves immutable and digest-addressable in GHCR, so downstream pins by
# digest. Pin here too if you need byte-for-byte reproducible local builds.
FROM python:3.12-slim AS base
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY src/ ./src/

# test stage — `docker build --target test` runs the unit tests; build fails if they fail
FROM base AS test
COPY pyproject.toml ./
COPY tests/ ./tests/
RUN pip install --no-cache-dir pytest && python -m pytest -q

FROM base AS final
ENV PYTHONUNBUFFERED=1
RUN useradd -u 10001 -r -s /usr/sbin/nologin appuser
USER 10001
CMD ["python", "-m", "src.main"]
