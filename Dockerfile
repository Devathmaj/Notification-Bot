FROM python:3.13-slim

# UTF-8 everywhere so emoji/markdown in embeds never crash logging/encoding.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONIOENCODING=utf-8 \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8

WORKDIR /app

# Install the shared runtime (deps from pyproject.toml).
COPY pyproject.toml ./
COPY bot ./bot
COPY webhook ./webhook
COPY config.py main.py ./
RUN pip install --no-cache-dir .

# Run the single process that hosts both the Discord bot and the webhook.
CMD ["python", "-m", "main"]

# Bind the Render-provided PORT (config override: PORT env var).
EXPOSE 43217