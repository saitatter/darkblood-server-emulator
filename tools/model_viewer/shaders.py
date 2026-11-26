"""GLSL programs of the model viewer."""

MESH_VS = """
#version 330
uniform mat4 u_mvp;
in vec3 in_pos; in vec3 in_nor; in vec2 in_uv; in vec3 in_col;
out vec3 v_nor; out vec2 v_uv; out vec3 v_col; out vec3 v_pos;
void main() {
    v_nor = in_nor; v_uv = in_uv; v_col = in_col; v_pos = in_pos;
    gl_Position = u_mvp * vec4(in_pos, 1.0);
}
"""

MESH_FS = """
#version 330
uniform int u_mode;            // 0 solid, 1 material, 2 weights, 3 flat colour (wire)
uniform bool u_has_tex;
uniform sampler2D u_tex;
uniform vec4 u_tint;
uniform float u_alpha_cut;     // < 0 disables
uniform vec3 u_eye;
uniform vec3 u_key;
in vec3 v_nor; in vec2 v_uv; in vec3 v_col; in vec3 v_pos;
out vec4 f_color;
void main() {
    if (u_mode == 3) { f_color = u_tint; return; }
    vec3 n = normalize(v_nor);
    vec3 view = normalize(u_eye - v_pos);
    if (dot(n, view) < 0.0) n = -n;                       // two-sided lighting
    float key = max(dot(n, normalize(u_key)), 0.0);
    float fill = max(dot(n, normalize(vec3(-0.6, 0.5, 0.3))), 0.0);
    float hemi = 0.5 + 0.5 * n.z;
    float rim = pow(1.0 - max(dot(n, view), 0.0), 3.0);
    vec4 base;
    if (u_mode == 2) base = vec4(v_col, 1.0);
    else if (u_mode == 1) {
        base = u_has_tex ? texture(u_tex, v_uv) : vec4(0.8, 0.8, 0.8, 1.0);
        base.rgb *= u_tint.rgb;
        if (u_alpha_cut >= 0.0 && base.a < u_alpha_cut) discard;
    } else base = vec4(0.80, 0.80, 0.80, 1.0);
    vec3 light;
    if (u_mode == 0) light = vec3(0.30 + 0.25 * hemi) + vec3(0.62) * key + vec3(0.18) * fill + vec3(0.12) * rim;
    else if (u_mode == 2) light = vec3(0.55 + 0.45 * key);
    else light = vec3(0.42 + 0.18 * hemi) + vec3(0.70, 0.68, 0.64) * key + vec3(0.20, 0.22, 0.26) * fill;
    vec3 rgb = base.rgb * light;
    if (u_mode == 0) {
        vec3 h = normalize(normalize(u_key) + view);
        rgb += vec3(0.25) * pow(max(dot(n, h), 0.0), 40.0);
    }
    f_color = vec4(rgb, u_mode == 1 && u_alpha_cut < 0.0 ? base.a : 1.0);
}
"""

LINE_VS = """
#version 330
uniform mat4 u_mvp;
uniform float u_point;
in vec3 in_pos; in vec4 in_col;
out vec4 v_col;
void main() { v_col = in_col; gl_Position = u_mvp * vec4(in_pos, 1.0); gl_PointSize = u_point; }
"""

LINE_FS = """
#version 330
in vec4 v_col; out vec4 f_color;
uniform bool u_round;
void main() {
    if (u_round) { vec2 d = gl_PointCoord - vec2(0.5); if (dot(d, d) > 0.25) discard; }
    f_color = v_col;
}
"""

BG_VS = """
#version 330
in vec2 in_pos; out float v_y;
void main() { v_y = in_pos.y * 0.5 + 0.5; gl_Position = vec4(in_pos, 0.999, 1.0); }
"""

BG_FS = """
#version 330
uniform vec3 u_top; uniform vec3 u_bottom;
in float v_y; out vec4 f_color;
void main() { f_color = vec4(mix(u_bottom, u_top, v_y), 1.0); }
"""
