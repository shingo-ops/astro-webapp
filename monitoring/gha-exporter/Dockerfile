FROM debian:bookworm-slim

ARG GHA_EXPORTER_VERSION=v0.0.15
ARG TARGETARCH=amd64

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

RUN curl -fsSL \
    "https://github.com/gravitational/gha-exporter/releases/download/${GHA_EXPORTER_VERSION}/gha-exporter-linux-${TARGETARCH}.tar.gz" \
    | tar -xz -C /usr/local/bin/

COPY docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod +x /docker-entrypoint.sh

EXPOSE 8080

ENTRYPOINT ["/docker-entrypoint.sh"]
