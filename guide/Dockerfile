# syntax=docker/dockerfile:1

# Build on the native builder platform, the output is static files.
FROM --platform=$BUILDPLATFORM node:22-slim AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM --platform=$TARGETPLATFORM nginx:1.27-alpine
COPY --from=build /app/.vitepress/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
