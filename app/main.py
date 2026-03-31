from __future__ import annotations

import json
import math
import mimetypes
import shutil
import subprocess
import tempfile
import threading
import traceback
import uuid
import zipfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, Response, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates


BASE_DIR = Path(__file__).resolve().parent.parent
APP_DIR = BASE_DIR / "app"
DATA_DIR = BASE_DIR / "data"
GENERATED_DIR = BASE_DIR / "generated"
OUTPUT_DIR = BASE_DIR / "output"
BLENDER_DIR = APP_DIR / "blender"
BLENDER_SCRIPT_PATH = BLENDER_DIR / "generate.py"

for directory in (DATA_DIR, GENERATED_DIR, OUTPUT_DIR, BLENDER_DIR):
    directory.mkdir(parents=True, exist_ok=True)

(APP_DIR / "static").mkdir(parents=True, exist_ok=True)
(APP_DIR / "templates").mkdir(parents=True, exist_ok=True)

app = FastAPI(title="Ocean Prototype UI")

templates = Jinja2Templates(directory=str(APP_DIR / "templates"))

app.mount("/static", StaticFiles(directory=str(APP_DIR / "static")), name="static")
app.mount("/generated", StaticFiles(directory=str(GENERATED_DIR)), name="generated")


REGION_ORDER = [
    "Europe",
    "Africa",
    "Asia-Pacific",
    "North America",
    "South America",
    "Oceania",
]

PRESETS = {
    "balanced": {
        "label": "Balanced",
        "base_radius_multiplier": 1.0,
        "core_height_multiplier": 1.0,
        "branch_density_multiplier": 1.0,
        "branch_thickness_multiplier": 1.0,
    },
    "x1c_safe": {
        "label": "Bambu X1C Safe Print",
        "base_radius_multiplier": 1.05,
        "core_height_multiplier": 0.95,
        "branch_density_multiplier": 0.85,
        "branch_thickness_multiplier": 1.15,
    },
    "dramatic": {
        "label": "Dramatic",
        "base_radius_multiplier": 1.10,
        "core_height_multiplier": 1.15,
        "branch_density_multiplier": 1.20,
        "branch_thickness_multiplier": 1.05,
    },
}

SHAPE_FAMILIES = {
    "coral": "Coral (experimental / slow)",
    "starfish": "Starfish",
    "seaweed": "Seaweed",
    "clownfish": "Clownfish",
}

SCAD_STARFISH = r"""
$fn = 96;

// {{TITLE}}

size_factor = {{SIZE_FACTOR}};

core_r = 8.8 * size_factor;
body_h = 6.8 * size_factor;

arm_len = 36 * size_factor;

root_r = 5.4 * size_factor;
mid_r1 = 4.3 * size_factor;
mid_r2 = 3.1 * size_factor;
tip_r = 1.6 * size_factor;

module rounded_arm() {
    hull() {
        translate([0, 0, 0])
            scale([1.08, 0.84, 0.40]) sphere(r=root_r);

        translate([arm_len * 0.30, 0.3 * size_factor, 0.10 * size_factor])
            scale([0.96, 0.68, 0.34]) sphere(r=mid_r1);

        translate([arm_len * 0.62, -0.2 * size_factor, 0.20 * size_factor])
            scale([0.86, 0.54, 0.28]) sphere(r=mid_r2);

        translate([arm_len * 0.92, 0.1 * size_factor, 0.08 * size_factor])
            scale([0.70, 0.34, 0.22]) sphere(r=tip_r);
    }
}

module center_body() {
    hull() {
        scale([1.00, 1.00, 0.34]) sphere(r=core_r);
        translate([0, 0, body_h * 0.12])
            scale([0.78, 0.78, 0.20]) sphere(r=core_r * 0.92);
    }
}

union() {
    center_body();

    for (i = [0:4]) {
        rotate([0, 0, i * 72])
            rounded_arm();
    }
}
"""

SCAD_SEAWEED = r"""
$fn = 72;

// {{TITLE}}

size_factor = {{SIZE_FACTOR}};
blade_count = 5;
blade_height = 92 * size_factor;
base_radius = 14 * size_factor;

module segment_pair(x0, y0, z0, r0, x1, y1, z1, r1) {
    hull() {
        translate([x0, y0, z0]) sphere(r=r0);
        translate([x1, y1, z1]) sphere(r=r1);
    }
}

module blade(seed_angle=0, bend=1.0, spread=1.0) {
    union() {
        for (i = [0:11]) {
            z0 = i * blade_height / 12;
            z1 = (i + 1) * blade_height / 12;

            x0 = sin(seed_angle + i * 10) * (3.5 + i * 0.45) * bend * size_factor;
            x1 = sin(seed_angle + (i + 1) * 10) * (3.5 + (i + 1) * 0.45) * bend * size_factor;

            y0 = cos(seed_angle + i * 7) * 1.2 * spread * size_factor;
            y1 = cos(seed_angle + (i + 1) * 7) * 1.2 * spread * size_factor;

            r0 = max((7.0 - i * 0.42) * size_factor, 1.45 * size_factor);
            r1 = max((7.0 - (i + 1) * 0.42) * size_factor, 1.10 * size_factor);

            segment_pair(x0, y0, z0, r0, x1, y1, z1, r1);
        }
    }
}

module holdfast() {
    hull() {
        cylinder(h=6 * size_factor, r=base_radius);
        translate([0, 0, 2 * size_factor]) cylinder(h=4 * size_factor, r=base_radius * 0.78);
    }
}

union() {
    holdfast();

    for (i = [0:blade_count - 1]) {
        rotate([0, 0, i * (360 / blade_count)])
            translate([base_radius * 0.30, 0, 3.0 * size_factor])
                blade(seed_angle=i * 19, bend=0.90 + 0.06 * i, spread=0.85 + 0.05 * i);
    }
}
"""

