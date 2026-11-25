"""Web interface for stljoiner: load STL parts, pick the faces to join, export.

Run:  stljoiner web   then open http://127.0.0.1:4300
"""
from __future__ import annotations

import argparse
import io
import itertools
import threading
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import trimesh
from flask import Flask, jsonify, request, send_file, send_from_directory

from stljoiner import join as stljoin
from stljoiner.version import __version__

STATIC = Path(__file__).parent / "static"
PALETTE = ["#4e79a7", "#f28e2b", "#59a14f", "#e15759", "#b07aa1",
           "#76b7b2", "#edc948", "#ff9da7", "#9c755f", "#bab0ac"]

app = Flask(__name__, static_folder=None)
app.config["MAX_CONTENT_LENGTH"] = 512 * 1024 * 1024
lock = threading.Lock()


@dataclass
class Part:
    id: int
    name: str
    mesh: trimesh.Trimesh                  # as loaded
    color: str
    group: int                             # parts joined together share a group
    world: np.ndarray = field(default_factory=lambda: np.eye(4))
    version: int = 0
    _placed: trimesh.Trimesh | None = None

    def placed(self) -> trimesh.Trimesh:
        if self._placed is None:
            self._placed = self.mesh.copy().apply_transform(self.world)
        return self._placed

    def move(self, world: np.ndarray) -> None:
        self.world = world
        self.version += 1
        self._placed = None

    def info(self) -> dict:
        m = self.mesh
        return {"id": self.id, "name": self.name, "color": self.color, "group": self.group,
                "version": self.version, "triangles": len(m.faces),
                "watertight": bool(m.is_watertight)}


class Session:
    def __init__(self) -> None:
        self.parts: dict[int, Part] = {}
        self.ids = itertools.count(1)
        self.history: list[dict[int, tuple[np.ndarray, int]]] = []
        self.pending: dict | None = None   # last manual join, for cycling rotations

    def snapshot(self) -> None:
        self.history.append({p.id: (p.world.copy(), p.group) for p in self.parts.values()})
        del self.history[:-50]

    def restore(self, snap: dict[int, tuple[np.ndarray, int]]) -> None:
        for pid, (world, group) in snap.items():
            if pid in self.parts:
                self.parts[pid].move(world)
                self.parts[pid].group = group

    def group_members(self, group: int) -> list[Part]:
        return [p for p in self.parts.values() if p.group == group]

    def merge_groups(self, keep: int, absorb: int) -> None:
        for p in self.group_members(absorb):
            p.group = keep

    def state(self) -> dict:
        return {"parts": [p.info() for p in self.parts.values()],
                "canUndo": bool(self.history),
                "pending": None if not self.pending else {
                    "fits": [round(f[1] * 100, 1) for f in self.pending["fits"]],
                    "index": self.pending["index"]}}


S = Session()
# Host names the server answers to; None means any (set when --host opens it to the network).
ALLOWED_HOSTS: set[str] | None = {"localhost", "127.0.0.1"}


@app.before_request
def check_host():
    """Refuse requests for other host names (guards against DNS rebinding)."""
    if ALLOWED_HOSTS is not None and request.host.rsplit(":", 1)[0] not in ALLOWED_HOSTS:
        return error("unknown host", 403)
    return None


def error(msg: str, code: int = 400):
    return jsonify({"error": msg}), code


# --------------------------------------------------------------------------
# Routes
# --------------------------------------------------------------------------

@app.get("/")
def index():
    return send_from_directory(STATIC, "index.html")


@app.get("/static/<path:name>")
def static_files(name):
    return send_from_directory(STATIC, name)


@app.get("/api/state")
def state():
    with lock:
        return jsonify(S.state())


@app.post("/api/parts")
def upload():
    files = request.files.getlist("files")
    if not files:
        return error("no files uploaded")
    errors = []
    with lock:
        for f in files:
            filename = Path(f.filename or "part.stl").name
            try:
                parts = stljoin.load_parts(io.BytesIO(f.read()), filename)
            except Exception as exc:  # noqa: BLE001 - report any unreadable file back to the page
                errors.append(f"{filename}: {exc}")
                continue
            for name, m in parts:
                pid = next(S.ids)
                S.parts[pid] = Part(id=pid, name=name, mesh=m, color=PALETTE[(pid - 1) % len(PALETTE)], group=pid)
        S.pending = None
        out = S.state()
    out["errors"] = errors
    return jsonify(out)


@app.delete("/api/parts/<int:pid>")
def delete(pid):
    with lock:
        if S.parts.pop(pid, None) is None:
            return error("no such part", 404)
        S.pending = None
        return jsonify(S.state())


