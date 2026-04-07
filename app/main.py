from __future__ import annotations

import base64
import binascii
import json
import math
import mimetypes
import os
import secrets
import sys
import time 
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

BASIC_AUTH_USERNAME = os.getenv("OCEAN_UI_USERNAME", "PUT_USERNAME_HERE")
BASIC_AUTH_PASSWORD = os.getenv("OCEAN_UI_PASSWORD", "PUT_PASSWORD_HERE")


def _basic_auth_unauthorized() -> Response:
    return Response(
        status_code=401,
        headers={"WWW-Authenticate": 'Basic realm="Ocean Reef Prototype UI"'},
    )


def _basic_auth_service_unavailable() -> JSONResponse:
    return JSONResponse(
        {
            "error": "Basic auth is enabled but credentials are not configured.",
            "detail": "Set OCEAN_UI_USERNAME and OCEAN_UI_PASSWORD before starting the app.",
        },
        status_code=503,
        headers={"Cache-Control": "no-store"},
    )


def _is_basic_auth_valid(request: Request) -> bool:
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Basic "):
        return False

    token = auth_header[6:].strip()
    try:
        decoded = base64.b64decode(token).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError):
        return False

    username, sep, password = decoded.partition(":")
    if not sep:
        return False

    return secrets.compare_digest(username, BASIC_AUTH_USERNAME) and secrets.compare_digest(password, BASIC_AUTH_PASSWORD)


@app.middleware("http")
async def basic_auth_middleware(request: Request, call_next):
    if request.url.path == "/favicon.ico":
        return await call_next(request)

    if not BASIC_AUTH_USERNAME or not BASIC_AUTH_PASSWORD:
        return _basic_auth_service_unavailable()

    if not _is_basic_auth_valid(request):
        return _basic_auth_unauthorized()

    return await call_next(request)


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
    "coral": "Coral",
    "starfish": "Starfish",
    "seaweed": "Seaweed",
    "clownfish": "Clownfish",
}

SCAD_STARFISH = r"""
$fn = 72;

// {{TITLE}}

size_factor = {{SIZE_FACTOR}};
thickness = 8 * size_factor;
arm_length = 34 * size_factor;
arm_width = 11 * size_factor;

module arm() {
    hull() {
        translate([0, 0, 0]) cylinder(h=thickness, r=arm_width);
        translate([arm_length * 0.55, 0, 0]) cylinder(h=thickness * 0.90, r=arm_width * 0.62);
        translate([arm_length, 0, 0]) cylinder(h=thickness * 0.72, r=arm_width * 0.24);
    }
}

module center_body() {
    hull() {
        cylinder(h=thickness, r=arm_width * 1.05);
        translate([0, 0, thickness * 0.20]) cylinder(h=thickness * 0.65, r=arm_width * 0.92);
    }
}

union() {
    center_body();
    for (i = [0:4]) {
        rotate([0, 0, i * 72]) arm();
    }
}
"""

SCAD_SEAWEED = r"""
$fn = 36;

// {{TITLE}}

size_factor = {{SIZE_FACTOR}};
footprint_scale = pow(size_factor, 1.20);
height_scale = pow(size_factor, 1.32);
thickness_scale = pow(size_factor, 0.92);
blade_count = 4;
blade_height = 92 * height_scale;
base_radius = 12.5 * thickness_scale;

module segment_pair(x0, y0, z0, r0, x1, y1, z1, r1) {
    hull() {
        translate([x0, y0, z0]) sphere(r=r0);
        translate([x1, y1, z1]) sphere(r=r1);
    }
}

module blade(seed_angle=0, bend=1.0, spread=1.0) {
    union() {
        for (i = [0:8]) {
            z0 = i * blade_height / 9;
            z1 = (i + 1) * blade_height / 9;

            x0 = sin(seed_angle + i * 10) * (3.5 + i * 0.45) * bend * footprint_scale;
            x1 = sin(seed_angle + (i + 1) * 10) * (3.5 + (i + 1) * 0.45) * bend * footprint_scale;

            y0 = cos(seed_angle + i * 7) * 1.2 * spread * footprint_scale;
            y1 = cos(seed_angle + (i + 1) * 7) * 1.2 * spread * footprint_scale;

            r0 = max((7.0 - i * 0.42) * thickness_scale, 1.45 * thickness_scale);
            r1 = max((7.0 - (i + 1) * 0.42) * thickness_scale, 1.10 * thickness_scale);

            segment_pair(x0, y0, z0, r0, x1, y1, z1, r1);
        }
    }
}

module holdfast() {
    hull() {
        cylinder(h=6 * thickness_scale, r=base_radius);
        translate([0, 0, 2 * thickness_scale]) cylinder(h=4 * thickness_scale, r=base_radius * 0.78);
    }
}

union() {
    holdfast();

    for (i = [0:blade_count - 1]) {
        rotate([0, 0, i * (360 / blade_count)])
            translate([base_radius * 0.30, 0, 3.0 * thickness_scale])
                blade(seed_angle=i * 19, bend=0.90 + 0.06 * i, spread=0.85 + 0.05 * i);
    }
}
"""

