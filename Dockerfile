# Multi-stage build for Baloo Code Review Agent
# Pin to specific version for security patching - update periodically
FROM python:3.14.5-slim-bookworm as base

# Build arguments for version tracking
ARG BALOO_VERSION=dev
ARG BALOO_COMMIT_SHA=unknown
ARG BALOO_BUILD_DATE=unknown

# Set as environment variables
ENV BALOO_VERSION=${BALOO_VERSION}
ENV BALOO_COMMIT_SHA=${BALOO_COMMIT_SHA}
ENV BALOO_BUILD_DATE=${BALOO_BUILD_DATE}

# Install system dependencies and ensure OpenSSL is up-to-date
RUN apt-get update && apt-get install -y \
    curl \
    git \
    bubblewrap \
    && apt-get upgrade -y openssl libssl3 \
    && rm -rf /var/lib/apt/lists/*

# Install Node.js (required for PI coding agent)
RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy dependency files first (for better layer caching)
COPY pyproject.toml ./

# Install Python dependencies
RUN pip install --no-cache-dir -e .

# Install PI coding agent globally (provides the 'pi' CLI)
RUN npm install -g @mariozechner/pi-coding-agent

# Install AST tools extension dependencies
COPY extensions/package.json extensions/package-lock.json /app/extensions/
RUN cd /app/extensions && npm ci --production

# Copy application code
COPY . .

# Create non-root user for security
RUN useradd -m -u 1000 baloo && chown -R baloo:baloo /app
USER baloo

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Run the application
CMD ["python", "main.py"]
