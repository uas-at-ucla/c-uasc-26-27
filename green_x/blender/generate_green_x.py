"""Render synthetic green X targets and look-alike negatives with Blender.

Run with Blender, not normal Python, from the repo root:
  /Applications/Blender.app/Contents/MacOS/Blender -b \
      --python green_x/blender/generate_green_x.py -- \
      --samples 20 --out ../data/blender_v2_smoke

Writes <out>/dataset/images/ and <out>/dataset/labels.csv (label format v2),
plus <out>/generation.json with the exact settings used.

Pixel convention: pixel centers are at integer coordinates. The top-left
pixel center is (0, 0), and the image spans -0.5 .. width - 0.5.

Scene types (column scene_type):
  x            white board with green X: the target (target_present=1)
  plus         white board with green + (negative)
  plain        white board with no markings (negative)
  other_color  white board with a non-green X (negative)
  absent       no board (negative)
"""
import argparse
import csv
import json
import math
import random
import sys
from pathlib import Path

import bpy
from mathutils import Vector, Quaternion
from bpy_extras.object_utils import world_to_camera_view

sys.path.insert(0, str(Path(__file__).resolve().parent))
from geometry import shapes, prism


SCENE_TYPES = ('x', 'plus', 'plain', 'other_color', 'absent')
BOARD_TOP_Z = 0.013
CENTER_Z = 0.0154          # top of the X strokes, where the label point sits
BUCKET_DEPTH = 0.165       # estimate: 15-18 cm tall
BUCKET_R_BOTTOM = 0.09     # estimate: 18-20 cm across
BUCKET_R_TOP = 0.10

GROUND_COLORS = {
    'concrete': (0.45, 0.44, 0.41),
    'dry_soil': (0.52, 0.40, 0.27),
    'dry_grass': (0.42, 0.47, 0.25),
    'asphalt': (0.28, 0.29, 0.27),
}
BUCKET_COLORS = {
    'blue': (0.20, 0.23, 0.75),
    'orange': (0.90, 0.35, 0.05),
    'grey': (0.50, 0.50, 0.50),
    'black': (0.05, 0.05, 0.05),
    'white': (0.85, 0.85, 0.85),
}
OTHER_X_COLORS = {
    'red': (0.60, 0.04, 0.04),
    'blue': (0.04, 0.10, 0.60),
    'black': (0.03, 0.03, 0.03),
    'orange': (0.85, 0.30, 0.02),
}

FIELDS = [
    'filename', 'source', 'session_id', 'scene_type', 'width', 'height',
    'target_present', 'x', 'y', 'occluded', 'truncated',
    'bbox_xmin', 'bbox_ymin', 'bbox_xmax', 'bbox_ymax',
    # Metadata for failure analysis.
    'altitude_m', 'tilt_deg', 'ground', 'sun_energy', 'exposure',
    'bucket_visible', 'bucket_color', 'x_color', 'clutter_count', 'seed',
]


def parse_mix(text):
    mix = {}
    for part in text.split(','):
        name, weight = part.split('=')
        name = name.strip()
        if name not in SCENE_TYPES:
            raise ValueError(f'unknown scene type {name!r}; use {SCENE_TYPES}')
        mix[name] = float(weight)
    if min(mix.values()) < 0 or sum(mix.values()) <= 0:
        raise ValueError('scene mix weights must be >= 0 with a positive sum')
    return mix


