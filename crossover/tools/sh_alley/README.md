# Silent Hill opening alley -> Resident Evil rooms (prototype pipeline)

Python prototype (numpy, scipy, Pillow) that turns Silent Hill's opening
nightmare alley (map chunks THRF905/THRF906 from your own disc) into three
fixed-camera Resident Evil rooms, played with RE's engine and mechanics.

Inputs: Silent Hill assets extracted with the SH decomp's
`tools/silentassets/extract.py` into `shassets/`, and your RE `USA` data tree.

    python build_alley.py <RE english/USA folder> <mod folder>

Writes `stage1/ROOM1080/1090/1120*.RDT`, their `RC1xxC.pak` backgrounds and
`data/bio_card.dat` (new games start in the alley). Point `config.ini`
`[Assets] ModPath` at the mod folder.

What it does:
* `shmap.py`   IPD/LM map chunks -> world triangles (materials, CLUT rows, stitched vertices)
* `walk.py`    floor/wall rasterisation -> walkable grid
* `camrender.py` pre-renders 320x240 backgrounds with RE's exact camera projection
* `build_alley.py` rooms, cameras, collision boxes, camera-switch zones, doors, init script, RDT/PAK writer
* `check_rooms.py`, `sim.py`, `pathcheck.py` read the output back and verify it
  (collision vs background, door spawns, walkability at the player's 422-unit radius)

Generated files contain material from both games - never commit them.
