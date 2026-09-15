# Build stage
FROM node:20-alpine AS build

WORKDIR /app

# Copy package files (lockfile first: reproducible installs)
COPY package.json package-lock.json ./

# Install dependencies
RUN npm ci

# Copy source files
COPY . .

# Build the app
RUN npm run build

# Production stage
FROM nginx:alpine

# Copy built files
COPY --from=build /app/dist /usr/share/nginx/html

# Copy nginx configuration template. The official nginx entrypoint renders
# /etc/nginx/templates/*.template automatically (envsubst), so no manual
# envsubst in CMD is needed.
COPY nginx.conf.template /etc/nginx/templates/default.conf.template

# Decides the listeners before the templates are rendered. The nginx image
# runs /docker-entrypoint.d in name order and renders at 20-, so this lands
# first. Explicitly chmod'ed: a file copied from a Windows checkout arrives
# without its executable bit and the entrypoint would skip it silently.
COPY docker-entrypoint.d/15-anyq-tls.sh /docker-entrypoint.d/15-anyq-tls.sh
RUN chmod +x /docker-entrypoint.d/15-anyq-tls.sh

# Default backend URL (can be overridden at runtime)
ENV BACKEND_URL=http://backend:8000
# Docker's embedded DNS, so the backend can move without taking the site down.
ENV DNS_RESOLVER=127.0.0.11
# Off by default: this stack is normally run on localhost, where there is no
# certificate to serve.
ENV HTTPS_TERMINATED=0
ENV TLS_SERVER_NAME=localhost

EXPOSE 3000 3443

CMD ["nginx", "-g", "daemon off;"]