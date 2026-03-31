
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

    # --- BODY ---
    body = add_uv_sphere(
        radius=1.3 * scale,
        scale=(2.0, 1.1, 0.9),
        location=(0, 0, 0),
        name="Body",
    )

    head = add_uv_sphere(
        radius=1.0 * scale,
        scale=(1.1, 1.0, 0.9),
        location=(-2.0 * scale, 0, 0),
        name="Head",
    )

    tail_core = add_uv_sphere(
        radius=0.7 * scale,
        scale=(0.7, 0.8, 0.8),
        location=(2.4 * scale, 0, 0),
        name="TailCore",
    )

    # --- TAIL ---
    tail_top = add_cone(
        location=(3.3 * scale, 0, 0.8 * scale),
        radius1=0.9 * scale,
        radius2=0.05 * scale,
        depth=2.0 * scale,
        rotation=(0, math.radians(90), 0),
        name="TailTop",
    )

    tail_bottom = add_cone(
        location=(3.3 * scale, 0, -0.8 * scale),
        radius1=0.9 * scale,
        radius2=0.05 * scale,
        depth=2.0 * scale,
        rotation=(0, math.radians(90), 0),
        name="TailBottom",
    )

    # --- FINS ---
    dorsal = add_cone(
        location=(0, 0, 1.3 * scale),
        radius1=0.8 * scale,
        radius2=0.1 * scale,
        depth=1.6 * scale,
        rotation=(math.radians(90), 0, 0),
        name="Dorsal",
    )

    ventral = add_cone(
        location=(0, 0, -1.1 * scale),
        radius1=0.5 * scale,
        radius2=0.1 * scale,
        depth=1.2 * scale,
        rotation=(math.radians(-90), 0, 0),
        name="Ventral",
    )

    pectoral = add_cone(
        location=(-1.0 * scale, 1.0 * scale, 0),
        radius1=0.4 * scale,
        radius2=0.05 * scale,
        depth=1.0 * scale,
        rotation=(0, math.radians(70), math.radians(20)),
        name="Pectoral",
    )

    objects = [
        body,
        head,
        tail_core,
        tail_top,
        tail_bottom,
        dorsal,
        ventral,
        pectoral,
    ]

    fish = join_objects(objects, name="Clownfish")

    # 🔥 WICHTIG: weniger zerstörerisch als vorher
    add_remesh(fish, voxel_size=0.08 * scale)
    shade_smooth(fish)

    # --- STRIPES (optional) ---
    for xpos in (-1.5 * scale, 0.0 * scale, 1.2 * scale):
        bpy.ops.mesh.primitive_cube_add(location=(xpos, 0, 0))
        cutter = bpy.context.active_object
        cutter.scale = (0.25 * scale, 3.0 * scale, 2.0 * scale)

        mod = fish.modifiers.new(name="StripeCut", type="BOOLEAN")
        mod.operation = "DIFFERENCE"
        mod.object = cutter
        apply_modifier(fish, mod.name)

        bpy.data.objects.remove(cutter, do_unlink=True)

    shade_smooth(fish)

    return fish, (0, 0, 0.3 * scale), 1.4 * scale

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
