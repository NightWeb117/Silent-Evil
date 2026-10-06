# Silent Hill × Resident Evil — crossover launcher

Play Resident Evil (PC, 1997) as **Harry Mason** from Silent Hill (PS1).

This project ships **no game assets**. Like other decompilation-based ports, you
provide your own copies of both games; the launcher reads them and generates the
converted files on your machine. Neither game's files are ever modified.

## What you need

| Game | What to point the launcher at |
|---|---|
| Resident Evil (PC — GOG, Steam or the 1997 CD release) | the install folder. The launcher finds the `USA` data tree inside it (`USA\`, `english\USA\`, ...). |
| Silent Hill (PS1) — NTSC-U 1.1 (`SLUS-00707`), NTSC-J or PAL | a disc image you dumped: `.cue` + `.bin`, a raw `.bin`, or a 2048-byte `.iso`. |

## Using the launcher (Windows)

1. Put `CrossoverLauncher.exe` in the same folder as `residentevil.exe` (the
   release zip already does this).
2. Run `CrossoverLauncher.exe`, choose your Resident Evil folder and your Silent
   Hill disc image.
3. Press **Play**. The first time, the launcher builds the Silent Hill assets
   (it takes well under a second), then starts the game.

The launcher:

* writes the converted models to `mods\silent-hill\` beside itself;
* sets `config.ini` → `[Assets] Path` to your Resident Evil install (read-only use),
  `[Assets] ModPath=mods\silent-hill`, and `[Save] Path=SAVE`, so this game keeps
  its own save files;
* rebuilds automatically if you change either game path or the options.

To go back to the plain game, empty `ModPath=` in `config.ini` (or delete
`mods\silent-hill\`).

## Linux / command line

`shre_convert` does the same build without a GUI:

```
cmake -S crossover -B build-crossover && cmake --build build-crossover
./build-crossover/shre_convert --re ~/Games/ResidentEvil --sh ~/roms/silent-hill.cue --out ./mods/silent-hill
```

then in `config.ini`:

```
[Assets]
Path=/path/to/ResidentEvil/english     ; the folder that contains USA/
ModPath=mods/silent-hill
[Save]
Path=SAVE
```

Other options: `--jill` (also replace Jill — experimental), `--list` (list
Silent Hill's files), `--extract CHARA/HERO.ILM out.ilm`.

## What is converted so far

| Status | Content |
|---|---|
| done | Harry Mason replaces Chris (model, texture, proportions; RE animations) |
| experimental | Harry replaces Jill (`--jill` / checkbox) — small seam at the neck in some poses |
| known gap | with a weapon drawn, the gun hand comes from `players\W0x.EMW` and is still Chris's gloved hand |
| planned | Silent Hill creatures as enemies, Silent Hill music/sound, Silent Hill locations |

## How the conversion works

`lib/harry.cpp`, in order:

1. **Read the disc.** ISO9660 → `SYSTEM.CNF` → boot executable → release check
   (CRC32 of its first 4 KB, same table as the Silent Hill decomp's
   `tools/silentassets/extract.py`) → file table → `CHARA/HERO.ILM`,
   `CHARA/HERO.TIM`, `ANIM/HB_BASE.ANM` straight out of `SILENT.`.
2. **Pose Harry** with the first keyframe of `HB_BASE.ANM` (bone hierarchy,
   Q0.7 rotation matrices, shifted translations).
3. **Resolve stitched vertices.** Silent Hill draws a character's bone models in
   the ILM's *model order* through a shared scratch buffer; each model writes
   its vertices at `vertexOffset` and may index vertices the previous models
   left there (that is how thighs join hips without seams). The converter
   replays that order to give every polygon corner a real position.
4. **Fit to the RE skeleton.** SH space (+Z forward) → RE space (+X forward) by
   a proper rotation (no mirroring); one global scale puts Harry's waist at the
   RE root height; each limb segment is re-aimed along RE's rest pose (limbs
   straight down) keeping Harry's own lengths, and the EMD's joint offsets are
   rewritten to match. RE's animations are rotations only, so they drive the
   new proportions unchanged.
5. **Write the EMD.** 15 TMD objects of textured Gouraud triangles (mode 0x34,
   RE's winding: `cross(v1-v0, v2-v0)` opposes the normal), the original's
   extra objects, and an 8bpp 256×256 TIM: Harry's 4bpp texture with its CLUT
   row baked into each texel's index, split into RE's two 128-texel pages
   (the few triangles that straddle the split get a copy of their texels in
   the free lower half).

The output was checked against an independent Python implementation (byte-for-
byte identical) and rendered posed by RE's own animation frames.

## Legal

Silent Hill is © Konami. Resident Evil / Biohazard is © Capcom. This is an
unofficial fan project, not affiliated with either. It contains no assets from
either game, and the files it generates come from your own copies — do not
redistribute them.
