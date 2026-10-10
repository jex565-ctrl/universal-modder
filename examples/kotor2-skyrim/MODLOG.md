# MODLOG: KOTOR 2 → Skyrim SE

## 2026-10-10: session 1 (cloud container, no games installed)
- **Ask:** KOTOR 2 maps, quests, dialogue, every weapon, the same characters with the same voice lines,
  in Skyrim with real-time combat.
- **Environment:** Linux container. No Steam, no KOTOR 2, no Skyrim, no Blender. Nothing here can be
  launched, so everything was built against synthetic installs.
- **Knowledge base:** `um kb search` found nothing for KOTOR, Odyssey or this mashup. Bethesda notes
  used: plugin record format, ESL light masters, the choosing-a-mashup-route route table.
- **Route:** asset/data conversion into Skyrim (mashup pattern 1). Reasons in PLAN.md.

### Decisions
- **KOTOR formats via PyKotor 2.3.12** (LGPL, from PyPI) instead of new readers: it is used on real game
  files and can write synthetic installs (`create_installation`), which made the tests possible.
- **Skyrim plugins written by our own code** (`k2s/esp.py`), with layouts read from xEdit's
  `Core/wbDefinitionsTES5.pas` (dev-4.1.6, fetched from raw.githubusercontent.com):
  - WEAP DNAM is 100 bytes: anim type @0, speed @4, reach @8, flags @12 (0x1 = ignores normal weapon
    resistance), skill @76, resist @88, stagger @96.
  - CRDT is 24 bytes on SSE, with the effect FormID @16.
  - AMMO DATA on SSE: projectile, flags (0x4 = "Non-Bolt", i.e. an arrow), damage, value, weight.
  - ARMO uses BOD2 (slots, armour type) or LE-era BODT (slots, flags, 3 unused, type); DNAM = rating × 100.
- **No hard-coded vanilla FormIDs.** Templates are found by EditorID, or by structure (anim type 9 =
  crossbow, AMMO without the Non-Bolt flag), in the user's own Skyrim.esm, Update.esm and Dawnguard.esm.
  FormIDs are remapped from each master's own master list into ours, and later masters override earlier
  ones.
- **Blasters use the crossbow archetype** with a new AMMO, "Power Cell", that borrows the vanilla bolt's
  projectile for now.
- **Robes are light armour** (rating 12-30), not clothing, so robed Jedi builds are viable.

### Verified
- 12 pytest tests on synthetic installs: catalog, property decoding, dialogue, characters, voice (ffmpeg
  to 44.1 kHz mono), map layout units and rotation, model export transforms, stats, the arsenal plugin and
  `--use-meshes`.
- LOOT's esplugin 6.1.4 (Rust, built in scratch) parses the arsenal plugin and the synthetic masters:
  masters, light flag, version 1.71, record count.

### Not verified / guesses to check on the first real run
- `baseitems.2da` column names (numdice, dietoroll, critthreat, crithitmult, equipableslots,
  rangedweapon, baseac, defaultmodel). The catalog records missing ones under `diagnostics`.
- Saber colour by ModelVariation (1 blue, 2 red, 3 green, 4 yellow, 5 violet, as KOTOR's g_w_lghtsbr01-05).
  Higher variations are marked "guess".
- Vanilla template EditorIDs (SteelSword, DLC1Crossbow, ArmorLeatherCuirass...). Structural fallbacks
  exist; `arsenal.json` lists which templates were used.
- KOTOR → Skyrim facing (`rz = pi/2 - bearing`).
- Blender + PyNifly export (`blender/obj_to_nif.py`).

### Next step
On the user's PC:
1. Run `um scan` for both games, then `k2s catalog` and read its diagnostics.
2. Run `k2s arsenal`, load the plugin in an MO2 profile on a throwaway save, spawn the footlocker, and
   test one saber and one blaster against a bandit.
3. Screenshot the result, then start phase 2 (meshes).