SCAD_CLOWNFISH = r"""
$fn = 96;

// {{TITLE}}

size_factor = {{SIZE_FACTOR}};

body_len = 70 * size_factor;
body_height = 15 * size_factor;
body_width = 11 * size_factor;
tail_len = 20 * size_factor;

module body() {
    hull() {
        translate([-body_len * 0.35, 0, 0])
            scale([1.15, 0.95, 0.82]) sphere(r=body_height);

        translate([0, 0, 0])
            scale([1.45, 1.00, 0.88]) sphere(r=body_height);

        translate([body_len * 0.25, 0, 0])
            scale([0.90, 0.82, 0.74]) sphere(r=body_height * 0.88);
    }
}

module head() {
    translate([-body_len * 0.55, 0, -body_height * 0.03])
        scale([0.92, 0.88, 0.78]) sphere(r=body_height * 0.82);
}

module tail() {
    hull() {
        translate([body_len * 0.45, 0, 0])
            scale([0.62, 0.68, 0.68]) sphere(r=body_height * 0.78);

        translate([body_len * 0.45 + tail_len, 0, body_height * 0.72])
            sphere(r=body_width * 0.82);

        translate([body_len * 0.45 + tail_len, 0, -body_height * 0.72])
            sphere(r=body_width * 0.82);
    }
}

module dorsal_fin() {
    hull() {
        translate([-8 * size_factor, 0, body_height * 0.82])
            sphere(r=body_width * 0.42);

        translate([10 * size_factor, 0, body_height * 1.22])
            sphere(r=body_width * 0.24);
    }
}

module bottom_fin() {
    hull() {
        translate([-3 * size_factor, 0, -body_height * 0.62])
            sphere(r=body_width * 0.26);

        translate([10 * size_factor, 0, -body_height * 0.92])
            sphere(r=body_width * 0.14);
    }
}

union() {
    body();
    head();
    tail();
    dorsal_fin();
    bottom_fin();
}
"""

