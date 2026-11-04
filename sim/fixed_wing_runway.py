#!/usr/bin/env python3
"""PX4 fixed-wing aircraft on the local grassy runway.

Run with: isaac_run worlds/fixed_wing_runway.py
Runway geometry is saved in worlds/assets/; regenerate it with worlds/_generation/.
Adapted from uas-pegasus-sim/examples/13_px4_fixedwing.py.
"""

import argparse
import json
import math
import os
from pathlib import Path
import sys


WORLD_ASSET = Path(__file__).resolve().parent / "assets/grassy_runway.usda"


def nonnegative_float(value):
    result = float(value)
    if not math.isfinite(result) or result < 0:
        raise argparse.ArgumentTypeError("must be finite and nonnegative")
    return result


def nonnegative_int(value):
    result = int(value)
    if result < 0:
        raise argparse.ArgumentTypeError("must be nonnegative")
    return result


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--headless", action="store_true", help="run without the Isaac window")
    parser.add_argument("--duration", type=nonnegative_float, default=0,
                        help="simulation seconds to run; 0 keeps the app open")
    parser.add_argument("--px4-dir", type=Path, default=Path.home() / "PX4-Autopilot",
                        help="built PX4 checkout (default: ~/PX4-Autopilot)")
    parser.add_argument("--vehicle-id", type=nonnegative_int, default=0)
    parser.add_argument("--no-autolaunch", action="store_true",
                        help="connect to an externally launched PX4 instance")
    parser.add_argument("--pegasus-root", type=Path, default=os.environ.get("PEGASUS_PATH"),
                        help="Pegasus/isaac-uav checkout or extension directory; also accepts PEGASUS_PATH")
    parser.add_argument("--check-spawn", action="store_true",
                        help="verify disarmed spawn stability and PX4 actuator communication")
    args = parser.parse_args()
    args.px4_dir = args.px4_dir.expanduser().resolve()
    if not args.no_autolaunch and not (args.px4_dir / "build/px4_sitl_default/bin/px4").is_file():
        parser.error(f"PX4 SITL is missing in {args.px4_dir}; build it with 'make px4_sitl_default'")
    if not WORLD_ASSET.is_file():
        parser.error("Runway asset missing; run 'isaac_run worlds/_generation/generate_runway_world.py'")
    if args.check_spawn and args.duration == 0:
        args.duration = 15.0

    # Prefer the adjacent project fork, which includes its fixed-wing PX4 adapter.
    root = args.pegasus_root
    if root is None:
        adjacent = Path(__file__).resolve().parents[2] / "uas-pegasus-sim"
        if (adjacent / "extensions/pegasus.simulator/pegasus/simulator").is_dir():
            root = adjacent
    if root is not None:
        root = root.expanduser().resolve()
        extension = root / "extensions/pegasus.simulator"
        if not (extension / "pegasus/simulator").is_dir():
            extension = root
        if not (extension / "pegasus/simulator").is_dir():
            parser.error(f"No pegasus/simulator package found under {root}")
        sys.path.insert(0, str(extension))
    return args


