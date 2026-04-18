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


# ---------- DAZ Genesis 8 ----------
# DAZ splits each lip into Inner+Outer (finer than XPS) and eyelid into
# Upper/Lower × Inner/Outer/base. Slots map to the full set; weights sum
# and clamp to 1.0 so overlapping subgroups produce full-coverage blend.
DAZ_G8_MAP = {
    'lip.upper.L': ['lLipUpperInner', 'lLipUpperOuter'],
    'lip.upper.M': ['LipUpperMiddle'],
    'lip.upper.R': ['rLipUpperInner', 'rLipUpperOuter'],
    'lip.lower.L': ['lLipLowerInner', 'lLipLowerOuter'],
    'lip.lower.M': ['LipLowerMiddle'],
    'lip.lower.R': ['rLipLowerInner', 'rLipLowerOuter'],
    'lip.corner.L': ['lLipCorner'],
    'lip.corner.R': ['rLipCorner'],
    'eyelid.upper.L': ['lEyelidUpper', 'lEyelidUpperInner', 'lEyelidUpperOuter'],
    'eyelid.upper.R': ['rEyelidUpper', 'rEyelidUpperInner', 'rEyelidUpperOuter'],
    'eyelid.lower.L': ['lEyelidLower', 'lEyelidLowerInner', 'lEyelidLowerOuter'],
    'eyelid.lower.R': ['rEyelidLower', 'rEyelidLowerInner', 'rEyelidLowerOuter'],
    'brow.inner.L': ['lBrowInner'],
    'brow.mid.L':   ['lBrowMid'],
    'brow.outer.L': ['lBrowOuter'],
    'brow.inner.R': ['rBrowInner'],
    'brow.mid.R':   ['rBrowMid'],
    'brow.outer.R': ['rBrowOuter'],
    'jaw': ['lowerJaw'],
    'cheek.L': ['lCheekUpper', 'lCheekLower'],
    'cheek.R': ['rCheekUpper', 'rCheekLower'],
    '_eye_bone_vgs': ['lEye', 'rEye', '目.L', '目.R'],
}


# Rig registry. Add new rig: put map above + register here + add signature
# to detect_rig() in morph_transfer_poc.py.
RIG_MAPS = {
    'xps_inase': XPS_INASE_MAP,
    'daz_g8':    DAZ_G8_MAP,
}
