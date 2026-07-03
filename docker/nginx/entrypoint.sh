#!/bin/sh
set -e

# Substitute only our env vars into the nginx config template.
# Passing an explicit variable list prevents envsubst from mangling
# nginx's own $host, $uri, $1, etc.
envsubst '${OS_MAPS_API_KEY} ${SERVER_HOSTNAME}' \
    < /etc/nginx/templates/skitak.conf.template \
    > /etc/nginx/conf.d/skitak.conf

exec nginx -g 'daemon off;'
