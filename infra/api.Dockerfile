FROM rust:1.88-bookworm AS redactor-builder

WORKDIR /build
COPY apps/redactor-rs/Cargo.toml apps/redactor-rs/Cargo.lock ./apps/redactor-rs/
COPY apps/redactor-rs/src ./apps/redactor-rs/src
RUN cargo build --manifest-path apps/redactor-rs/Cargo.toml --release


FROM python:3.11-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    BLOCKVAULT_REDACTION_ENGINE_BIN=/usr/local/bin/blockvault-redactor \
    BLOCKVAULT_ZKPT_SNARKJS_BIN=/usr/local/bin/snarkjs \
    BLOCKVAULT_ZKPT_NODE_BIN=/usr/bin/node \
    BLOCKVAULT_RUNTIME_ROLE=api \
    NODE_PATH=/usr/lib/node_modules

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates gnupg libgl1 libglib2.0-0 \
    && mkdir -p /etc/apt/keyrings \
    && curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key | gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg \
    && echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_20.x nodistro main" > /etc/apt/sources.list.d/nodesource.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends nodejs \
    && npm install -g snarkjs@0.7.6 circomlibjs@0.1.7 \
    && apt-get purge -y --auto-remove curl gnupg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY apps/api /app/apps/api
COPY apps/worker /app/apps/worker
COPY circuits /app/circuits
COPY contracts /app/contracts
COPY infra/start-runtime.sh /app/infra/start-runtime.sh
COPY scripts /app/scripts
COPY README.md /app/README.md
COPY --from=redactor-builder /build/apps/redactor-rs/target/release/blockvault-redactor /usr/local/bin/blockvault-redactor

RUN python -m pip install --upgrade pip \
    && python -m pip install -e /app/apps/api[dev] -e /app/apps/worker \
    && chmod +x /app/infra/start-runtime.sh

EXPOSE 8000

CMD ["/app/infra/start-runtime.sh"]
