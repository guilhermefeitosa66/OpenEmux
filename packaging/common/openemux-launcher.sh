#!/bin/sh
# Launcher for the native (.deb/.rpm) installs. The app expects a "project root"
# holding src/, vendors/ (the RetroArch AppImage) and requirements.lock; the
# packages install that tree under /opt/openemux, so point the app at it the
# same way the AppImage's AppRun does.
set -eu

export OPENEMUX_PROJECT_ROOT="/opt/openemux"
export PYTHONPATH="/opt/openemux/src${PYTHONPATH:+:$PYTHONPATH}"

exec python3 -m openemux.main "$@"
