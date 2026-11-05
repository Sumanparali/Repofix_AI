FROM python:3.12-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml README.md ./
RUN mkdir -p src/repofix && touch src/repofix/__init__.py
RUN python -m pip install --no-cache-dir ".[web,worker]"
COPY src ./src
RUN python -m pip install --no-cache-dir --no-deps .
RUN useradd --uid 65532 --create-home repofix && mkdir -p /data /work && chown -R 65532:65532 /data /work
USER 65532:65532
ENV REPOFIX_DATABASE=/data/repofix.db
CMD ["repofix-web"]
