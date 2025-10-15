# Builder stage
FROM python:3.11-slim AS builder

RUN apt-get update -y && apt-get install -y --no-install-recommends \
    curl ca-certificates && \
    rm -rf /var/lib/apt/lists/*

# Download ncp-iam-authenticator in builder stage with retry logic
RUN curl --retry 3 --retry-delay 2 --retry-max-time 30 \
    -L -o /tmp/ncp-iam-authenticator \
    "https://github.com/NaverCloudPlatform/ncp-iam-authenticator/releases/download/v1.1.1/ncp-iam-authenticator_linux_amd64" && \
    chmod +x /tmp/ncp-iam-authenticator && \
    echo "✅ ncp-iam-authenticator v1.1.1 download successful in builder stage!"

# Final stage
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    APP_HOME=/app

WORKDIR ${APP_HOME}

# Copy pre-downloaded binary from builder stage
COPY --from=builder /tmp/ncp-iam-authenticator /usr/local/bin/ncp-iam-authenticator

# Add a non-root user
RUN useradd --create-home appuser

# Create user bin directory and setup PATH for appuser
RUN mkdir -p /home/appuser/bin && \
    cp /usr/local/bin/ncp-iam-authenticator /home/appuser/bin/ncp-iam-authenticator && \
    chown -R appuser:appuser /home/appuser/bin && \
    echo 'export PATH=$PATH:$HOME/bin' >> /home/appuser/.bashrc && \
    echo "✅ ncp-iam-authenticator setup complete in final stage!"

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=appuser:appuser app ./app

# Switch to the non-root user
USER appuser

EXPOSE 8080

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]


