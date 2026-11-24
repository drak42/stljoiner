"""Draw stljoiner's media in the green-screen style of the drak42 projects.

Makes, in this folder:
  banner.svg / banner.png   1280x640 (GitHub's social-preview size): STL code rain,
                            a CRT console running stljoin and the split part
                            drawn as a glowing wireframe, cut faces lit.
  how-it-works.gif          the scattered pieces fly together onto their cut
                            faces and fuse into one solid.

The geometry is the real test part from tests/make_test_parts.py. Rendering
the SVGs to PNG uses headless Google Chrome; building the GIF needs Pillow.

    .venv/bin/python docs/images/make_media.py
"""
from __future__ import annotations

import math
import random
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from xml.sax.saxutils import escape

import numpy as np
import trimesh
from trimesh.transformations import quaternion_from_matrix, quaternion_matrix, quaternion_slerp

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from make_test_parts import make_original, split  # noqa: E402

GREEN, BRIGHT, PALE, CYAN, DIM = "#39ff7a", "#d8ffe4", "#7dffaa", "#2fd8ff", "#1d6b3c"
TOKENS = ["solid", "facet", "normal", "vertex", "outer", "loop", "endloop", "endfacet", "0", "1", "2", "3",
          "4", "5", "6", "7", "8", "9", ".", "-", "e", "+"]

DEFS = """<defs>
  <radialGradient id="vignette" cx="50%" cy="50%" r="75%">
    <stop offset="55%" stop-color="#000" stop-opacity="0"/>
    <stop offset="100%" stop-color="#000" stop-opacity="0.85"/>
  </radialGradient>
  <linearGradient id="screen" x1="0" y1="0" x2="0" y2="1">
    <stop offset="0" stop-color="#03140a"/><stop offset="1" stop-color="#010804"/>
  </linearGradient>
  <filter id="glow" x="-20%" y="-20%" width="140%" height="140%">
    <feGaussianBlur stdDeviation="2.2" result="b"/>
    <feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge>
  </filter>
  <filter id="bigglow" x="-30%" y="-60%" width="160%" height="220%">
    <feGaussianBlur stdDeviation="7" result="b"/>
    <feMerge><feMergeNode in="b"/><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge>
  </filter>
  <pattern id="scan" width="4" height="4" patternUnits="userSpaceOnUse">
    <rect width="4" height="2" fill="#000" fill-opacity="0.28"/>
  </pattern>
  <filter id="soft" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation="28"/></filter>
  <clipPath id="crt"><rect x="70" y="150" width="640" height="400" rx="26"/></clipPath>
</defs>"""


# --------------------------------------------------------------------------
# Shared drawing pieces
# --------------------------------------------------------------------------

def svg_open(w: int, h: int, title: str) -> list[str]:
    return [f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" '
            'font-family="DejaVu Sans Mono, Menlo, Consolas, monospace">', f"<title>{escape(title)}</title>",
            DEFS, f'<rect width="{w}" height="{h}" fill="#000"/>']


def svg_close(out: list[str], w: int, h: int) -> str:
    out.append(f'<rect width="{w}" height="{h}" fill="url(#vignette)"/>')
    out.append(f'<rect width="{w}" height="{h}" fill="url(#scan)" fill-opacity="0.35"/>')
    out.append("</svg>")
    return "\n".join(out)


