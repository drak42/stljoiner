# stljoiner user guide

![The scattered pieces fly together onto their cut faces and fuse into one solid](images/how-it-works.gif)

Did you split a model to fit your print bed, or download a model that came in pieces, and now want it back as one part? stljoiner puts STL pieces back together by matching the faces where they were cut, then saves them as a single solid STL.

This guide covers the web interface first, since it's the easiest way to use stljoiner. The command-line version is covered near the end.

---

## Setting up (one time)

You need Python 3.10 or newer. Install stljoiner with [pipx](https://pipx.pypa.io/), which keeps it in its own tidy environment:

```bash
pipx install stljoiner
```

No pipx? `pip install stljoiner` works too. To update later: `pipx upgrade stljoiner`.

## Starting the app

```bash
stljoiner web
```

Then open **http://127.0.0.1:4300** in your browser.

> The 3D viewer loads from the internet the first time, so you need a connection. Your STL files never leave your computer: they go only to the app running on your own machine.

To stop the app, press `Ctrl+C` in the terminal.

---

## A quick tour of the screen

![The web interface: the parts list on the left with two pieces joined, the face-picking panel, and the parts in the 3D view](images/web-ui.png)

| Area | What it's for |
|---|---|
| **Drop zone** (top left) | Add STL files by dragging them in or clicking *browse*. |
| **Parts list** | Every loaded piece, with its color in the 3D view. |
| **Join by faces** | Shows the two faces you've picked and the **Join B → A** button. |
| **Selected parts** | Auto-join, Undo, Reset positions and Export. |
| **3D view** (right) | Your parts. Drag to orbit, right-drag to pan, scroll to zoom. **Fit view** brings everything back into frame. |

---

## Joining your parts, step by step

### 1. Add your pieces

Drag all the STL pieces onto the drop zone or the 3D view. Each one gets its own color.

A ⚠ next to a name means that piece has holes in its mesh. It can still be joined, but merging into one solid may not work cleanly. Repairing the piece in your slicer or mesh tool first helps.

### 2. Choose which parts to work with

Each part in the list has a checkbox. **Only checked parts are used.** Unchecked parts:

- are faded out in the 3D view,
- can't be clicked,
- are left out of Auto-join and Export.

This is handy when you've loaded extra pieces, or several models at once, and want to focus on just the ones that go together.

### 3. Pick the two faces that touch

1. Click the **cut face** on the first part. It lights up **yellow**. This is face **A**, and this part stays still.
2. Click the matching cut face on another part. It lights up **cyan**. This is face **B**, and this part will move.
3. Press **Join B → A**.

Part B jumps into place against part A. Any parts already joined to B move along with it.

**Tips for picking faces:**
- Orbit around until you can see the flat cut face clearly, then click it.
- If the cut went through a hole or slot, the face may be split into several flat pieces. Click any one of them and stljoiner selects them all.
- Clicked the wrong face? Click again to start over, or press **Clear** (or `Esc`).

### 4. Fix the rotation if needed

Some cut faces look the same when turned around. A rectangle, for example, fits two ways and a square fits four. If your part lands upside down or turned the wrong way:

- Press **Next rotation** under the Join button to step through every way the faces fit. The button only appears when a face fits more than one way.
- The **Fit %** shows how well the faces line up. A correct cut usually reads 100%.

### 5. Repeat for the remaining pieces

Keep picking pairs of faces until everything is connected. Joined parts show a **joined #** label in the list.

### 6. Export

Press **Export STL**. With **merge into one solid** ticked (the default), you get a single clean solid called `joined.stl`, ready for your slicer. Untick it to keep the pieces as separate bodies in one file.

---

## Letting stljoiner guess: Auto-join

**Auto-join** tries to work out every joint among the checked parts by itself. It works well when:

- the pieces are **still in their original positions**, for example if you exported them from your slicer's cut tool without moving them, or
- every cut face has a **unique shape**, for example with dowel holes, pegs or a jagged cut.

It can be fooled when a piece has an end face the same shape as a cut face, such as both ends of a plain rectangular bar. If Auto-join gets something wrong, press **Undo** and join those parts by picking faces yourself.

---

## Other handy buttons

| Button | What it does |
|---|---|
| **Undo** | Steps back one change (up to 50). |
| **Reset positions** | Puts every part back where it was in its original file and separates all joins. |
| **detach** (in the parts list) | Separates one part from its group without moving it. |
| **✕** (in the parts list) | Removes a part from the session. |
| **Fit view** | Zooms the 3D view to fit the checked parts. |

---

## Troubleshooting

**"Those parts are already joined together"**
Both faces you picked belong to the same group. Pick face B on a part that isn't joined to A yet, or **detach** one first.

**The part landed in a strange spot.**
You probably picked a face that isn't the real cut face. A part's end or top can be the same size as the cut. Press **Undo** and pick again.

**It's the right face but turned the wrong way.**
Press **Next rotation**.

**The exported file isn't a single solid / my slicer complains.**
This usually means one of the pieces had holes in its mesh (look for ⚠ in the parts list). Repair the piece and try again, or export with **merge into one solid** unticked.

**The 3D view is blank.**
Check your internet connection (the viewer loads from a CDN), then reload the page.

**Port 4300 is already in use.**
Start the app on another port, for example `stljoiner web --port 4301`.

---

## Using the command line instead

To join files without the browser:

```bash
stljoiner part1.stl part2.stl part3.stl -o joined.stl
```

This works like Auto-join, with the same strengths and limits. Useful options:

| Option | Meaning |
|---|---|
| `-o FILE` | Output file name (default `joined.stl`). |
| `--no-union` | Place the parts but don't merge them into one solid. |
| `--export-parts DIR` | Also save each repositioned piece separately. |
| `--tolerance 0.05` | How closely faces must match (5% by default). Raise it a little if matching faces have small differences. |
| `-q` | Quiet mode. |

---

## Tips for best results

- **When splitting a model, keep the pieces in place** when you export them. stljoiner then rejoins them perfectly with no guessing.
- **Use connectors** (pegs, dowels, keys) when cutting. They give each cut face a unique shape, so the right match is obvious.
- **Make sure each piece is watertight** before joining. Most slicers can repair meshes.

---

## Enjoying stljoiner?

It's free and open source. If it rescued a print, you can [buy me a coffee](https://buymeacoffee.com/drak42) ☕. Found a bug or have an idea? [Open an issue](https://github.com/drak42/stljoiner/issues/new/choose). Attaching the STL pieces helps the most.
