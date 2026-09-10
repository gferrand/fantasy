FROM python:3.12-slim-bookworm

ENV FANTASY_REPO_ROOT=/app \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN groupadd --system --gid 999 fantasy \
    && useradd --system --uid 999 --gid 999 --no-create-home fantasy

COPY . /app
RUN python -m pip install --no-cache-dir . \
    && mkdir -p /app/data /app/reports \
    && chown -R 999:999 /app

USER fantasy

CMD ["python", "-m", "fantasy_advisor.scheduler"]
