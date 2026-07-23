FROM python:3.11-slim

WORKDIR /app

# Install system deps for opencv
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Create a virtualenv outside /app so the bind-mount doesn't shadow it
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
ENV VIRTUAL_ENV="/opt/venv"

# Install Python deps into the venv
COPY pyproject.toml .
RUN pip install --no-cache-dir ".[dev,ml]"

# Copy app source
COPY . .

EXPOSE 8000

# Generate encryption key at startup if not set, then run migrations and start uvicorn
ENTRYPOINT ["sh", "-c", \
    "if [ -z \"$$FA_ENCRYPTION_KEY\" ]; then echo \"Generating encryption key...\"; export FA_ENCRYPTION_KEY=$(python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\"); fi; \
    python -m alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port 8000"]
