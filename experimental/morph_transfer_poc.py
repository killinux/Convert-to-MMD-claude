"""PoC: Template bone_morph -> source shape key via TPS warp.

Phase 1 goal: end-to-end single morph 'あ' from Purifier Inase 18 (template)
to Inase XPS (source). Validates non-rigid wrap pipeline end-to-end before
scaling up to 19 morphs.

Run from Blender Python console or via cli.py exec. Does NOT register as
operator yet — intentionally kept as standalone script for fast iteration.
"""

import bpy
import bmesh
import numpy as np
from mathutils import Vector, Quaternion


# ---------- Step 0: bake one bone_morph -> shape key on template mesh ----------

def bake_bone_morph_to_shape_key(mmd_root_obj, mesh_obj, morph_name):
    """Apply bone_morph pose, read evaluated mesh, write delta as shape key.

    Returns: created shape key block, or None if morph not found.
    """
    mr = mmd_root_obj.mmd_root
    bm = mr.bone_morphs.get(morph_name)
    if bm is None:
        print(f"[bake] morph '{morph_name}' not found")
        return None

    # Find armature under this mmd_root
    arm = None
    for child in mmd_root_obj.children_recursive:
        if child.type == 'ARMATURE' and not child.name.startswith('.'):
            arm = child
            break
    if arm is None:
        print("[bake] no armature found under mmd_root")
        return None

    # Must be visible for depsgraph to evaluate pose
    arm_hidden = arm.hide_viewport
    mesh_hidden = mesh_obj.hide_viewport
    arm.hide_viewport = False
    mesh_obj.hide_viewport = False

    # Save current pose
    saved = {}
    for pb in arm.pose.bones:
        saved[pb.name] = (
            pb.location.copy(),
            pb.rotation_quaternion.copy(),
            pb.rotation_mode,
        )
        pb.rotation_mode = 'QUATERNION'

    # Apply morph offsets
    applied = 0
    for d in bm.data:
        pb = arm.pose.bones.get(d.bone)
        if pb is None:
            print(f"[bake] bone '{d.bone}' not in armature — skipped")
            continue
        pb.location = Vector(d.location)
        pb.rotation_quaternion = Quaternion(d.rotation)
        applied += 1
    print(f"[bake] '{morph_name}': applied {applied}/{len(bm.data)} bone offsets")

    # Force depsgraph update
    bpy.context.view_layer.update()
    dep = bpy.context.evaluated_depsgraph_get()
    eval_mesh = mesh_obj.evaluated_get(dep).data

    # Read rest (basis) vs deformed positions
    # Ensure basis shape key exists
    if mesh_obj.data.shape_keys is None:
        mesh_obj.shape_key_add(name='Basis', from_mix=False)
    rest = np.array([v.co[:] for v in mesh_obj.data.vertices])
    deformed = np.array([v.co[:] for v in eval_mesh.vertices])

    # Create / overwrite shape key
    key_blocks = mesh_obj.data.shape_keys.key_blocks
    if morph_name in key_blocks:
        # remove old
        mesh_obj.shape_key_remove(key_blocks[morph_name])
    sk = mesh_obj.shape_key_add(name=morph_name, from_mix=False)
    for i, d in enumerate(deformed):
        sk.data[i].co = Vector(d)
    # verify non-zero offset
    delta = deformed - rest
    max_mag = np.linalg.norm(delta, axis=1).max()
    n_moved = int((np.linalg.norm(delta, axis=1) > 1e-5).sum())
    print(f"[bake] '{morph_name}': max offset = {max_mag*1000:.2f}mm, {n_moved} verts moved")

    # Restore pose
    for pb in arm.pose.bones:
        loc, quat, mode = saved[pb.name]
        pb.location = loc
        pb.rotation_quaternion = quat
        pb.rotation_mode = mode
    bpy.context.view_layer.update()

    arm.hide_viewport = arm_hidden
    mesh_obj.hide_viewport = mesh_hidden

    return sk