def args_parse():
    tail = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
    p = argparse.ArgumentParser()
    p.add_argument('--out', default='output')
    p.add_argument('--samples', type=int, default=250)
    p.add_argument('--width', type=int, default=2560)
    p.add_argument('--height', type=int, default=1440)
    p.add_argument('--hfov-deg', type=float, default=71.5,
                   help='horizontal field of view; ZR10 at 1x zoom')
    p.add_argument('--alt-min', type=float, default=8.0)
    p.add_argument('--alt-max', type=float, default=40.0)
    p.add_argument('--max-tilt-deg', type=float, default=30.0,
                   help='maximum camera tilt away from straight down')
    p.add_argument('--margin-px', type=float, default=20.0,
                   help='minimum distance from the board center to the image edge')
    p.add_argument('--span-m', type=float, default=5.0)
    p.add_argument('--size-mode', choices=['side', 'diagonal'], default='diagonal')
    p.add_argument('--stroke-width-m', type=float, default=0.06)
    p.add_argument('--scene-mix',
                   default='x=0.5,plus=0.125,plain=0.125,other_color=0.125,absent=0.125')
    p.add_argument('--occlusion-prob', type=float, default=0.30)
    p.add_argument('--no-occlusion', action='store_true',
                   help='same as --occlusion-prob 0')
    p.add_argument('--clutter-prob', type=float, default=0.5)
    p.add_argument('--clutter-max', type=int, default=3)
    p.add_argument('--format', choices=['jpg', 'png'], default='jpg')
    p.add_argument('--jpeg-quality', type=int, default=90)
    p.add_argument('--seed', type=int, default=7)
    p.add_argument('--session-id', default=None)
    cfg = p.parse_args(tail)
    if cfg.no_occlusion:
        cfg.occlusion_prob = 0.0
    if cfg.session_id is None:
        cfg.session_id = f'blender_seed{cfg.seed}'
    if not 0 < cfg.alt_min <= cfg.alt_max:
        raise ValueError('need 0 < alt-min <= alt-max')
    cfg.mix = parse_mix(cfg.scene_mix)
    return cfg


def material(name, rgb, roughness=0.85):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    set_color(m, rgb)
    bsdf = m.node_tree.nodes.get('Principled BSDF')
    if bsdf:
        bsdf.inputs['Roughness'].default_value = roughness
    return m


def set_color(mat, rgb):
    mat.diffuse_color = (*rgb, 1)
    bsdf = mat.node_tree.nodes.get('Principled BSDF')
    if bsdf:
        bsdf.inputs['Base Color'].default_value = (*rgb, 1)


def make_mesh(name, poly, z0, z1, mat):
    verts, faces = prism(poly, z0, z1)
    me = bpy.data.meshes.new(name)
    me.from_pydata(verts, [], faces)
    me.update()
    obj = bpy.data.objects.new(name, me)
    bpy.context.collection.objects.link(obj)
    obj.data.materials.append(mat)
    return obj


def show(objs, visible):
    for obj in objs:
        obj.hide_render = not visible


def look_at(camera, point, roll=0.0):
    camera.rotation_mode = 'QUATERNION'
    quat = (Vector(point) - camera.location).to_track_quat('-Z', 'Y')
    camera.rotation_quaternion = quat @ Quaternion((0, 0, 1), roll)


def project(scene, cam, point, width, height):
    """World point -> (x, y, depth) in pixel-center image coordinates."""
    p = world_to_camera_view(scene, cam, Vector(point))
    return p.x * width - 0.5, (1.0 - p.y) * height - 0.5, p.z


def inside(x, y, width, height, margin=0.0):
    return (-0.5 + margin <= x <= width - 0.5 - margin and
            -0.5 + margin <= y <= height - 0.5 - margin)


def place_camera(cam, rng, cfg, aim_origin=False):
    """Random altitude, tilt, heading and roll, aimed near the board."""
    h = rng.uniform(cfg.alt_min, cfg.alt_max)
    tilt = math.radians(rng.uniform(0.0, cfg.max_tilt_deg))
    heading = rng.uniform(-math.pi, math.pi)
    roll = rng.uniform(-math.pi, math.pi)
    if aim_origin:
        tilt, aim = 0.0, (0.0, 0.0, 0.0)
    else:
        reach = 0.45 * h * math.tan(math.radians(cfg.hfov_deg) / 2)
        aim = (rng.uniform(-reach, reach), rng.uniform(-reach, reach), 0.0)
    d = h * math.tan(tilt)
    cam.location = (aim[0] - d * math.cos(heading),
                    aim[1] - d * math.sin(heading), h)
    look_at(cam, aim, roll)
    return h, math.degrees(tilt)


