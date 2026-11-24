# stljoiner

Reassemble STL parts that were split apart (for example, to fit a print bed) by matching their mating faces, then write one combined mesh.

```
uv venv && uv pip install -r requirements.txt
```

## Web interface

```
.venv/bin/python app.py          # then open http://127.0.0.1:5000
```

1. Drop your STL parts in. Only checked parts can be picked, joined or exported. Unchecked parts are faded out so they stay out of the way.
2. Click the mating face on one part (A, yellow), then the matching face on another part (B, cyan), and press **Join B → A**. Part B, plus anything already joined to it, moves onto A.
3. If the face is symmetric and B comes out turned the wrong way, press **Next rotation**.
4. **Auto-join** guesses the joints for the checked parts. **Undo** and **Reset positions** are there if it guesses wrong.
5. **Export STL** writes the checked parts as one merged solid.

## Command line

```
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

- Auto-join (and the CLI) only goes by face shape. A cut face with a symmetric outline (rectangle, circle) can fit in more than one rotation. The tool warns when this happens. A matching end face elsewhere on the part can also be confused with the real cut face. In the web UI you can avoid this by picking the faces yourself. Otherwise, export the pieces at their original positions (most slicers' cut tools can), or use cut connectors such as dowels or keys so each joint is unique.
