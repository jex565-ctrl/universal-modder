"""KOTOR 2's d20 numbers → Skyrim's real-time numbers.

KOTOR resolves combat in rounds: an attack roll against defence, then dice (a lightsaber is 2d8 energy)
plus item properties. Skyrim swings in real time: damage per hit, swing speed, reach, and an armour
rating that reduces damage. Copying KOTOR's dice into Skyrim would make every weapon feel the same, so each
KOTOR weapon gets a *power score* (average dice + average bonus damage + half the attack bonus), and the
scores are ranked within each archetype and mapped onto the vanilla Skyrim range for that archetype.
The weakest KOTOR blaster pistol lands at about iron-crossbow level and the best lightsabers just above
Daedric, so balance follows Skyrim's own curve and Skyrim's perks and smithing still apply.

All numbers are in one table (ARCHETYPES) so they can be tuned without touching code.
"""
from __future__ import annotations

from dataclasses import dataclass

# Skyrim DNAM animation types.
ANIM_ONE_HAND_SWORD, ANIM_DAGGER, ANIM_AXE, ANIM_MACE, ANIM_TWO_HAND_SWORD, ANIM_TWO_HAND_AXE = 1, 2, 3, 4, 5, 6
ANIM_BOW, ANIM_CROSSBOW = 7, 9


@dataclass(frozen=True)
class Archetype:
    template: str          # which vanilla template group skyrim.py uses for models, sounds and keywords
    anim: int
    damage: tuple[int, int]  # Skyrim damage for the weakest and the strongest KOTOR weapon of the kind
    speed: float
    reach: float
    weight: float
    ignores_resistance: bool = False
    stagger: float = 0.0


ARCHETYPES: dict[str, Archetype] = {
    # Lightsabers: a little faster than steel and just above Daedric at the top; energy ignores the
    # "normal weapon resistance" (ghosts, some Daedra).
    "lightsaber/standard": Archetype("sword", ANIM_ONE_HAND_SWORD, (12, 18), 1.15, 1.0, 3.0, True),
    "lightsaber/short": Archetype("dagger", ANIM_DAGGER, (9, 13), 1.35, 0.8, 2.0, True),
    "lightsaber/double": Archetype("greatsword", ANIM_TWO_HAND_SWORD, (19, 27), 0.95, 1.25, 6.0, True, 1.0),
    "melee/blade": Archetype("sword", ANIM_ONE_HAND_SWORD, (7, 14), 1.0, 1.0, 9.0),
    "melee/dagger": Archetype("dagger", ANIM_DAGGER, (4, 11), 1.3, 0.7, 2.5),
    "melee/blunt": Archetype("mace", ANIM_MACE, (8, 16), 0.8, 1.0, 12.0, stagger=0.75),
    "melee/staff": Archetype("greatsword", ANIM_TWO_HAND_SWORD, (14, 22), 0.85, 1.3, 14.0, stagger=1.0),
    "melee/blade2": Archetype("greatsword", ANIM_TWO_HAND_SWORD, (15, 24), 0.75, 1.3, 17.0, stagger=1.1),
    # Blasters use the crossbow: aimed, real-time projectiles with ammo ("power cells").
    "ranged/pistol": Archetype("crossbow", ANIM_CROSSBOW, (10, 17), 1.0, 1.0, 4.0),
    "ranged/rifle": Archetype("crossbow", ANIM_CROSSBOW, (15, 23), 1.0, 1.0, 10.0),
    "ranged/heavy": Archetype("crossbow", ANIM_CROSSBOW, (19, 27), 1.0, 1.0, 16.0),
}

