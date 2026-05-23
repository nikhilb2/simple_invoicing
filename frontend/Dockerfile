# syntax=docker/dockerfile:1

# Stage 1: Build on the native builder platform to avoid emulation crashes
FROM --platform=$BUILDPLATFORM node:22-slim AS build
WORKDIR /app
COPY package.json .
RUN npm install
COPY . .
ARG VITE_API_BASE_URL

RUN if [ -n "$VITE_API_BASE_URL" ]; then \
      echo "VITE_API_BASE_URL=$VITE_API_BASE_URL" > .env.production; \
    fi && \
    npm run build

# Stage 2: Serve
FROM --platform=$TARGETPLATFORM nginx:alpine

COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]