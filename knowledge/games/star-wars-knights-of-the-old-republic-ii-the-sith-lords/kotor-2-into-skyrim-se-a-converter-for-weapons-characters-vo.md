---
kind: game
title: "KOTOR 2 into Skyrim SE: a converter for weapons, characters, voice, dialogue, quests and maps"
game: "Star Wars: Knights of the Old Republic II - The Sith Lords"
games_also: ["The Elder Scrolls V: Skyrim Special Edition"]
game_version: "not yet run on a real install; targets KOTOR 2 PC (Steam/GOG, 2021 Aspyr update or original) and Skyrim SE/AE with Dawnguard (plugin form version 44, HEDR 1.71)"
platform: windows
engine: native
route: data
tools: ["PyKotor 2.3.12 (PyPI)", "xEdit wbDefinitionsTES5.pas (dev-4.1.6) for record layouts", "esplugin 6.1.4 (Rust) as an independent plugin parser", "ffmpeg", "Blender + PyNifly (planned)", "xWMAEncode + Creation Kit (planned)"]
anti_cheat: "none in either game; offline single-player only. The converter only reads KOTOR 2's files."
status: in-progress
agents: ["Claude Code (Opus 5.5)"]
humans: []
date: 2026-10-10
links: ["examples/kotor2-skyrim"]
tags: [total-conversion, content-port, mashup, odyssey, bioware, gff, 2da, tlk, dlg, jrl, lyt, bwm, mdl, creation, esp, esl, weap, armo, ammo, voice, fuz, xwma, pykotor, esplugin]
---

# KOTOR 2 into Skyrim SE: a converter for weapons, characters, voice, dialogue, quests and maps

> `examples/kotor2-skyrim` (`k2s`) reads the user's own KOTOR 2 install through PyKotor and the user's own
> Skyrim masters, and writes Skyrim content into a private folder:
> - a light plugin with every lightsaber, blaster and armour rescaled to Skyrim's real-time stats;
> - dialogue trees and quest stages;
> - per-character line lists with the original voice audio converted for Skyrim;
> - map layouts in Skyrim units, plus room and walkmesh OBJs.
>
> Built in a container with neither game installed: every exporter is tested against synthetic
> installs, and LOOT's esplugin parses the generated plugin. **Nothing has been loaded in Skyrim yet.**

## Setup
- **KOTOR 2 side:** PyKotor 2.3.12 from PyPI (`uv run --with pykotor==2.3.12`), which pulls in
  kaitaistruct, bioware-kaitai-formats, ply and defusedxml.
- **Skyrim side:** no library. `k2s/esp.py` writes and reads plugins; the layouts come from xEdit's
  `Core/wbDefinitionsTES5.pas`, branch dev-4.1.6.
- **ffmpeg** for voice. Blender + PyNifly for meshes and xWMAEncode for voice are still to be run on
  Windows.

## Route and why
- **Route:** content conversion with Skyrim as the only running game (mashup pattern 1, "port the
  content"). KOTOR's round-based rules are the part the user wanted gone, so they don't run at all: its
  numbers become Skyrim stats.
- **Rejected:** passthrough and an engine rebuild. Skyrim already has the real-time combat, AI, followers
  and quest systems.

## How the games work (what we had to learn)
- **KOTOR's resource order:** override > modules (`*.rim`, `*_s.rim`, TSL's `*_dlg.erf`, `.mod`) >
  TexturePacks ERFs > BIFs via `chitin.key`. PyKotor's `Installation` exposes each source separately
  (`chitin_resources`, `module_resources(name)`, `texturepack_resources(name)`, `override_resources()`).
  Build one index with that priority.
