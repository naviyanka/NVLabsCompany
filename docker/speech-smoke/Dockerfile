# Speech-enabled Linux smoke (no Azure call, no token, no audio device).
#
# Build phase has network access. The smoke itself must run with the network disabled:
#
#   docker build -f docker/speech-smoke/Dockerfile -t nexus-speech-smoke .
#   docker run --rm --network none nexus-speech-smoke
#
# Other architecture (the SDK ships native wheels for amd64 and arm64):
#   docker build --platform linux/arm64 -f docker/speech-smoke/Dockerfile -t nexus-speech-smoke-arm64 .
#   docker run --rm --platform linux/arm64 --network none nexus-speech-smoke-arm64
#
# The runtime stage installs no apt packages unless RUNTIME_APT says so. See docs/azure-speech-provider.md.
FROM python:3.12-slim AS build
WORKDIR /build
COPY pyproject.toml README.md ./
COPY src/ ./src/
# --only-binary for the SDK: it has no source distribution, so a platform without a native wheel
# must fail here, never fall back to a source build.
RUN python -m venv /opt/venv \
 && /opt/venv/bin/pip install --no-cache-dir --upgrade pip \
 && /opt/venv/bin/pip install --no-cache-dir --only-binary azure-cognitiveservices-speech ".[speech]"

FROM python:3.12-slim AS runtime
ARG RUNTIME_APT=""
RUN if [ -n "$RUNTIME_APT" ]; then \
      apt-get update && apt-get install -y --no-install-recommends $RUNTIME_APT \
      && rm -rf /var/lib/apt/lists/*; \
    fi
COPY --from=build /opt/venv /opt/venv
COPY scripts/speech_container_smoke.py /smoke/speech_container_smoke.py
ENV PATH="/opt/venv/bin:$PATH" PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
USER nobody
CMD ["python", "/smoke/speech_container_smoke.py"]