BLENDER_GENERATE_SCRIPT = r'''
import argparse
import json
import math
import random
import sys
from pathlib import Path

import bpy


def parse_args():
    argv = sys.argv
    if "--" in argv:
        argv = argv[argv.index("--") + 1 :]
    else:
        argv = []

    parser = argparse.ArgumentParser()
    parser.add_argument("--params", required=True)
    parser.add_argument("--stl", required=False, default="")
    parser.add_argument("--png", required=False, default="")
    return parser.parse_args(argv)


def load_params(path_str: str) -> dict:
    path = Path(path_str)
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def unpack_params(payload: dict) -> dict:
    params = dict(payload.get("shape_params", {}))
    params["shape_family"] = payload.get("shape_family", "coral")
    params["title"] = payload.get("title", "Ocean Reef Prototype")
    params["dataset_name"] = payload.get("dataset_name", "")
    params["summary"] = payload.get("summary", {})
    return params


def reset_scene():
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)

    for collection in (
        bpy.data.meshes,
        bpy.data.curves,
        bpy.data.materials,
        bpy.data.cameras,
        bpy.data.lights,
        bpy.data.metaballs,
        bpy.data.images,
    ):
        for block in list(collection):
            if block.users == 0:
                collection.remove(block)


def set_scene_defaults():
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_EEVEE"
    scene.eevee.taa_render_samples = 32
    scene.render.image_settings.file_format = "PNG"
    scene.render.resolution_x = 1400
    scene.render.resolution_y = 1000
    scene.render.film_transparent = False

    world = bpy.data.worlds.get("World")
    if world is None:
        world = bpy.data.worlds.new("World")
    scene.world = world
    world.use_nodes = True

    bg = world.node_tree.nodes.get("Background")
    if bg:
        bg.inputs[0].default_value = (0.97, 0.98, 1.0, 1.0)
        bg.inputs[1].default_value = 0.9


def ensure_stl_export():
    try:
        bpy.ops.preferences.addon_enable(module="io_mesh_stl")
    except Exception:
        pass


def deselect_all():
    bpy.ops.object.select_all(action="DESELECT")


def select_objects(objects):
    deselect_all()
    for obj in objects:
        obj.select_set(True)
    if objects:
        bpy.context.view_layer.objects.active = objects[0]


def join_objects(objects, name="JoinedObject"):
    if not objects:
        raise RuntimeError("No objects to join.")
    select_objects(objects)
    bpy.ops.object.join()
    obj = bpy.context.view_layer.objects.active
    obj.name = name
    return obj


def apply_modifier(obj, modifier_name):
    bpy.context.view_layer.objects.active = obj
    try:
        bpy.ops.object.modifier_apply(modifier=modifier_name)
    except Exception:
        pass


def convert_to_mesh(obj):
    bpy.context.view_layer.objects.active = obj
    try:
        bpy.ops.object.convert(target="MESH")
    except Exception:
        pass
    return bpy.context.view_layer.objects.active


def add_uv_sphere(location=(0, 0, 0), radius=1.0, scale=(1, 1, 1), name="Sphere"):
    bpy.ops.mesh.primitive_uv_sphere_add(radius=radius, location=location)
    obj = bpy.context.active_object
    obj.scale = scale
    obj.name = name
    return obj


def add_cylinder(location=(0, 0, 0), radius=1.0, depth=2.0, rotation=(0, 0, 0), name="Cylinder"):
    bpy.ops.mesh.primitive_cylinder_add(radius=radius, depth=depth, location=location, rotation=rotation)
    obj = bpy.context.active_object
    obj.name = name
    return obj


def add_cone(location=(0, 0, 0), radius1=1.0, radius2=0.0, depth=2.0, rotation=(0, 0, 0), name="Cone"):
    bpy.ops.mesh.primitive_cone_add(
        radius1=radius1,
        radius2=radius2,
        depth=depth,
        location=location,
        rotation=rotation,
    )
    obj = bpy.context.active_object
    obj.name = name
    return obj


def add_bezier_curve(points, bevel_depth=0.12, resolution=16, name="Curve"):
    curve_data = bpy.data.curves.new(name=name, type="CURVE")
    curve_data.dimensions = "3D"
    curve_data.resolution_u = resolution
    curve_data.bevel_depth = bevel_depth
    curve_data.bevel_resolution = 6
    curve_data.fill_mode = "FULL"

    spline = curve_data.splines.new("POLY")
    spline.points.add(len(points) - 1)
    for idx, (x, y, z) in enumerate(points):
        spline.points[idx].co = (x, y, z, 1.0)

    obj = bpy.data.objects.new(name, curve_data)
    bpy.context.collection.objects.link(obj)
    return obj

def create_material(name: str, base_color):
    mat = bpy.data.materials.get(name)
    if mat is not None:
        return mat

    mat = bpy.data.materials.new(name=name)
    mat.use_nodes = True

    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    if bsdf:
        bsdf.inputs["Base Color"].default_value = base_color
        bsdf.inputs["Roughness"].default_value = 0.55
        bsdf.inputs["Specular"].default_value = 0.35

    return mat


def assign_material(obj, material):
    if obj.data and hasattr(obj.data, "materials"):
        obj.data.materials.clear()
        obj.data.materials.append(material)


def add_remesh(obj, voxel_size=0.18, smooth=True):
    mod = obj.modifiers.new(name="Remesh", type="REMESH")
    mod.mode = "VOXEL"
    mod.voxel_size = voxel_size
    mod.use_smooth_shade = smooth
    apply_modifier(obj, mod.name)


def add_decimate(obj, ratio=0.92):
    mod = obj.modifiers.new(name="Decimate", type="DECIMATE")
    mod.ratio = ratio
    apply_modifier(obj, mod.name)


def shade_smooth(obj):
    try:
        bpy.context.view_layer.objects.active = obj
        bpy.ops.object.shade_smooth()
    except Exception:
        pass


def look_at(obj, target=(0, 0, 0)):
    loc = obj.location
    dx = target[0] - loc.x
    dy = target[1] - loc.y
    dz = target[2] - loc.z
    distance_xy = max(math.sqrt(dx * dx + dy * dy), 1e-6)
    obj.rotation_euler[0] = math.atan2(dz, distance_xy)
    obj.rotation_euler[1] = 0.0
    obj.rotation_euler[2] = math.atan2(dx, dy) * -1.0


def setup_camera_and_light(target=(0, 0, 2.0), scale_hint=1.0):
    cam_distance = 12.0 * scale_hint

    bpy.ops.object.camera_add(location=(cam_distance, -cam_distance * 1.2, cam_distance * 0.68))
    cam = bpy.context.active_object
    bpy.context.scene.camera = cam
    look_at(cam, target)

    bpy.ops.object.light_add(type="SUN", location=(cam_distance * 0.8, -cam_distance * 0.4, cam_distance * 1.5))
    sun = bpy.context.active_object
    sun.data.energy = 3.0
    sun.rotation_euler = (math.radians(35), math.radians(0), math.radians(25))

    bpy.ops.object.light_add(type="AREA", location=(-cam_distance * 0.5, -cam_distance * 0.2, cam_distance * 0.7))
    area = bpy.context.active_object
    area.data.energy = 2500
    area.data.shape = "RECTANGLE"
    area.data.size = 8.0 * scale_hint
    area.data.size_y = 8.0 * scale_hint
    look_at(area, target)


def export_png(png_path: str):
    if not png_path:
        return
    bpy.context.scene.render.filepath = png_path
    bpy.ops.render.render(write_still=True)


def export_stl(obj, stl_path: str):
    if not stl_path:
        return

    ensure_stl_export()

    bpy.context.view_layer.objects.active = obj
    deselect_all()
    obj.select_set(True)

    convert_to_mesh(obj)

    try:
        bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)
    except Exception:
        pass

    export_error = None

    try:
        bpy.ops.export_mesh.stl(filepath=stl_path, use_selection=True)
    except Exception as exc:
        export_error = exc

    if not Path(stl_path).exists() or Path(stl_path).stat().st_size == 0:
        try:
            bpy.ops.wm.stl_export(filepath=stl_path, export_selected_objects=True)
            export_error = None
        except Exception as exc:
            if export_error is None:
                export_error = exc

    if not Path(stl_path).exists() or Path(stl_path).stat().st_size == 0:
        raise RuntimeError(f"STL export failed: {export_error}")


def finalize_mesh(obj, remesh_voxel=0.12, decimate_ratio=None):
    convert_to_mesh(obj)
    add_remesh(obj, voxel_size=remesh_voxel)
    if decimate_ratio is not None:
        add_decimate(obj, ratio=decimate_ratio)
    shade_smooth(obj)
    return obj

def create_coral(params):
    scale = params["size_factor"]
    density = params["density_factor"]
    thickness = params["thickness_factor"]

    objects = []

    base = add_cylinder(location=(0, 0, 0.25 * scale), radius=1.35 * scale, depth=0.55 * scale, name="CoralBase")
    base.scale = (1.0, 1.0, 0.65)
    objects.append(base)

    branch_count = max(8, min(16, int(round(8 + density * 6))))
    rng = random.Random(params["seed"])

    for i in range(branch_count):
        angle = i * (2 * math.pi / branch_count)
        outward = 0.18 * scale + (i % 3) * 0.12 * scale
        x0 = math.cos(angle) * outward
        y0 = math.sin(angle) * outward

        points = [(x0, y0, 0.25 * scale)]
        branch_height = (3.0 + rng.random() * 2.2) * scale

        for j in range(1, 5):
            t = j / 4.0
            x = x0 + math.sin(angle * 0.7 + t * 1.5 + rng.random()) * (0.35 + 0.80 * t) * scale
            y = y0 + math.cos(angle * 0.9 + t * 1.2 + rng.random()) * (0.25 + 0.70 * t) * scale
            z = 0.25 * scale + branch_height * t
            points.append((x, y, z))

        curve = add_bezier_curve(
            points,
            bevel_depth=max(0.11 * thickness * scale, 0.075),
            resolution=14,
            name=f"CoralBranch_{i}",
        )
        objects.append(curve)

        if i % 2 == 0:
            bx, by, bz = points[-2]
            tip = add_bezier_curve(
                [
                    (bx, by, bz),
                    (
                        bx + math.sin(angle + 1.3) * 0.75 * scale,
                        by + math.cos(angle + 1.1) * 0.55 * scale,
                        bz + 1.0 * scale,
                    ),
                ],
                bevel_depth=max(0.07 * thickness * scale, 0.045),
                resolution=10,
                name=f"CoralTip_{i}",
            )
            objects.append(tip)

    select_objects(objects)
    for obj in objects:
        bpy.context.view_layer.objects.active = obj
        convert_to_mesh(obj)

    coral = join_objects(objects, name="Coral")
    finalize_mesh(coral, remesh_voxel=max(0.10 * scale, 0.07), decimate_ratio=0.95)
    return coral, (0, 0, 2.2 * scale), 1.25 * scale


def create_clownfish(params):
    scale = params["size_factor"]

    body_main = add_uv_sphere(
        radius=1.30 * scale,
        scale=(2.15, 1.05, 0.82),
        location=(0.10 * scale, 0, 0),
        name="FishBodyMain",
    )
    body_front = add_uv_sphere(
        radius=0.95 * scale,
        scale=(1.10, 0.95, 0.82),
        location=(-2.05 * scale, 0, 0),
        name="FishBodyFront",
    )
    cheek = add_uv_sphere(
        radius=0.70 * scale,
        scale=(0.90, 0.90, 0.74),
        location=(-2.75 * scale, 0, -0.05 * scale),
        name="FishCheek",
    )
    tail_root = add_uv_sphere(
        radius=0.62 * scale,
        scale=(0.75, 0.72, 0.72),
        location=(2.55 * scale, 0, 0),
        name="FishTailRoot",
    )

    tail_top = add_cone(
        location=(3.65 * scale, 0, 0.72 * scale),
        radius1=0.82 * scale,
        radius2=0.08 * scale,
        depth=2.05 * scale,
        rotation=(0, math.radians(90), 0),
        name="FishTailTop",
    )
    tail_bottom = add_cone(
        location=(3.65 * scale, 0, -0.72 * scale),
        radius1=0.82 * scale,
        radius2=0.08 * scale,
        depth=2.05 * scale,
        rotation=(0, math.radians(90), 0),
        name="FishTailBottom",
    )

    dorsal_front = add_cone(
        location=(-0.45 * scale, 0, 1.18 * scale),
        radius1=0.72 * scale,
        radius2=0.10 * scale,
        depth=1.25 * scale,
        rotation=(math.radians(90), 0, 0),
        name="FishDorsalFront",
    )
    dorsal_back = add_cone(
        location=(0.95 * scale, 0, 1.02 * scale),
        radius1=0.52 * scale,
        radius2=0.08 * scale,
        depth=1.00 * scale,
        rotation=(math.radians(90), 0, 0),
        name="FishDorsalBack",
    )

    ventral = add_cone(
        location=(-0.10 * scale, 0, -0.98 * scale),
        radius1=0.46 * scale,
        radius2=0.08 * scale,
        depth=0.95 * scale,
        rotation=(math.radians(-90), 0, 0),
        name="FishVentral",
    )

    pectoral_left = add_cone(
        location=(-1.15 * scale, 0.72 * scale, -0.05 * scale),
        radius1=0.34 * scale,
        radius2=0.06 * scale,
        depth=0.82 * scale,
        rotation=(0, math.radians(68), math.radians(18)),
        name="FishPectoralLeft",
    )
    pectoral_right = add_cone(
        location=(-1.15 * scale, -0.72 * scale, -0.05 * scale),
        radius1=0.34 * scale,
        radius2=0.06 * scale,
        depth=0.82 * scale,
        rotation=(0, math.radians(-68), math.radians(-18)),
        name="FishPectoralRight",
    )

    objects = [
        body_main,
        body_front,
        cheek,
        tail_root,
        tail_top,
        tail_bottom,
        dorsal_front,
        dorsal_back,
        ventral,
        pectoral_left,
        pectoral_right,
    ]

    fish = join_objects(objects, name="Clownfish")
    finalize_mesh(fish, remesh_voxel=max(0.07 * scale, 0.05), decimate_ratio=0.98)

    for xpos, width, tilt in (
        (-1.55 * scale, 0.12 * scale, 9),
        (-0.25 * scale, 0.14 * scale, 3),
        (1.10 * scale, 0.12 * scale, -6),
    ):
        bpy.ops.mesh.primitive_cube_add(location=(xpos, 0, 0))
        cutter = bpy.context.active_object
        cutter.scale = (width, 2.10 * scale, 1.35 * scale)
        cutter.rotation_euler[1] = math.radians(tilt)

        mod = fish.modifiers.new(name=f"StripeCut_{xpos}", type="BOOLEAN")
        mod.operation = "DIFFERENCE"
        mod.solver = "FAST"
        mod.object = cutter
        apply_modifier(fish, mod.name)

        bpy.data.objects.remove(cutter, do_unlink=True)

    shade_smooth(fish)
    return fish, (0, 0, 0.15 * scale), 1.40 * scale


def create_shape(params):
    shape = params["shape_family"]
    if shape == "clownfish":
        return create_clownfish(params)
    return create_coral(params)


def main():
    args = parse_args()
    payload = load_params(args.params)
    params = unpack_params(payload)

    reset_scene()
    set_scene_defaults()

    obj, target, scale_hint = create_shape(params)

    material_color = {
        "coral": (0.93, 0.67, 0.58, 1.0),
        "clownfish": (0.95, 0.56, 0.32, 1.0),
    }.get(params["shape_family"], (0.85, 0.85, 0.85, 1.0))

    mat = create_material("OceanMaterial", material_color)
    assign_material(obj, mat)

    setup_camera_and_light(target=target, scale_hint=scale_hint)

    export_stl(obj, args.stl)
    export_png(args.png)


if __name__ == "__main__":
    main()
'''


