"""Which video driver RetroArch runs, and which shader presets it can load (#366).

A shader preset is not portable across video drivers. ``.glslp`` is the legacy
GLSL path and only the ``gl`` driver reads it; ``.slangp`` is the Vulkan-era
format that ``vulkan``, ``glcore``, ``d3d10/11/12`` and ``metal`` read and that
``gl`` cannot. Handing a driver the wrong one is not an error the user sees --
RetroArch discards it and carries on.

That is exactly what happened on Windows. ``ShaderCatalog`` preferred glsl
unconditionally, and RetroArch's Windows default is ``d3d11``, so every console
with a shader configured launched without one and the launch log did not carry a
single shader line to say why (issue #366).

So the backend follows the driver, and the driver stops being a guess:

* on Windows the launch override *names* ``d3d11``, the driver RetroArch would
  have chosen anyway, so what OpenEmux resolves presets for and what RetroArch
  runs cannot drift apart;
* on Linux nothing is written, because the vendored build's default is ``gl``
  and writing a key to restate a default is a line that reads as load-bearing
  and is not. Measured rather than assumed: run the vendored RetroArch with an
  empty config and its log says ``[GL] Found GL context``.

Launch-scoped like every other value OpenEmux writes: ``--appendconfig`` plus
``config_save_on_exit = false``, so a user's own RetroArch keeps whatever they
chose.
"""

from openemux.core.platform import IS_WINDOWS

#: ``video_driver: auto`` in config.yaml -- the platform's own default. The
#: default, and the only value most installs ever have.
AUTO = "auto"

#: The driver RetroArch picks for itself when nothing names one. Windows is
#: ``d3d11`` (issue #366's log says so); every desktop Linux build is ``gl``.
WINDOWS_DEFAULT = "d3d11"
LINUX_DEFAULT = "gl"

#: Presets by the driver that can load them. A driver in neither set loads no
#: preset at all -- ``sdl2``, ``null`` and the software drivers have no shader
#: pipeline -- and asking RetroArch for one is how a shader silently goes
#: missing.
GLSL_DRIVERS = frozenset({"gl"})
SLANG_DRIVERS = frozenset({"glcore", "vulkan", "metal", "d3d10", "d3d11", "d3d12"})


def default_video_driver():
    """The driver RetroArch runs here when nobody names one."""
    return WINDOWS_DEFAULT if IS_WINDOWS else LINUX_DEFAULT


def resolve_video_driver(setting):
    """The driver to write into the launch override, or ``None`` to write none.

    ``auto`` (the default) names the driver on Windows and stays quiet on
    Linux; any other value is passed through, for the ``vulkan`` and ``glcore``
    setups that want to say so.
    """
    value = (setting or "").strip().lower() or AUTO
    if value != AUTO:
        return value
    return WINDOWS_DEFAULT if IS_WINDOWS else None


def effective_video_driver(setting):
    """The driver RetroArch will actually run, written or not.

    Never ``None``: the shader backend has to be chosen against something, and
    "nothing was written" means "RetroArch's own default", not "unknown".
    """
    return resolve_video_driver(setting) or default_video_driver()


def preset_backends(video_driver):
    """The preset backends ``video_driver`` can load, best first.

    Empty for a driver that loads neither -- and empty is an answer, not a
    failure to have one. The caller says so instead of handing RetroArch a
    preset it will drop on the floor without a word.
    """
    driver = (video_driver or "").strip().lower()
    if driver in GLSL_DRIVERS:
        return ("glsl",)
    if driver in SLANG_DRIVERS:
        return ("slang",)
    return ()
