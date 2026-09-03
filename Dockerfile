# Lineup Lab — production image.
#
# Matches the Python version this app is actually developed/tested
# against locally (see .venv) rather than jumping to "latest", so a
# deploy doesn't hit subtly different pandas/numpy behavior for free.
FROM python:3.9-slim

WORKDIR /app

# Dependencies first (own layer) so a code-only change doesn't force a
# full reinstall on every rebuild.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Most hosting platforms assign the listen port via $PORT at runtime
# rather than a fixed one — falls back to 8420 (this app's normal local
# port) when nothing sets it, so `docker run` without extra flags still
# works the same way ./run.sh does locally.
ENV PORT=8420
EXPOSE 8420

# --proxy-headers (+ trusting any forwarding IP) makes uvicorn read the
# reverse proxy's X-Forwarded-Proto header — without it, request.url.scheme
# always reads "http" behind a TLS-terminating proxy, and this app's own
# session cookie logic (server.py's _set_session_cookie) would then never
# set the Secure flag even though the site really is served over HTTPS.
# Nearly every PaaS (Render, Railway, Fly.io, etc.) terminates TLS at a
# proxy in front of the container exactly like this.
CMD ["sh", "-c", "uvicorn server:app --host 0.0.0.0 --port ${PORT:-8420} --proxy-headers --forwarded-allow-ips=*"]