# ---------- Step 1: TPS fit / apply (biharmonic 3D) ----------

def tps_fit(src_pts, dst_pts):
    """Fit biharmonic TPS from src_pts -> dst_pts in 3D.

    Returns dict with keys: src, W, A (affine). Use tps_apply() to evaluate.
    """
    src = np.asarray(src_pts, dtype=np.float64)
    dst = np.asarray(dst_pts, dtype=np.float64)
    N = len(src)
    # Kernel: phi(r) = r (biharmonic in 3D)
    K = np.linalg.norm(src[:, None, :] - src[None, :, :], axis=-1)
    P = np.hstack([np.ones((N, 1)), src])  # (N, 4)
    # Assemble (N+4) x (N+4) linear system
    L = np.zeros((N + 4, N + 4))
    L[:N, :N] = K
    L[:N, N:] = P
    L[N:, :N] = P.T
    Y = np.zeros((N + 4, 3))
    Y[:N] = dst
    # Add small regularization for numerical stability
    L[:N, :N] += np.eye(N) * 1e-8
    coef = np.linalg.solve(L, Y)
    return {"src": src, "W": coef[:N], "A": coef[N:]}


def tps_apply(params, query):
    """Evaluate TPS at query points (M, 3). Returns (M, 3)."""
    q = np.asarray(query, dtype=np.float64)
    K = np.linalg.norm(q[:, None, :] - params["src"][None, :, :], axis=-1)
    P = np.hstack([np.ones((q.shape[0], 1)), q])
    return K @ params["W"] + P @ params["A"]


# ---------- Step 2-4: transfer offset via deformed-template + barycentric ----------

def transfer_morph(
    tpl_mesh, tpl_lms, morph_name,
    src_mesh, src_lms,
    face_mask_radius_factor=0.6,
):
    """Transfer one shape key from tpl_mesh to src_mesh via TPS + nearest triangle.

    tpl_lms / src_lms: (N, 3) landmark world coords (N matched pairs).
    Returns: source shape key block.
    """
    key_blocks = tpl_mesh.data.shape_keys.key_blocks
    if morph_name not in key_blocks:
        raise RuntimeError(f"template has no shape key '{morph_name}' — run bake first")

    # Read template rest + morph positions (object local)
    tpl_rest = np.array([v.co[:] for v in tpl_mesh.data.vertices])
    tpl_morph = np.array([key_blocks[morph_name].data[i].co[:] for i in range(len(tpl_mesh.data.vertices))])
    tpl_offset = tpl_morph - tpl_rest  # (Nt, 3), per-vert offset in template local

    # Convert to world
    Mtpl = np.array(tpl_mesh.matrix_world)
    tpl_rest_w = (tpl_rest @ Mtpl[:3, :3].T) + Mtpl[:3, 3]
    # Offset transforms as direction — rotation/scale only
    tpl_offset_w = tpl_offset @ Mtpl[:3, :3].T

    Msrc = np.array(src_mesh.matrix_world)
    src_rest = np.array([v.co[:] for v in src_mesh.data.vertices])
    src_rest_w = (src_rest @ Msrc[:3, :3].T) + Msrc[:3, 3]

    # Fit TPS: template space -> source space (landmark-driven warp)
    tps = tps_fit(tpl_lms, src_lms)

    # Warp template verts to source space
    tpl_warped_w = tps_apply(tps, tpl_rest_w)

    # Also warp template-morph verts -> source space (so offsets reflect warp Jacobian implicitly)
    tpl_morph_w = tpl_rest_w + tpl_offset_w
    tpl_morph_warped_w = tps_apply(tps, tpl_morph_w)
    tpl_offset_warped = tpl_morph_warped_w - tpl_warped_w  # (Nt, 3) offset in source space

    # Face mask: keep only source verts near landmark centroid
    src_lms_arr = np.asarray(src_lms)
    centroid = src_lms_arr.mean(axis=0)
    # Radius = max landmark distance to centroid * factor
    lm_spread = np.linalg.norm(src_lms_arr - centroid, axis=1).max()
    radius = lm_spread * (1.0 + face_mask_radius_factor)
    dist_to_c = np.linalg.norm(src_rest_w - centroid, axis=1)
    in_face = dist_to_c <= radius
    print(f"[transfer] face mask: {int(in_face.sum())}/{len(src_rest_w)} src verts included (R={radius:.3f})")

    # For each src vert in face region, find nearest k warped template verts, IDW offset
    # Simple KDTree via bmesh or just numpy (template has 169k verts — brute force too slow)
    # Use Blender's KDTree
    from mathutils import kdtree
    kd = kdtree.KDTree(len(tpl_warped_w))
    for i, p in enumerate(tpl_warped_w):
        kd.insert(Vector(p), i)
    kd.balance()

    k = 4
    src_offset = np.zeros_like(src_rest_w)
    for j in np.where(in_face)[0]:
        hits = kd.find_n(Vector(src_rest_w[j]), k)
        # hits: list of (co, index, dist)
        idxs = np.array([h[1] for h in hits])
        dists = np.array([h[2] for h in hits])
        # Inverse distance weights (eps to avoid div0)
        w = 1.0 / (dists + 1e-6)
        w = w / w.sum()
        src_offset[j] = (tpl_offset_warped[idxs] * w[:, None]).sum(axis=0)

    # Transform source offset from world back to src local
    src_offset_local = src_offset @ np.linalg.inv(Msrc[:3, :3]).T

    # Write shape key
    if src_mesh.data.shape_keys is None:
        src_mesh.shape_key_add(name='Basis', from_mix=False)
    kbs = src_mesh.data.shape_keys.key_blocks
    if morph_name in kbs:
        src_mesh.shape_key_remove(kbs[morph_name])
    sk = src_mesh.shape_key_add(name=morph_name, from_mix=False)
    new_co = src_rest + src_offset_local
    for i, c in enumerate(new_co):
        sk.data[i].co = Vector(c)

    mag = np.linalg.norm(src_offset_local, axis=1)
    n_moved = int((mag > 1e-5).sum())
    print(f"[transfer] '{morph_name}': max={mag.max()*1000:.2f}mm, {n_moved} verts moved")
    return sk


