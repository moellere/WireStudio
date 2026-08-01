#!/bin/sh
# PlatformIO takes its lock at `<dir>.lock` -- a sibling of the managed
# directory, not a child. So pointing PLATFORMIO_PLATFORMS_DIR straight at the
# prewarmed tree baked into the image puts the lock on the image filesystem,
# and every build dies with:
#
#   OSError: [Errno 30] Read-only file system: '/opt/pio/platforms.lock'
#
# Keep the core dir on the writable volume and link the prewarmed trees in from
# there, so the locks land next to the links (writable) while the content still
# resolves to the read-only baked copy. No re-download, no 7 GB duplicated onto
# the volume.
#
# Done here rather than in the Dockerfile because /data is a volume: anything
# written to that path at build time is masked once it is mounted.
set -e

CORE_DIR="${PLATFORMIO_CORE_DIR:-/data/pio}"
if [ -d /opt/pio ]; then
    mkdir -p "$CORE_DIR" 2>/dev/null || true
    for d in platforms packages; do
        if [ -d "/opt/pio/$d" ] && [ ! -e "$CORE_DIR/$d" ]; then
            ln -sfn "/opt/pio/$d" "$CORE_DIR/$d" 2>/dev/null || true
        fi
    done
fi

exec "$@"
