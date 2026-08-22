# CCOA frontend — docs/07 §3.9.
FROM node:22-alpine AS build
WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY tsconfig*.json vite.config.ts index.html ./
COPY src ./src
COPY public ./public
RUN npm run build

FROM nginx:stable-alpine AS runtime

COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY nginx-security-headers.conf /etc/nginx/security-headers.conf

# Port 8080 and a non-root user, so the task definition needs no added capabilities.
# Everything nginx writes then has to live somewhere the `nginx` user owns. The pidfile
# is the one that bites: it defaults to /run, which is root-owned, and the failure is
# total — nginx exits with "open() /run/nginx.pid failed (13: Permission denied)" and the
# container never serves a byte.
#
# The `grep` is not decoration. The first version of this line rewrote `/var/run/nginx.pid`,
# a path this base image no longer uses, so `sed` matched nothing, reported success, and
# the image built green and died on start. A rewrite that must match is asserted.
#
# The pidfile goes in a directory `nginx` owns rather than /tmp. Sticky-bit /tmp looks
# writable and is not: `nginx -t` below runs as root and leaves a root-owned nginx.pid
# there, which uid 101 can then neither open nor unlink — the same permission error, one
# layer further along. The final `rm` clears whatever the config test wrote.
RUN sed -i -E 's|^pid .*;|pid /var/cache/nginx/nginx.pid;|' /etc/nginx/nginx.conf \
 && grep -q '^pid /var/cache/nginx/nginx.pid;' /etc/nginx/nginx.conf \
 && sed -i '/^user /d' /etc/nginx/nginx.conf \
 && rm -f /docker-entrypoint.d/10-listen-on-ipv6-by-default.sh \
 && nginx -t \
 && rm -f /var/cache/nginx/nginx.pid \
 && chown -R nginx:nginx /usr/share/nginx/html /var/cache/nginx

USER nginx
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD wget -qO- http://localhost:8080/healthz || exit 1

CMD ["nginx", "-g", "daemon off;"]