class Rain:
    """Columns of falling STL tokens; step() moves them down for animation."""

    def __init__(self, w: int, h: int, seed: int, size: int = 15, step_y: int = 18) -> None:
        rng = random.Random(seed)
        self.w, self.h, self.size, self.step_y = w, h, size, step_y
        self.cols = []
        for col in range(w // 22 + 1):
            tokens = []
            for _ in range(40):
                t = rng.choice(TOKENS)
                tokens.append(t[: rng.choice((1, 2))] if len(t) > 2 else t)
            self.cols.append({"x": col * 22 + 4, "head": rng.uniform(-100, h + 200),
                              "len": rng.randint(6, 26), "speed": rng.uniform(4, 11), "tokens": tokens})

    def step(self) -> None:
        for c in self.cols:
            c["head"] += c["speed"]
            if c["head"] - c["len"] * self.step_y > self.h + 20:
                c["head"] = -20

    def draw(self) -> str:
        parts = [f'<g font-size="{self.size}">']
        for c in self.cols:
            shift = int(c["head"] // self.step_y)
            for i in range(c["len"]):
                y = c["head"] - i * self.step_y
                if y < -20 or y > self.h + 20:
                    continue
                fade = 1 - i / c["len"]
                colour, opacity = ("#b8ffcf", 0.75) if i == 0 else ("#00ff66", 0.08 + 0.42 * fade ** 1.6)
                token = c["tokens"][(i + shift) % len(c["tokens"])]
                parts.append(f'<text x="{c["x"]}" y="{y:.0f}" fill="{colour}" '
                             f'fill-opacity="{opacity:.2f}">{escape(token)}</text>')
        parts.append("</g>")
        return "\n".join(parts)


class View:
    """Orthographic camera: world mm -> screen px."""

    def __init__(self, azimuth: float = -58, elevation: float = 24) -> None:
        az, el = math.radians(azimuth), math.radians(elevation)
        d = np.array([math.cos(el) * math.cos(az), math.cos(el) * math.sin(az), math.sin(el)])
        self.right = np.cross(-d, [0, 0, 1.0])
        self.right /= np.linalg.norm(self.right)
        self.up = np.cross(self.right, -d)
        self.dir = d
        self.scale, self.offset = 1.0, np.zeros(2)

    def raw(self, p: np.ndarray) -> np.ndarray:
        return np.stack([p @ self.right, -(p @ self.up)], axis=-1)

    def fit(self, points: np.ndarray, box: tuple[float, float, float, float]) -> None:
        """Scale/offset so `points` fill box = (x, y, w, h)."""
        s = self.raw(points)
        lo, hi = s.min(0), s.max(0)
        x, y, w, h = box
        self.scale = min(w / (hi - lo)[0], h / (hi - lo)[1])
        self.offset = np.array([x + w / 2, y + h / 2]) - self.scale * (lo + hi) / 2

    def __call__(self, p: np.ndarray) -> np.ndarray:
        return self.raw(p) * self.scale + self.offset


def feature_edges(mesh: trimesh.Trimesh, angle: float = 20) -> np.ndarray:
    """Edges where the surface bends: the lines of a clean wireframe. (n,2,3)"""
    sharp = mesh.face_adjacency_angles > math.radians(angle)
    return mesh.vertices[mesh.face_adjacency_edges[sharp]]


def cut_face_polys(mesh: trimesh.Trimesh, xs: list[float]) -> list[np.ndarray]:
    """Triangles (m,3,3) of the faces lying on the planes x = cut (in part coordinates)."""
    out = []
    for x in xs:
        on = np.all(np.abs(mesh.triangles[:, :, 0] - x) < 1e-6, axis=1)
        if on.any():
            out.append(mesh.triangles[on])
    return out


def draw_part(view: View, T: np.ndarray, edges: np.ndarray, faces: list[np.ndarray],
              colour: str, face_colour: str, face_opacity: float, edge_opacity: float = 1.0) -> str:
    parts = []
    for tris in faces:
        pts = view(trimesh.transform_points(tris.reshape(-1, 3), T)).reshape(-1, 3, 2)
        d = " ".join(f"M{a[0]:.1f},{a[1]:.1f}L{b[0]:.1f},{b[1]:.1f}L{c[0]:.1f},{c[1]:.1f}Z" for a, b, c in pts)
        if face_opacity > 0.01:
            parts.append(f'<path d="{d}" fill="{face_colour}" fill-opacity="{face_opacity:.2f}" stroke="none"/>')
    if len(edges):
        e = view(trimesh.transform_points(edges.reshape(-1, 3), T)).reshape(-1, 2, 2)
        d = " ".join(f"M{a[0]:.1f},{a[1]:.1f}L{b[0]:.1f},{b[1]:.1f}" for a, b in e)
        parts.append(f'<path d="{d}" fill="none" stroke="{colour}" stroke-opacity="{edge_opacity:.2f}" '
                     'stroke-width="1.8" stroke-linecap="round"/>')
    return "\n".join(parts)


def grid_plate(view: View, z: float, half: tuple[float, float], center=(0.0, 0.0), n: int = 8) -> str:
    cx, cy = center
    hx, hy = half
    parts = []
    corners = np.array([[cx - hx, cy - hy, z], [cx + hx, cy - hy, z], [cx + hx, cy + hy, z], [cx - hx, cy + hy, z]])
    c = view(corners)
    parts.append('<polygon points="' + " ".join(f"{x:.0f},{y:.0f}" for x, y in c) +
                 f'" stroke="{DIM}" stroke-width="2" fill="#03140a" fill-opacity="0.8"/>')
    for i in range(1, n):
        t = i / n
        for a, b in (([cx - hx + 2 * hx * t, cy - hy, z], [cx - hx + 2 * hx * t, cy + hy, z]),
                     ([cx - hx, cy - hy + 2 * hy * t, z], [cx + hx, cy - hy + 2 * hy * t, z])):
            p = view(np.array([a, b]))
            parts.append(f'<line x1="{p[0][0]:.0f}" y1="{p[0][1]:.0f}" x2="{p[1][0]:.0f}" y2="{p[1][1]:.0f}" '
                         'stroke="#0f3d22" stroke-width="1"/>')
    return "\n".join(parts)


# --------------------------------------------------------------------------
# Geometry
# --------------------------------------------------------------------------

CUTS = [-20.0, 25.0]
ORIGINAL = make_original()
PIECES = split(ORIGINAL, CUTS)
EDGES = [feature_edges(p) for p in PIECES]
CUT_FACES = [cut_face_polys(p, CUTS) for p in PIECES]
WHOLE_EDGES = feature_edges(ORIGINAL)


def translate(v) -> np.ndarray:
    T = np.eye(4)
    T[:3, 3] = v
    return T


# --------------------------------------------------------------------------
# Banner
# --------------------------------------------------------------------------

def banner() -> str:
    W, H = 1280, 640
    out = svg_open(W, H, "stljoiner")
    out.append(Rain(W, H, seed=7).draw())
    out.append('<ellipse cx="640" cy="98" rx="470" ry="70" fill="#000" fill-opacity="0.92" filter="url(#soft)"/>')
    out.append('<ellipse cx="1000" cy="360" rx="270" ry="230" fill="#000" fill-opacity="0.92" filter="url(#soft)"/>')

    out.append('<g filter="url(#bigglow)"><text x="640" y="92" text-anchor="middle" font-size="76" '
               f'font-weight="bold" letter-spacing="10" fill="{GREEN}">STLJOINER</text></g>')
    out.append(f'<text x="640" y="126" text-anchor="middle" font-size="17" letter-spacing="5" fill="{PALE}" '
               'fill-opacity="0.85">SPLIT PARTS IN &#183; CUT FACES MATCHED &#183; ONE SOLID OUT</text>')

    # CRT console with a real run (long lines wrapped to fit the screen).
    out.append('<rect x="58" y="138" width="664" height="424" rx="34" fill="#0a0f0b" stroke="#1f3a28" '
               'stroke-width="3"/>')
    out.append('<rect x="70" y="150" width="640" height="400" rx="26" fill="url(#screen)"/>')
    lines = [
        ("$ stljoin.py bracket_*.stl -o bracket.stl", "#b6ffcc"),
        ("", None),
        ("Finding mating faces among 3 parts...", GREEN),
        ("  bracket_a.stl: 6 candidate faces", GREEN),
        ("  bracket_b.stl: 6 candidate faces", GREEN),
        ("  bracket_c.stl: 8 candidate faces", GREEN),
        ("  joined bracket_c.stl → bracket_b.stl:", GREEN),
        ("    face area 1200.0 mm², fit 100.0%", GREEN),
        ("  joined bracket_b.stl → bracket_a.stl:", GREEN),
        ("    face area 840.0 mm², fit 100.0%", GREEN),
        ("Wrote bracket.stl — 120.0 × 40.0 × 80.0 mm,", "#9dffbd"),
        ("  watertight=True", "#9dffbd"),
        ("$ █", "#b6ffcc"),
    ]
    out.append('<g clip-path="url(#crt)" filter="url(#glow)" font-size="18">')
    for n, (text, colour) in enumerate(lines):
        if colour:
            out.append(f'<text x="98" y="{196 + n * 26}" fill="{colour}" xml:space="preserve">{escape(text)}</text>')
    out.append("</g>")
    out.append('<rect x="70" y="150" width="640" height="400" rx="26" fill="url(#scan)"/>')
    out.append(f'<rect x="70" y="150" width="640" height="400" rx="26" fill="none" stroke="{GREEN}" '
               'stroke-opacity="0.25" stroke-width="2"/>')
    out.append('<path d="M96 162 Q 380 150 690 170 L 690 196 Q 380 178 96 192 Z" fill="#fff" fill-opacity="0.035"/>')

    # The three pieces pulled apart along their cuts, cut faces lit, arrows closing the gaps.
    gap = 52.0
    moves = [translate([-gap, 0, 0]), np.eye(4), translate([gap, 0, 0])]
    view = View()
    pts = np.vstack([trimesh.transform_points(p.vertices, T) for p, T in zip(PIECES, moves, strict=True)])
    view.fit(np.vstack([pts, [[-120, -45, -15], [120, 45, -15]]]), (770, 175, 460, 330))
    out.append('<g filter="url(#glow)">')
    out.append(grid_plate(view, -15.5, (120, 45)))
    for p_edges, faces, T in zip(EDGES, CUT_FACES, moves, strict=True):
        out.append(draw_part(view, T, p_edges, faces, GREEN, CYAN, 0.30))
    # two arrows closing each gap, meeting in its middle
    for left, right in ((CUTS[0] - gap, CUTS[0]), (CUTS[1], CUTS[1] + gap)):
        mid = (left + right) / 2
        for s, e in (((left + 3, 0, 24), (mid - 3, 0, 24)), ((right - 3, 0, 24), (mid + 3, 0, 24))):
            a, b = view(np.array([s, e]))
            out.append(f'<line x1="{a[0]:.0f}" y1="{a[1]:.0f}" x2="{b[0]:.0f}" y2="{b[1]:.0f}" stroke="{BRIGHT}" '
                       'stroke-width="2" stroke-dasharray="5 4"/>')
            v = (b - a) / np.linalg.norm(b - a)
            n = np.array([-v[1], v[0]])
            tip = [b, b - 9 * v + 5 * n, b - 9 * v - 5 * n]
            out.append('<polygon points="' + " ".join(f"{p[0]:.0f},{p[1]:.0f}" for p in tip) + f'" fill="{BRIGHT}"/>')
    out.append("</g>")
    label = view(np.array([[CUTS[0] - gap / 2, 0, 24]]))[0]
    out.append(f'<text x="{label[0]:.0f}" y="{label[1] - 22:.0f}" text-anchor="middle" font-size="14" fill="{PALE}" '
               'fill-opacity="0.9" filter="url(#glow)">FIT 100.0%</text>')
    return svg_close(out, W, H)


# --------------------------------------------------------------------------
# How-it-works animation
# --------------------------------------------------------------------------

def ease(t: float) -> float:
    t = min(max(t, 0.0), 1.0)
    return t * t * (3 - 2 * t)


def scattered_poses(seed: int = 3) -> list[np.ndarray]:
    rng = np.random.default_rng(seed)
    offsets = [[-70, -30, 35], [0, 40, 60], [75, -20, 25]]
    poses = []
    for off in offsets:
        R = trimesh.transformations.random_rotation_matrix(rng.random(3))
        R[:3, 3] = off
        poses.append(R)
    return poses


def pose_at(start: np.ndarray, center: np.ndarray, t: float) -> np.ndarray:
    """Blend from `start` to identity: slerp the rotation about the piece's centre, lerp its position."""
    q = quaternion_slerp(quaternion_from_matrix(start), [1, 0, 0, 0], t)
    R = quaternion_matrix(q)
    start_center = trimesh.transform_points([center], start)[0]
    pos = start_center * (1 - t) + center * t
    return translate(pos) @ R @ translate(-center)


def frames(W: int = 800, H: int = 450) -> list[tuple[str, int]]:
    """[(svg, duration_ms)]"""
    rain = Rain(W, H, seed=11, size=13, step_y=16)
    starts = scattered_poses()
    centers = [p.bounds.mean(0) for p in PIECES]
    view = View()
    reach = np.vstack([trimesh.transform_points(p.vertices, s) for p, s in zip(PIECES, starts, strict=True)]
                      + [ORIGINAL.vertices])
    view.fit(np.vstack([reach, [[-100, -60, -20], [100, 60, -20]]]), (140, 60, 520, 300))

    captions = [(0, "Split parts, any position"), (14, "Cut faces matched, pieces snap together"),
                (44, "Fused into one watertight solid")]
    timeline = []
    for f in range(66):
        if f < 14:          # hold scattered, cut faces pulsing
            t, glow, fuse = 0.0, 0.35 + 0.25 * math.sin(f / 2.2), 0.0
        elif f < 42:        # fly together
            t, glow, fuse = ease((f - 14) / 26), 0.45, 0.0
        else:               # fuse: cut faces and seams fade out, whole outline fades in
            t, glow, fuse = 1.0, 0.45 * (1 - ease((f - 42) / 10)), ease((f - 42) / 10)
        caption = [c for start, c in captions if f >= start][-1]

        out = svg_open(W, H, "stljoiner: how it works")
        rain.step()
        out.append(rain.draw())
        out.append(f'<ellipse cx="{W / 2}" cy="{H / 2 - 10}" rx="300" ry="190" fill="#000" fill-opacity="0.93" '
                   'filter="url(#soft)"/>')
        out.append('<g filter="url(#glow)">')
        out.append(grid_plate(view, -15.5, (100, 45)))
        for piece_edges, faces, start, c in zip(EDGES, CUT_FACES, starts, centers, strict=True):
            T = pose_at(start, c, t)
            out.append(draw_part(view, T, piece_edges, faces, GREEN, CYAN, glow, edge_opacity=1 - fuse))
        if fuse > 0:
            out.append(draw_part(view, np.eye(4), WHOLE_EDGES, [], BRIGHT if fuse < 1 else GREEN, CYAN, 0,
                                 edge_opacity=fuse))
        out.append("</g>")
        out.append(f'<rect x="0" y="{H - 52}" width="{W}" height="52" fill="#000" fill-opacity="0.85"/>')
        out.append(f'<text x="{W / 2}" y="{H - 19}" text-anchor="middle" font-size="20" letter-spacing="2" '
                   f'fill="{GREEN}" filter="url(#glow)">{escape(caption)}</text>')
        hold = {13: 900, 41: 300, 65: 2400}.get(f, 70)
        timeline.append((svg_close(out, W, H), hold))
    return timeline


# --------------------------------------------------------------------------
# Rendering
# --------------------------------------------------------------------------

def chrome() -> str:
    for name in ("google-chrome", "chromium", "chromium-browser", "chrome"):
        if path := shutil.which(name):
            return path
    sys.exit("Google Chrome or Chromium is needed to render the SVGs to PNG")


def render(svg: Path, png: Path, w: int, h: int) -> None:
    subprocess.run([chrome(), "--headless=new", "--hide-scrollbars", "--disable-gpu",
                    f"--window-size={w},{h}", f"--screenshot={png}", svg.as_uri()],
                   check=True, capture_output=True)


def main() -> None:
    from PIL import Image

    (HERE / "banner.svg").write_text(banner(), encoding="utf-8")
    render(HERE / "banner.svg", HERE / "banner.png", 1280, 640)
    print("wrote banner.svg, banner.png")

    with tempfile.TemporaryDirectory() as tmp:
        imgs, durations = [], []
        for i, (svg, ms) in enumerate(frames()):
            s, p = Path(tmp) / f"f{i:03d}.svg", Path(tmp) / f"f{i:03d}.png"
            s.write_text(svg, encoding="utf-8")
            render(s, p, 800, 450)
            imgs.append(Image.open(p).convert("RGB"))
            durations.append(ms)
        # One shared palette keeps the colours steady from frame to frame.
        # Built from frames across the whole animation so every colour (the cyan
        # cut faces too) gets palette entries.
        sample = imgs[:: max(1, len(imgs) // 6)]
        sheet = Image.new("RGB", (imgs[0].width, imgs[0].height * len(sample)))
        for k, im in enumerate(sample):
            sheet.paste(im, (0, k * im.height))
        palette = sheet.quantize(colors=160, method=Image.Quantize.MEDIANCUT)
        frames_p = [im.quantize(palette=palette, dither=Image.Dither.NONE) for im in imgs]
        frames_p[0].save(HERE / "how-it-works.gif", save_all=True, append_images=frames_p[1:],
                         duration=durations, loop=0, optimize=True)
    print(f"wrote how-it-works.gif ({len(imgs)} frames)")


if __name__ == "__main__":
    main()
