#!/usr/bin/env bash
# =============================================================================
# Dubbing Studio -- install directly on an Ubuntu 22.04/24.04 server
# =============================================================================
#
#   ssh ubuntu@YOUR-SERVER
#   git clone <YOUR-REPO-URL> dub && cd dub
#   sudo bash deploy/install-on-server.sh
#
# Use this when the box already exists (EC2 you made by hand, Lightsail, a VPS,
# or re-installing on a box created by deploy/aws-deploy.sh).
#
# Installs: Docker + compose, Node 20, nginx; builds the API + worker containers
# and the static frontend; wires nginx to serve the UI and proxy /api.
# Safe to re-run -- it updates in place and never touches your data volume.
# -----------------------------------------------------------------------------
set -euo pipefail

APP_DIR="${APP_DIR:-$(cd "$(dirname "$0")/.." && pwd)}"
WEB_ROOT="${WEB_ROOT:-/var/www/dub}"
S3_BUCKET="${S3_BUCKET:-}"                 # empty -> local disk storage
S3_REGION="${S3_REGION:-ap-southeast-1}"
SECRET_ID="${SECRET_ID:-dub-studio/gemini}"
ACCESS_TOKEN="${ACCESS_TOKEN:-}"

ok()   { printf '\033[32m  ok\033[0m  %s\n' "$*"; }
run()  { printf '\033[36m  ..\033[0m  %s\n' "$*"; }
step() { printf '\n\033[1m[%s/8] %s\033[0m\n' "$1" "$2"; }
die()  { printf '\033[31mfail\033[0m  %s\n' "$*" >&2; exit 1; }

[ "$(id -u)" = 0 ] || die "run with sudo"
. /etc/os-release 2>/dev/null || true
[ "${ID:-}" = ubuntu ] || printf '\033[33mwarn\033[0m  tested on Ubuntu only\n'
command -v openssl >/dev/null && [ -z "$ACCESS_TOKEN" ] && ACCESS_TOKEN="$(openssl rand -hex 24)"

step 1 "System packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y ca-certificates curl git nginx ffmpeg jq
ok "base packages"

step 2 "Docker"
if ! command -v docker >/dev/null; then
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
  chmod a+r /etc/apt/keyrings/docker.asc
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $VERSION_CODENAME stable" \
    > /etc/apt/sources.list.d/docker.list
  apt-get update -y
  apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
  ok "docker installed"
else
  ok "docker already present: $(docker --version)"
fi
systemctl enable --now docker

step 3 "Node.js 20 (frontend build only)"
if ! command -v node >/dev/null || [ "$(node -v | cut -c2-3)" -lt 20 ]; then
  curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
  apt-get install -y nodejs
fi
ok "node $(node -v)"

step 4 "backend/.env"
if [ -f "$APP_DIR/backend/.env" ]; then
  ok "keeping existing backend/.env"
else
  storage=local; [ -n "$S3_BUCKET" ] && storage=s3
  cat > "$APP_DIR/backend/.env" <<ENV
# Providers start in mock mode -- flip them on one at a time.
DUB_PROVIDER_TRANSCRIPTION=mock
DUB_PROVIDER_TRANSLATION=mock
DUB_PROVIDER_TTS_MY=mock
DUB_PROVIDER_TTS_EN=mock
DUB_PROVIDER_TTS_FALLBACK=mock
DUB_PROVIDER_LIPSYNC=mock
DUB_PROVIDER_RENDER=ffmpeg
DUB_PROVIDER_STORAGE=$storage
DUB_S3_BUCKET=${S3_BUCKET:-dub-studio-media}
DUB_S3_REGION=$S3_REGION
DUB_SECRETS_MANAGER_GEMINI_ID=$SECRET_ID
DUB_WORKER_INLINE=0
DUB_REQUIRE_AUTH=true
DUB_ACCESS_TOKEN=$ACCESS_TOKEN
ENV
  ok "written (storage=$storage)"
fi

step 5 "API + worker containers"
cd "$APP_DIR"
docker compose up -d --build api worker
ok "$(docker compose ps --services --filter status=running | tr '\n' ' ')"

step 6 "Frontend build"
run "npm ci && npm run build (a few minutes)"
cd "$APP_DIR/frontend"
npm ci --no-audit --no-fund
npm run build
rm -rf "$WEB_ROOT"; mkdir -p "$WEB_ROOT"
cp -r dist/* "$WEB_ROOT/"
ok "served from $WEB_ROOT"

step 7 "nginx"
cat > /etc/nginx/sites-available/dub <<NGINX
server {
  listen 80 default_server;
  server_name _;
  client_max_body_size 0;          # uploads go straight to S3, not through here
  root $WEB_ROOT;
  index index.html;

  location /api/ {
    proxy_pass http://127.0.0.1:8000;
    proxy_http_version 1.1;
    proxy_set_header Host \$host;
    proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto \$scheme;
    proxy_read_timeout 600s;       # long renders
  }

  location / { try_files \$uri \$uri/ /index.html; }
}
NGINX
rm -f /etc/nginx/sites-enabled/default
ln -sf /etc/nginx/sites-available/dub /etc/nginx/sites-enabled/dub
nginx -t
systemctl restart nginx
ok "listening on :80"

step 8 "Health check"
sleep 3
if curl -fsS --max-time 10 http://127.0.0.1/api/health >/dev/null; then ok "API healthy"
else printf '\033[33mwarn\033[0m  /api/health not answering yet -- docker compose logs -f\n'; fi

IP="$(curl -fsS --max-time 3 https://checkip.amazonaws.com 2>/dev/null || hostname -I | awk '{print $1}')"
cat <<SUMMARY

  Open         http://$IP
  Token        $(grep '^DUB_ACCESS_TOKEN=' "$APP_DIR/backend/.env" | cut -d= -f2-)
  Logs         cd $APP_DIR && sudo docker compose logs -f
  Update       cd $APP_DIR && sudo git pull && sudo bash deploy/install-on-server.sh
  Providers    sudo nano $APP_DIR/backend/.env && sudo docker compose up -d

SUMMARY
