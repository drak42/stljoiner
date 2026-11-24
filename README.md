# stljoiner

Reassemble STL parts that were split apart (for example, to fit a print bed) by matching their mating faces, then write one combined mesh.

```
uv venv && uv pip install -r requirements.txt
.venv/bin/python stljoin.py part1.stl part2.stl part3.stl -o joined.stl
```

## How it works

1. Finds the largest flat faces on each part. These are the candidate cut faces.
2. For each pair of faces on two different parts, turns one face to point against the other. It then searches the rotation within the plane for the best outline overlap (IoU, with holes counted).
3. Joins parts along the best-fitting faces, using each face once. Pieces that already touch in place are kept where they are.
4. Joins the pieces into one watertight mesh (boolean union with manifold3d). Use `--no-union` to just place the pieces.

## Options

- `--tolerance 0.05`: how much the mating faces may differ.
- `--export-parts DIR`: also write each repositioned piece.
- `--max-faces`, `--min-area`: control which flat faces count as cut candidates.

## Known limitations

- A cut face with a symmetric outline (rectangle, circle) can fit in more than one rotation. The tool warns when this happens. A matching end face elsewhere on the part can also be confused with the real cut face. For reliable results, export the pieces at their original positions (most slicers' cut tools can), or use cut connectors such as dowels or keys so each joint is unique.