BLENDER_GENERATE_SCRIPT = r'''
import argparse
import json
import math
import random
import sys
from pathlib import Path

try:
    import bpy
    import bmesh
except ImportError:
    bpy = None
    bmesh = None


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
    node_tree = world.node_tree
    if node_tree is None:
        try:
            world.use_nodes = True
        except Exception:
            pass
        node_tree = world.node_tree

    if node_tree is not None:
        bg = node_tree.nodes.get("Background")
        if bg:
            color_socket = bg.inputs.get("Color") or (bg.inputs[0] if len(bg.inputs) > 0 else None)
            strength_socket = bg.inputs.get("Strength") or (bg.inputs[1] if len(bg.inputs) > 1 else None)
            if color_socket is not None:
                color_socket.default_value = (0.97, 0.98, 1.0, 1.0)
            if strength_socket is not None:
                strength_socket.default_value = 0.9


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
    node_tree = mat.node_tree
    if node_tree is None:
        try:
            mat.use_nodes = True
        except Exception:
            pass
        node_tree = mat.node_tree

    if node_tree is None:
        return mat

    bsdf = node_tree.nodes.get("Principled BSDF")
    if bsdf:
        base_color_socket = bsdf.inputs.get("Base Color")
        roughness_socket = bsdf.inputs.get("Roughness")
        specular_socket = bsdf.inputs.get("Specular IOR Level") or bsdf.inputs.get("Specular")

        if base_color_socket is not None:
            base_color_socket.default_value = base_color
        if roughness_socket is not None:
            roughness_socket.default_value = 0.55
        if specular_socket is not None:
            specular_socket.default_value = 0.35

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

def add_subsurf(obj, levels=1):
    mod = obj.modifiers.new(name="Subsurf", type="SUBSURF")
    mod.levels = levels
    mod.render_levels = levels
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
    height = params.get("height_factor", 1.0)

    footprint_scale = pow(scale, 1.16)
    height_scale = pow(height, 1.14)
    branch_thickness = max(0.75, thickness) * pow(scale, 0.86)

    objects = []

    base = add_cylinder(
        location=(0, 0, 0.25 * height_scale),
        radius=1.35 * footprint_scale,
        depth=0.55 * height_scale,
        name="CoralBase",
    )
    base.scale = (1.0, 1.0, 0.65)
    objects.append(base)

    branch_count = max(8, min(16, int(round(8 + density * 6))))
    rng = random.Random(params["seed"])

    for i in range(branch_count):
        angle = i * (2 * math.pi / branch_count)
        outward = (0.18 + (i % 3) * 0.12) * footprint_scale
        x0 = math.cos(angle) * outward
        y0 = math.sin(angle) * outward

        points = [(x0, y0, 0.25 * height_scale)]
        branch_height = (3.2 + rng.random() * 2.6) * height_scale

        for j in range(1, 5):
            t = j / 4.0
            x = x0 + math.sin(angle * 0.7 + t * 1.5 + rng.random()) * (0.35 + 0.80 * t) * footprint_scale
            y = y0 + math.cos(angle * 0.9 + t * 1.2 + rng.random()) * (0.25 + 0.70 * t) * footprint_scale
            z = 0.25 * height_scale + branch_height * t
            points.append((x, y, z))

        curve = add_bezier_curve(
            points,
            bevel_depth=max(0.09 * branch_thickness, 0.07),
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
                        bx + math.sin(angle + 1.3) * 0.75 * footprint_scale,
                        by + math.cos(angle + 1.1) * 0.55 * footprint_scale,
                        bz + 1.0 * height_scale,
                    ),
                ],
                bevel_depth=max(0.06 * branch_thickness, 0.045),
                resolution=10,
                name=f"CoralTip_{i}",
            )
            objects.append(tip)

    select_objects(objects)
    for obj in objects:
        bpy.context.view_layer.objects.active = obj
        convert_to_mesh(obj)

    coral = join_objects(objects, name="Coral")
    finalize_mesh(coral, remesh_voxel=max(0.09 * branch_thickness, 0.07), decimate_ratio=0.95)
    return coral, (0, 0, 2.2 * height_scale), 0.95 + 0.52 * pow(scale, 0.74)

def create_cartoon_fish_body(scale: float):
    mesh = bpy.data.meshes.new("CartoonFishBody")
    obj = bpy.data.objects.new("CartoonFishBody", mesh)
    bpy.context.collection.objects.link(obj)

    bm = bmesh.new()

    # side silhouette in X/Z plane, inspired by a cartoon clownfish profile
    pts = [
        (-2.60 * scale,  0.10 * scale),   # mouth top
        (-2.15 * scale,  0.72 * scale),   # forehead
        (-1.10 * scale,  1.18 * scale),   # upper head/body
        ( 0.20 * scale,  1.28 * scale),   # top mid body
        ( 1.30 * scale,  1.02 * scale),   # upper tail root
        ( 2.00 * scale,  0.55 * scale),   # tail neck top
        ( 2.55 * scale,  1.35 * scale),   # tail fin top
        ( 3.10 * scale,  0.35 * scale),   # tail tip mid
        ( 2.55 * scale, -1.35 * scale),   # tail fin bottom
        ( 2.00 * scale, -0.55 * scale),   # tail neck bottom
        ( 1.10 * scale, -1.02 * scale),   # lower tail root
        (-0.10 * scale, -1.22 * scale),   # belly
        (-1.40 * scale, -0.98 * scale),   # lower cheek
        (-2.30 * scale, -0.45 * scale),   # mouth lower
    ]

    verts = [bm.verts.new((x, 0.0, z)) for x, z in pts]
    bm.verts.ensure_lookup_table()

    face = bm.faces.new(verts)
    bmesh.ops.recalc_face_normals(bm, faces=[face])

    bm.to_mesh(mesh)
    bm.free()

    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)

    # give thickness
    solid = obj.modifiers.new(name="Solidify", type="SOLIDIFY")
    solid.thickness = 0.95 * scale
    solid.offset = 0.0
    apply_modifier(obj, solid.name)

    # soften blockiness
    bevel = obj.modifiers.new(name="Bevel", type="BEVEL")
    bevel.width = 0.10 * scale
    bevel.segments = 3
    apply_modifier(obj, bevel.name)

    subsurf = obj.modifiers.new(name="Subsurf", type="SUBSURF")
    subsurf.levels = 2
    subsurf.render_levels = 2
    apply_modifier(obj, subsurf.name)

    shade_smooth(obj)
    return obj
    
def create_clownfish(params):
    scale = params["size_factor"]

    # -------- base half-mesh from a side/profile-driven cartoon fish silhouette --------
    mesh = bpy.data.meshes.new("ClownfishMesh")
    fish = bpy.data.objects.new("Clownfish", mesh)
    bpy.context.collection.objects.link(fish)
    bpy.context.view_layer.objects.active = fish
    fish.select_set(True)

    bm = bmesh.new()

    # x = length axis, z = height axis
    # y is mirrored later, so we only build the center plane
    # This is intentionally short, tall, and "Nemo-ish"
    rings = [
        {"x": -2.45 * scale, "z":  0.00 * scale, "h": 0.42 * scale, "w": 0.00 * scale},  # mouth / snout
        {"x": -2.05 * scale, "z":  0.08 * scale, "h": 0.92 * scale, "w": 0.30 * scale},  # forehead
        {"x": -1.35 * scale, "z":  0.12 * scale, "h": 1.22 * scale, "w": 0.62 * scale},  # head bulk
        {"x": -0.25 * scale, "z":  0.10 * scale, "h": 1.28 * scale, "w": 0.82 * scale},  # front body
        {"x":  0.75 * scale, "z":  0.02 * scale, "h": 1.12 * scale, "w": 0.74 * scale},  # mid body
        {"x":  1.45 * scale, "z": -0.02 * scale, "h": 0.82 * scale, "w": 0.42 * scale},  # tail root pinch
        {"x":  2.00 * scale, "z":  0.00 * scale, "h": 0.42 * scale, "w": 0.16 * scale},  # tail neck
    ]

    ring_verts = []

    # each ring has top / mid / bottom on the center half
    for ring in rings:
        x = ring["x"]
        z = ring["z"]
        h = ring["h"]
        w = ring["w"]

        verts = [
            bm.verts.new((x, 0.0, z + h * 0.95)),     # top center
            bm.verts.new((x, w,   z + h * 0.35)),     # upper side
            bm.verts.new((x, w,   z - h * 0.35)),     # lower side
            bm.verts.new((x, 0.0, z - h * 0.98)),     # bottom center
        ]
        ring_verts.append(verts)

    bm.verts.ensure_lookup_table()

    # connect body rings
    for i in range(len(ring_verts) - 1):
        a = ring_verts[i]
        b = ring_verts[i + 1]

        for j in range(3):
            try:
                bm.faces.new((a[j], b[j], b[j + 1], a[j + 1]))
            except ValueError:
                pass

    # close nose
    nose = bm.verts.new((-2.72 * scale, 0.0, 0.0))
    bm.verts.ensure_lookup_table()
    first = ring_verts[0]
    for j in range(3):
        try:
            bm.faces.new((nose, first[j], first[j + 1]))
        except ValueError:
            pass

    # tail fin as proper mesh, not cones
    tail_top = bm.verts.new((2.85 * scale, 0.0,  1.18 * scale))
    tail_mid = bm.verts.new((3.20 * scale, 0.0,  0.00 * scale))
    tail_bot = bm.verts.new((2.85 * scale, 0.0, -1.18 * scale))

    tail_side_top = bm.verts.new((2.65 * scale, 0.18 * scale,  0.75 * scale))
    tail_side_mid = bm.verts.new((2.95 * scale, 0.20 * scale,  0.00 * scale))
    tail_side_bot = bm.verts.new((2.65 * scale, 0.18 * scale, -0.75 * scale))

    last = ring_verts[-1]

    tail_pairs = [
        (last[0], tail_top, tail_side_top, last[1]),
        (last[1], tail_side_top, tail_side_mid, last[2]),
        (last[2], tail_side_mid, tail_side_bot, last[3]),
        (tail_top, tail_mid, tail_side_mid, tail_side_top),
        (tail_side_mid, tail_mid, tail_bot, tail_side_bot),
    ]
    for face in tail_pairs:
        try:
            bm.faces.new(face)
        except ValueError:
            pass

    # dorsal fin as mesh
    dorsal_front = bm.verts.new((-0.55 * scale, 0.0, 1.18 * scale))
    dorsal_peak  = bm.verts.new(( 0.25 * scale, 0.0, 1.78 * scale))
    dorsal_back  = bm.verts.new(( 1.05 * scale, 0.0, 1.28 * scale))
    dorsal_side  = bm.verts.new(( 0.20 * scale, 0.16 * scale, 1.32 * scale))

    for face in (
        (dorsal_front, dorsal_peak, dorsal_side),
        (dorsal_side, dorsal_peak, dorsal_back),
    ):
        try:
            bm.faces.new(face)
        except ValueError:
            pass

    # ventral fin as mesh
    ventral_front = bm.verts.new((-0.20 * scale, 0.0, -0.98 * scale))
    ventral_peak  = bm.verts.new(( 0.35 * scale, 0.0, -1.35 * scale))
    ventral_back  = bm.verts.new(( 0.92 * scale, 0.0, -1.00 * scale))
    ventral_side  = bm.verts.new(( 0.30 * scale, 0.12 * scale, -1.02 * scale))

    for face in (
        (ventral_front, ventral_side, ventral_peak),
        (ventral_side, ventral_back, ventral_peak),
    ):
        try:
            bm.faces.new(face)
        except ValueError:
            pass

    # pectoral fin on one side; mirror creates the other
    pectoral_root_a = bm.verts.new((-1.10 * scale, 0.32 * scale,  0.15 * scale))
    pectoral_root_b = bm.verts.new((-0.80 * scale, 0.34 * scale, -0.05 * scale))
    pectoral_tip    = bm.verts.new((-1.45 * scale, 1.05 * scale, -0.08 * scale))

    for face in (
        (pectoral_root_a, pectoral_tip, pectoral_root_b),
    ):
        try:
            bm.faces.new(face)
        except ValueError:
            pass

    bm.normal_update()
    bm.to_mesh(mesh)
    bm.free()

    # -------- modifiers --------
    mirror = fish.modifiers.new(name="Mirror", type="MIRROR")
    mirror.use_axis[0] = False
    mirror.use_axis[1] = True
    mirror.use_axis[2] = False
    mirror.use_clip = True
    mirror.merge_threshold = 0.001

    solidify = fish.modifiers.new(name="Solidify", type="SOLIDIFY")
    solidify.thickness = 0.10 * scale
    solidify.offset = 0.0

    bevel = fish.modifiers.new(name="Bevel", type="BEVEL")
    bevel.width = 0.05 * scale
    bevel.segments = 2

    subsurf = fish.modifiers.new(name="Subsurf", type="SUBSURF")
    subsurf.levels = 2
    subsurf.render_levels = 2

    # apply only mirror + solidify + bevel; keep subsurf live until after shape tweaks
    apply_modifier(fish, "Mirror")
    apply_modifier(fish, "Solidify")
    apply_modifier(fish, "Bevel")
    apply_modifier(fish, "Subsurf")

    # light smoothing / cleanup
    shade_smooth(fish)

    return fish, (0.10 * scale, 0.0, 0.0), 1.35 * scale

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

    if shape_family == "coral":
        size_factor = scale_total(total, source_max, 0.82, 2.30) * base_radius_multiplier
        density_factor = scale_total(total, source_max, 0.90, 1.75) * branch_density_multiplier
        thickness_factor = scale_total(total, source_max, 0.92, 1.18) * branch_thickness_multiplier
        height_factor = scale_total(total, source_max, 0.90, 1.95) * core_height_multiplier
    else:
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
        if sys.platform == "darwin":
            return False, "Blender not found in PATH. Install Blender (for example: brew install --cask blender)."
        if sys.platform.startswith("linux"):
            return False, "Blender not found in PATH. Install it with: sudo apt-get install -y blender"
        return False, "Blender not found in PATH. Install Blender and make sure the 'blender' command is available."

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
        if sys.platform == "darwin":
            return False, "OpenSCAD not found in PATH. Install it (for example: brew install --cask openscad)."
        if sys.platform.startswith("linux"):
            return False, "OpenSCAD not found in PATH. Install it with: sudo apt-get install -y openscad"
        return False, "OpenSCAD not found in PATH. Install OpenSCAD and ensure 'openscad' is available."

    if completed.returncode != 0:
        return False, (completed.stderr or completed.stdout or "OpenSCAD failed").strip()

    return True, ""

def _openscad_png_command(scad_path: Path, png_path: Path) -> tuple[list[str] | None, str | None]:
    if shutil.which("openscad") is None:
        if sys.platform == "darwin":
            return None, "OpenSCAD not found in PATH. Install it (for example: brew install --cask openscad)."
        if sys.platform.startswith("linux"):
            return None, "OpenSCAD not found in PATH. Install it with: sudo apt-get install -y openscad"
        return None, "OpenSCAD not found in PATH. Install OpenSCAD and ensure 'openscad' is available."

    openscad_cmd = [
        "openscad",
        "--render",
        "--imgsize=1600,1200",
        "-o",
        str(png_path),
        str(scad_path),
    ]

    is_linux = sys.platform.startswith("linux")
    has_display = bool(os.getenv("DISPLAY") or os.getenv("WAYLAND_DISPLAY"))

    if is_linux and not has_display:
        xvfb = shutil.which("xvfb-run")
        if xvfb is None:
            return (
                None,
                "Headless Linux environment detected without X display. Install xvfb-run: sudo apt-get install -y xvfb",
            )
        return [xvfb, "-a", "-s", "-screen 0 1600x1200x24", *openscad_cmd], None

    return openscad_cmd, None


def render_png_from_scad(scad_path: Path, png_path: Path) -> tuple[bool, str]:
    cmd, setup_error = _openscad_png_command(scad_path, png_path)
    if setup_error:
        return False, setup_error

    assert cmd is not None

    try:
        completed = subprocess.run(cmd, capture_output=True, text=True, check=False)
    except FileNotFoundError:
        return False, "OpenSCAD command failed to start. Verify OpenSCAD installation and PATH."

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

    if shape_family == "seaweed":
        size_factor = scale_total(total, source_max, 0.85, 2.10)
    else:
        size_factor = scale_total(total, source_max, 0.85, 1.55)

    if shape_family == "starfish":
        scad_code = render_simple_scad(SCAD_STARFISH, title=title, size_factor=size_factor)
    elif shape_family == "seaweed":
        scad_code = render_simple_scad(SCAD_SEAWEED, title=title, size_factor=size_factor)
    elif shape_family == "clownfish":
        scad_code = render_simple_scad(SCAD_CLOWNFISH, title=title, size_factor=size_factor)
    else:
        result = {
            "job_id": job_id,
            "dataset_name": demo_file,
            "summary": summary,
            "preset": request_data["preset"],
            "export_mode": export_mode,
            "shape_family": shape_family,
        }
        update_job(
            job_id,
            status="error",
            message=f"OpenSCAD shape not supported: {shape_family}",
            result=result,
            summary=summary,
            stage="error",
            eta_seconds=None,
        )
        return

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

        finalize_job(job_id, status="done", message="Preview generated.",
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

        finalize_job(job_id, status="done", message="STL generated.",
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

            finalize_job(job_id, status="done", message="ZIP bundle generated.",
                result=result,
                summary=summary,
                progress=100,
                stage="done",
                eta_seconds=None,
            )
            return
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

def render_png_from_stl_with_openscad(stl_path: Path, png_path: Path) -> tuple[bool, str]:
    wrapper_scad = GENERATED_DIR / f"_preview_{stl_path.stem}.scad"

    wrapper_code = f"""
$fn=96;

module preview_model() {{
    import("{stl_path.as_posix()}");
}}

color([1.0, 0.45, 0.20])
preview_model();
""".strip()

    wrapper_scad.write_text(wrapper_code, encoding="utf-8")

    try:
        cmd, setup_error = _openscad_png_command(wrapper_scad, png_path)
        if setup_error:
            return False, setup_error

        assert cmd is not None

        try:
            completed = subprocess.run(cmd, capture_output=True, text=True, check=False)
        except FileNotFoundError:
            return False, "OpenSCAD command failed to start. Verify OpenSCAD installation and PATH."

        if completed.returncode != 0:
            return False, (completed.stderr or completed.stdout or "PNG render from STL failed").strip()

        if not png_path.exists() or png_path.stat().st_size == 0:
            return False, "PNG render from STL produced no usable file."

        return True, ""
    finally:
        try:
            wrapper_scad.unlink(missing_ok=True)
        except Exception:
            pass

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
            message="Rendering STL with Blender for preview...",
            progress=55,
            stage="rendering_preview_stl",
            eta_seconds=None,
        )

        temp_stl_path = OUTPUT_DIR / f"reef_{job_id}_preview_tmp.stl"

        ok, message = run_blender(params_path, temp_stl_path, None)
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

        update_job(
            job_id,
            message="Rendering PNG preview with OpenSCAD...",
            progress=80,
            stage="rendering_png",
            eta_seconds=None,
        )

        ok, message = render_png_from_stl_with_openscad(temp_stl_path, main_png_path)
        try:
            temp_stl_path.unlink(missing_ok=True)
        except Exception:
            pass

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

        finalize_job(job_id, status="done", message="Preview generated.",
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
            message="Rendering STL with Blender...",
            progress=45,
            stage="rendering_stl",
            eta_seconds=None,
        )

        ok, message = run_blender(params_path, main_stl_path, None)
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

        update_job(
            job_id,
            message="Rendering PNG preview with OpenSCAD...",
            progress=82,
            stage="rendering_png",
            eta_seconds=None,
        )

        ok, message = render_png_from_stl_with_openscad(main_stl_path, main_png_path)
        if ok:
            result["png_url"] = f"/output/{main_png_name}"
        else:
            result["png_warning"] = message

        finalize_job(job_id, status="done", message="STL generated.",
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

            ok, message = run_blender(bundle_params_path, bundle_stl_path, None)
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

            ok, png_message = render_png_from_stl_with_openscad(bundle_stl_path, bundle_png_path)

            region_files.append({
                "region": "Main",
                "scad_url": None,
                "stl_url": f"/output/{main_stl_name}",
                "png_url": f"/output/{main_png_name}" if ok else None,
            })

            shutil.copy2(bundle_stl_path, main_stl_path)
            result["stl_url"] = f"/output/{main_stl_name}"

            if ok:
                shutil.copy2(bundle_png_path, main_png_path)
                result["png_url"] = f"/output/{main_png_name}"
            else:
                result["png_warning"] = png_message

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

            finalize_job(job_id, status="done", message="ZIP bundle generated.",
                result=result,
                summary=summary,
                progress=100,
                stage="done",
                eta_seconds=None,
            )
            return
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    update_job(
        job_id,
        status="error",
        message=f"Unknown export mode: {export_mode}",
        result=result,
        summary=summary,
        stage="error",
        eta_seconds=None,
    )



def finalize_job(job_id: str, status: str, message: str, **updates: Any) -> None:
    job = get_job_record(job_id) or {}
    started_at = job.get("started_at")
    duration_seconds = None
    if isinstance(started_at, (int, float)):
        duration_seconds = round(time.time() - started_at, 2)

    payload = {
        "status": status,
        "message": message,
        "duration_seconds": duration_seconds,
        **updates,
    }
    update_job(job_id, **payload)

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

        if shape_family == "clownfish":
            process_blender_job(job_id, request_data, agg, summary)
            return

        process_blender_job(job_id, request_data, agg, summary)

    except Exception as exc:
        traceback.print_exc()
        finalize_job(job_id, status="error", message=f"Unhandled server error: {exc}",
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
            "started_at": time.time(),
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
    candidate = Path(filename)
    if candidate.is_absolute() or candidate.name != filename:
        return JSONResponse({"error": "File not found."}, status_code=404)

    output_root = OUTPUT_DIR.resolve()
    path = (output_root / candidate).resolve()

    try:
        path.relative_to(output_root)
    except ValueError:
        return JSONResponse({"error": "File not found."}, status_code=404)

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
