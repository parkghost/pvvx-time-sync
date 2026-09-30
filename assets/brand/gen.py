import math
from pathlib import Path


def pt(cx, cy, r, deg):
    a = math.radians(deg)
    return cx + r * math.cos(a), cy + r * math.sin(a)


def icon(ring, hands, badge, badge_fg, cut):
    cx = cy = 236
    r = 172
    sw = 46
    start, end = -62, 236  # clockwise sweep in SVG degrees (y down)
    x0, y0 = pt(cx, cy, r, start)
    x1, y1 = pt(cx, cy, r, end)
    large = 1 if (end - start) % 360 > 180 else 0
    # Arrowhead at the end, pointing along the clockwise tangent.
    t = math.radians(end)
    tx, ty = -math.sin(t), math.cos(t)
    nx, ny = math.cos(t), math.sin(t)
    tip = (x1 + tx * 58, y1 + ty * 58)
    b1 = (x1 + nx * 62 - tx * 6, y1 + ny * 62 - ty * 6)
    b2 = (x1 - nx * 62 - tx * 6, y1 - ny * 62 - ty * 6)
    hx, hy = pt(cx, cy, 88, 0)  # hour hand at 3 o'clock
    mx, my = pt(cx, cy, 124, -90)  # minute hand at 12 o'clock
    bx, by, br = 396, 396, 100
    rune = (
        f"M{bx - 30},{by - 30} L{bx + 30},{by + 26} L{bx},{by + 56} L{bx},{by - 56} "
        f"L{bx + 30},{by - 26} L{bx - 30},{by + 30}"
    )
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512" width="512" height="512">
  <path d="M{x0:.1f},{y0:.1f} A{r},{r} 0 {large} 1 {x1:.1f},{y1:.1f}" fill="none"
        stroke="{ring}" stroke-width="{sw}" stroke-linecap="round"/>
  <path d="M{tip[0]:.1f},{tip[1]:.1f} L{b1[0]:.1f},{b1[1]:.1f} L{b2[0]:.1f},{b2[1]:.1f} Z"
        fill="{ring}" stroke="{ring}" stroke-width="10" stroke-linejoin="round"/>
  <g stroke="{hands}" stroke-linecap="round">
    <line x1="{cx}" y1="{cy}" x2="{hx:.1f}" y2="{hy:.1f}" stroke-width="40"/>
    <line x1="{cx}" y1="{cy}" x2="{mx:.1f}" y2="{my:.1f}" stroke-width="30"/>
  </g>
  <circle cx="{cx}" cy="{cy}" r="26" fill="{hands}"/>
  <circle cx="{bx}" cy="{by}" r="{br + 18}" fill="{cut}"/>
  <circle cx="{bx}" cy="{by}" r="{br}" fill="{badge}"/>
  <path d="{rune}" fill="none" stroke="{badge_fg}" stroke-width="17"
        stroke-linecap="round" stroke-linejoin="round"/>
</svg>
"""


light = icon(
    ring="#1E88E5", hands="#263238", badge="#1E88E5", badge_fg="#FFFFFF", cut="#FFFFFF"
)
dark = icon(
    ring="#64B5F6", hands="#ECEFF1", badge="#64B5F6", badge_fg="#102027", cut="#1C1C1C"
)
Path("icon.svg").write_text(light)
Path("dark_icon.svg").write_text(dark)


def logo(icon_svg, accent, text):
    inner = icon_svg.split(">", 1)[1].rsplit("</svg>", 1)[0]
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1500 512" width="1500" height="512">
  <svg x="0" y="0" width="512" height="512" viewBox="0 0 512 512">{inner}</svg>
  <text x="560" y="238" font-family="Inter" font-weight="800" font-size="200" fill="{accent}">pvvx</text>
  <text x="566" y="420" font-family="Inter" font-weight="600" font-size="150" fill="{text}">Time Sync</text>
</svg>
"""


Path("logo.svg").write_text(logo(light, "#1E88E5", "#263238"))
Path("dark_logo.svg").write_text(logo(dark, "#64B5F6", "#ECEFF1"))