@app.get("/api/parts/<int:pid>/mesh")
def mesh(pid):
    with lock:
        p = S.parts.get(pid)
        if p is None:
            return error("no such part", 404)
        data = p.placed().export(file_type="stl")
    return send_file(io.BytesIO(data), mimetype="model/stl", download_name=f"{pid}.stl")


@app.post("/api/face")
def face():
    """Flat region of a part containing the clicked triangle."""
    body = request.get_json()
    with lock:
        p = S.parts.get(body.get("part"))
        if p is None:
            return error("no such part", 404)
        m = p.placed()
        tri = int(body.get("triangle", -1))
        if not 0 <= tri < len(m.faces):
            return error("bad triangle index")
        region = stljoin.planar_region(m, tri)
        return jsonify({"triangles": region.tolist(), "area": round(float(m.area_faces[region].sum()), 2)})


@app.post("/api/suggest")
def suggest():
    """Faces on the other checked parts that best fit the clicked face, best first."""
    body = request.get_json()
    with lock:
        a = S.parts.get(body.get("part"))
        if a is None:
            return error("no such part", 404)
        ma = a.placed()
        tri = int(body.get("triangle", -1))
        if not 0 <= tri < len(ma.faces):
            return error("bad triangle index")
        fa = stljoin.make_face(ma, a.id, stljoin.planar_region(ma, tri))
        if fa is None:
            return error("couldn't read the selected face")
        ids = body.get("ids") or list(S.parts)
        found = []
        for pid in ids:
            b = S.parts.get(pid)
            if b is None or b.group == a.group:
                continue
            for fb in stljoin.extract_faces(b.placed(), b.id, max_faces=16, min_area_frac=0.002):
                if abs(fa.area - fb.area) > 0.15 * max(fa.area, fb.area):
                    continue
                fits = stljoin.rotation_fits(fa, fb)
                if fits and fits[0][1] >= 0.5:
                    found.append({"part": b.id, "triangle": int(fb.tri_index[0]),
                                  "triangles": fb.tri_index.tolist(), "area": round(fb.area, 2),
                                  "fit": round(fits[0][1] * 100, 1)})
        found.sort(key=lambda f: -f["fit"])
        return jsonify({"suggestions": found[:5]})


@app.post("/api/nudge")
def nudge():
    """Move a part and everything joined to it: {part, move: [dx, dy, dz]} or {part, axis, degrees}."""
    body = request.get_json()
    with lock:
        p = S.parts.get(body.get("part"))
        if p is None:
            return error("no such part", 404)
        members = S.group_members(p.group)
        if "move" in body:
            T = np.eye(4)
            T[:3, 3] = [float(v) for v in body["move"]]
        else:
            axis = {"x": [1, 0, 0], "y": [0, 1, 0], "z": [0, 0, 1]}.get(body.get("axis"))
            if axis is None:
                return error("axis must be x, y or z")
            bounds = np.vstack([m.placed().bounds for m in members])
            center = (bounds.min(0) + bounds.max(0)) / 2
            T = trimesh.transformations.rotation_matrix(np.radians(float(body.get("degrees", 90))), axis, center)
        S.snapshot()
        S.pending = None
        for m in members:
            m.move(T @ m.world)
        return jsonify(S.state())


def _apply_pending(index: int) -> None:
    pend = S.pending
    T = pend["transforms"][index]
    for pid, w0 in pend["start"].items():
        S.parts[pid].move(T @ w0)
    pend["index"] = index


@app.post("/api/join")
def join():
    """Move part b (and everything joined to it) so face b sits on face a."""
    body = request.get_json()
    with lock:
        a, b = S.parts.get(body.get("a")), S.parts.get(body.get("b"))
        if a is None or b is None:
            return error("no such part", 404)
        if a.group == b.group:
            return error("those parts are already joined together")
        ma, mb = a.placed(), b.placed()
        fa = stljoin.make_face(ma, a.id, stljoin.planar_region(ma, int(body["faceA"])))
        fb = stljoin.make_face(mb, b.id, stljoin.planar_region(mb, int(body["faceB"])))
        if fa is None or fb is None:
            return error("couldn't read the selected faces")
        fits = stljoin.rotation_fits(fa, fb)
        if not fits:
            return error("faces don't overlap in any rotation")
        # Offer only the rotations that fit about as well as the best one.
        fits = [f for f in fits if f[1] >= fits[0][1] - 0.03]
        S.snapshot()
        moving = S.group_members(b.group)
        S.pending = {"fits": fits,
                     "transforms": [stljoin.placement(fa, fb, th, dth, off) for th, _, dth, off in fits],
                     "start": {p.id: p.world.copy() for p in moving}}
        _apply_pending(0)
        S.merge_groups(a.group, b.group)
        return jsonify(S.state())


