#!/bin/sh
# Substitute the CSP's connect-src at container start — docs/07 §3.9.
#
# The nginx image's own `20-envsubst-on-templates.sh` only processes
# /etc/nginx/templates into /etc/nginx/conf.d, and the security headers live in an
# include one directory up. Rather than reshape the config to suit that script, this does
# the one substitution the include needs.
#
# The default is `'self'`, so an image started with no environment is still restrictive.
# Widening it is a deliberate act by whoever runs the container.
set -eu

: "${CSP_CONNECT_SRC:="'self'"}"

# The template stays root-owned and read-only; only the generated copy is writable, and
# it lives in a directory owned by the `nginx` user. nginx runs unprivileged here, so it
# cannot write /etc/nginx — and it should not be able to rewrite its own security headers
# even if it could.
TEMPLATE=/etc/nginx/security-headers.conf.template
TARGET=/etc/nginx/generated/security-headers.conf

if grep -q '@CSP_CONNECT_SRC@' "$TEMPLATE"; then
  # `sed` with `|` as the delimiter: the value is a list of URLs and is full of `/`.
  # Not `envsubst`, because the placeholder deliberately is not shell syntax — see the
  # comment in nginx-security-headers.conf for why.
  sed "s|@CSP_CONNECT_SRC@|${CSP_CONNECT_SRC}|g" "$TEMPLATE" > "$TARGET"
  echo "csp: connect-src ${CSP_CONNECT_SRC}"
fi