JOBS: dict[str, dict[str, Any]] = {}
JOBS_LOCK = threading.Lock()

def ensure_blender_script() -> None:
    BLENDER_DIR.mkdir(parents=True, exist_ok=True)
    BLENDER_SCRIPT_PATH.write_text(BLENDER_GENERATE_SCRIPT, encoding="utf-8")


def list_demo_files() -> list[str]:
    return sorted([p.name for p in DATA_DIR.glob("*.json")])


def parse_timestamp(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(timezone.utc)


def load_signatures(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def aggregate_signatures(signatures: list[dict[str, Any]]) -> dict[str, Any]:
    counts = defaultdict(int)
    latest_ts: datetime | None = None

    for sig in signatures:
        region = sig.get("region", "Unknown")
        counts[region] += 1
        ts = sig.get("timestamp")
        if ts:
            dt = parse_timestamp(ts)
            if latest_ts is None or dt > latest_ts:
                latest_ts = dt

    total = len(signatures)
    recent_counts = defaultdict(int)

    if latest_ts is not None:
        for sig in signatures:
            ts = sig.get("timestamp")
            if not ts:
                continue
            dt = parse_timestamp(ts)
            age_hours = (latest_ts - dt).total_seconds() / 3600.0
            if age_hours <= 24:
                recent_counts[sig.get("region", "Unknown")] += 1

    return {
        "total": total,
        "counts_by_region": dict(counts),
        "recent_by_region": dict(recent_counts),
    }


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def scale_total(total: int, source_max: int, out_min: float, out_max: float) -> float:
    if source_max <= 0:
        return out_min
    ratio = clamp(total / source_max, 0.0, 1.0)
    return out_min + (out_max - out_min) * ratio


def build_summary(agg: dict[str, Any]) -> dict[str, Any]:
    rows = []
    for region in REGION_ORDER:
        rows.append({
            "region": region,
            "count": agg["counts_by_region"].get(region, 0),
            "recent_24h": agg["recent_by_region"].get(region, 0),
        })
    return {
        "total": agg["total"],
        "regions": rows,
    }


def render_simple_scad(template: str, title: str, size_factor: float) -> str:
    return (
        template
        .replace("{{TITLE}}", title)
        .replace("{{SIZE_FACTOR}}", str(round(size_factor, 3)))
    )

def build_shape_params(
    agg: dict[str, Any],
    source_max: int,
    base_radius_multiplier: float,
    core_height_multiplier: float,
    branch_density_multiplier: float,
    branch_thickness_multiplier: float,
    shape_family: str,
) -> dict[str, Any]:
    total = agg["total"]

    size_factor = scale_total(total, source_max, 0.80, 1.75) * base_radius_multiplier
    density_factor = scale_total(total, source_max, 0.85, 1.65) * branch_density_multiplier
    thickness_factor = scale_total(total, source_max, 0.90, 1.35) * branch_thickness_multiplier
    height_factor = scale_total(total, source_max, 0.85, 1.45) * core_height_multiplier

    return {
        "shape_family": shape_family,
        "size_factor": round(size_factor, 3),
        "density_factor": round(density_factor, 3),
        "thickness_factor": round(thickness_factor, 3),
        "height_factor": round(height_factor, 3),
        "seed": int(total + source_max),
        "total": int(total),
    }


def update_job(job_id: str, **updates: Any) -> None:
    with JOBS_LOCK:
        if job_id in JOBS:
            JOBS[job_id].update(updates)


def create_job_record(job_id: str, payload: dict[str, Any]) -> None:
    with JOBS_LOCK:
        JOBS[job_id] = payload


def get_job_record(job_id: str) -> dict[str, Any] | None:
    with JOBS_LOCK:
        job = JOBS.get(job_id)
        if job is None:
            return None
        return dict(job)

def run_blender(params_path: Path, out_stl: Path | None, out_png: Path | None) -> tuple[bool, str]:
    ensure_blender_script()

    cmd = [
        "blender",
        "-b",
        "-P",
        str(BLENDER_SCRIPT_PATH),
        "--",
        "--params",
        str(params_path),
    ]

    if out_stl is not None:
        cmd.extend(["--stl", str(out_stl)])
    if out_png is not None:
        cmd.extend(["--png", str(out_png)])

    try:
        completed = subprocess.run(cmd, capture_output=True, text=True, check=False)
    except FileNotFoundError:
        return False, "Blender not found in PATH. Install it with: sudo apt install blender -y"

    stderr = (completed.stderr or "").strip()
    stdout = (completed.stdout or "").strip()
    combined = "\n".join(part for part in [stderr, stdout] if part)

    if completed.returncode != 0:
        return False, combined or "Blender export failed."

    if out_stl is not None:
        if not out_stl.exists() or out_stl.stat().st_size == 0:
            return False, combined or "Blender finished without creating a usable STL file."

    if out_png is not None:
        if not out_png.exists() or out_png.stat().st_size == 0:
            return False, combined or "Blender finished without creating a usable PNG file."

    return True, ""

def run_openscad(scad_path: Path, stl_path: Path) -> tuple[bool, str]:
    cmd = ["openscad", "-o", str(stl_path), str(scad_path)]
    try:
        completed = subprocess.run(cmd, capture_output=True, text=True, check=False)
    except FileNotFoundError:
        return False, "OpenSCAD not found in PATH."

    if completed.returncode != 0:
        return False, (completed.stderr or completed.stdout or "OpenSCAD failed").strip()

    return True, ""


def render_png_from_scad(scad_path: Path, png_path: Path) -> tuple[bool, str]:
    cmd = [
        "xvfb-run",
        "-a",
        "-s",
        "-screen 0 1600x1200x24",
        "openscad",
        "--render",
        "--imgsize=1600,1200",
        "--colorscheme=Tomorrow",
        "-o",
        str(png_path),
        str(scad_path),
    ]
    try:
        completed = subprocess.run(cmd, capture_output=True, text=True, check=False)
    except FileNotFoundError as exc:
        missing = str(exc)
        if "xvfb-run" in missing:
            return False, "xvfb-run not found. Install it with: sudo apt-get install -y xvfb"
        return False, "OpenSCAD not found in PATH."

    if completed.returncode != 0:
        return False, (completed.stderr or completed.stdout or "PNG render failed").strip()

    if not png_path.exists() or png_path.stat().st_size == 0:
        return False, "PNG render produced no usable file."

    return True, ""

def process_openscad_job(job_id: str, request_data: dict[str, Any], agg: dict[str, Any], summary: dict[str, Any]) -> None:
    shape_family = request_data["shape_family"]
    demo_file = request_data["demo_file"]
    export_mode = request_data["export_mode"]
    source_max = int(request_data["source_max"])
    total = agg["total"]

    title = f"Ocean Reef Prototype - {demo_file} - {shape_family}"
    main_scad_name = f"reef_{job_id}.scad"
    main_stl_name = f"reef_{job_id}.stl"
    main_png_name = f"reef_{job_id}.png"

    main_scad_path = GENERATED_DIR / main_scad_name
    main_stl_path = OUTPUT_DIR / main_stl_name
    main_png_path = OUTPUT_DIR / main_png_name

    size_factor = scale_total(total, source_max, 0.85, 1.55)

    if shape_family == "starfish":
        scad_code = render_simple_scad(SCAD_STARFISH, title=title, size_factor=size_factor)
    else:
        scad_code = render_simple_scad(SCAD_SEAWEED, title=title, size_factor=size_factor)

    main_scad_path.write_text(scad_code, encoding="utf-8")

    result: dict[str, Any] = {
        "job_id": job_id,
        "dataset_name": demo_file,
        "summary": summary,
        "preset": request_data["preset"],
        "export_mode": export_mode,
        "shape_family": shape_family,
        "scad_url": f"/generated/{main_scad_name}",
        "params_url": None,
        "stl_url": None,
        "png_url": None,
        "zip_url": None,
        "region_files": [],
        "params": {
            "source_max": source_max,
            "base_radius_multiplier": request_data["base_radius_multiplier"],
            "core_height_multiplier": request_data["core_height_multiplier"],
            "branch_density_multiplier": request_data["branch_density_multiplier"],
            "branch_thickness_multiplier": request_data["branch_thickness_multiplier"],
        },
    }

    if export_mode == "scad_only":
        update_job(
            job_id,
            message="Rendering PNG preview with OpenSCAD...",
            progress=70,
            stage="rendering_png",
            eta_seconds=None,
        )

        ok, message = render_png_from_scad(main_scad_path, main_png_path)
        if not ok:
            update_job(
                job_id,
                status="error",
                message=message,
                result=result,
                summary=summary,
                stage="error",
                eta_seconds=None,
            )
            return

        result["png_url"] = f"/output/{main_png_name}"

        update_job(
            job_id,
            status="done",
            message="Preview generated.",
            result=result,
            summary=summary,
            progress=100,
            stage="done",
            eta_seconds=None,
        )
        return

    if export_mode == "single_stl":
        update_job(
            job_id,
            message="Rendering STL and PNG with OpenSCAD...",
            progress=45,
            stage="rendering_stl",
            eta_seconds=None,
        )

        ok, message = run_openscad(main_scad_path, main_stl_path)
        if not ok:
            update_job(
                job_id,
                status="error",
                message=message,
                result=result,
                summary=summary,
                stage="error",
                eta_seconds=None,
            )
            return

        result["stl_url"] = f"/output/{main_stl_name}"

        ok, message = render_png_from_scad(main_scad_path, main_png_path)
        if ok:
            result["png_url"] = f"/output/{main_png_name}"
        else:
            result["png_warning"] = message

        update_job(
            job_id,
            status="done",
            message="STL generated.",
            result=result,
            summary=summary,
            progress=100,
            stage="done",
            eta_seconds=None,
        )
        return

    if export_mode == "separate_regions_zip":
        update_job(
            job_id,
            message="Rendering ZIP bundle with OpenSCAD...",
            progress=45,
            stage="rendering_regions",
            eta_seconds=None,
        )

        region_files: list[dict[str, str | None]] = []
        zip_name = f"reef_bundle_{job_id}.zip"
        zip_path = OUTPUT_DIR / zip_name

        temp_dir = Path(tempfile.mkdtemp(prefix=f"reef_{job_id}_"))
        try:
            bundle_scad_path = temp_dir / main_scad_name
            bundle_stl_path = temp_dir / main_stl_name
            bundle_png_path = temp_dir / main_png_name

            shutil.copy2(main_scad_path, bundle_scad_path)

            ok, message = run_openscad(main_scad_path, bundle_stl_path)
            if not ok:
                update_job(
                    job_id,
                    status="error",
                    message=message,
                    result=result,
                    summary=summary,
                    stage="error",
                    eta_seconds=None,
                )
                return

            ok, _ = render_png_from_scad(main_scad_path, bundle_png_path)

            shutil.copy2(bundle_stl_path, main_stl_path)
            result["stl_url"] = f"/output/{main_stl_name}"

            if ok:
                shutil.copy2(bundle_png_path, main_png_path)
                result["png_url"] = f"/output/{main_png_name}"

            region_files.append({
                "region": "Main",
                "scad_url": f"/generated/{main_scad_name}",
                "stl_url": f"/output/{main_stl_name}",
                "png_url": result["png_url"],
            })

            update_job(
                job_id,
                message="Packaging ZIP...",
                progress=95,
                stage="packaging_zip",
                eta_seconds=None,
            )

            with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                for file_path in temp_dir.glob("*"):
                    zf.write(file_path, arcname=file_path.name)

            result["region_files"] = region_files
            result["zip_url"] = f"/output/{zip_name}"

            update_job(
                job_id,
                status="done",
                message="ZIP bundle generated.",
                result=result,
                summary=summary,
                progress=100,
                stage="done",
                eta_seconds=None,
            )
            return
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

def process_blender_job(job_id: str, request_data: dict[str, Any], agg: dict[str, Any], summary: dict[str, Any]) -> None:
    demo_file = request_data["demo_file"]
    export_mode = request_data["export_mode"]
    source_max = int(request_data["source_max"])
    base_radius_multiplier = float(request_data["base_radius_multiplier"])
    core_height_multiplier = float(request_data["core_height_multiplier"])
    branch_density_multiplier = float(request_data["branch_density_multiplier"])
    branch_thickness_multiplier = float(request_data["branch_thickness_multiplier"])
    shape_family = request_data["shape_family"]

    shape_params = build_shape_params(
        agg=agg,
        source_max=source_max,
        base_radius_multiplier=base_radius_multiplier,
        core_height_multiplier=core_height_multiplier,
        branch_density_multiplier=branch_density_multiplier,
        branch_thickness_multiplier=branch_thickness_multiplier,
        shape_family=shape_family,
    )

    title = f"Ocean Reef Prototype - {demo_file} - {shape_family}"
    params_name = f"reef_{job_id}_params.json"
    main_stl_name = f"reef_{job_id}.stl"
    main_png_name = f"reef_{job_id}.png"

    params_path = GENERATED_DIR / params_name
    main_stl_path = OUTPUT_DIR / main_stl_name
    main_png_path = OUTPUT_DIR / main_png_name

    blender_payload = {
        "title": title,
        "dataset_name": demo_file,
        "shape_family": shape_family,
        "shape_params": shape_params,
        "summary": summary,
    }
    params_path.write_text(json.dumps(blender_payload, indent=2, ensure_ascii=False), encoding="utf-8")

    result: dict[str, Any] = {
        "job_id": job_id,
        "dataset_name": demo_file,
        "summary": summary,
        "preset": request_data["preset"],
        "export_mode": export_mode,
        "shape_family": shape_family,
        "scad_url": None,
        "params_url": f"/generated/{params_name}",
        "stl_url": None,
        "png_url": None,
        "zip_url": None,
        "region_files": [],
        "params": {
            "source_max": source_max,
            "base_radius_multiplier": base_radius_multiplier,
            "core_height_multiplier": core_height_multiplier,
            "branch_density_multiplier": branch_density_multiplier,
            "branch_thickness_multiplier": branch_thickness_multiplier,
        },
    }

    if export_mode == "scad_only":
        update_job(
            job_id,
            message="Rendering PNG preview with Blender...",
            progress=70,
            stage="rendering_png",
            eta_seconds=None,
        )

        ok, message = run_blender(params_path, None, main_png_path)
        if not ok:
            update_job(
                job_id,
                status="error",
                message=message,
                result=result,
                summary=summary,
                stage="error",
                eta_seconds=None,
            )
            return

        result["png_url"] = f"/output/{main_png_name}"

        update_job(
            job_id,
            status="done",
            message="Preview generated.",
            result=result,
            summary=summary,
            progress=100,
            stage="done",
            eta_seconds=None,
        )
        return

    if export_mode == "single_stl":
        update_job(
            job_id,
            message="Rendering STL and PNG with Blender...",
            progress=45,
            stage="rendering_stl",
            eta_seconds=None,
        )

        ok, message = run_blender(params_path, main_stl_path, main_png_path)
        if not ok:
            update_job(
                job_id,
                status="error",
                message=message,
                result=result,
                summary=summary,
                stage="error",
                eta_seconds=None,
            )
            return

        result["stl_url"] = f"/output/{main_stl_name}"
        result["png_url"] = f"/output/{main_png_name}"

        update_job(
            job_id,
            status="done",
            message="STL generated.",
            result=result,
            summary=summary,
            progress=100,
            stage="done",
            eta_seconds=None,
        )
        return

    if export_mode == "separate_regions_zip":
        update_job(
            job_id,
            message="Rendering ZIP bundle with Blender...",
            progress=45,
            stage="rendering_regions",
            eta_seconds=None,
        )

        region_files: list[dict[str, str | None]] = []
        zip_name = f"reef_bundle_{job_id}.zip"
        zip_path = OUTPUT_DIR / zip_name

        temp_dir = Path(tempfile.mkdtemp(prefix=f"reef_{job_id}_"))
        try:
            bundle_params_path = temp_dir / params_name
            bundle_stl_path = temp_dir / main_stl_name
            bundle_png_path = temp_dir / main_png_name

            shutil.copy2(params_path, bundle_params_path)

            ok, message = run_blender(bundle_params_path, bundle_stl_path, bundle_png_path)
            if not ok:
                update_job(
                    job_id,
                    status="error",
                    message=message,
                    result=result,
                    summary=summary,
                    stage="error",
                    eta_seconds=None,
                )
                return

            region_files.append({
                "region": "Main",
                "scad_url": None,
                "stl_url": f"/output/{main_stl_name}",
                "png_url": f"/output/{main_png_name}",
            })

            shutil.copy2(bundle_stl_path, main_stl_path)
            shutil.copy2(bundle_png_path, main_png_path)

            update_job(
                job_id,
                message="Packaging ZIP...",
                progress=95,
                stage="packaging_zip",
                eta_seconds=None,
            )

            with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                for file_path in temp_dir.glob("*"):
                    zf.write(file_path, arcname=file_path.name)

            result["region_files"] = region_files
            result["zip_url"] = f"/output/{zip_name}"
            result["stl_url"] = f"/output/{main_stl_name}"
            result["png_url"] = f"/output/{main_png_name}"

            update_job(
                job_id,
                status="done",
                message="ZIP bundle generated.",
                result=result,
                summary=summary,
                progress=100,
                stage="done",
                eta_seconds=None,
            )
            return
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

def process_job(job_id: str, request_data: dict[str, Any]) -> None:
    try:
        update_job(
            job_id,
            status="running",
            message="Loading dataset...",
            progress=10,
            stage="loading_dataset",
            eta_seconds=None,
        )

        demo_file = request_data["demo_file"]
        dataset_path = DATA_DIR / demo_file
        if not dataset_path.exists():
            update_job(
                job_id,
                status="error",
                message=f"Dataset not found: {demo_file}",
                stage="error",
                eta_seconds=None,
            )
            return

        signatures = load_signatures(dataset_path)
        agg = aggregate_signatures(signatures)
        summary = build_summary(agg)

        update_job(
            job_id,
            message="Building model parameters...",
            summary=summary,
            progress=20,
            stage="building_model",
            eta_seconds=None,
        )

        shape_family = request_data["shape_family"]

        if shape_family in {"starfish", "seaweed"}:
            process_openscad_job(job_id, request_data, agg, summary)
            return

        process_blender_job(job_id, request_data, agg, summary)

    except Exception as exc:
        traceback.print_exc()
        update_job(
            job_id,
            status="error",
            message=f"Unhandled server error: {exc}",
            error_type=type(exc).__name__,
            stage="error",
            eta_seconds=None,
        )


ensure_blender_script()


@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "demo_files": list_demo_files(),
            "presets": PRESETS,
            "shape_families": SHAPE_FAMILIES,
        },
    )

