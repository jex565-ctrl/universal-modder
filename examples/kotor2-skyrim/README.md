# KOTOR 2 in Skyrim: a converter that reads your own installs

The goal: Knights of the Old Republic II: The Sith Lords inside Skyrim Special Edition. That means
its lightsabers, blasters and armour, its characters with their original voice acting, its dialogue,
quests and maps, all played with Skyrim's real-time combat instead of KOTOR's rounds.

This folder is the converter, `k2s`. It reads **your** KOTOR 2 install (through
[PyKotor](https://pypi.org/project/pykotor/)) and **your** Skyrim masters, and writes Skyrim files into a
private output folder. It ships no game data, and its output must never be uploaded: that output *is*
KOTOR's assets and text.

**Status: in progress, and nothing has been run on a real install yet.**
- Every step below is tested end to end against synthetic installs: invented items, lines and rooms,
  written with PyKotor's own writers and with Skyrim-shaped masters.
- The generated plugin passes LOOT's [esplugin](https://crates.io/crates/esplugin) 6.1.4 parser, an
  independent check.
- None of it has been launched in Skyrim or run against the real KOTOR 2 files.

What runs today, and what's still ahead, is in [PLAN.md](PLAN.md).

## What each step does

| step | reads | writes | state |
|---|---|---|---|
| `catalog` | KOTOR 2 install | `catalog.json`: every item (class, dice, properties, saber colour), creature, force power, journal quest, module | tested on synthetic data |
| `arsenal` | catalog + `Skyrim.esm`, `Update.esm`, `Dawnguard.esm` | `KotOR2_Arsenal.esp` (light plugin): every lightsaber, vibroblade, blaster, armour, robe, helmet, glove; "Power Cell" ammo; a footlocker with one of each | tested; esplugin parses it; **not yet loaded in Skyrim** |
| `console` | `arsenal.json` | `kotor2.txt` for the console's `bat` command (spawns the footlocker) | tested |
| `dialogue` | every `.dlg` + journal | per-conversation JSON + a readable script (`.md`), `quests.json` (journal → quest stages), `scripts_to_port.json` (every KOTOR script a conversation calls) | tested on synthetic data |
| `characters` | catalog + dialogue | `characters.json`: each character, companion flag, stats, gear, and every line they speak with its voice file | tested on synthetic data |
| `voice` | `characters.json` + `StreamVoice` | the original performances as 44.1 kHz mono WAV per character voice type, `manifest.json`, `encode_voice.bat` (xWMA) | tested with ffmpeg on synthetic audio |
| `maps` | modules (.ifo/.are/.git/.lyt/.wok) | per area: `layout.json` (rooms + every placement in Skyrim units/rotation), room OBJs, walkmesh OBJs (navmesh guide) | tested on synthetic data |
| `models` | weapon models (.mdl/.mdx), textures (.tpc) | OBJ + MTL per model, separate `_blade.obj` for lightsaber blades, DDS textures | tested on a synthetic model |
| `blender/obj_to_nif.py` | the OBJs | Skyrim SE NIFs via Blender + PyNifly | **written, not run** (no Blender here) |
| `inspect` | any plugin | its records | tested |

### How the arsenal gets Skyrim's real-time combat
KOTOR rolls dice in rounds. In Skyrim every swing and shot is real time, so the converter doesn't copy
dice. Instead it ranks each weapon inside its archetype and maps it onto Skyrim's vanilla range
([`k2s/stats.py`](k2s/stats.py), one tunable table):

| archetype | Skyrim animation | damage (weakest → best) | notes |
|---|---|---|---|
| lightsaber | one-handed sword | 12 → 18 | speed 1.15; ignores normal weapon resistance |
| short lightsaber | dagger | 9 → 13 | speed 1.35 |
| double-bladed lightsaber | greatsword | 19 → 27 | |
| vibroblade / sword | one-handed sword | 7 → 14 | |
| vibro double-blade, force pike, staff | greatsword | 14 → 24 | |
| baton / stun weapons | mace | 8 → 16 | |
| blaster pistol / rifle / heavy (repeaters) | crossbow | 10 → 17 / 15 → 23 / 19 → 27 | fires "Power Cells" |
| light / heavy armour, Jedi robes | light / heavy cuirass | 20 → 38 / 28 → 49 / 12 → 30 | robes are light armour so a robed Jedi is viable |

- **Power score:** average dice, plus the average of "Damage Bonus" properties, plus half the attack
  bonus. The properties are decoded through `itempropdef` → `iprp_costtable` → each cost table.
- **Placeholders:** models, sounds, impact sets and keywords come from vanilla templates (steel sword,
  Dawnguard crossbow...). They are found in your masters by EditorID or by structure, with no
  hard-coded FormIDs, so everything is usable before a single mesh is converted.
- **KOTOR meshes:** `--use-meshes` points weapons at `meshes/kotor2/<model>.nif` wherever you've built
  one.

## Run it

You need Python 3.10+ and [uv](https://docs.astral.sh/uv/), plus ffmpeg for `voice` (`um win setup`
installs it on Windows). Run everything from this folder, with an output folder **outside any git repo**:

```sh
K2="C:/Program Files (x86)/Steam/steamapps/common/Knights of the Old Republic II"
SKY="C:/Program Files (x86)/Steam/steamapps/common/Skyrim Special Edition/Data"
OUT="$HOME/k2s-out"
k2s() { uv run --with pykotor==2.3.12 python -m k2s "$@"; }

k2s catalog    --kotor2 "$K2" --out "$OUT"        # read the summary and the diagnostics it prints
k2s arsenal    --skyrim-data "$SKY" --out "$OUT"  # -> $OUT/KotOR2_Arsenal.esp
k2s dialogue   --kotor2 "$K2" --out "$OUT"
k2s characters --out "$OUT"
k2s voice      --kotor2 "$K2" --out "$OUT" --only kreia,atton --limit 50   # try a few lines first
k2s maps       --kotor2 "$K2" --out "$OUT" --module 101per                 # Peragus first
k2s models     --kotor2 "$K2" --out "$OUT"
```

**Try the arsenal in game:**
1. Use a Mod Organizer 2 profile, or back up first with `um backup create`.
2. Install `KotOR2_Arsenal.esp` as a mod, enable it, and start a throwaway save.
3. In the console, run `help "KotOR 2 Footlocker" 4`. Its ID is the plugin prefix followed by three hex
   digits: in `FE001A3C` the prefix is `FE001`.
4. Type `player.placeatme FE001A3C 1` (your ID), or run `k2s console --out "$OUT" --prefix FE001`,
   put `kotor2.txt` next to `SkyrimSE.exe`, and type `bat kotor2`.

**Tests:** `uv run --with pykotor==2.3.12 --with pytest pytest -q tests`

## Files

| file | what it does |
|---|---|
| `k2s/kotor.py` | KOTOR 2 install index (override > modules > texture packs > BIFs), GFF → plain data, 2DA/TLK helpers |
| `k2s/catalog.py` | items, creatures, force powers, journal, modules → `catalog.json` |
| `k2s/stats.py` | d20 → Skyrim real-time conversion (all numbers in one table) |
| `k2s/esp.py` | Skyrim SE plugin writer and reader (records, groups, XXXX escape, compressed records, light plugins) |
| `k2s/skyrim.py` | your masters as template source: EditorID lookups, FormID remapping across masters, override order |
| `k2s/arsenal.py` | weapons/armour/ammo/footlocker plugin |
| `k2s/dialogue.py` | DLG graphs → JSON, readable scripts, script worklist; journal → quest stages |
| `k2s/characters.py` | who speaks which line (speaker tags, conversation owners), companions, voice types |
| `k2s/voice.py` | StreamVoice → WAV for Skyrim, `.fuz` packing |
| `k2s/maps.py` | areas → layout + placements in Skyrim units, room and walkmesh OBJs |
| `k2s/models.py` | MDL/MDX → OBJ (node transforms flattened, blades split), TPC → DDS |
| `blender/obj_to_nif.py` | OBJ → NIF with PyNifly (unrun) |
| `tests/` | synthetic installs (`fixtures.py`) and end-to-end tests |

## Rules this follows
- **Inputs:** your own copies of both games, offline and single-player. KOTOR 2 has no anti-cheat, and
  the converter only reads its files.
- **Distribution:** nothing from either game is in this repo. The output folder is personal. Ports of
  another game's assets aren't allowed on Nexus Mods without permission, so share the converter, not
  what it makes.
- **Credits:** PyKotor (LGPL-3.0) reads KOTOR's formats. The plugin layouts follow xEdit's
  `wbDefinitionsTES5.pas`. This converter was written by an AI agent (Claude Code); see `MODLOG.md`.
