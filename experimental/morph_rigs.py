"""Rig adapter maps for Path D morph synthesis.

Each rig (XPS Inase, DAZ Genesis 8, future Mixamo/VRoid/…) provides a
`slot → list[vg_name]` dict. Recipe code in morph_transfer_poc.py reads
slots; this file resolves slots to actual vertex group names.

Adding a new rig: copy an existing map, translate vg names, add entry
to RIG_MAPS + detection rule to detect_rig() in morph_transfer_poc.py.

Slot naming convention:
  - lip.{upper,lower}.{L,M,R}   — L/R/mid segments, M is the single
    'middle' bone that XPS has; DAZ uses LipUpperMiddle/LipLowerMiddle.
  - lip.corner.{L,R}            — single bone per side.
  - eyelid.{upper,lower}.{L,R}  — DAZ may have multiple sub-bones per
    slot (Upper + UpperInner + UpperOuter); list all of them.
  - brow.{inner,mid,outer}.{L,R} — 3 segments × 2 sides.
  - jaw                          — single, no L/R.
  - cheek.{L,R}                  — optional, not used in POC recipes.

Special keys (underscore prefix):
  - `_eye_bone_vgs`: list of vg names that identify an eyeball mesh
    (used by find_meshes_by_role for mesh role detection).
"""


# All valid slot identifiers. Used by _expand_slot_pattern for wildcards.
# Keep in sync with RIG_MAPS keys and UNIVERSAL_RECIPES slot references.
ALL_SLOTS = frozenset([
    # Lip
    'lip.upper.L', 'lip.upper.M', 'lip.upper.R',
    'lip.lower.L', 'lip.lower.M', 'lip.lower.R',
    'lip.corner.L', 'lip.corner.R',
    # Eyelid
    'eyelid.upper.L', 'eyelid.upper.R',
    'eyelid.lower.L', 'eyelid.lower.R',
    # Brow
    'brow.inner.L', 'brow.inner.R',
    'brow.mid.L',   'brow.mid.R',
    'brow.outer.L', 'brow.outer.R',
    # Structural
    'jaw',
    'cheek.L', 'cheek.R',
])


# ---------- XPS XNA Lara (Inase-compatible) ----------
# VG names: `head {part} {side} {n}` pattern. Eyebrow has 3 segments
# numbered 1/2/3 (inner/mid/outer). No cheek subdivision — just
# `head cheek {side} 1`. Eyeball identified by renamed `目.L/R` post
# step-1 or raw `head eyeball left/right` pre-step-1.
XPS_INASE_MAP = {
    'lip.upper.L': ['head lip upper left'],
    'lip.upper.M': ['head lip upper middle'],
    'lip.upper.R': ['head lip upper right'],
    'lip.lower.L': ['head lip lower left'],
    'lip.lower.M': ['head lip lower middle'],
    'lip.lower.R': ['head lip lower right'],
    'lip.corner.L': ['head mouth corner left'],
    'lip.corner.R': ['head mouth corner right'],
    'eyelid.upper.L': ['head eyelid upper left'],
    'eyelid.upper.R': ['head eyelid upper right'],
    'eyelid.lower.L': ['head eyelid lower left'],
    'eyelid.lower.R': ['head eyelid lower right'],
    'brow.inner.L': ['head eyebrow left 1'],
    'brow.mid.L':   ['head eyebrow left 2'],
    'brow.outer.L': ['head eyebrow left 3'],
    'brow.inner.R': ['head eyebrow right 1'],
    'brow.mid.R':   ['head eyebrow right 2'],
    'brow.outer.R': ['head eyebrow right 3'],
    'jaw': ['head jaw'],
    'cheek.L': ['head cheek left 1'],
    'cheek.R': ['head cheek right 1'],
    '_eye_bone_vgs': ['head eyeball left', 'head eyeball right', '目.L', '目.R'],
}


# Rig registry. Future DAZ_G8_MAP / MIXAMO_MAP / VROID_MAP slot here.
RIG_MAPS = {
    'xps_inase': XPS_INASE_MAP,
}