# Armour: Skyrim armour rating for the weakest and strongest KOTOR item, armour type, weight.
ARMOR_TYPES = {"light": 0, "heavy": 1, "clothing": 2}
ARMOR: dict[str, dict] = {
    "armor/light": {"template": "cuirass_light", "rating": (20, 38), "type": "light", "slot": 0x4, "weight": 8.0},
    "armor/heavy": {"template": "cuirass_heavy", "rating": (28, 49), "type": "heavy", "slot": 0x4, "weight": 35.0},
    # Jedi robes: wearable as light armour so a robed Jedi is viable, a little under real armour.
    "robe": {"template": "cuirass_light", "rating": (12, 30), "type": "light", "slot": 0x4, "weight": 2.0},
    "head": {"template": "helmet_light", "rating": (8, 17), "type": "light", "slot": 0x1 | 0x2, "weight": 1.5},
    "hands": {"template": "gauntlets_light", "rating": (4, 12), "type": "light", "slot": 0x8, "weight": 1.0},
    # No Skyrim visuals for these yet: playable, no armature, effects come from enchantments later.
    "arms": {"template": None, "rating": (0, 0), "type": "clothing", "slot": 0x10, "weight": 1.0},
    "implant": {"template": None, "rating": (0, 0), "type": "clothing", "slot": 1 << (52 - 30), "weight": 0.1},
    "belt": {"template": None, "rating": (0, 0), "type": "clothing", "slot": 1 << (49 - 30), "weight": 0.5},
}


def archetype_key(item: dict) -> str | None:
    c = item.get("class")
    kind = item.get("kind")
    if c == "lightsaber":
        return f"lightsaber/{kind}" if f"lightsaber/{kind}" in ARCHETYPES else "lightsaber/standard"
    if c == "melee":
        if kind == "blade" and item.get("hands") == 2:
            return "melee/blade2"
        return f"melee/{kind}" if f"melee/{kind}" in ARCHETYPES else "melee/blade"
    if c == "ranged":
        return f"ranged/{kind}" if f"ranged/{kind}" in ARCHETYPES else "ranged/pistol"
    return None


def armor_key(item: dict) -> str | None:
    c = item.get("class")
    if c == "armor":
        return "armor/heavy" if item.get("armor_class", 0) >= 7 else "armor/light"
    return c if c in ARMOR else None


def weapon_power(item: dict) -> float:
    n, d = item.get("dice") or (0, 0)
    dice_avg = n * (d + 1) / 2 if n and d else 0.0
    return dice_avg + float(item.get("damage_bonus_avg", 0.0)) + 0.5 * float(item.get("attack_bonus", 0.0))


def armor_power(item: dict) -> float:
    return float(item.get("base_ac", 0)) + float(item.get("ac_bonus", 0.0)) + float(item.get("armor_class", 0)) * 0.01


def scale(value: float, lo: float, hi: float, out: tuple[float, float]) -> float:
    if hi <= lo:
        return (out[0] + out[1]) / 2
    t = min(1.0, max(0.0, (value - lo) / (hi - lo)))
    return out[0] + t * (out[1] - out[0])


def ranges(items: list[dict], key_fn, power_fn) -> dict[str, tuple[float, float]]:
    """Per archetype, the lowest and highest power score among the items."""
    out: dict[str, list[float]] = {}
    for it in items:
        k = key_fn(it)
        if k:
            out.setdefault(k, []).append(power_fn(it))
    return {k: (min(v), max(v)) for k, v in out.items()}


def gold(cost: int) -> int:
    """KOTOR credits → Skyrim septims (a KOTOR lightsaber at ~2000-8000 credits lands at 200-800 gold)."""
    return max(5, int(round(cost / 10)))


def weapon_stats(item: dict, rng: dict[str, tuple[float, float]]) -> dict:
    key = archetype_key(item)
    a = ARCHETYPES[key]
    lo, hi = rng.get(key, (0.0, 0.0))
    dmg = int(round(scale(weapon_power(item), lo, hi, a.damage)))
    crit_mult = item.get("crit_mult") or 2
    return {
        "archetype": key,
        "template": a.template,
        "anim": a.anim,
        "damage": dmg,
        "crit_damage": max(1, int(round(dmg * crit_mult / 4))),  # vanilla crits are ~half of base damage
        "speed": a.speed,
        "reach": a.reach,
        "weight": a.weight,
        "value": gold(item.get("cost", 0)),
        "ignores_resistance": a.ignores_resistance,
        "stagger": a.stagger,
    }


def armor_stats(item: dict, rng: dict[str, tuple[float, float]]) -> dict:
    key = armor_key(item)
    a = ARMOR[key]
    lo, hi = rng.get(key, (0.0, 0.0))
    return {
        "archetype": key,
        "template": a["template"],
        "rating": int(round(scale(armor_power(item), lo, hi, a["rating"]))),
        "armor_type": ARMOR_TYPES[a["type"]],
        "slot": a["slot"],
        "weight": a["weight"],
        "value": gold(item.get("cost", 0)),
    }