@app.post("/api/join/rotation")
def join_rotation():
    """Switch the last manual join to another rotation that also fits."""
    index = int(request.get_json().get("index", 0))
    with lock:
        if not S.pending or not 0 <= index < len(S.pending["transforms"]):
            return error("nothing to rotate")
        _apply_pending(index)
        return jsonify(S.state())


@app.post("/api/auto")
def auto():
    """Automatically join the selected parts (already-joined groups move as one)."""
    ids = request.get_json().get("ids") or list(S.parts)
    tol = float(request.get_json().get("tolerance", 0.05))
    with lock:
        groups = sorted({S.parts[i].group for i in ids if i in S.parts})
        if len(groups) < 2:
            return error("select parts from at least two separate groups")
        members = {g: S.group_members(g) for g in groups}
        meshes = [trimesh.util.concatenate([p.placed() for p in members[g]]) for g in groups]
        names = [", ".join(p.name for p in members[g]) for g in groups]
        world, chosen = stljoin.assemble(meshes, names, max_faces=12, min_area_frac=0.005,
                                         tol=tol, verbose=False)
        if not chosen:
            return error("no matching faces found between the selected parts")
        S.snapshot()
        S.pending = None
        # Only groups connected by a match move/merge.
        linked: dict[int, set[int]] = {i: {i} for i in range(len(groups))}
        for m in chosen:
            s = linked[m.a.part] | linked[m.b.part]
            for k in s:
                linked[k] = s
        for i, g in enumerate(groups):
            if len(linked[i]) == 1:
                continue
            for p in members[g]:
                p.move(world[i] @ p.world)
            S.merge_groups(groups[min(linked[i])], g)
        out = S.state()
        out["joins"] = [{"a": names[m.a.part], "b": names[m.b.part], "fit": round(m.iou * 100, 1),
                         "ambiguous": m.ambiguous, "inPlace": m.in_place} for m in chosen]
        return jsonify(out)


@app.post("/api/unjoin/<int:pid>")
def unjoin(pid):
    """Detach a part from its group (it stays where it is)."""
    with lock:
        p = S.parts.get(pid)
        if p is None:
            return error("no such part", 404)
        S.snapshot()
        S.pending = None
        p.group = max(S.parts) + 1000 + pid
        return jsonify(S.state())


@app.post("/api/undo")
def undo():
    with lock:
        if not S.history:
            return error("nothing to undo")
        S.restore(S.history.pop())
        S.pending = None
        return jsonify(S.state())


@app.post("/api/reset")
def reset():
    with lock:
        S.snapshot()
        S.pending = None
        for p in S.parts.values():
            p.move(np.eye(4))
            p.group = p.id
        return jsonify(S.state())


@app.post("/api/export")
def export():
    body = request.get_json()
    ids = body.get("ids") or list(S.parts)
    fmt = str(body.get("format", "stl")).lower()
    if fmt not in stljoin.OUTPUT_FORMATS:
        return error(f"unsupported format '{fmt}'")
    with lock:
        parts = [S.parts[i] for i in ids if i in S.parts]
        if not parts:
            return error("no parts selected")
        data = stljoin.export_result([p.placed() for p in parts], [p.name for p in parts], fmt,
                                     union=bool(body.get("union", True)))
    return send_file(io.BytesIO(data), mimetype="application/octet-stream", as_attachment=True,
                     download_name=f"joined.{fmt}")


def main(argv: list[str] | None = None) -> int:
    global ALLOWED_HOSTS
    ap = argparse.ArgumentParser(prog="stljoiner web", description="Start the stljoiner web interface.")
    ap.add_argument("--host", default="127.0.0.1",
                    help="address to listen on (default 127.0.0.1: this computer only)")
    ap.add_argument("--port", type=int, default=4300, help="port to listen on (default 4300)")
    ap.add_argument("--version", action="version", version=f"stljoiner {__version__}")
    args = ap.parse_args(argv)
    if args.host not in ("127.0.0.1", "localhost"):
        ALLOWED_HOSTS = None
        print("warning: the web interface has no login; anyone who can reach this address can use it")
    print(f"stljoiner web interface: http://{args.host}:{args.port}  (Ctrl+C to stop)")
    app.run(host=args.host, port=args.port, threaded=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