def main():
    cfg = args_parse()
    rng = random.Random(cfg.seed)
    W, H = cfg.width, cfg.height
    out = Path(cfg.out).expanduser().resolve()
    model_dir = out / 'model'
    images = out / 'dataset' / 'images'
    model_dir.mkdir(parents=True, exist_ok=True)
    images.mkdir(parents=True, exist_ok=True)

    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=False)

    x_mesh = shapes(cfg.span_m, cfg.size_mode, cfg.stroke_width_m, pattern='x')
    plus_mesh = shapes(cfg.span_m, cfg.size_mode, cfg.stroke_width_m, pattern='plus')
    side = x_mesh['side_m']

    white = material('Mat_White_Fabric', (0.92, 0.91, 0.87))
    green = material('Mat_Green_X', (0.025, 0.50, 0.10))
    other_x = material('Mat_Other_X', OTHER_X_COLORS['red'])
    clutter_mat = material('Mat_White_Clutter', (0.88, 0.88, 0.86))
    bucket_mat = material('Mat_Bucket', BUCKET_COLORS['blue'], roughness=0.5)
    ground_mats = {name: material(f'Mat_{name}', rgb)
                   for name, rgb in GROUND_COLORS.items()}

    board = make_mesh('White_Target_Board', x_mesh['square'], 0.003, BOARD_TOP_Z, white)
    x_strokes = [
        make_mesh('Green_Diagonal_A', x_mesh['strokes'][0], 0.0132, 0.0143, green),
        make_mesh('Green_Diagonal_B', x_mesh['strokes'][1], 0.0143, CENTER_Z, green),
    ]
    plus_strokes = [
        make_mesh('Green_Plus_A', plus_mesh['strokes'][0], 0.0132, 0.0143, green),
        make_mesh('Green_Plus_B', plus_mesh['strokes'][1], 0.0143, CENTER_Z, green),
    ]
    board_corners = [(px, py, BOARD_TOP_Z) for px, py in x_mesh['square']]

    unit_square = [(-0.5, -0.5), (0.5, -0.5), (0.5, 0.5), (-0.5, 0.5)]
    clutter = [make_mesh(f'Clutter_{k}', unit_square, 0.002, 0.008, clutter_mat)
               for k in range(cfg.clutter_max)]

    # Ground is a separate mesh, excluded from the target OBJ export.
    bpy.ops.mesh.primitive_cube_add(size=1, location=(0, 0, -0.035))
    ground = bpy.context.object
    ground.name = 'Environment_Ground'
    ground.dimensions = (400, 400, 0.06)  # large enough for 40 m altitude at 30 deg tilt
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    ground.data.materials.append(ground_mats['concrete'])

    # Approximate package: bucket plus handle. Dimensions are estimates.
    bpy.ops.mesh.primitive_cone_add(vertices=40, radius1=BUCKET_R_BOTTOM,
                                    radius2=BUCKET_R_TOP, depth=BUCKET_DEPTH,
                                    location=(0, 0, 0))
    bucket = bpy.context.object
    bucket.name = 'Package_Bucket'
    bucket.data.materials.append(bucket_mat)
    bpy.ops.mesh.primitive_torus_add(major_radius=BUCKET_R_TOP, minor_radius=0.005,
                                     location=(0, 0, 0), rotation=(math.pi / 2, 0, 0))
    handle = bpy.context.object
    handle.name = 'Package_Bucket_Handle'
    handle.data.materials.append(bucket_mat)
    handle.parent = bucket
    handle.location = (0, 0, BUCKET_DEPTH / 2)   # ring centered on the rim
    package = [bucket, handle]

    bpy.ops.object.camera_add(location=(0, 0, 20))
    cam = bpy.context.object
    cam.name = 'ZR10_Camera'
    cam.data.type = 'PERSP'
    cam.data.sensor_fit = 'HORIZONTAL'
    cam.data.sensor_width = 36
    cam.data.lens = 18 / math.tan(math.radians(cfg.hfov_deg) / 2)
    scene = bpy.context.scene
    scene.camera = cam

    bpy.ops.object.light_add(type='SUN', location=(0, 0, 20))
    sun = bpy.context.object
    sun.name = 'Sun'
    sun.data.angle = 0.08
    world = bpy.data.worlds.new('Daylight') if scene.world is None else scene.world
    scene.world = world
    world.use_nodes = True
    bg = world.node_tree.nodes.get('Background')
    if bg:
        bg.inputs['Color'].default_value = (0.7, 0.78, 0.9, 1)
        bg.inputs['Strength'].default_value = 0.7

    scene.render.resolution_x = W
    scene.render.resolution_y = H
    scene.render.resolution_percentage = 100
    scene.render.pixel_aspect_x = 1
    scene.render.pixel_aspect_y = 1
    scene.render.film_transparent = False
    settings = scene.render.image_settings
    if cfg.format == 'jpg':
        settings.file_format = 'JPEG'
        settings.quality = cfg.jpeg_quality
    else:
        settings.file_format = 'PNG'
    settings.color_mode = 'RGB'
    scene.view_settings.view_transform = 'Standard'
    try:
        scene.render.engine = 'BLENDER_EEVEE_NEXT'
    except Exception:
        scene.render.engine = 'BLENDER_EEVEE'
    try:
        scene.eevee.taa_render_samples = 32
    except AttributeError:
        pass

    # Export only the dimensioned X target; not camera, lights, ground or clutter.
    bpy.ops.object.select_all(action='DESELECT')
    for item in [board] + x_strokes:
        item.select_set(True)
    bpy.context.view_layer.objects.active = board
    try:
        bpy.ops.wm.obj_export(filepath=str(model_dir / 'green_x.obj'),
                              export_selected_objects=True)
    except (AttributeError, TypeError, RuntimeError):
        try:
            bpy.ops.export_scene.obj(filepath=str(model_dir / 'green_x.obj'),
                                     use_selection=True)
        except Exception as e:
            print('OBJ export failed; use prebuilt OBJ instead:', e)
    bpy.ops.object.select_all(action='DESELECT')
    bpy.ops.wm.save_as_mainfile(filepath=str(model_dir / 'green_x.blend'))
    spec = {
        'source': 'C-UASC 2026 official rules, page 13 (Rev 3, Feb 23 2026)',
        'official': 'Target approximately 5 meters in diameter, white with green X. '
                    'Exact square side and stripe width not specified.',
        'span_m': cfg.span_m, 'size_mode': cfg.size_mode, 'square_side_m': side,
        'stroke_width_m_assumed': cfg.stroke_width_m,
        'target_center_world_m': [0, 0, CENTER_Z],
        'warning': 'Model dimensions beyond ~5m overall size are simulation '
                   'assumptions, not competition-certified.',
    }
    (model_dir / 'spec.json').write_text(json.dumps(spec, indent=2))
    generation = {k: v for k, v in vars(cfg).items() if k != 'mix'}
    generation['blender_version'] = bpy.app.version_string
    generation['camera_lens_mm'] = cam.data.lens
    (out / 'generation.json').write_text(json.dumps(generation, indent=2))

    names = list(cfg.mix)
    weights = [cfg.mix[n] for n in names]
    ext = 'jpg' if cfg.format == 'jpg' else 'png'
    rows = []

    for i in range(cfg.samples):
        scene_type = rng.choices(names, weights)[0]
        has_board = scene_type != 'absent'

        # Board and markings.
        show([board], has_board)
        show(x_strokes, scene_type in ('x', 'other_color'))
        show(plus_strokes, scene_type == 'plus')
        x_color = ''
        if scene_type == 'other_color':
            x_color = rng.choice(list(OTHER_X_COLORS))
            set_color(other_x, OTHER_X_COLORS[x_color])
        for obj in x_strokes:
            obj.data.materials[0] = other_x if scene_type == 'other_color' else green

        # Lighting and ground.
        ground_name = rng.choice(list(GROUND_COLORS))
        ground.data.materials[0] = ground_mats[ground_name]
        sun.rotation_euler = (rng.uniform(0.2, 0.9), rng.uniform(-1, 1),
                              rng.uniform(-math.pi, math.pi))
        sun.data.energy = rng.uniform(1.3, 3.3)
        exposure = rng.uniform(-0.35, 0.35)
        scene.view_settings.exposure = exposure

        # Package. On a board it sits on the center, for negatives too, so the
        # bucket itself is not a shortcut cue for "target present".
        bucket_visible = rng.random() < cfg.occlusion_prob
        bucket_color = ''
        if bucket_visible:
            bucket_color = rng.choice(list(BUCKET_COLORS))
            set_color(bucket_mat, BUCKET_COLORS[bucket_color])
            if has_board:
                bx, by = rng.uniform(-0.05, 0.05), rng.uniform(-0.05, 0.05)
            else:
                bx, by = rng.uniform(-5, 5), rng.uniform(-5, 5)
            bucket.location = (bx, by, CENTER_Z + BUCKET_DEPTH / 2)
            bucket.rotation_euler = (0, 0, rng.uniform(-math.pi, math.pi))
        show(package, bucket_visible)
        occluded = int(has_board and bucket_visible)

        # White clutter, kept clear of the board.
        n_clutter = 0
        if cfg.clutter_max > 0 and rng.random() < cfg.clutter_prob:
            n_clutter = rng.randint(1, cfg.clutter_max)
        for k, obj in enumerate(clutter):
            if k >= n_clutter:
                obj.hide_render = True
                continue
            w = rng.uniform(0.3, 4.0)
            length = min(8.0, w * rng.uniform(1.0, 4.0))
            r_min = side * 0.75 + max(w, length) / 2 + 0.5 if has_board else 0.0
            r = rng.uniform(r_min, r_min + 15.0)
            a = rng.uniform(-math.pi, math.pi)
            obj.location = (r * math.cos(a), r * math.sin(a), 0.0)
            obj.scale = (w, length, 1.0)
            obj.rotation_euler = (0, 0, rng.uniform(-math.pi, math.pi))
            obj.hide_render = False

        # Camera: retry until the board center is in frame.
        for _ in range(100):
            altitude, tilt_deg = place_camera(cam, rng, cfg)
            bpy.context.view_layer.update()
            if not has_board:
                break
            cx, cy, depth = project(scene, cam, (0, 0, CENTER_Z), W, H)
            if depth > 0 and inside(cx, cy, W, H, cfg.margin_px):
                break
        else:
            altitude, tilt_deg = place_camera(cam, rng, cfg, aim_origin=True)
            bpy.context.view_layer.update()

        row = {name: '' for name in FIELDS}
        filename = f'frame_{i:05d}.{ext}'
        row.update({
            'filename': filename, 'source': 'blender',
            'session_id': cfg.session_id, 'scene_type': scene_type,
            'width': W, 'height': H,
            'target_present': int(scene_type == 'x'),
            'occluded': occluded,
            'altitude_m': round(altitude, 3), 'tilt_deg': round(tilt_deg, 2),
            'ground': ground_name, 'sun_energy': round(sun.data.energy, 3),
            'exposure': round(exposure, 3),
            'bucket_visible': int(bucket_visible), 'bucket_color': bucket_color,
            'x_color': 'green' if scene_type == 'x' else x_color,
            'clutter_count': n_clutter, 'seed': cfg.seed,
        })
        if has_board:
            corners = [project(scene, cam, c, W, H) for c in board_corners]
            xs = [c[0] for c in corners]
            ys = [c[1] for c in corners]
            row['truncated'] = int(not all(inside(cx_, cy_, W, H)
                                           for cx_, cy_, _ in corners))
            row['bbox_xmin'] = round(max(-0.5, min(xs)), 2)
            row['bbox_ymin'] = round(max(-0.5, min(ys)), 2)
            row['bbox_xmax'] = round(min(W - 0.5, max(xs)), 2)
            row['bbox_ymax'] = round(min(H - 0.5, max(ys)), 2)
        if scene_type == 'x':
            cx, cy, _ = project(scene, cam, (0, 0, CENTER_Z), W, H)
            row['x'], row['y'] = round(cx, 4), round(cy, 4)

        scene.render.filepath = str(images / filename)
        bpy.ops.render.render(write_still=True)
        rows.append(row)
        if (i + 1) % 25 == 0:
            print(f'RENDERED {i + 1}/{cfg.samples}', flush=True)

    with (out / 'dataset' / 'labels.csv').open('w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    print('SUCCESS. Labeled images:', images, ' Frames:', len(rows), flush=True)


if __name__ == '__main__':
    main()
