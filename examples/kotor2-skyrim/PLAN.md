# KOTOR 2 → Skyrim: the whole plan

What the user asked for:
- KOTOR 2's maps, missions (quests) and dialogue in Skyrim, with all of its lightsabers, guns and
  everything else;
- the same characters with the same voice lines;
- Skyrim-style real-time combat, not KOTOR's turn-based rounds.

This is a total conversion, the "one open-world RPG converted into another" route in
`knowledge/techniques/choosing-a-mashup-route.md`. Skyrim is the only game that runs. KOTOR 2 is only a
data source, converted offline on the user's machine (mashup pattern 1, "port the content").

## Route and why
- **Asset and data conversion into a host with real-time combat.** Skyrim's combat engine is the
  requirement, so KOTOR's rules don't run at all. Its numbers become Skyrim stats (`stats.py`), and its
  scripted logic becomes Papyrus.
- **Rejected: passthrough** (both games running and exchanging state). KOTOR's combat is the part the
  user wants gone, and a second process adds only fragility.
- **Rejected: an engine rebuild** (xoreos-style). Skyrim already provides the real-time combat, physics,
  AI, followers and quest systems this port needs.
- **Every player needs:** their own KOTOR 2 (Steam/GOG, the 2021 Aspyr update or the original), Skyrim
  Special Edition/AE with Dawnguard, Windows to run the Creation Kit and xWMAEncode, and Blender with
  PyNifly.

## Phases
Each phase ends with a check in the real game (the oracle), not only a green test.

| # | phase | the work | done when | state |
|---|---|---|---|---|
| 0 | Recon and lab | `um scan` both games; MO2 profile "K2S"; `um backup create` for saves; exact versions into MODLOG.md | both installs scanned, versions written down | needs the user's PC |
| 1 | **Arsenal** | `k2s catalog` + `k2s arsenal` | all lightsabers, blasters and armour in the footlocker, equipped, swung, fired, killing a bandit | **code done**; to load in game |
| 2 | Meshes and textures | `k2s models` → `blender/obj_to_nif.py` → `arsenal --use-meshes`; blade glow via BSEffectShaderProperty; crystal colours as texture sets | a real KOTOR hilt in hand, blade glowing in the crystal's colour | OBJ export done; Blender step unrun |
| 3 | Real-time feel | blaster bolt projectile (PROJ + LIGH, red/blue), fire-rate tuning, lightsaber hum (SNDR from KOTOR's own saber sounds), bolt deflection while blocking with a saber (a perk + Papyrus, or a small SKSE plugin) | a saber blocks and reflects blaster fire in game | not started |
| 4 | Force powers | `catalog.force_powers` → SPEL/MGEF using vanilla effect archetypes: Push → Unrelenting Force style, Lightning → shock concentration, Heal → restoration, Speed → Whirlwind-style, Stun/Choke → paralysis/damage over time, Battle Meditation → cloak; Force Points → Magicka; light/dark side as a global affecting costs | the main powers castable with the right visuals | not started |
| 5 | **Characters** | `k2s characters`: one NPC_ per character. Humans (Atton, Mira, Disciple, Handmaiden, Kreia, Visas...) on a Skyrim human race with FaceGen from the Creation Kit, matched to KOTOR's look. Aliens (Bao-Dur's Iridonian, Hanharr's Wookiee, Twi'leks, Rodians, Duros) as custom races with KOTOR head models. Droids (HK-47, T3-M4, G0-T0) on custom creature races; the hardest part, since skeletons and behaviours must come from Skyrim creatures (Dwarven sphere/centurion) or new animations | each companion standing in the Ebon Hawk, looking right | sheets exported; records not started |
| 6 | **Voice** | `k2s voice` → `encode_voice.bat` (xWMAEncode) → Creation Kit lip generation → `.fuz` named after each INFO (`<quest>_<topic>_<INFO formid>_1.fuz`). One VTYP per character so only they say their lines | Kreia speaks her own opening lines, lip-synced | WAV export done |
| 7 | **Dialogue** | generate DIAL/INFO/DLBR per conversation from `dialogue/*.json`: NPC lines → INFOs, player replies → topics with "choices" links, starters → branch start. Conditions: KOTOR globals (`globalcat.2da`, plot flags) → Skyrim GLOB records and quest stages. Actions: the script worklist (`scripts_to_port.json`) ported to Papyrus fragments, after decompiling NCS outside the repo | one full conversation (Kreia on Peragus) playable with branches and voice | trees and worklist done; record writer not started |
| 8 | **Quests** | `quests.json` → QUST records: journal entry IDs become stages, entry text the log, `End` completes; aliases for the characters | the Peragus escape quest updates and completes | stages exported; records not started |
| 9 | **Maps** | per module: `k2s maps` → rooms to NIF (Blender) → STAT records; REFR/ACHR from `layout.json`; interior cells per area (KOTOR areas are small, enclosed rooms). Navmesh: generated in the Creation Kit, using the walkmesh OBJ as the guide. Doors with load doors between areas. Order: Ebon Hawk, Peragus, Harbinger, Telos Citadel Station, Nar Shaddaa, Dxun, Onderon, Dantooine, Korriban, Malachor V | walk Peragus end to end with NPCs and loot where KOTOR puts them | layout export done |
| 10 | Galaxy | the Ebon Hawk as a hub; a galaxy map activator (MESG menu) to travel between planets; a start: an alternate-start choice or a door from Skyrim into Peragus | a new game starts on Peragus | not started |
| 11 | Showcase and notes | `um win record` → `um video compile`; field note update; installer notes | a 30-45 s clip | not started |

