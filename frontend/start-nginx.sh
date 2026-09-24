#!/bin/sh
# Generate nginx config based on deployment mode:
# - Docker Compose: BACKEND_URL=http://backend:8000 → proxy /api/ and /genie/ to backend
# - K8s: BACKEND_URL=none (or unset) → static files only, browser calls API via VITE_API_BASE
#
# Runtime env injection: VITE_API_BASE env var → window.__ENV__ in index.html
# so the browser knows where to call the API without rebuilding the image.

HTML="/usr/share/nginx/html/index.html"
CONF="/etc/nginx/conf.d/default.conf"

# ── Runtime env injection ──────────────────────────────────────────────────
# Inject window.__ENV__ into index.html so JS can read VITE_API_BASE at runtime.
# This lets K8s set the API URL without rebuilding the frontend image.
if [ -n "$VITE_API_BASE" ]; then
  echo "Injecting runtime env: VITE_API_BASE=$VITE_API_BASE"
  # Insert script tag before </head>
  sed -i "s|</head>|<script>window.__ENV__={VITE_API_BASE:\"${VITE_API_BASE}\"};</script></head>|" "$HTML"
fi

# ── Nginx config ───────────────────────────────────────────────────────────
if [ -n "$BACKEND_URL" ] && [ "$BACKEND_URL" != "none" ]; then
  # Extract hostname for Host header (e.g., https://dev-apis.example.com/genie → dev-apis.example.com)
  BACKEND_HOST=$(echo "$BACKEND_URL" | sed 's|https\?://||' | cut -d'/' -f1)
  # Get container's DNS resolver for nginx (CoreDNS in K8s)
  DNS_RESOLVER=$(grep nameserver /etc/resolv.conf | head -1 | awk '{print $2}')
  echo "Nginx: proxy mode (BACKEND_URL=$BACKEND_URL, Host=$BACKEND_HOST, resolver=$DNS_RESOLVER)"
  cat > "$CONF" <<EOF
resolver ${DNS_RESOLVER} valid=30s ipv6=off;

server {
    listen 80;
    server_name _;
    root /usr/share/nginx/html;
    index index.html;

    location /api/ {
        proxy_pass ${BACKEND_URL}/api/;
        proxy_http_version 1.1;
        proxy_ssl_server_name on;
        proxy_ssl_verify off;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host ${BACKEND_HOST};
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_buffering off;
        proxy_cache off;
        proxy_read_timeout 600s;
        proxy_send_timeout 600s;
    }

    location /assets/ {
        expires 30d;
        add_header Cache-Control "public, immutable";
    }

    location / {
        try_files \$uri \$uri/ /index.html;
    }
}
EOF
else
  echo "Nginx: static mode (no backend proxy — browser uses VITE_API_BASE)"
  cat > "$CONF" <<EOF
server {
    listen 80;
    server_name _;
    root /usr/share/nginx/html;
    index index.html;

    location /assets/ {
        expires 30d;
        add_header Cache-Control "public, immutable";
    }

    location / {
        try_files \$uri \$uri/ /index.html;
    }
}
EOF
fi

exec nginx -g 'daemon off;'
