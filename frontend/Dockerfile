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

# Default backend URL (can be overridden at runtime)
ENV BACKEND_URL=http://backend:8000

EXPOSE 3000

CMD ["nginx", "-g", "daemon off;"]