# ---------- Step 5: landmark empty scaffolding ----------

LANDMARK_NAMES = [
    "lm_eye_outer_L",
    "lm_eye_outer_R",
    "lm_eye_inner_L",
    "lm_eye_inner_R",
    "lm_nose_tip",
    "lm_mouth_corner_L",
    "lm_mouth_corner_R",
    "lm_lip_upper",
    "lm_chin",
]


def create_landmarks(prefix, approx_positions=None, size=0.02):
    """Create N pre-named empties under a parent 'LM_<prefix>'.

    prefix: e.g. 'TPL' or 'SRC'.
    approx_positions: optional dict {name: (x,y,z)} for starting coords.
    """
    parent_name = f"LM_{prefix}"
    if parent_name in bpy.data.objects:
        return bpy.data.objects[parent_name]
    parent = bpy.data.objects.new(parent_name, None)
    bpy.context.scene.collection.objects.link(parent)
    parent.empty_display_type = 'PLAIN_AXES'
    parent.empty_display_size = 0.05

    for name in LANDMARK_NAMES:
        full = f"{prefix}_{name}"
        e = bpy.data.objects.new(full, None)
        bpy.context.scene.collection.objects.link(e)
        e.parent = parent
        e.empty_display_type = 'SPHERE'
        e.empty_display_size = size
        if approx_positions and name in approx_positions:
            e.location = approx_positions[name]
    return parent


def read_landmarks(prefix):
    """Read world coords of the N landmarks in canonical order."""
    pts = []
    for name in LANDMARK_NAMES:
        full = f"{prefix}_{name}"
        o = bpy.data.objects.get(full)
        if o is None:
            raise RuntimeError(f"missing landmark '{full}'")
        pts.append(tuple(o.matrix_world.translation))
    return pts
