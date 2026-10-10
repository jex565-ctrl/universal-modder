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

## 2026-10-10: session 2 (user's Windows PC, both games installed)
- **Versions:** Skyrim SE 1.7.104 + SKSE 2.3.1 (Steam, no MO2), KOTOR 2 Steam (Aspyr update). Python 3.12.15
  venv with PyKotor 2.3.12; all 12 tests pass here.
- **Real catalog:** 40 lightsabers, 85 crystals, 127 blasters, 76 melee, 93 armour, 25 robes, 1215 creatures,
  213 force powers, 117 quests, 82 modules, 973 conversations.
- **Fixed from the real data:**
  - baseitems row 11 is `Lightsaber_Crystals`: crystals now have their own class (were counted as sabers).
  - UTI properties with `UpgradeType != 255` only apply when that upgrade slot is filled; they are now kept
    in `upgrade_properties` and no longer summed into the item's power.
  - Saber colour is read from the blade texture in the saber's own model (`w_lsabre<code>01`: blue, red,
    gren, yelo, purp, gold=orange, turq=cyan, dgrn=viridian, silv=silver). All 40 sabers resolve.
  - Designer tags (`{x01}`) are stripped; `<FullName>` becomes "Exile".
  - `base_label` is the 2DA label, not the row number.
- **Arsenal on the real masters:** every template found by EditorID; 233 weapons, 321 armour pieces.
- **In game:** with `KotOR2_Arsenal.esp` enabled, Skyrim reached the main menu (SKSE DataLoaded fired, so the
  plugin parsed). `coc RiverwoodSleepingGiantInn` from the main menu then closed the game with no Windows
  error event. Not yet isolated: plugin vs. coc-from-menu on a fresh, never-configured install.
- **Driving Skyrim:** its console ignores unicode `type`; send each character as `key <VK>` under
  `scanmode on`. Console key is VK 0xC0.
- **Crash cause found:** my hand-written `Skyrim.ini` lacked `sResourceArchiveList` (it normally comes from
  `Skyrim_Default.ini`), so entering any cell crashed, with or without the plugin. INIs are now copies of
  `Skyrim_Default.ini` and `High.ini` plus windowed settings.
- **Arsenal verified in game (phase 1):** in Riverwood and a wilderness cell, the red lightsaber equips and
  swings in real-time combat; HK-47's rifle fires Power Cells (100 → 97 after three shots). Note: `tgm`
  also gives infinite ammo, so ammo counts only drop with it off.
- **Meshes (phase 2), no Blender needed:**
  - PyKotor 2.3.12 misreads the K2 trimesh header (MDX offsets garbage) on these files, so hilts and
    blasters had no vertices. `k2s/mdlraw.py` reads geometry directly (layout in its docstring).
  - Texture packs were added with equal priority, so the low-res `tpc` won; now `tpa` wins (hilt 64 px is
    the real maximum in TSL).
  - `k2s/bsa.py` reads SSE BSAs; `k2s/nif.py` reads/writes SSE NIFs (byte-identical round trip on the
    vanilla steel sword, greatsword, dagger and crossbow) and builds weapons on a vanilla template: root,
    BSX, `Prn` and collision kept; KOTOR hilt as BSTriShape + lighting shader, blade as BSTriShape +
    additive BSEffectShaderProperty.
  - `k2s meshes` built 61 melee meshes and 46 textures; 102 weapon records use them (`arsenal --use-meshes`).
  - **In game:** the red lightsaber shows KOTOR's hilt and a glowing red blade in first and third person.
- **Not yet:** blaster meshes (the crossbow template is skinned and animated), collision fitted to sabers
  (they use the steel sword's), dialogue, characters, maps.
- **Driving notes:** coc closes the console; `hold` doesn't reach DirectInput but `key X down`/`up` does;
  menus take relative mouse moves then `mdown`; the window is 1920x1080 logical at 150% scaling.

## 2026-10-10: session 2b: Peragus 101PER (maps, characters, dialogue)
- `k2s area --module 101per`: 66 rooms as static NIFs (k2s/nif.static), collision from the walkmesh
  (floor prisms + 3 m walls on unshared edges, convex shapes in bhkListShape chunks), interior cell
  K2_101PER, a fill light per room, COC marker at the module entry, TXI blend modes (glass additive,
  grates alpha-test). Skinned room meshes (dead miners) skipped: they show in bind pose.
- Kreia and Atton as NPC_ with vanilla traits templates (Idgrod, Brynjolf) for FaceGen. Verified in game:
  Peragus renders, Kreia stands in the morgue in a hooded robe with a Talk prompt.
- k2s/talk.py turns 101kreia.dlg into QUST/DIAL/INFO/DLBR + original voice WAVs. Records match vanilla
  layout, quest is running, GetIsID(Kreia) = 1, but **talking opens no dialogue yet** (also without
  conditions). Unresolved; next suspects: missing AI packages (PKID dropped), WAV voice, quest fields.
- Driving: console state desyncs easily; sStartingConsoleCommand did not fire in SSE. Restart per test.
- The modified KotOR2_101PER.esp in Data is the no-condition experiment; rebuild with `k2s area --install`.
