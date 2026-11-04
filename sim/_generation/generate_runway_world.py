#!/usr/bin/env python3
"""Generate the runway asset: isaac_run worlds/_generation/generate_runway_world.py.

Adapted from uas-pegasus-sim/tools/generate_runway_world.py.
"""

import argparse
from pathlib import Path
import random


def generate_world(destination):
    from pxr import Gf, Sdf, Usd, UsdGeom, UsdLux, UsdPhysics, UsdShade

    destination = Path(destination).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    stage = Usd.Stage.CreateNew(str(destination))
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.z)
    UsdGeom.SetStageMetersPerUnit(stage, 1.0)
    root = UsdGeom.Xform.Define(stage, "/RunwayWorld")
    stage.SetDefaultPrim(root.GetPrim())
    root.GetPrim().SetDocumentation(
        "600 x 24 m east-west runway, 1600 x 1600 m grassy field. "
        "One flat collider at z=0; all paint and asphalt are visual only."
    )
    root.GetPrim().SetCustomData({"runway_length_m": 600.0, "runway_width_m": 24.0, "ground_height_m": 0.0})
    prefix = "/RunwayWorld"

    def material(name, color, roughness=0.9, vertex_color=False):
        mat = UsdShade.Material.Define(stage, f"{prefix}/Materials/{name}")
        shader = UsdShade.Shader.Define(stage, mat.GetPath().AppendChild("Surface"))
        shader.CreateIdAttr("UsdPreviewSurface")
        diffuse = shader.CreateInput("diffuseColor", Sdf.ValueTypeNames.Color3f)
        diffuse.Set(Gf.Vec3f(*color))
        shader.CreateInput("roughness", Sdf.ValueTypeNames.Float).Set(roughness)
        if vertex_color:
            reader = UsdShade.Shader.Define(stage, mat.GetPath().AppendChild("Color"))
            reader.CreateIdAttr("UsdPrimvarReader_float3")
            reader.CreateInput("varname", Sdf.ValueTypeNames.Token).Set("displayColor")
            diffuse.ConnectToSource(reader.ConnectableAPI(), "result")
        mat.CreateSurfaceOutput().ConnectToSource(shader.ConnectableAPI(), "surface")
        return mat

    grass = material("Grass", (0.17, 0.30, 0.07), vertex_color=True)
    asphalt = material("Asphalt", (0.075, 0.085, 0.095))
    white = material("RunwayPaint", (0.92, 0.92, 0.86))
    metal = material("Pole", (0.4, 0.43, 0.45), 0.5)
    orange = material("Windsock", (0.95, 0.25, 0.035))

    def mesh(name, points, faces, mat, colors=None):
        obj = UsdGeom.Mesh.Define(stage, f"{prefix}/{name}")
        obj.CreatePointsAttr(points)
        obj.CreateFaceVertexCountsAttr([len(face) for face in faces])
        obj.CreateFaceVertexIndicesAttr([index for face in faces for index in face])
        obj.CreateSubdivisionSchemeAttr("none")
        obj.CreateDoubleSidedAttr(True)
        UsdShade.MaterialBindingAPI.Apply(obj.GetPrim()).Bind(mat)
        if colors:
            obj.CreateDisplayColorPrimvar(UsdGeom.Tokens.uniform).Set(colors)
        return obj

    def rectangle(name, cx, cy, length, width, z, mat=white):
        return mesh(name, [(cx-length/2, cy-width/2, z), (cx+length/2, cy-width/2, z),
                           (cx+length/2, cy+width/2, z), (cx-length/2, cy+width/2, z)], [(0, 1, 2, 3)], mat)

    # The only ground collision surface, extending beneath the entire runway.
    ground = UsdGeom.Cube.Define(stage, prefix + "/GroundCollider")
    ground.AddTranslateOp().Set(Gf.Vec3d(0, 0, -0.25))
    ground.AddScaleOp().Set(Gf.Vec3f(800, 800, 0.25))
    ground.CreateVisibilityAttr("invisible")
    UsdPhysics.CollisionAPI.Apply(ground.GetPrim())
    ground_mat = UsdShade.Material.Define(stage, prefix + "/Materials/GroundPhysics")
    physics_mat = UsdPhysics.MaterialAPI.Apply(ground_mat.GetPrim())
    physics_mat.CreateStaticFrictionAttr(0.8)
    physics_mat.CreateDynamicFrictionAttr(0.65)
    physics_mat.CreateRestitutionAttr(0.0)
    UsdShade.MaterialBindingAPI.Apply(ground.GetPrim()).Bind(ground_mat, materialPurpose="physics")

    rng = random.Random(7)
    points, faces, colors = [], [], []
    for x in range(-800, 800, 20):
        for y in range(-800, 800, 20):
            i = len(points)
            points.extend([(x, y, 0), (x+20, y, 0), (x+20, y+20, 0), (x, y+20, 0)])
            faces.append((i, i+1, i+2, i+3))
            shade = rng.uniform(0.90, 1.10)
            colors.append((0.17 * shade, 0.30 * shade, 0.07 * shade))
    mesh("Grass", points, faces, grass, colors)
    rectangle("Runway", 0, 0, 600, 24, 0.002, asphalt)
    for side in (-1, 1):
        rectangle(f"Markings/Edge_{side:+d}".replace("+", "p").replace("-", "m"), 0, side*11.3, 590, 0.2, 0.004)
        for i in range(8):
            rectangle(f"Markings/Threshold_{side}_{i}".replace("-", "m"), side*288, (i-3.5)*2.4, 9, 1.2, 0.004)
    for i, x in enumerate(range(-240, 241, 24)):
        rectangle(f"Markings/Center_{i}", x, 0, 12, 0.35, 0.004)

    # Seven-segment runway numbers. u is right, v is forward on the runway.
    segments = {"0": "abcedf", "9": "abcdfg", "2": "abged", "7": "abc"}
    bars = {"a": (0, 3, 2, .35), "b": (.85, 1.5, .35, 3), "c": (.85, -1.5, .35, 3),
            "d": (0, -3, 2, .35), "e": (-.85, -1.5, .35, 3), "f": (-.85, 1.5, .35, 3), "g": (0, 0, 2, .35)}
    for label, x, direction in (("09", -272, 1), ("27", 272, -1)):
        for digit, glyph in enumerate(label):
            for segment in segments[glyph]:
                u, v, width, length = bars[segment]
                rectangle(f"Markings/Number_{label}_{digit}_{segment}", x+direction*v,
                          -direction*(u+(digit-.5)*3.1), length, width, 0.004)

    pole = UsdGeom.Cylinder.Define(stage, prefix + "/Windsock/Pole")
    pole.CreateRadiusAttr(0.055)
    pole.CreateHeightAttr(5)
    pole.AddTranslateOp().Set(Gf.Vec3d(-255, 28, 2.5))
    UsdShade.MaterialBindingAPI.Apply(pole.GetPrim()).Bind(metal)
    sock = UsdGeom.Cone.Define(stage, prefix + "/Windsock/Sock")
    sock.CreateRadiusAttr(0.35)
    sock.CreateHeightAttr(1.8)
    sock.CreateAxisAttr("X")
    sock.AddTranslateOp().Set(Gf.Vec3d(-254.1, 28, 4.8))
    UsdShade.MaterialBindingAPI.Apply(sock.GetPrim()).Bind(orange)

    sun = UsdLux.DistantLight.Define(stage, prefix + "/Sun")
    sun.CreateIntensityAttr(2500)
    sun.CreateAngleAttr(1.0)
    sun.AddRotateXYZOp().Set(Gf.Vec3f(-35, -25, 25))
    dome = UsdLux.DomeLight.Define(stage, prefix + "/Sky")
    dome.CreateIntensityAttr(700)
    dome.CreateColorAttr(Gf.Vec3f(0.65, 0.78, 1.0))

    # Identity rotation looks straight down -Z with north (+Y) at the top.
    camera = UsdGeom.Camera.Define(stage, prefix + "/TopDownCamera")
    camera.CreateProjectionAttr(UsdGeom.Tokens.orthographic)
    camera.AddTranslateOp().Set(Gf.Vec3d(0, 0, 300))
    camera.CreateHorizontalApertureAttr(7000.0)
    camera.CreateVerticalApertureAttr(3937.5)
    camera.CreateClippingRangeAttr(Gf.Vec2f(0.1, 10000))
    stage.GetRootLayer().Save()
    return destination


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parents[1] /
                        "assets/grassy_runway.usda")
    args = parser.parse_args()
    try:
        from pxr import Usd
        app = None
    except ImportError:
        from isaacsim import SimulationApp
        app = SimulationApp({"headless": True, "fast_shutdown": True})
    try:
        print(generate_world(args.output), flush=True)
        if app is not None:
            app.update()
    except Exception:
        import traceback
        traceback.print_exc()
        if app is not None:
            import omni.kit.app
            omni.kit.app.get_app().post_quit(1)
        raise
    finally:
        if app is not None:
            app.close(wait_for_replicator=False)
