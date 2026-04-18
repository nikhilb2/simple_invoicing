# syntax=docker/dockerfile:1

# Stage 1: Build on the native builder platform to avoid emulation crashes
FROM --platform=$BUILDPLATFORM node:22-slim AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
ARG VITE_API_BASE_URL

RUN if [ -n "$VITE_API_BASE_URL" ]; then \
      echo "VITE_API_BASE_URL=$VITE_API_BASE_URL" > .env.production; \
    fi && \
    npm run build

# Stage 2: Serve
FROM --platform=$TARGETPLATFORM node:22-slim

RUN npm install -g serve

WORKDIR /app
COPY --from=build /app/dist /app/dist

EXPOSE 3000
CMD ["serve", "-s", "/app/dist", "-l", "3000"]