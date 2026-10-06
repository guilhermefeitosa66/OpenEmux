#version 450
// OpenEmux in-game control bar: keep the bottom of the screen for the bar.
// The slang twin of margin.glsl, for the Vulkan-era drivers (glcore, vulkan,
// d3d11/12). Same arithmetic: shrink by (1 - MARGIN), top-anchored, centered.

layout(push_constant) uniform Push
{
    vec4 SourceSize;
    vec4 OutputSize;
    float MARGIN;
} params;

#pragma parameter MARGIN "Bottom margin for the control bar" 0.083333 0.0 0.5 0.005

layout(std140, set = 0, binding = 0) uniform UBO
{
    mat4 MVP;
} global;

#pragma stage vertex
layout(location = 0) in vec4 Position;
layout(location = 1) in vec2 TexCoord;
layout(location = 0) out vec2 vTexCoord;

void main()
{
    gl_Position = global.MVP * Position;
    vTexCoord = TexCoord;
}

#pragma stage fragment
layout(location = 0) in vec2 vTexCoord;
layout(location = 0) out vec4 FragColor;
layout(set = 0, binding = 2) uniform sampler2D Source;

void main()
{
    float s = 1.0 - params.MARGIN;
    vec2 src = vec2((vTexCoord.x - (1.0 - s) * 0.5) / s, vTexCoord.y / s);
    if (src.x < 0.0 || src.x > 1.0 || src.y < 0.0 || src.y > 1.0)
        FragColor = vec4(0.0, 0.0, 0.0, 1.0);
    else
        FragColor = texture(Source, src);
}
