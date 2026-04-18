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

    # INVERSE TPS (Sumner-style): fit src landmarks -> tpl landmarks, so we can
    # map each src vert into template space and look up the corresponding tpl offset.
    tps_fwd = tps_fit(tpl_lms, src_lms)  # kept for Jacobian calculation
    tps_inv = tps_fit(src_lms, tpl_lms)  # src -> tpl

    # Face mask in src world space
    src_lms_arr = np.asarray(src_lms)
    centroid = src_lms_arr.mean(axis=0)
    lm_spread = np.linalg.norm(src_lms_arr - centroid, axis=1).max()
    radius = lm_spread * (1.0 + face_mask_radius_factor)
    dist_to_c = np.linalg.norm(src_rest_w - centroid, axis=1)
    in_face = dist_to_c <= radius
    print(f"[transfer] face mask: {int(in_face.sum())}/{len(src_rest_w)} src verts included (R={radius:.3f})")

    # Map masked src verts into template space
    src_face_idx = np.where(in_face)[0]
    src_in_tpl = tps_apply(tps_inv, src_rest_w[src_face_idx])

    # Build KDTree on template rest positions (world)
    from mathutils import kdtree
    kd = kdtree.KDTree(len(tpl_rest_w))
    for i, p in enumerate(tpl_rest_w):
        kd.insert(Vector(p), i)
    kd.balance()

    # Compute local-Jacobian of forward TPS at each src face vert so we can
    # map the tpl offset (in tpl space) into src space correctly.
    # Approximate J via finite difference: d(warp(tpl_p))/d(tpl_p)
    # For small offsets, offset_src = J @ offset_tpl.
    def jacobian_at(params, p, eps=1e-3):
        # 3x3 Jacobian at point p in source space (of tps_fwd: tpl -> src)
        # p: template-space point
        p = np.asarray(p)
        J = np.zeros((3, 3))
        for ax in range(3):
            dp = np.zeros(3); dp[ax] = eps
            f_plus = tps_apply(params, (p + dp)[None, :])[0]
            f_minus = tps_apply(params, (p - dp)[None, :])[0]
            J[:, ax] = (f_plus - f_minus) / (2 * eps)
        return J

    k = 4
    src_offset = np.zeros_like(src_rest_w)
    for n, j in enumerate(src_face_idx):
        tpl_p = src_in_tpl[n]
        hits = kd.find_n(Vector(tpl_p), k)
        idxs = np.array([h[1] for h in hits])
        dists = np.array([h[2] for h in hits])
        w = 1.0 / (dists + 1e-6)
        w = w / w.sum()
        # IDW-blended tpl offset (in template world space)
        off_tpl = (tpl_offset_w[idxs] * w[:, None]).sum(axis=0)
        # Transform tpl offset via local forward Jacobian at tpl_p
        J = jacobian_at(tps_fwd, tpl_p)
        src_offset[j] = J @ off_tpl

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


# ---------- Path C: Surface Deform based transfer ----------

def align_template_to_source(tpl_root, tpl_lms, src_lms, use_first_n=5):
    """Apply uniform scale + translation to tpl_root so its first-N landmarks
    best-fit the source's first-N landmarks. Uses eye+nose (not mouth/chin which
    vary more across anatomies).

    tpl_root: the mmd root empty parent of template mesh/armature.
    tpl_lms, src_lms: LANDMARK_NAMES ordered lists of world coords.
    """
    t = np.asarray(tpl_lms[:use_first_n])
    s = np.asarray(src_lms[:use_first_n])
    tc = t.mean(0)
    sc = s.mean(0)
    t_spread = np.linalg.norm(t - tc, axis=1).mean()
    s_spread = np.linalg.norm(s - sc, axis=1).mean()
    scale = s_spread / t_spread
    # world: tpl_w_new = (tpl_w_old - tc) * scale + sc
    # Assumes tpl_root has identity rotation + unit scale + zero location initially.
    # For each tpl landmark (currently at world L), after scaling root by `scale` and
    # setting root.location = dL, new world L' = (L - 0) * scale + dL.
    # We want L' = (L - tc) * scale + sc, i.e. dL = sc - scale * tc.
    # If root already has a scale/location we should compose; here we assume caller
    # resets root to identity before calling.
    from mathutils import Vector
    tpl_root.scale = (float(scale), float(scale), float(scale))
    tpl_root.location = Vector((
        float(sc[0] - scale * tc[0]),
        float(sc[1] - scale * tc[1]),
        float(sc[2] - scale * tc[2]),
    ))
    bpy.context.view_layer.update()
    print(f"[align] scale={scale:.3f}  location=({tpl_root.location.x:+.3f},{tpl_root.location.y:+.3f},{tpl_root.location.z:+.3f})")
    return scale


