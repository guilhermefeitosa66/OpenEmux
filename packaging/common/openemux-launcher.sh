#!/bin/sh
# Launcher for the native (.deb/.rpm) installs. The app expects a "project root"
# holding src/, vendors/ (the RetroArch AppImage) and requirements.lock; the
# packages install that tree under /opt/openemux.
set -eu

PROJECT_ROOT="/opt/openemux"
export OPENEMUX_PROJECT_ROOT="$PROJECT_ROOT"
export PYTHONPATH="$PROJECT_ROOT/src${PYTHONPATH:+:$PYTHONPATH}"

# A pyenv/conda/virtualenv environment exports this, and it would send the
# distro interpreter looking for its stdlib in the wrong prefix.
unset PYTHONHOME 2>/dev/null || true

# Deliberately NOT `python3` from PATH. Version managers (pyenv, asdf, conda)
# put a shim first in PATH, and those interpreters have no PyGObject: the app
# is installed correctly and still dies with "No module named 'gi'". Pick the
# first interpreter that can actually import gi, preferring the distro one the
# package depends on.
for candidate in /usr/bin/python3 /usr/local/bin/python3 python3; do
    interpreter="$(command -v "$candidate" 2>/dev/null)" || continue
    if "$interpreter" -c 'import gi' >/dev/null 2>&1; then
        exec "$interpreter" -m openemux.main "$@"
    fi
done

cat >&2 <<'EOF'
openemux: no Python 3 interpreter with PyGObject (the "gi" module) was found.

The package depends on it, so this usually means the distro python was shadowed
in PATH by a version manager (pyenv, conda, asdf). Install the bindings for the
system interpreter:

  Debian/Ubuntu:  sudo apt install python3-gi python3-gi-cairo gir1.2-gtk-4.0 gir1.2-adw-1
  Fedora:         sudo dnf install python3-gobject gtk4 libadwaita
EOF
exit 1
