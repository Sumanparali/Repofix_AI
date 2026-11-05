FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/workspace

RUN python -m pip install --no-cache-dir pytest==8.3.5

WORKDIR /workspace
USER 65532:65532

CMD ["python", "-m", "pytest", "-q"]

