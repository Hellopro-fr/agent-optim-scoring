# =============================================================================
# Stage 1 : docker-installer
# Recupere docker-ce-cli + docker-compose-plugin depuis les depots officiels
# =============================================================================
FROM debian:bookworm-slim AS docker-installer

RUN apt-get update && apt-get install -y --no-install-recommends \
        curl \
        ca-certificates \
        gnupg \
    && install -m 0755 -d /etc/apt/keyrings \
    && curl -fsSL https://download.docker.com/linux/debian/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg \
    && chmod a+r /etc/apt/keyrings/docker.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/debian bookworm stable" > /etc/apt/sources.list.d/docker.list \
    && apt-get update && apt-get install -y --no-install-recommends \
        docker-ce-cli \
        docker-compose-plugin


# =============================================================================
# Stage 2 : builder (installation des deps Python dans un venv isole)
# =============================================================================
FROM python:3.11-slim AS builder

WORKDIR /build

COPY requirements.txt .
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir --upgrade pip \
    && /opt/venv/bin/pip install --no-cache-dir -r requirements.txt


# =============================================================================
# Stage 3 : runtime (image finale, minimaliste)
# =============================================================================
FROM python:3.11-slim AS runtime

# Runtime tools uniquement :
# - nodejs : execute le wrapper claude CLI monte depuis l'hote
# - git : operations git dans /rag-hp-pub (Claude commit les iterations)
# - curl : utilise par le healthcheck docker-compose
RUN apt-get update && apt-get install -y --no-install-recommends \
        nodejs \
        git \
        curl \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Docker CLI copie depuis le stage installer (pas d'apt residuel)
COPY --from=docker-installer /usr/bin/docker /usr/bin/docker
COPY --from=docker-installer /usr/libexec/docker/cli-plugins/docker-compose /usr/libexec/docker/cli-plugins/docker-compose

# Venv Python copie depuis le builder
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# User non-root pour securite (UID 1000 = default utilisateur VM Ubuntu)
# group_add:docker dans docker-compose.yml requis pour acces /var/run/docker.sock
RUN groupadd --system --gid 1000 app \
    && useradd --system --uid 1000 --gid app --home-dir /app --shell /bin/bash app

WORKDIR /app

COPY --chown=app:app . .

# /app lui-meme doit appartenir a app (WORKDIR le cree en root par defaut).
# Necessaire pour que gunicorn puisse ecrire son fichier de controle /app/.gunicorn
RUN chown app:app /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    FLASK_ENV=production \
    PROJECT_ROOT=/app

USER app

EXPOSE 5050

CMD ["gunicorn", "-c", "gunicorn.conf.py", "dashboard.app:app"]
