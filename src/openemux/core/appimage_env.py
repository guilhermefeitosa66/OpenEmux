"""The environment a child process gets when OpenEmux runs from its AppImage.

An AppImage rewrites the environment of everything it starts: the dynamic
loader path, ``LD_PRELOAD``, ``PYTHONHOME``, the GObject typelib and
gdk-pixbuf caches, ``XDG_DATA_DIRS``. That is right for the app -- it *is*
the bundle -- and wrong for the vendored RetroArch AppImage it launches,
which is a self-contained bundle of its own and has to see the host.

The trap is that RetroArch lives *inside* our AppDir
(``$APPDIR/usr/lib/openemux/vendors/``), and appimage-builder's AppRun hooks
decide by path: a binary under ``$APPDIR`` is treated as part of this bundle
and handed this bundle's environment. Measured inside the built AppImage, a
process started from ``vendors/`` inherited ``LD_LIBRARY_PATH`` and
``LD_PRELOAD=libapprun_hooks.so`` pointing into the AppDir, ``PYTHONHOME``,
``PYTHONPATH``, ``GI_TYPELIB_PATH``, ``GDK_PIXBUF_MODULEDIR``,
``GSETTINGS_SCHEMA_DIR``, ``GTK_PATH`` and a ``PATH``/``XDG_DATA_DIRS``
leading into the mount (issue #249). So RetroArch resolved its libraries
against the Ubuntu-noble stack bundled for a GTK4 app, with a pixbuf loader
cache and a typelib path that are not its own.

An environment passed explicitly to ``Popen`` is *not* re-decorated by the
hooks -- verified the same way -- so building one here is the whole fix.

What the session had is not guesswork: before AppRun overwrites a variable it
keeps the old value as ``APPRUN_ORIGINAL_<NAME>``, and those are the ones the
child needs back. Nothing inside the bundle can recover them independently --
``openemux-run.sh`` looks like the place to record them, but it already runs
with the bundle's environment applied and would only write the bundle's own
values back under a different name.

Outside an AppImage this module does nothing: a native or Flatpak install has
no bundle variables to strip, and stripping the user's own would be the same
mistake in the other direction.
"""

import os

from openemux.core.paths import is_running_in_appimage

#: Variables an AppImage bundle sets that no child of ours may inherit. The
#: loader ones are the dangerous half; the rest point GTK, GI and gdk-pixbuf
#: at caches built for this app's library versions.
BUNDLE_VARS = (
    "APPDIR",
    "APPIMAGE",
    "APPIMAGE_UUID",
    "ARGV0",
    "OWD",
    "ORIGIN",
    "LD_LIBRARY_PATH",
    "LD_PRELOAD",
    "PYTHONHOME",
    "PYTHONPATH",
    "GI_TYPELIB_PATH",
    "GDK_PIXBUF_MODULEDIR",
    "GDK_PIXBUF_MODULE_FILE",
    "GIO_MODULE_DIR",
    "GSETTINGS_SCHEMA_DIR",
    "GTK_EXE_PREFIX",
    "GTK_DATA_PREFIX",
    "GTK_PATH",
    # Ours, not the bundle's, but it names a path inside the mount and the
    # child has no use for it.
    "OPENEMUX_PROJECT_ROOT",
    "OPENEMUX_SELFTEST",
)

#: Everything under these prefixes goes too: appimage-builder's AppRun keeps
#: its own bookkeeping there (``APPDIR_LIBRARY_PATH``, ``APPRUN_STARTUP_*``,
#: ``APPRUN_ORIGINAL_*``), which is ours to read and means nothing to a child.
BUNDLE_PREFIXES = ("APPDIR_", "APPRUN_")

#: Where AppRun parks a variable's pre-bundle value.
ORIGINAL_PREFIX = "APPRUN_ORIGINAL_"

#: Variables whose value is a ``:``-separated path list. After the restore
#: below, any component still pointing inside the AppDir is swept from these
#: -- the last line of defence if AppRun's record did not survive.
PATH_LIST_VARS = (
    "PATH",
    "XDG_DATA_DIRS",
    "XDG_CONFIG_DIRS",
    "LD_LIBRARY_PATH",
    "GI_TYPELIB_PATH",
)

#: A minimal PATH, for the case where sweeping leaves nothing at all. A child
#: with no PATH cannot find so much as ``sh``.
FALLBACK_PATH = "/usr/local/bin:/usr/bin:/bin"


def _host_values(env):
    """Every ``APPRUN_ORIGINAL_<NAME>``, as ``{name: value or None}``.

    AppRun writes one for each variable it is about to overwrite, so this is
    the session as it stood before the bundle. An entry with an empty value
    means the session had none -- a real answer, and a different one from
    "not recorded".
    """
    return {
        key[len(ORIGINAL_PREFIX):]: (value or None)
        for key, value in env.items()
        if key.startswith(ORIGINAL_PREFIX)
    }


def _without_appdir(value, appdir):
    """``value`` as a path list with every component inside ``appdir`` gone."""
    if not value or not appdir:
        return value
    kept = [
        part
        for part in value.split(os.pathsep)
        if part and not (part == appdir or part.startswith(appdir + os.sep))
    ]
    return os.pathsep.join(kept)


def host_env(env=None, in_appimage=None):
    """A copy of ``env`` fit for a process that is not part of this bundle.

    Outside an AppImage this is ``dict(env)`` and nothing else: there is no
    bundle to strip, and a native install's ``LD_PRELOAD`` or ``PYTHONPATH``
    belongs to the user.
    """
    env = dict(os.environ if env is None else env)
    if in_appimage is None:
        in_appimage = is_running_in_appimage()
    if not in_appimage:
        return env

    appdir = env.get("APPDIR") or ""
    cleaned = {
        name: value
        for name, value in env.items()
        if name not in BUNDLE_VARS and not name.startswith(BUNDLE_PREFIXES)
    }

    # Put back exactly what the session had, wherever AppRun recorded it --
    # including "it had none", which is why this drops as well as sets. A
    # variable the session never defined is one the bundle invented, and
    # handing the child a trimmed version of an invention is still an
    # invention. This is also the only way XDG_DATA_DIRS comes back whole:
    # AppRun replaces it outright, so the desktop's own entries are not
    # sitting in the value waiting to be trimmed out.
    for name, original in _host_values(env).items():
        if original is None:
            cleaned.pop(name, None)
        else:
            cleaned[name] = original

    # Then sweep any path component still inside the AppDir. This is what
    # saves a bundle whose records did not survive -- an old AppImage, or an
    # AppRun that renamed its bookkeeping -- and a no-op when they did.
    for name in PATH_LIST_VARS:
        swept = _without_appdir(cleaned.get(name), appdir)
        if swept:
            cleaned[name] = swept
        else:
            cleaned.pop(name, None)

    if not cleaned.get("PATH"):
        cleaned["PATH"] = FALLBACK_PATH
    return cleaned