@app.get("/favicon.ico")
async def favicon() -> Response:
    return Response(status_code=204)


@app.post("/generate")
async def generate(
    demo_file: str | None = Form(default=None),
    preset: str = Form(default="balanced"),
    export_mode: str = Form(default="single_stl"),
    source_max: int = Form(default=100000),
    base_radius_multiplier: float = Form(default=1.0),
    core_height_multiplier: float = Form(default=1.0),
    branch_density_multiplier: float = Form(default=1.0),
    branch_thickness_multiplier: float = Form(default=1.0),
    shape_family: str = Form(default="coral"),
    upload_file: UploadFile | None = File(default=None),
) -> JSONResponse:
    if upload_file and upload_file.filename:
        return JSONResponse(
            {"error": "Async mode currently supports demo datasets only."},
            status_code=400,
        )

    if not demo_file:
        return JSONResponse({"error": "No dataset selected."}, status_code=400)

    selected_preset = PRESETS.get(preset, PRESETS["balanced"])

    if preset in PRESETS:
        base_radius_multiplier = float(selected_preset["base_radius_multiplier"])
        core_height_multiplier = float(selected_preset["core_height_multiplier"])
        branch_density_multiplier = float(selected_preset["branch_density_multiplier"])
        branch_thickness_multiplier = float(selected_preset["branch_thickness_multiplier"])

    job_id = uuid.uuid4().hex[:10]

    create_job_record(
        job_id,
        {
            "job_id": job_id,
            "status": "queued",
            "message": "Job queued.",
            "progress": 5,
            "stage": "queued",
            "eta_seconds": None,
            "result": None,
            "summary": None,
            "created_at": datetime.now(timezone.utc).isoformat(),
        },
    )

    request_data = {
        "demo_file": demo_file,
        "preset": preset,
        "export_mode": export_mode,
        "source_max": source_max,
        "base_radius_multiplier": base_radius_multiplier,
        "core_height_multiplier": core_height_multiplier,
        "branch_density_multiplier": branch_density_multiplier,
        "branch_thickness_multiplier": branch_thickness_multiplier,
        "shape_family": shape_family,
    }

    thread = threading.Thread(target=process_job, args=(job_id, request_data), daemon=True)
    thread.start()

    return JSONResponse(
        {
            "job_id": job_id,
            "status": "queued",
            "message": "Job started.",
        }
    )

@app.get("/job/{job_id}")
async def get_job(job_id: str) -> JSONResponse:
    job = get_job_record(job_id)
    if job is None:
        return JSONResponse({"error": "Job not found."}, status_code=404)
    return JSONResponse(job)


@app.get("/output/{filename}")
async def serve_output(filename: str):
    path = OUTPUT_DIR / filename

    if not path.exists() or not path.is_file():
        return JSONResponse({"error": "File not found."}, status_code=404)

    suffix = path.suffix.lower()

    if suffix == ".png":
        media_type = "image/png"
    elif suffix in (".jpg", ".jpeg"):
        media_type = "image/jpeg"
    elif suffix == ".stl":
        media_type = "model/stl"
    elif suffix == ".zip":
        media_type = "application/zip"
    elif suffix == ".json":
        media_type = "application/json"
    elif suffix == ".scad":
        media_type = "text/plain; charset=utf-8"
    else:
        guessed_type, _ = mimetypes.guess_type(str(path))
        media_type = guessed_type or "application/octet-stream"

    return FileResponse(path, media_type=media_type)
