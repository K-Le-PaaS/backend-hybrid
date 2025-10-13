FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    APP_HOME=/app

WORKDIR ${APP_HOME}

RUN apt-get update -y && apt-get install -y --no-install-recommends \
    curl ca-certificates && \
    rm -rf /var/lib/apt/lists/*

# Install NCP IAM Authenticator for NKS cluster access
RUN curl -L -o /usr/local/bin/ncp-iam-authenticator "https://kr.object.ncloudstorage.com/nks-download/ncp-iam-authenticator/v1.0.0/linux/amd64/ncp-iam-authenticator" && \
    chmod +x /usr/local/bin/ncp-iam-authenticator && \
    ncp-iam-authenticator --version

# Add a non-root user
RUN useradd --create-home appuser

# Create user bin directory and setup PATH for appuser
RUN mkdir -p /home/appuser/bin && \
    cp /usr/local/bin/ncp-iam-authenticator /home/appuser/bin/ncp-iam-authenticator && \
    chown -R appuser:appuser /home/appuser/bin && \
    echo 'export PATH=$PATH:$HOME/bin' >> /home/appuser/.bashrc

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=appuser:appuser app ./app

# Switch to the non-root user
USER appuser

EXPOSE 8080

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]


