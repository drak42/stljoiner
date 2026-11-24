#!/usr/bin/env python3
"""stljoin - reassemble split STL parts by matching their mating faces.

Given several STL files that were cut from one part (e.g. split to fit a
print bed), stljoin finds the planar faces that mate with each other,
computes the rigid transform that puts each part back in place, and writes
a single combined mesh (boolean union by default).

Parts can be scattered, rotated or flipped; the alignment is found from the
shape of the cut faces alone. If the parts are already in place, that
placement is detected and kept.
"""
from __future__ import annotations

import argparse
import math
import sys
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import trimesh
from shapely import affinity
from shapely.geometry import Polygon
from shapely.ops import unary_union


# --------------------------------------------------------------------------
# Data structures
# --------------------------------------------------------------------------

@dataclass
class Face:
    """A planar region of a part that could be a mating (cut) face."""
    part: int
    index: int
    normal: np.ndarray          # outward unit normal
    centroid: np.ndarray        # area-weighted 3D centroid
    area: float
    perimeter: float
    vertices3d: np.ndarray      # vertices of the region's triangles (n,3)
    triangles: np.ndarray       # (m,3,3) triangle coordinates
    basis: np.ndarray = field(default=None)  # (2,3) in-plane axes
    polygon: Polygon = field(default=None)   # outline in (basis) coords, centered on centroid


@dataclass
class Match:
    a: Face
    b: Face
    iou: float
    transform: np.ndarray       # 4x4: moves part b so face b sits on face a
    ambiguous: bool             # other rotations fit nearly as well (symmetric face)
    in_place: bool              # parts already touch at this face

    @property
    def score(self) -> float:
        return self.iou * math.sqrt(min(self.a.area, self.b.area))


# --------------------------------------------------------------------------
# Geometry helpers
# --------------------------------------------------------------------------

def plane_basis(normal: np.ndarray) -> np.ndarray:
    """Two orthonormal in-plane axes for a plane with the given normal."""
    helper = np.array([1.0, 0, 0]) if abs(normal[0]) < 0.9 else np.array([0, 1.0, 0])
    u = np.cross(normal, helper)
    u /= np.linalg.norm(u)
    v = np.cross(normal, u)
    return np.vstack([u, v])