## Who owns what (the contract)
- **Units and axes:** KOTOR metres → Skyrim units ×70. Both use Z up, X east, Y north.
- **Facing:** KOTOR measures counter-clockwise from east, Skyrim clockwise from north:
  `rz = pi/2 - bearing`. Check it on one placeable in game.
- **IDs:** KOTOR resref → Skyrim EditorID `K2W_`/`K2A_` + resref; the FormIDs are in `arsenal.json`.
  Later plugins master `KotOR2_Arsenal.esp`, so NPC loadouts reference the same records.
- **Plugins:** the arsenal stays a light plugin. Characters, dialogue, quests and maps will exceed 2048
  records, so they go in one regular `KotOR2.esp` with `KotOR2_Arsenal.esp` as its master.
- **Strings:** inline and non-localized (cp1252). KOTOR's English TLK fits; other languages need a
  localized plugin with `.STRINGS` files.

## Known hard parts (be honest with the user)
1. **Scripts.** Quest and dialogue logic is KOTOR NWScript, compiled to NCS. Every condition and action
   (`scripts_to_port.json` counts them) needs a hand-checked Papyrus equivalent. This is most of the
   effort, and no converter does it automatically.
2. **Droid and alien bodies.** KOTOR skeletons and animations don't fit Skyrim's behaviour graphs. Humans
   are fine; droids need creature races or new Havok animations.
3. **Navmesh.** The Creation Kit generates it, but every area needs a manual pass.
4. **Voice naming.** A .fuz name embeds its INFO FormID, so voice files are packed after the dialogue
   plugin exists, never before.
5. **Scale.** KOTOR 2 has thousands of voiced lines and dozens of areas. Plan on many sessions;
   convert one planet at a time, starting with Peragus.

## Verification so far
- Synthetic installs (`tests/fixtures.py`) exercise every exporter end to end (12 tests).
- LOOT's `esplugin` 6.1.4 parses the generated plugin: masters, light flag, header version 1.71 and
  record/group count all as expected.
- **Not verified:** the real KOTOR 2 files (column names in `baseitems.2da`, saber colour variations,
  StreamVoice layout), loading in Skyrim, and the Blender step. The catalog prints `diagnostics` so
  wrong guesses about the real 2DAs show up on the first run.