- **PyKotor's `create_installation(path, Game.K2, bif_resources=..., modules_resources=...,
  override_resources=..., dialog_entries=[...])` writes a real install layout.** That makes synthetic
  end-to-end tests possible. Two gotchas:
  - It types resources by file extension through `ResourceType[EXT]`. `2da` doesn't resolve (the enum
    member is `TwoDA`), so 2DAs in `bif_resources` silently become `.utc`; put them in
    `override_resources`.
  - It writes no `global.jrl` and no StreamVoice; add those by hand.
- **GFF through PyKotor:** iterating a `GFFStruct` yields `(label, type, value)`, with values as
  LocalizedString, ResRef, GFFList or GFFStruct. Converting them to plain dicts once (`kotor.gff_dict`)
  keeps the rest of the converter independent of PyKotor's object model.
- **Item properties:** `PropertyName` → `itempropdef.2da` row (its `subtyperesref` names the subtype
  2DA). `CostTable` → an `iprp_costtable.2da` row whose `name` is the cost 2DA, and `CostValue` → a row
  of that 2DA (damage tables have `numdice`/`die`). This is how "Damage Bonus: Energy 2d6" is decoded.
- **Equip slots** (`baseitems.2da equipableslots`, from Aurora): head 0x1, body 0x2, hands 0x8, right
  hand 0x10, left hand 0x20, arms 0x80/0x100, implant 0x200, belt 0x400.
- **DLG graph:**
  - Lists: EntryList (NPC lines, `RepliesList` links), ReplyList (player lines, `EntriesList` links),
    StartingList.
  - Links carry `Active` (plus `Active2` in TSL), `Not`/`Not2`, `Logic` and `IsChild`.
  - Lines carry `Speaker` (a creature tag; empty means the conversation's owner), `Script`/`Script2`,
    `VO_ResRef`, `Quest`/`QuestEntry`.
- **Voice:** `StreamVoice/<folder>/<vo_resref>.wav`. Some files carry KOTOR's 470-byte SFX header
  (magic `FF F3 60 C4`), a 20-byte VO header before a second `RIFF`, or are MP3 in a WAV wrapper (RIFF
  size 50, 58-byte header). PyKotor's `get_deobfuscation_result` returns the clean bytes and which case
  it was.
- **MDL:** PyKotor reads binary MDL plus MDX. Each node has a position and an orientation quaternion
  `(x, y, z, w)`, and mesh vertices are local to their node. Lightsaber blades are separate nodes
  (`saber` set, or "blade" in the name). Pass the MDX bytes as `source_ext`, or normals and UVs are lost.
- **Skyrim WEAP records:**
  - DNAM is 100 bytes: anim type at 0 (1 sword, 2 dagger, 4 mace, 5 greatsword, 9 crossbow), speed at
    4, reach at 8, flags at 12 (0x1 ignores normal weapon resistance), skill at 76, stagger at 96.
  - SSE CRDT is 24 bytes, with the effect FormID at 16.
  - SSE AMMO DATA is projectile, flags (0x4 = Non-Bolt, i.e. an arrow), damage, value, weight.
- **Skyrim ARMO records:** Skyrim.esm's armour often has the LE-era BODT (slots, flags, 3 unused,
  type) instead of BOD2 (slots, type); handle both. `MODL` in ARMO is an ARMA FormID, not a path.
- **FormID remapping:** a record copied from Dawnguard.esm (masters: Skyrim.esm, Update.esm) refers to
  index 00/01/02 of *Dawnguard's* list. Resolve each FormID to (defining file, object ID), then
  re-index it into the new plugin's master list. Later masters override earlier ones (Update.esm wins).

## Build steps
See `examples/kotor2-skyrim/README.md`, in this order:
1. `k2s catalog`
2. `k2s arsenal --skyrim-data <Data>`
3. `k2s dialogue`
4. `k2s characters`
5. `k2s voice`
6. `k2s maps --module 101per`
7. `k2s models`

## Verification
- **Tests:** 12 pytest tests over synthetic installs (`tests/fixtures.py`) covering:
  - the catalog and property decoding;
  - dialogue trees and the script worklist;
  - speakers and voice (ffmpeg output checked as 44.1 kHz, 16-bit mono);
  - map units and rotation;
  - model transforms (a node rotated 90° about Z under a translated parent);
  - stats scaling;
  - every byte that matters in the WEAP/ARMO/AMMO/CONT records, and `--use-meshes`.
- **esplugin 6.1.4** parses the arsenal plugin: masters, light flag valid, version 1.71, record and group
  count 22 = 5 groups + 17 records.
- **Not verified:**
  - loading in Skyrim;
  - the real KOTOR 2 2DA column names;
  - saber colour per ModelVariation beyond 1-5;
  - the KOTOR → Skyrim facing formula;
  - the Blender/PyNifly step;
  - xWMA, lip and .fuz in game.

## Gotchas
1. **PyKotor floods the console with `DEBUG(root): No case-insensitive match...`.** **Cause:** its
   logger is configured at DEBUG with its own handlers, so setting levels on named loggers doesn't help.
   **Fix:** `logging.disable(logging.INFO)` before using it.
2. **2DAs in a synthetic BIF come back as UTC.** **Cause:** `create_installation` maps the extension
   through `ResourceType["2DA"]`, which doesn't exist. **Fix:** put 2DAs in `override_resources`.
3. **MDL normals and UVs vanish.** **Cause:** the MDX wasn't passed. **Fix:**
   `read_mdl(mdl_bytes, source_ext=mdx_bytes)`; in tests, `write_mdl(m, mdl_buf, target_ext=mdx_buf)`.
4. **A copied template keeps a sound the override removed.** **Cause:** reading Skyrim.esm's record
   instead of Update.esm's override. **Fix:** key records by (file, object ID) and let later masters
   replace earlier ones.
5. **A 70 KB description desyncs a reader.** **Cause:** a subrecord over 65535 bytes. **Fix:** write and
   read the `XXXX` escape; there's a test for it.
6. **Light plugin overflow.** **Cause:** a light plugin holds object IDs 0x800-0xFFF, 2048 new records at
   most. **Fix:** the arsenal falls back to a regular plugin if KOTOR has more weapons and armour than
   that, and the later dialogue/map plugin must be a regular ESP.

## Assets
None generated. All KOTOR content is converted locally from the user's install and stays in their
output folder. Placeholder models, sounds and keywords come from the user's own Skyrim masters.

## Cost and time
One session (several hours), with no game installed.

## Open questions
- The real `baseitems.2da` columns in the Aspyr build; the first `k2s catalog` run's `diagnostics`
  answers it.
- Bolt deflection with a lightsaber (perk + Papyrus vs SKSE).
- Droid and alien races.
- Porting NWScript conditions and actions to Papyrus at scale.
- NPC_ and dialogue record writers (phases 5-8 in PLAN.md).