def rotation_between(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """3x3 rotation taking unit vector a onto unit vector b."""
    a = a / np.linalg.norm(a)
    b = b / np.linalg.norm(b)
    c = float(np.dot(a, b))
    if c > 1 - 1e-12:
        return np.eye(3)
    if c < -1 + 1e-12:
        # 180 degrees about any axis perpendicular to a
        axis = plane_basis(a)[0]
        return trimesh.transformations.rotation_matrix(math.pi, axis)[:3, :3]
    axis = np.cross(a, b)
    angle = math.atan2(np.linalg.norm(axis), c)
    return trimesh.transformations.rotation_matrix(angle, axis)[:3, :3]


def project_polygon(triangles: np.ndarray, origin: np.ndarray, basis: np.ndarray) -> Polygon:
    """Union of triangles projected into a 2D frame -> outline polygon (with holes)."""
    pts = (triangles - origin) @ basis.T            # (m,3,2)
    polys = [Polygon(t) for t in pts]
    polys = [p.buffer(0) for p in polys if p.area > 0]
    if not polys:
        return Polygon()
    # A tiny dilate/erode closes slivers between triangles from float noise.
    eps = 1e-6 * max(1.0, math.sqrt(sum(p.area for p in polys)))
    return unary_union([p.buffer(eps) for p in polys]).buffer(-eps)


def iou(p: Polygon, q: Polygon) -> float:
    if p.is_empty or q.is_empty:
        return 0.0
    inter = p.intersection(q).area
    union = p.area + q.area - inter
    return inter / union if union > 0 else 0.0


# --------------------------------------------------------------------------
# Face extraction
# --------------------------------------------------------------------------

def extract_faces(mesh: trimesh.Trimesh, part: int, max_faces: int, min_area_frac: float) -> list[Face]:
    """Find the largest planar regions of a mesh: candidates for cut faces."""
    groups = coplanar_groups(mesh)

    areas = np.array([mesh.area_faces[g].sum() for g in groups])
    order = np.argsort(-areas)
    total = mesh.area
    faces: list[Face] = []
    for gi in order:
        if len(faces) >= max_faces or areas[gi] < min_area_frac * total:
            break
        f = make_face(mesh, part, groups[gi], len(faces))
        if f is not None:
            faces.append(f)
    return faces


def make_face(mesh: trimesh.Trimesh, part: int, tri_idx: np.ndarray, index: int = 0) -> Face | None:
    """Build a Face from a set of (coplanar) triangle indices."""
    g = np.asarray(tri_idx)
    tri = mesh.triangles[g]
    a = mesh.area_faces[g]
    normal = (mesh.face_normals[g] * a[:, None]).sum(0)
    normal /= np.linalg.norm(normal)
    centroid = (mesh.triangles_center[g] * a[:, None]).sum(0) / a.sum()
    basis = plane_basis(normal)
    poly = project_polygon(tri, centroid, basis)
    if poly.is_empty:
        return None
    return Face(part=part, index=index, normal=normal, centroid=centroid,
                area=float(a.sum()), perimeter=float(poly.length),
                vertices3d=tri.reshape(-1, 3), triangles=tri, basis=basis, polygon=poly)


def coplanar_groups(mesh: trimesh.Trimesh) -> list[np.ndarray]:
    """Triangle indices grouped by the plane they lie on.

    Separate flat islands on the same plane form one group: a cut through a
    hole or slot leaves several islands that together make one cut face.
    """
    if "coplanar_groups" in mesh._cache.cache:
        return mesh._cache.cache["coplanar_groups"]
    regions = [np.asarray(f) for f in mesh.facets]
    in_facet = np.zeros(len(mesh.faces), dtype=bool)
    for g in regions:
        in_facet[g] = True
    # Lone triangles count as planar regions too (e.g. a triangular cut face).
    regions += [np.array([i]) for i in np.nonzero(~in_facet)[0]]

    scale = max(float(mesh.scale), 1e-9)
    buckets: dict[tuple, list[np.ndarray]] = {}
    for g in regions:
        a = mesh.area_faces[g]
        n = (mesh.face_normals[g] * a[:, None]).sum(0)
        norm = np.linalg.norm(n)
        if norm == 0:
            continue
        n /= norm
        d = float(np.dot(n, mesh.triangles_center[g[0]]))
        key = tuple(np.round(n, 3)) + (round(d / (1e-4 * scale)),)
        buckets.setdefault(key, []).append(g)
    groups = [np.concatenate(gs) for gs in buckets.values()]
    mesh._cache.cache["coplanar_groups"] = groups
    return groups


def planar_region(mesh: trimesh.Trimesh, triangle: int) -> np.ndarray:
    """Indices of all triangles on the same plane as `triangle`."""
    for g in coplanar_groups(mesh):
        if triangle in g:
            return g
    return np.array([triangle])


# --------------------------------------------------------------------------
# Face matching
# --------------------------------------------------------------------------

def rotation_fits(fa: Face, fb: Face, coarse_step: float = 2.0) -> list[tuple[float, float]]:
    """All distinct in-plane rotations (degrees) placing face b on face a.

    Returns [(theta, iou), ...] sorted best first: one entry per local
    optimum, so a symmetric face (e.g. a rectangle) yields several.
    """
    # R0 turns B so its face normal points opposite A's (faces touching).
    r0 = rotation_between(fb.normal, -fa.normal)
    tri_b = (fb.triangles - fb.centroid) @ r0.T     # B's face, centered, in world orientation
    poly_b = project_polygon(tri_b, np.zeros(3), fa.basis)
    if poly_b.is_empty:
        return []

    def score_at(theta_deg: float) -> float:
        return iou(fa.polygon, affinity.rotate(poly_b, theta_deg, origin=(0, 0)))

    angles = np.arange(0, 360, coarse_step)
    scores = np.array([score_at(t) for t in angles])
    # Local maxima of the circular score curve are the candidate rotations.
    peaks = [i for i in range(len(scores))
             if scores[i] >= scores[i - 1] and scores[i] >= scores[(i + 1) % len(scores)] and scores[i] > 0]
    peaks = sorted(peaks, key=lambda i: -scores[i])[:8]

    fits: list[tuple[float, float]] = []
    for idx in peaks:
        lo, hi = angles[idx] - coarse_step, angles[idx] + coarse_step
        best, best_theta = scores[idx], float(angles[idx])
        for _ in range(3):                         # successive grid refinement
            grid = np.linspace(lo, hi, 9)
            s = [score_at(t) for t in grid]
            k = int(np.argmax(s))
            span = (hi - lo) / 8
            lo, hi = grid[k] - span, grid[k] + span
            if s[k] > best:
                best, best_theta = s[k], float(grid[k])
        theta = best_theta % 360
        if all(abs(((theta - t + 180) % 360) - 180) > 2 * coarse_step for t, *_ in fits):
            fits.append((theta, float(best)))
    fits.sort(key=lambda f: -f[1])
    # Snap each rotation exactly onto the outline vertices.
    a_pts = outline_points(fa.polygon)
    b_pts = outline_points(poly_b)
    return [(theta, score, *refine_2d(a_pts, b_pts, theta)) for theta, score in fits]


def outline_points(poly) -> np.ndarray:
    geoms = getattr(poly, "geoms", [poly])
    pts = [np.asarray(r.coords) for g in geoms for r in [g.exterior, *g.interiors]]
    return np.vstack(pts) if pts else np.zeros((0, 2))


def refine_2d(a_pts: np.ndarray, b_pts: np.ndarray, theta: float, iters: int = 30) -> tuple[float, float]:
    """Snap outline b onto outline a with 2D ICP, starting from rotation `theta`.

    Returns (rotation correction in degrees, in-plane offset of b's centroid)."""
    from scipy.spatial import cKDTree
    if len(a_pts) < 3 or len(b_pts) < 3:
        return (0.0, np.zeros(2))
    tree = cKDTree(a_pts)
    t = math.radians(theta)
    R = np.array([[math.cos(t), -math.sin(t)], [math.sin(t), math.cos(t)]])
    off = np.zeros(2)
    tol = 0.05 * math.sqrt(max(np.ptp(a_pts, axis=0).prod(), 1e-12))
    for _ in range(iters):
        moved = b_pts @ R.T + off
        dist, idx = tree.query(moved)
        keep = dist < tol
        if keep.sum() < 3:
            break
        src, dst = b_pts[keep], a_pts[idx[keep]]
        sc, dc = src.mean(0), dst.mean(0)
        H = (src - sc).T @ (dst - dc)
        U, _, Vt = np.linalg.svd(H)
        Rn = Vt.T @ U.T
        if np.linalg.det(Rn) < 0:
            Vt[-1] *= -1
            Rn = Vt.T @ U.T
        off_n = dc - Rn @ sc
        done = np.allclose(Rn, R, atol=1e-12) and np.allclose(off_n, off, atol=1e-12)
        R, off = Rn, off_n
        if done:
            break
    dtheta = math.degrees(math.atan2(R[1, 0], R[0, 0])) - theta
    return (dtheta, off)


def placement(fa: Face, fb: Face, theta: float, dtheta: float = 0.0, offset=(0.0, 0.0)) -> np.ndarray:
    """4x4 transform putting face b against face a, rotated theta degrees in-plane
    (plus an optional exact correction dtheta and in-plane offset from refine_2d)."""
    r0 = rotation_between(fb.normal, -fa.normal)
    r_theta = trimesh.transformations.rotation_matrix(math.radians(theta + dtheta), fa.normal)[:3, :3]
    rot = r_theta @ r0
    T = np.eye(4)
    T[:3, :3] = rot
    T[:3, 3] = fa.centroid + np.asarray(offset) @ fa.basis - rot @ fb.centroid
    return T


def match_faces(fa: Face, fb: Face, mesh_b: trimesh.Trimesh, tol: float, coarse_step: float = 2.0) -> Match | None:
    """Try to place face b of part B onto face a of part A.

    Returns the best rigid transform (as a Match) or None if the outlines
    don't agree.
    """
    # Cheap rejections: area and perimeter must agree.
    if abs(fa.area - fb.area) > tol * max(fa.area, fb.area):
        return None
    if abs(fa.perimeter - fb.perimeter) > 2 * tol * max(fa.perimeter, fb.perimeter):
        return None

    fits = rotation_fits(fa, fb, coarse_step)
    if not fits or fits[0][1] < 1 - tol:
        return None
    best_theta, best, dtheta, offset = fits[0]
    # Another rotation that fits almost as well => symmetric face.
    ambiguous = len(fits) > 1 and fits[1][1] > best - 0.02
    T = placement(fa, fb, best_theta, dtheta, offset)

    # B's body must end up on the far side of the face, not inside A.
    side = np.dot(trimesh.transform_points([mesh_b.center_mass if mesh_b.is_volume else mesh_b.centroid], T)[0] - fa.centroid, fa.normal)
    if side <= 0:
        return None

    in_place = bool(np.allclose(T, np.eye(4), atol=max(1e-3, 1e-4 * math.sqrt(fa.area))))
    return Match(a=fa, b=fb, iou=best, transform=T, ambiguous=ambiguous, in_place=in_place)


def already_in_place(fa: Face, fb: Face, tol: float) -> Match | None:
    """Parts that already touch at coincident, opposed faces need no motion."""
    if np.dot(fa.normal, fb.normal) > -0.999:
        return None
    gap = abs(np.dot(fb.centroid - fa.centroid, fa.normal))
    scale = math.sqrt(max(fa.area, fb.area))
    if gap > 1e-3 * scale + 1e-4:
        return None
    poly_b = project_polygon(fb.triangles, fa.centroid, fa.basis)
    s = iou(fa.polygon, poly_b)
    if s < 1 - tol:
        return None
    return Match(a=fa, b=fb, iou=s, transform=np.eye(4), ambiguous=False, in_place=True)


# --------------------------------------------------------------------------
# Assembly
# --------------------------------------------------------------------------

def assemble(meshes: list[trimesh.Trimesh], names: list[str], *, max_faces: int, min_area_frac: float,
             tol: float, verbose: bool) -> tuple[list[np.ndarray], list[Match]]:
    """Return one world transform per part plus the face matches used."""
    n = len(meshes)
    faces = [extract_faces(m, i, max_faces, min_area_frac) for i, m in enumerate(meshes)]
    if verbose:
        for i, fs in enumerate(faces):
            print(f"  {names[i]}: {len(fs)} candidate faces "
                  f"(largest {fs[0].area:.1f} mm²)" if fs else f"  {names[i]}: no planar faces", file=sys.stderr)

    # Score every candidate pairing between every pair of parts.
    candidates: list[Match] = []
    for i in range(n):
        for j in range(i + 1, n):
            for fa in faces[i]:
                for fb in faces[j]:
                    m = already_in_place(fa, fb, tol) or match_faces(fa, fb, meshes[j], tol)
                    if m:
                        candidates.append(m)

    # Greedy maximum spanning tree: best matches first, each face used once.
    # Matches where the parts already sit in place are preferred.
    candidates.sort(key=lambda m: (m.in_place, m.score), reverse=True)
    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    used: set[tuple[int, int]] = set()
    chosen: list[Match] = []
    for m in candidates:
        ka, kb = (m.a.part, m.a.index), (m.b.part, m.b.index)
        if ka in used or kb in used:
            continue
        ra, rb = find(m.a.part), find(m.b.part)
        if ra == rb:
            continue
        parent[rb] = ra
        used |= {ka, kb}
        chosen.append(m)

    # Walk the tree from part 0 (or the largest part) composing transforms.
    root = int(np.argmax([m.volume if m.is_volume else m.area for m in meshes]))
    world: list[np.ndarray | None] = [None] * n
    world[root] = np.eye(4)
    adj: dict[int, list[tuple[int, np.ndarray]]] = {i: [] for i in range(n)}
    for m in chosen:
        i, j = m.a.part, m.b.part
        adj[i].append((j, m.transform))                 # j into i's frame
        adj[j].append((i, np.linalg.inv(m.transform)))  # i into j's frame
    stack = [root]
    while stack:
        i = stack.pop()
        for j, T in adj[i]:
            if world[j] is None:
                world[j] = world[i] @ T
                stack.append(j)

    missing = [names[i] for i in range(n) if world[i] is None]
    if missing:
        print(f"warning: no mating face found for: {', '.join(missing)} — left where they are",
              file=sys.stderr)
        world = [w if w is not None else np.eye(4) for w in world]
    return world, chosen


def snap_seams(meshes: list[trimesh.Trimesh], eps: float = 1e-3) -> list[trimesh.Trimesh]:
    """Weld vertices that sit within eps (mm) of a vertex on another part.

    Aligned parts meet at faces that are coincident only to float precision;
    left as-is, the boolean union turns the tiny offsets into sliver triangles.
    """
    from scipy.spatial import cKDTree
    out = [m.copy() for m in meshes]
    for i in range(1, len(out)):
        ref = np.vstack([m.vertices for m in out[:i]])
        dist, idx = cKDTree(ref).query(out[i].vertices, distance_upper_bound=eps)
        hit = np.isfinite(dist)
        if hit.any():
            v = out[i].vertices.copy()
            v[hit] = ref[idx[hit]]
            out[i].vertices = v
    return out


def combine(meshes: list[trimesh.Trimesh], union: bool) -> trimesh.Trimesh:
    if union and len(meshes) > 1:
        meshes = snap_seams(meshes)
        try:
            return trimesh.boolean.union(meshes, engine="manifold")
        except Exception as exc:  # non-watertight input, etc.
            print(f"warning: boolean union failed ({exc}); writing parts concatenated instead",
                  file=sys.stderr)
    return trimesh.util.concatenate(meshes)


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("inputs", nargs="+", type=Path, help="STL files to join (2 or more)")
    ap.add_argument("-o", "--output", type=Path, default=Path("joined.stl"), help="output STL (default: joined.stl)")
    ap.add_argument("--no-union", action="store_true",
                    help="just place the parts and concatenate them (no boolean union)")
    ap.add_argument("--tolerance", type=float, default=0.05,
                    help="allowed mismatch between mating faces, as a fraction (default 0.05)")
    ap.add_argument("--max-faces", type=int, default=12,
                    help="planar faces per part considered as cut faces (default 12)")
    ap.add_argument("--min-area", type=float, default=0.005,
                    help="ignore planar faces smaller than this fraction of the part's surface (default 0.005)")
    ap.add_argument("--export-parts", type=Path, metavar="DIR",
                    help="also write each repositioned part to DIR")
    ap.add_argument("-q", "--quiet", action="store_true")
    args = ap.parse_args(argv)

    if len(args.inputs) < 2:
        ap.error("need at least two STL files")
    verbose = not args.quiet

    meshes, names = [], []
    for p in args.inputs:
        m = trimesh.load_mesh(p, force="mesh")
        m.merge_vertices()
        if verbose and not m.is_watertight:
            print(f"warning: {p.name} is not watertight; union may fail", file=sys.stderr)
        meshes.append(m)
        names.append(p.name)

    if verbose:
        print(f"Finding mating faces among {len(meshes)} parts...", file=sys.stderr)
    world, chosen = assemble(meshes, names, max_faces=args.max_faces, min_area_frac=args.min_area,
                             tol=args.tolerance, verbose=verbose)

    if verbose:
        for m in chosen:
            note = " (already in place)" if m.in_place else ""
            if m.ambiguous:
                note += "  ⚠ face is symmetric; rotation may be wrong"
            print(f"  joined {names[m.b.part]} → {names[m.a.part]}: face area {m.a.area:.1f} mm², "
                  f"fit {m.iou * 100:.1f}%{note}", file=sys.stderr)

    placed = [m.copy().apply_transform(T) for m, T in zip(meshes, world)]
    if args.export_parts:
        args.export_parts.mkdir(parents=True, exist_ok=True)
        for m, name in zip(placed, names):
            m.export(args.export_parts / name)

    out = combine(placed, union=not args.no_union)
    out.export(args.output)
    if verbose:
        ext = out.extents
        print(f"Wrote {args.output} — {len(out.faces)} triangles, "
              f"{ext[0]:.1f} × {ext[1]:.1f} × {ext[2]:.1f} mm, "
              f"watertight={out.is_watertight}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
