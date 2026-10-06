// OpenEmux in-game control bar: keep the bottom of the screen for the bar.
// Shrinks the game by (1 - MARGIN), aspect kept, anchored to the top and
// centered, so the bottom strip stays black for the overlay dock to sit in.
// Runs as the last pass, at viewport scale. MARGIN must agree with STRIP / H
// in scripts/build_overlay.py.
#if defined(VERTEX)
#if __VERSION__ >= 130
#define COMPAT_VARYING out
#define COMPAT_ATTRIBUTE in
#else
#define COMPAT_VARYING varying
#define COMPAT_ATTRIBUTE attribute
#endif
COMPAT_ATTRIBUTE vec4 VertexCoord;
COMPAT_ATTRIBUTE vec4 TexCoord;
COMPAT_VARYING vec4 TEX0;
uniform mat4 MVPMatrix;
void main() {
    gl_Position = MVPMatrix * VertexCoord;
    TEX0.xy = TexCoord.xy;
}
#elif defined(FRAGMENT)
#ifdef GL_ES
precision mediump float;
#endif
#if __VERSION__ >= 130
#define COMPAT_VARYING in
#define COMPAT_TEXTURE texture
out vec4 FragColor;
#else
#define COMPAT_VARYING varying
#define FragColor gl_FragColor
#define COMPAT_TEXTURE texture2D
#endif
uniform sampler2D Texture;
uniform vec2 TextureSize;
uniform vec2 InputSize;
COMPAT_VARYING vec4 TEX0;
#pragma parameter MARGIN "Bottom margin for the control bar" 0.083333 0.0 0.5 0.005
#ifdef PARAMETER_UNIFORM
uniform float MARGIN;
#else
#define MARGIN 0.083333
#endif
void main() {
    vec2 uv = TEX0.xy * TextureSize / InputSize;
    float s = 1.0 - MARGIN;
    vec2 src = vec2((uv.x - (1.0 - s) * 0.5) / s, uv.y / s);
    if (src.x < 0.0 || src.x > 1.0 || src.y < 0.0 || src.y > 1.0) {
        FragColor = vec4(0.0, 0.0, 0.0, 1.0);
    } else {
        FragColor = COMPAT_TEXTURE(Texture, src * InputSize / TextureSize);
    }
}
#endif