def transfer_morph_surface_deform(
    tpl_mesh, morph_name,
    src_mesh,
    vertex_group=None,
):
    """Transfer one shape key from tpl_mesh to src_mesh via Surface Deform.

    Assumes tpl_mesh and src_mesh are already spatially aligned
    (use align_template_to_source() first).

    Returns src shape key, or None on bind failure.
    """
    # Ensure both neutral for binding
    if tpl_mesh.data.shape_keys:
        for k in tpl_mesh.data.shape_keys.key_blocks:
            if k.name != 'Basis':
                k.value = 0.0
    if src_mesh.data.shape_keys:
        for k in src_mesh.data.shape_keys.key_blocks:
            if k.name != 'Basis':
                k.value = 0.0
    bpy.context.view_layer.update()

    # Ensure src has Basis shape key
    if src_mesh.data.shape_keys is None:
        src_mesh.shape_key_add(name='Basis', from_mix=False)

    # Remove any stale SD modifier
    for m in list(src_mesh.modifiers):
        if m.name == '_morph_sd':
            src_mesh.modifiers.remove(m)

    # Add Surface Deform modifier
    sd = src_mesh.modifiers.new(name='_morph_sd', type='SURFACE_DEFORM')
    sd.target = tpl_mesh
    if vertex_group:
        sd.vertex_group = vertex_group
    # Put SD above armature in stack so armature doesn't mask it
    # (Blender evaluates modifiers top-down; armature deformation should be preserved)
    while src_mesh.modifiers[0] != sd:
        bpy.ops.object.modifier_move_up({'object': src_mesh}, modifier='_morph_sd')

    # Bind — requires src_mesh as active
    bpy.context.view_layer.objects.active = src_mesh
    src_mesh.select_set(True)
    bpy.ops.object.surfacedeform_bind(modifier='_morph_sd')

    if not sd.is_bound:
        print(f"[SD] bind FAILED for morph '{morph_name}'")
        src_mesh.modifiers.remove(sd)
        return None
    print(f"[SD] bound: tpl={tpl_mesh.name} → src={src_mesh.name}")

    # Record rest positions after bind
    rest = np.array([v.co[:] for v in src_mesh.data.vertices])

    # Activate morph on tpl
    tpl_mesh.data.shape_keys.key_blocks[morph_name].value = 1.0
    bpy.context.view_layer.update()

    # Read evaluated src mesh (SD applied)
    dep = bpy.context.evaluated_depsgraph_get()
    em = src_mesh.evaluated_get(dep).data
    deformed = np.array([v.co[:] for v in em.vertices])

    offset = deformed - rest
    mag = np.linalg.norm(offset, axis=1)
    print(f"[SD] '{morph_name}': max={mag.max()*1000:.2f}mm, verts>0.5mm={int((mag>0.0005).sum())}")

    # Write shape key on src (in local coords — rest is already local)
    kbs = src_mesh.data.shape_keys.key_blocks
    if morph_name in kbs:
        src_mesh.shape_key_remove(kbs[morph_name])
    sk = src_mesh.shape_key_add(name=morph_name, from_mix=False)
    for i, d in enumerate(deformed):
        sk.data[i].co = Vector(d)

    # Reset tpl slider + remove SD modifier
    tpl_mesh.data.shape_keys.key_blocks[morph_name].value = 0.0
    bpy.context.view_layer.update()
    src_mesh.modifiers.remove(sd)

    return sk


# ---------- Batch: bake + transfer all bone_morphs ----------

def bake_and_transfer_all(
    tpl_root, tpl_mesh, src_mesh,
    tpl_lms, src_lms,
    morph_names=None,
    face_mask_radius_factor=0.6,
):
    """Bake every bone_morph on template + transfer to source.

    morph_names: optional subset, default = all bone_morphs.
    Returns list of (name, sk) for successfully transferred morphs.
    """
    mr = tpl_root.mmd_root
    names = morph_names if morph_names else [bm.name for bm in mr.bone_morphs]
    results = []
    for n in names:
        print(f"\n=== processing '{n}' ===")
        sk_tpl = bake_bone_morph_to_shape_key(tpl_root, tpl_mesh, n)
        if sk_tpl is None:
            continue
        try:
            sk_src = transfer_morph(
                tpl_mesh, tpl_lms, n,
                src_mesh, src_lms,
                face_mask_radius_factor=face_mask_radius_factor,
            )
            results.append((n, sk_src))
        except Exception as e:
            print(f"  [transfer] FAILED for '{n}': {e}")
    return results
