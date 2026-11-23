"""Run with Blender, not normal Python:
/Applications/Blender.app/Contents/MacOS/Blender -b --python blender/generate_green_x.py -- --samples 250
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


def args_parse():
    tail = sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else []
    p=argparse.ArgumentParser()
    p.add_argument('--out',default='output')
    p.add_argument('--samples',type=int,default=250)
    p.add_argument('--size',type=int,default=256)
    p.add_argument('--span-m',type=float,default=5.0)
    p.add_argument('--size-mode',choices=['side','diagonal'],default='diagonal')
    p.add_argument('--stroke-width-m',type=float,default=0.06)
    p.add_argument('--seed',type=int,default=7)
    p.add_argument('--no-occlusion',action='store_true')
    return p.parse_args(tail)


def material(name,rgb,roughness=0.85):
    m=bpy.data.materials.new(name)
    m.diffuse_color=(*rgb,1)
    m.use_nodes=True
    bsdf=m.node_tree.nodes.get('Principled BSDF')
    if bsdf:
        bsdf.inputs['Base Color'].default_value=(*rgb,1)
        bsdf.inputs['Roughness'].default_value=roughness
    return m


def make_mesh(name,poly,z0,z1,mat):
    verts,faces=prism(poly,z0,z1)
    me=bpy.data.meshes.new(name)
    me.from_pydata(verts,[],faces)
    me.update()
    obj=bpy.data.objects.new(name,me)
    bpy.context.collection.objects.link(obj)
    obj.data.materials.append(mat)
    return obj


def look_at(camera,point,roll=0.0):
    camera.rotation_mode='QUATERNION'
    quat=(Vector(point)-camera.location).to_track_quat('-Z','Y')
    camera.rotation_quaternion=quat @ Quaternion((0,0,1),roll)


def main():
    cfg=args_parse()
    random.seed(cfg.seed)
    out=Path(cfg.out).expanduser().resolve()
    model_dir=out/'model'
    images=out/'dataset'/'images'
    model_dir.mkdir(parents=True,exist_ok=True)
    images.mkdir(parents=True,exist_ok=True)
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=False)
    mesh=shapes(cfg.span_m,cfg.size_mode,cfg.stroke_width_m)
    white=material('Mat_White_Fabric',(0.92,0.91,0.87))
    green=material('Mat_Green_X',(0.025,0.50,0.10))
    ground_materials=[
      material('Mat_Concrete',(0.45,0.44,0.41)),
      material('Mat_Dry_Soil',(0.52,0.40,0.27)),
      material('Mat_Dry_Grass',(0.42,0.47,0.25)),
      material('Mat_Asphalt',(0.28,0.29,0.27)),
    ]
    target=[]
    target.append(make_mesh('White_Target_Board',mesh['square'],0.003,0.013,white))
    target.append(make_mesh('Green_Diagonal_A',mesh['strokes'][0],0.0132,0.0143,green))
    target.append(make_mesh('Green_Diagonal_B',mesh['strokes'][1],0.0143,0.0154,green))
    # Ground is deliberately a separate mesh, excluded from target OBJ export.
    bpy.ops.mesh.primitive_cube_add(size=1,location=(0,0,-0.035))
    ground=bpy.context.object
    ground.name='Environment_Ground'
    ground.dimensions=(100,100,0.06)
    bpy.ops.object.transform_apply(location=False,rotation=False,scale=True)
    ground.data.materials.append(ground_materials[0])

    # Optional approximate bucket occluder, NOT part of the competition-accurate asset.
    bpy.ops.mesh.primitive_cone_add(vertices=40,radius1=0.095,radius2=0.13,depth=0.27,location=(0,0,0.15))
    bucket=bpy.context.object
    bucket.name='Optional_Occluding_Bucket_Placeholder'
    bucket.data.materials.append(material('Mat_Bucket_Placeholder',(0.20,0.23,0.75)))
    bucket.hide_render=True

    bpy.ops.object.camera_add(location=(3,-5,14))
    cam=bpy.context.object
    cam.name='Drone_RGB_Camera'
    cam.data.type='PERSP'
    cam.data.lens=28
    cam.data.sensor_width=36
    look_at(cam,(0,0,0))
    scene=bpy.context.scene
    scene.camera=cam
    bpy.ops.object.light_add(type='SUN',location=(0,0,20))
    sun=bpy.context.object
    sun.name='Sun'
    sun.data.energy=2.0
    sun.data.angle=0.08
    sun.rotation_euler=(0.35,-0.5,0.4)
    world=bpy.data.worlds.new('Daylight') if scene.world is None else scene.world
    scene.world=world
    world.use_nodes=True
    bg=world.node_tree.nodes.get('Background')
    if bg:
        bg.inputs['Color'].default_value=(0.7,0.78,0.9,1)
        bg.inputs['Strength'].default_value=0.7

    scene.render.resolution_x=cfg.size
    scene.render.resolution_y=cfg.size
    scene.render.resolution_percentage=100
    scene.render.image_settings.file_format='PNG'
    scene.render.film_transparent=False
    scene.render.image_settings.color_mode='RGB'
    scene.render.filepath=str(out/'preview.png')
    scene.render.film_transparent=False
    try:
        scene.render.engine='BLENDER_EEVEE_NEXT'
    except Exception:
        scene.render.engine='BLENDER_EEVEE'
    try:
        scene.eevee.taa_render_samples=32
    except AttributeError:
        pass

    # Export only the dimensioned target geometry; not camera, lights, ground or bucket.
    bpy.ops.object.select_all(action='DESELECT')
    for item in target: item.select_set(True)
    bpy.context.view_layer.objects.active=target[0]
    try:
        bpy.ops.wm.obj_export(filepath=str(model_dir/'green_x.obj'),export_selected_objects=True)
    except (AttributeError, TypeError, RuntimeError):
        try: bpy.ops.export_scene.obj(filepath=str(model_dir/'green_x.obj'),use_selection=True)
        except Exception as e: print('OBJ export failed; use prebuilt OBJ instead:',e)
    bpy.ops.object.select_all(action='DESELECT')
    bpy.ops.wm.save_as_mainfile(filepath=str(model_dir/'green_x.blend'))
    spec={
      'source':'C-UASC 2026 official rules, page 13 (Rev 3, Feb 23 2026)',
      'official':'Target approximately 5 meters in diameter, white with green X. Exact square side and stripe width not specified.',
      'span_m':cfg.span_m,'size_mode':cfg.size_mode,'square_side_m':mesh['side_m'],
      'stroke_width_m_assumed':cfg.stroke_width_m,
      'target_center_world_m':[0,0,0.0154],
      'warning':'Model dimensions beyond ~5m overall size are simulation assumptions, not competition-certified.'
    }
    (model_dir/'spec.json').write_text(json.dumps(spec,indent=2))

    rows=[]
    for i in range(cfg.samples):
        # Camera range gives a range of scale, angles and off-center locations.
        cam.location=(random.uniform(-7,7),random.uniform(-7,7),random.uniform(9,26))
        aim=(random.uniform(-3.8,3.8),random.uniform(-3.8,3.8),0)
        look_at(cam,aim,random.uniform(-math.pi,math.pi))
        cam.data.lens=random.uniform(24,38)
        scene.view_settings.view_transform='Standard'
        scene.view_settings.exposure=random.uniform(-0.35,0.35)
        sun.rotation_euler=(random.uniform(.2,.9),random.uniform(-1,1),random.uniform(-math.pi,math.pi))
        sun.data.energy=random.uniform(1.3,3.3)
        ground.data.materials[0]=random.choice(ground_materials)
        occluded=(not cfg.no_occlusion and random.random()<0.30)
        bucket.hide_render=not occluded
        # Convert 3D center to image pixels, with y increasing downward.
        bpy.context.view_layer.update()
        p=world_to_camera_view(scene,cam,Vector((0,0,0.0154)))
        x=p.x*(cfg.size-1)
        y=(1-p.y)*(cfg.size-1)
        if p.z<=0 or not (10<x<cfg.size-10 and 10<y<cfg.size-10):
            # Adjust aim to bring the center back into frame.
            look_at(cam,(0,0,0),random.uniform(-math.pi,math.pi))
            bpy.context.view_layer.update()
            p=world_to_camera_view(scene,cam,Vector((0,0,0.0154)))
            x=p.x*(cfg.size-1)
            y=(1-p.y)*(cfg.size-1)
        filename=f'frame_{i:05d}.png'
        scene.render.filepath=str(images/filename)
        bpy.ops.render.render(write_still=True)
        rows.append({'filename':filename,'x':round(x,4),'y':round(y,4),'occluded':int(occluded)})
        if (i+1)%25==0: print(f'RENDERED {i+1}/{cfg.samples}')
    with (out/'dataset'/'labels.csv').open('w',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=['filename','x','y','occluded'])
        writer.writeheader()
        writer.writerows(rows)
    print('SUCCESS. Asset:',model_dir,' Labeled images:',images,' Frames:',len(rows))


if __name__=='__main__':
    main()
