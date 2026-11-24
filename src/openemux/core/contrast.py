"""Text contrast as WCAG 2 measures it (issue 1011).

The theme editor warns when a text color and the surface under it are too
close to read. The math is the W3C's: relative luminance of each sRGB color,
then ``(lighter + 0.05) / (darker + 0.05)``, from 1:1 (the same color) to
21:1 (black on white). Level AA asks body text for at least 4.5:1.
"""

from openemux.core.cartridge_colors import hex_to_rgb

#: The ratio WCAG 2 level AA asks of normal-size text.
WCAG_AA = 4.5


def _linear(channel):
    c = channel / 255
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def relative_luminance(color_hex):
    """0 for black, 1 for white."""
    r, g, b = (_linear(c) for c in hex_to_rgb(color_hex))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(first, second):
    """How far apart two ``#rrggbb`` colors are, 1.0 to 21.0; order free."""
    a, b = relative_luminance(first), relative_luminance(second)
    lighter, darker = max(a, b), min(a, b)
    return (lighter + 0.05) / (darker + 0.05)


def passes_aa(first, second):
    return contrast_ratio(first, second) >= WCAG_AA