def main():
    args = parse_args()
    # The app must start before importing omni, USD, or Pegasus.
    from isaacsim import SimulationApp
    app = SimulationApp({"headless": args.headless, "display_options": 0, "fast_shutdown": True})
    world = aircraft = top_view = None
    try:
        import numpy as np
        from pxr import UsdPhysics
        from isaacsim.core.api import World
        from pegasus.simulator.params import ROBOTS, WORLD_SETTINGS
        from pegasus.simulator.logic.interface.pegasus_interface import PegasusInterface
        from pegasus.simulator.logic.backends.px4_fixedwing_backend import (
            PX4FixedWingBackend, PX4FixedWingBackendConfig,
        )
        from pegasus.simulator.logic.vehicles.fixedwing import FixedWing, FixedWingConfig
        from pegasus.simulator.ui.runway_top_view import RunwayTopView

        pg = PegasusInterface()
        pg._world = World(**WORLD_SETTINGS["px4"])
        world = pg.world
        world.get_physics_context().set_solver_type("TGS")
        # Use this repository's scene, independently of Pegasus's environment registry.
        pg.load_asset(str(WORLD_ASSET), "/World/layout")

        config = FixedWingConfig()
        config.simulation_mode = "autonomous"
        config.hold_on_spawn = True
        config.wing_area = 2.36
        config.wing_span = 4.46
        config.chord = 0.53
        config.CL_0 = 0.3
        config.CL_alpha = 4.0
        config.CL_max = 1.5
        config.CD_0 = 0.025
        config.prop_max_thrust = 100.0
        config.prop_max_rpm = 10000.0
        config.prop_thrust_coefficient = config.prop_max_thrust / config.prop_max_rpm**2
        config.mass_kg = 12.0
        config.backends = [PX4FixedWingBackend(PX4FixedWingBackendConfig({
            "vehicle_id": args.vehicle_id,
            "px4_autolaunch": not args.no_autolaunch,
            "px4_dir": str(args.px4_dir),
            "px4_vehicle_model": "gazebo-classic_plane",
            "air_density": config.air_density,
        }))]
        aircraft = FixedWing(
            stage_prefix=f"/World/px4_plane{args.vehicle_id}",
            usd_file=ROBOTS["Fixed Wing"],
            vehicle_id=args.vehicle_id,
            init_pos=[-260.0, 0.0, 0.5347397],
            init_orientation=[0.0, 0.0, 0.0, 1.0],
            config=config,
        )
        UsdPhysics.MassAPI(world.stage.GetPrimAtPath(aircraft._stage_prefix + "/body")).CreateMassAttr(12.0)
        pg.set_viewport_camera([-274, -16, 7], [-255, 0, 1])
        world.reset()
        top_view = RunwayTopView(world.stage, aircraft, show_ui=not args.headless)

        dc = aircraft.get_dc_interface()
        body = dc.get_rigid_body(aircraft._stage_prefix + "/body")
        pose = dc.get_rigid_body_pose(body)
        start = np.array(pose.p)
        initial_quat = np.array(pose.r)
        initial_quat /= np.linalg.norm(initial_quat)
        max_drift = max_rotation = max_speed = 0.0

        print("WORLD_METADATA " + json.dumps({
            "world": "fixed_wing_runway", "backend": "px4", "vehicle_id": args.vehicle_id,
            "runway_asset": str(WORLD_ASSET), "aircraft_asset": ROBOTS["Fixed Wing"],
            "aircraft_spawn_m": [-260.0, 0.0, 0.5347397], "px4_airframe": "gazebo-classic_plane",
        }), flush=True)
        world.play()
        print("PX4 plane on runway 09; launch hold waits for armed throttle.", flush=True)
        while app.is_running() and (args.duration == 0 or world.current_time < args.duration):
            world.step(render=not args.headless)
            top_view.update()
            if args.check_spawn:
                pose = dc.get_rigid_body_pose(body)
                quat = np.array(pose.r)
                quat /= np.linalg.norm(quat)
                max_drift = max(max_drift, float(np.linalg.norm(np.array(pose.p) - start)))
                max_rotation = max(max_rotation, float(2 * np.arccos(np.clip(abs(quat @ initial_quat), 0, 1))))
                max_speed = max(max_speed, float(np.linalg.norm(dc.get_rigid_body_linear_velocity(body))))
        if args.check_spawn:
            connected = all(backend._received_first_actuator for backend in aircraft._backends)
            print("SPAWN_CHECK " + json.dumps({
                "max_drift_m": max_drift, "max_rotation_rad": max_rotation,
                "max_speed_m_s": max_speed, "spawn_held": aircraft.spawn_held,
                "simulated_seconds": world.current_time, "px4_actuators_received": connected,
            }), flush=True)
            if (not connected or world.current_time < args.duration or not aircraft.spawn_held or
                    max_drift > 1e-4 or max_rotation > 1e-4 or max_speed > 1e-4):
                raise RuntimeError("Spawn stability or PX4 connection check failed")
    except Exception:
        # Preserve Python error details and the exit code through Kit's fast shutdown.
        import traceback
        import omni.kit.app
        traceback.print_exc()
        omni.kit.app.get_app().post_quit(1)
        raise
    finally:
        if top_view is not None:
            top_view.destroy()
        if world is not None:
            world.stop()
        if aircraft is not None:
            for backend in aircraft._backends:
                backend.stop()
        app.close(wait_for_replicator=False)


if __name__ == "__main__":
    main()
