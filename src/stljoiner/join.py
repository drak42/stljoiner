"""stljoiner - reassemble split STL parts by matching their mating faces.

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

from stljoiner.version import __version__

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
    tri_index: np.ndarray = field(default=None)  # the mesh triangles this face is made of


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
                vertices3d=tri.reshape(-1, 3), triangles=tri, basis=basis, polygon=poly, tri_index=g)


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
        key = (*np.round(n, 3).tolist(), round(d / (1e-4 * scale)))
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


def match_faces(fa: Face, fb: Face, mesh_b: trimesh.Trimesh, tol: float, coarse_step: float = 2.0) -> list[Match]:
    """All ways to place face b of part B onto face a of part A.

    Returns one Match per rotation that fits (several for a symmetric face),
    best first; empty if the outlines don't agree.
    """
    # Cheap rejections: area and perimeter must agree.
    if abs(fa.area - fb.area) > tol * max(fa.area, fb.area):
        return []
    if abs(fa.perimeter - fb.perimeter) > 2 * tol * max(fa.perimeter, fb.perimeter):
        return []

    fits = [f for f in rotation_fits(fa, fb, coarse_step) if f[1] >= 1 - tol]
    center_b = mesh_b.center_mass if mesh_b.is_volume else mesh_b.centroid
    matches = []
    for theta, score, dtheta, offset in fits:
        T = placement(fa, fb, theta, dtheta, offset)
        # B's body must end up on the far side of the face, not inside A.
        if np.dot(trimesh.transform_points([center_b], T)[0] - fa.centroid, fa.normal) <= 0:
            continue
        in_place = bool(np.allclose(T, np.eye(4), atol=max(1e-3, 1e-4 * math.sqrt(fa.area))))
        matches.append(Match(a=fa, b=fb, iou=score, transform=T, ambiguous=len(fits) > 1, in_place=in_place))
    return matches


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


def overlap_volume(a: trimesh.Trimesh, b: trimesh.Trimesh) -> float:
    """Volume shared by two meshes (0 when they only touch)."""
    lo, hi = np.maximum(a.bounds[0], b.bounds[0]), np.minimum(a.bounds[1], b.bounds[1])
    if np.any(hi - lo <= 1e-9):
        return 0.0
    try:
        inter = trimesh.boolean.intersection([a, b], engine="manifold")
    except Exception:  # noqa: BLE001 - meshes manifold can't handle are treated as not overlapping
        return 0.0
    return float(abs(inter.volume)) if len(inter.faces) else 0.0


def same_transform(t1: np.ndarray, t2: np.ndarray, scale: float) -> bool:
    return bool(np.allclose(t1[:3, :3], t2[:3, :3], atol=0.02) and
                np.linalg.norm(t1[:3, 3] - t2[:3, 3]) < 0.01 * scale + 1e-3)


@dataclass
class Joint:
    """One way to put part b against part a, backed by one or more face matches."""
    matches: list[Match]
    transform: np.ndarray
    score: float = 0.0

    @property
    def a(self) -> int:
        return self.matches[0].a.part

    @property
    def b(self) -> int:
        return self.matches[0].b.part

    @property
    def in_place(self) -> bool:
        return all(m.in_place for m in self.matches)


# --------------------------------------------------------------------------
# Assembly
# --------------------------------------------------------------------------

def find_joints(meshes: list[trimesh.Trimesh], faces: list[list[Face]], tol: float) -> list[Joint]:
    """Every plausible way to join every pair of parts, scored.

    Face matches that agree on the same placement are merged into one joint,
    so a stepped or dovetailed cut (several flat faces) scores as one strong
    joint. A face that fits many partners (a plain rectangle, say) is trusted
    less than one that fits a single partner.
    """
    n = len(meshes)
    matches: list[Match] = []
    for i in range(n):
        for j in range(i + 1, n):
            for fa in faces[i]:
                for fb in faces[j]:
                    m = already_in_place(fa, fb, tol)
                    matches.extend([m] if m else match_faces(fa, fb, meshes[j], tol))

    # How many partners each face could mate with.
    partners: dict[tuple[int, int], set[tuple[int, int]]] = {}
    for m in matches:
        ka, kb = (m.a.part, m.a.index), (m.b.part, m.b.index)
        partners.setdefault(ka, set()).add(kb)
        partners.setdefault(kb, set()).add(ka)

    joints: list[Joint] = []
    scale = max(float(m.scale) for m in meshes)
    for m in matches:
        for jt in joints:
            if jt.a == m.a.part and jt.b == m.b.part and same_transform(jt.transform, m.transform, scale):
                if all(x.a.index != m.a.index and x.b.index != m.b.index for x in jt.matches):
                    jt.matches.append(m)
                break
        else:
            joints.append(Joint(matches=[m], transform=m.transform))
    for jt in joints:
        jt.score = sum(m.score / math.sqrt(len(partners[(m.a.part, m.a.index)]) * len(partners[(m.b.part, m.b.index)]))
                       for m in jt.matches)
        # Several faces agreeing on one placement is strong evidence: that rarely
        # happens by chance, while a single plain face often fits elsewhere too.
        jt.score *= len(jt.matches) ** 2
        # Several rotations of the same faces: each is less certain.
        rivals = sum(1 for o in joints if o is not jt and {(x.a.index, x.b.index) for x in o.matches}
                     & {(x.a.index, x.b.index) for x in jt.matches} and o.a == jt.a and o.b == jt.b)
        jt.score /= 1 + rivals
    return joints


def assemble(meshes: list[trimesh.Trimesh], names: list[str], *, max_faces: int, min_area_frac: float,
             tol: float, verbose: bool) -> tuple[list[np.ndarray], list[Match]]:
    """Return one world transform per part plus the face matches used.

    Joints are taken best first (parts already in place before anything
    else). A joint is skipped if it reuses a face, links parts already
    connected, or would push one part into another.
    """
    n = len(meshes)
    faces = [extract_faces(m, i, max_faces, min_area_frac) for i, m in enumerate(meshes)]
    if verbose:
        for i, fs in enumerate(faces):
            print(f"  {names[i]}: {len(fs)} candidate faces "
                  f"(largest {fs[0].area:.1f} mm²)" if fs else f"  {names[i]}: no planar faces", file=sys.stderr)

    joints = find_joints(meshes, faces, tol)
    joints.sort(key=lambda j: (j.in_place, j.score), reverse=True)

    group = list(range(n))                      # group id per part
    pose = [np.eye(4) for _ in range(n)]        # part -> its group's frame
    used: set[tuple[int, int]] = set()
    chosen: list[Match] = []
    volumes = [abs(m.volume) if m.is_volume else 0.0 for m in meshes]
    for jt in joints:
        ga, gb = group[jt.a], group[jt.b]
        keys = {(m.a.part, m.a.index) for m in jt.matches} | {(m.b.part, m.b.index) for m in jt.matches}
        if ga == gb or keys & used:
            continue
        # Pose of every part of b's group in a's group frame.
        to_a = pose[jt.a] @ jt.transform @ np.linalg.inv(pose[jt.b])
        members_a = [k for k in range(n) if group[k] == ga]
        members_b = [k for k in range(n) if group[k] == gb]
        moved = {k: to_a @ pose[k] for k in members_b}
        clash = False
        for kb in members_b:
            mb = meshes[kb].copy().apply_transform(moved[kb])
            for ka in members_a:
                ma = meshes[ka].copy().apply_transform(pose[ka])
                limit = 0.005 * min(volumes[ka], volumes[kb]) if volumes[ka] and volumes[kb] else 0.0
                if limit and overlap_volume(ma, mb) > limit:
                    clash = True
                    break
            if clash:
                break
        if clash:
            continue
        for k in members_b:
            pose[k] = moved[k]
            group[k] = ga
        used |= keys
        best = max(jt.matches, key=lambda m: m.score)
        # Another joint for either of these faces that scores about as well: the
        # choice is a guess (a symmetric face, or another face of the same shape).
        mine = {(m.a.part, m.a.index) for m in jt.matches} | {(m.b.part, m.b.index) for m in jt.matches}
        rivals = [o for o in joints if o is not jt and abs(o.score - jt.score) < 0.05 * jt.score and
                  mine & ({(m.a.part, m.a.index) for m in o.matches} | {(m.b.part, m.b.index) for m in o.matches})]
        chosen.append(Match(a=best.a, b=best.b, iou=min(m.iou for m in jt.matches), transform=jt.transform,
                            ambiguous=bool(rivals), in_place=jt.in_place))

    # Express everything relative to the largest part, which stays put.
    root = int(np.argmax([m.volume if m.is_volume else m.area for m in meshes]))
    base = np.linalg.inv(pose[root])
    world = [base @ pose[k] if group[k] == group[root] else pose[k] for k in range(n)]
    missing = [names[k] for k in range(n) if group[k] != group[root]]
    if missing:
        print(f"warning: no mating face found for: {', '.join(missing)} — left where they are",
              file=sys.stderr)
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
        except Exception as exc:  # noqa: BLE001 - any union failure falls back to concatenation
            print(f"warning: boolean union failed ({exc}); writing parts concatenated instead",
                  file=sys.stderr)
    return trimesh.util.concatenate(meshes)


# --------------------------------------------------------------------------
# Files
# --------------------------------------------------------------------------

INPUT_FORMATS = ("stl", "3mf", "obj", "ply", "off", "glb", "gltf")
OUTPUT_FORMATS = ("stl", "3mf", "obj", "ply", "off", "glb")


def load_parts(source, name: str) -> list[tuple[str, trimesh.Trimesh]]:
    """Read a mesh file (path or file-like) into named parts.

    A file holding several objects (3MF, GLB) gives one part per object, named
    "file.3mf: object"; anything else gives a single part.
    """
    ext = Path(name).suffix.lower().lstrip(".")
    if ext not in INPUT_FORMATS:
        raise ValueError(f"unsupported file type '.{ext}' (use {', '.join('.' + e for e in INPUT_FORMATS)})")
    loaded = trimesh.load(source, file_type=ext)
    if isinstance(loaded, trimesh.Scene):
        meshes = []
        for node in sorted(loaded.graph.nodes_geometry):
            transform, geom_name = loaded.graph[node]
            geom = loaded.geometry[geom_name]
            if isinstance(geom, trimesh.Trimesh) and len(geom.faces):
                meshes.append((f"{name}: {node}", geom.copy().apply_transform(transform)))
        if len(meshes) == 1:
            meshes = [(name, meshes[0][1])]
    else:
        meshes = [(name, loaded)]
    if not meshes:
        raise ValueError(f"{name} holds no triangle meshes")
    for _, m in meshes:
        m.merge_vertices()
    return meshes


def export_result(parts: list[trimesh.Trimesh], names: list[str], fmt: str, union: bool) -> bytes:
    """Placed parts -> file bytes.

    With union, one merged solid. Without, 3MF and GLB keep each part as its
    own object (handy for multi-colour printing); other formats hold all the
    parts in one mesh.
    """
    fmt = fmt.lower().lstrip(".")
    if fmt not in OUTPUT_FORMATS:
        raise ValueError(f"unsupported output type '.{fmt}' (use {', '.join('.' + e for e in OUTPUT_FORMATS)})")
    if not union and fmt in ("3mf", "glb"):
        scene = trimesh.Scene()
        for mesh, name in zip(parts, names, strict=True):
            scene.add_geometry(mesh, geom_name=Path(name).stem or name, node_name=Path(name).stem or name)
        data = scene.export(file_type=fmt)
    else:
        data = combine(parts, union=union).export(file_type=fmt)
    return data.encode() if isinstance(data, str) else data


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="stljoiner", description=__doc__,
                                 epilog="Run 'stljoiner web' for the browser interface.",
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("inputs", nargs="+", type=Path,
                    help="mesh files to join: .stl, .3mf, .obj, .ply, .off, .glb (a 3MF or GLB with several "
                         "objects counts as several parts)")
    ap.add_argument("--version", action="version", version=f"stljoiner {__version__}")
    ap.add_argument("-o", "--output", type=Path, default=Path("joined.stl"),
                    help="output file; its extension picks the format: .stl, .3mf, .obj, .ply, .off, .glb "
                         "(default: joined.stl)")
    ap.add_argument("--no-union", action="store_true",
                    help="place the parts without merging them (3MF/GLB keep each part as its own object)")
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

    verbose = not args.quiet

    meshes, names = [], []
    for p in args.inputs:
        try:
            parts = load_parts(p, p.name)
        except (ValueError, OSError) as exc:
            ap.error(str(exc))
        for name, m in parts:
            if verbose and not m.is_watertight:
                print(f"warning: {name} is not watertight; union may fail", file=sys.stderr)
            meshes.append(m)
            names.append(name)
    if len(meshes) < 2:
        ap.error("need at least two parts to join")
    out_fmt = args.output.suffix.lower().lstrip(".") or "stl"
    if out_fmt not in OUTPUT_FORMATS:
        ap.error(f"can't write '.{out_fmt}' files (use {', '.join('.' + e for e in OUTPUT_FORMATS)})")

    if verbose:
        print(f"Finding mating faces among {len(meshes)} parts...", file=sys.stderr)
    world, chosen = assemble(meshes, names, max_faces=args.max_faces, min_area_frac=args.min_area,
                             tol=args.tolerance, verbose=verbose)

    if verbose:
        for m in chosen:
            note = " (already in place)" if m.in_place else ""
            if m.ambiguous:
                note += "  ⚠ other faces or rotations fit just as well: check this joint"
            print(f"  joined {names[m.b.part]} → {names[m.a.part]}: face area {m.a.area:.1f} mm², "
                  f"fit {m.iou * 100:.1f}%{note}", file=sys.stderr)

    placed = [m.copy().apply_transform(T) for m, T in zip(meshes, world, strict=True)]
    if args.export_parts:
        args.export_parts.mkdir(parents=True, exist_ok=True)
        for m, name in zip(placed, names, strict=True):
            safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in Path(name.replace(": ", "_")).stem)
            m.export(args.export_parts / f"{safe}.stl")

    args.output.write_bytes(export_result(placed, names, out_fmt, union=not args.no_union))
    if verbose:
        out = trimesh.util.concatenate(placed) if args.no_union else load_parts(args.output, args.output.name)[0][1]
        ext = out.extents
        print(f"Wrote {args.output} — {ext[0]:.1f} × {ext[1]:.1f} × {ext[2]:.1f} mm"
              + ("" if args.no_union else f", watertight={out.is_watertight}"), file=sys.stderr)
    return 0

if __name__ == "__main__":
    sys.exit(main())
