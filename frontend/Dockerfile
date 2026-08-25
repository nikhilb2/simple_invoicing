# syntax=docker/dockerfile:1

# Stage 1: Build on the native builder platform to avoid emulation crashes
FROM --platform=$BUILDPLATFORM node:22-slim AS build
WORKDIR /app
COPY package.json .
RUN npm install
COPY . .
ARG VITE_API_BASE_URL
ARG VITE_POSTHOG_PROJECT_TOKEN
ARG VITE_POSTHOG_HOST

# Build args are appended to .env.production rather than overwriting it: dotenv
# takes the last assignment of a key, so appending still wins over anything the
# build context carried in, and a variable that is not passed as an arg keeps
# whatever value the file already had. The previous `>` erased the whole file,
# which silently dropped the PostHog keys whenever an API URL was supplied.
RUN { \
      if [ -n "$VITE_API_BASE_URL" ]; then echo "VITE_API_BASE_URL=$VITE_API_BASE_URL"; fi; \
      if [ -n "$VITE_POSTHOG_PROJECT_TOKEN" ]; then echo "VITE_POSTHOG_PROJECT_TOKEN=$VITE_POSTHOG_PROJECT_TOKEN"; fi; \
      if [ -n "$VITE_POSTHOG_HOST" ]; then echo "VITE_POSTHOG_HOST=$VITE_POSTHOG_HOST"; fi; \
    } >> .env.production && \
    npm run build

# Stage 2: Serve
FROM --platform=$TARGETPLATFORM nginx:alpine

COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]