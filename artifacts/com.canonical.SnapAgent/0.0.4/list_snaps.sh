#!/bin/sh -x

echo "$0 Called!!!!!!!!!!!!"
echo "About to call CURL; which should list all the SNAPS..."
curl -sS --unix-socket /run/snapd.socket http://localhost/v2/snaps || true



