# Jennie — Frontend (React + Nginx)
# Works for both dev and prod
FROM node:20-alpine AS build

WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm install
COPY . .
RUN npm run build

# Serve with Nginx
FROM nginx:alpine

COPY --from=build /app/dist /usr/share/nginx/html
COPY start-nginx.sh /start-nginx.sh
RUN chmod +x /start-nginx.sh \
    && rm -f /etc/nginx/conf.d/default.conf \
    && rm -f /etc/nginx/templates/default.conf.template

# Docker Compose: BACKEND_URL=http://backend:8000 (proxy mode)
# K8s: BACKEND_URL=https://dev-apis.example.com/genie (DNS proxy mode)
# K8s static: BACKEND_URL=none (browser calls API via VITE_API_BASE)
ENV BACKEND_URL=http://backend:8000

EXPOSE 80

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD wget -q --spider http://localhost:80/ || exit 1

CMD ["/start-nginx.sh"]
