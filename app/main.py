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

for directory in (DATA_DIR, GENERATED_DIR, OUTPUT_DIR):
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
    "coral": "Coral",
    "starfish": "Starfish",
    "seaweed": "Seaweed",
    "clownfish": "Clownfish",
}

SCAD_CORAL = r"""
$fn = 72;

// {{TITLE}}

base_radius = {{BASE_RADIUS}};
core_height = {{CORE_HEIGHT}};
branch_scale = {{BRANCH_SCALE}};
branch_count = {{BRANCH_COUNT}};

module sphere_link(x0, y0, z0, r0, x1, y1, z1, r1) {
    hull() {
        translate([x0, y0, z0]) sphere(r=r0);
        translate([x1, y1, z1]) sphere(r=r1);
    }
}

module coral_arm(seed_angle=0, arm_bend=1.0, arm_twist=0) {
    union() {
        for (i = [0:7]) {
            z0 = i * core_height / 8;
            z1 = (i + 1) * core_height / 8;

            x0 = sin(seed_angle + i * (8 + arm_twist)) * (2 + i * 2.8) * arm_bend;
            x1 = sin(seed_angle + (i + 1) * (8 + arm_twist)) * (2 + (i + 1) * 2.8) * arm_bend;

            y0 = cos(seed_angle + i * (6 + arm_twist * 0.5)) * (1.4 + i * 1.6);
            y1 = cos(seed_angle + (i + 1) * (6 + arm_twist * 0.5)) * (1.4 + (i + 1) * 1.6);

            r0 = max((6.2 - i * 0.55) * branch_scale, 1.8 * branch_scale);
            r1 = max((6.2 - (i + 1) * 0.55) * branch_scale, 1.4 * branch_scale);

            sphere_link(x0, y0, z0, r0, x1, y1, z1, r1);

            if (i >= 3 && i <= 5) {
                bx0 = x1;
                by0 = y1;
                bz0 = z1;

                bx1 = x1 + sin(seed_angle + 90 + i * 16) * 10 * arm_bend;
                by1 = y1 + cos(seed_angle + 90 + i * 13) * 7 * arm_bend;
                bz1 = z1 + 10 + i * 1.2;

                br0 = r1 * 0.72;
                br1 = max(r1 * 0.42, 1.1 * branch_scale);

                sphere_link(bx0, by0, bz0, br0, bx1, by1, bz1, br1);
            }
        }
    }
}

module coral_base() {
    hull() {
        cylinder(h=8, r=base_radius);
        translate([0, 0, 4]) cylinder(h=5, r=base_radius * 0.82);
    }
}

union() {
    coral_base();

    for (i = [0:branch_count - 1]) {
        angle = i * 360 / branch_count;
        rotate([0, 0, angle])
            translate([base_radius * 0.18, 0, 4])
                coral_arm(
                    seed_angle=angle * 0.55,
                    arm_bend=0.90 + (i % 3) * 0.10,
                    arm_twist=(i % 4) * 2
                );
    }
}
"""

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

SCAD_CLOWNFISH = r"""
$fn = 96;

// {{TITLE}}

size_factor = {{SIZE_FACTOR}};
body_h = 19 * size_factor;
body_w = 14 * size_factor;
body_len = 74 * size_factor;
tail_len = 18 * size_factor;
stripe_depth = 2.2 * size_factor;

module body_core() {
    hull() {
        translate([-body_len * 0.42, 0, 0]) scale([1.00, 0.88, 0.72]) sphere(r=body_h);
        translate([-body_len * 0.15, 0, 0]) scale([1.28, 0.98, 0.84]) sphere(r=body_h);
        translate([body_len * 0.12, 0, 0]) scale([1.08, 0.94, 0.78]) sphere(r=body_h * 0.96);
        translate([body_len * 0.34, 0, 0]) scale([0.70, 0.76, 0.58]) sphere(r=body_h * 0.90);
    }
}

module tail_fin() {
    hull() {
        translate([body_len * 0.48, 0, 0]) scale([0.26, 0.45, 0.42]) sphere(r=body_h);
        translate([body_len * 0.48 + tail_len, 0, body_h * 0.78]) sphere(r=body_w * 0.70);
        translate([body_len * 0.48 + tail_len, 0, -body_h * 0.78]) sphere(r=body_w * 0.70);
    }
}

module dorsal_fin() {
    hull() {
        translate([-10 * size_factor, 0, body_h * 0.70]) sphere(r=body_w * 0.48);
        translate([2 * size_factor, 0, body_h * 1.15]) sphere(r=body_w * 0.34);
        translate([18 * size_factor, 0, body_h * 0.82]) sphere(r=body_w * 0.22);
    }
}

module ventral_fin() {
    hull() {
        translate([-2 * size_factor, 0, -body_h * 0.54]) sphere(r=body_w * 0.30);
        translate([12 * size_factor, 0, -body_h * 0.84]) sphere(r=body_w * 0.20);
        translate([20 * size_factor, 0, -body_h * 0.58]) sphere(r=body_w * 0.16);
    }
}

module pectoral_fin() {
    hull() {
        translate([-12 * size_factor, body_w * 0.60, 1 * size_factor]) sphere(r=body_w * 0.28);
        translate([-2 * size_factor, body_w * 1.05, 3 * size_factor]) sphere(r=body_w * 0.16);
        translate([8 * size_factor, body_w * 0.72, 0]) sphere(r=body_w * 0.12);
    }
}

module clownfish_raw() {
    union() {
        body_core();
        tail_fin();
        dorsal_fin();
        ventral_fin();
        pectoral_fin();
    }
}

module stripe_cut(xpos, width, tilt=0) {
    translate([xpos, 0, 0])
        rotate([0, tilt, 0])
            cube([width, body_w * 3.2, body_h * 3.0], center=true);
}

difference() {
    clownfish_raw();

    translate([-body_len * 0.28, body_w * 0.28, body_h * 0.18])
        sphere(r=body_w * 0.11);

    stripe_cut(-body_len * 0.18, stripe_depth, 8);
    stripe_cut(0, stripe_depth * 1.25, 2);
    stripe_cut(body_len * 0.22, stripe_depth, -5);
}
"""


JOBS: dict[str, dict[str, Any]] = {}
JOBS_LOCK = threading.Lock()


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


def build_branch_data(
    agg: dict[str, Any],
    source_max: int,
    base_radius_multiplier: float,
    core_height_multiplier: float,
    branch_density_multiplier: float,
    branch_thickness_multiplier: float,
) -> dict[str, Any]:
    total = agg["total"]
    counts_by_region = agg["counts_by_region"]
    recent_by_region = agg["recent_by_region"]

    base_radius = scale_total(total, source_max, 22.0, 34.0) * base_radius_multiplier
    core_height = scale_total(total, source_max, 42.0, 88.0) * core_height_multiplier
    branch_scale = scale_total(total, source_max, 0.85, 1.35) * branch_thickness_multiplier
    branch_count = max(10, min(24, math.ceil(10 + total / max(source_max, 1) * 18 * branch_density_multiplier)))

    return {
        "base_radius": round(base_radius, 2),
        "core_height": round(core_height, 2),
        "branch_scale": round(branch_scale, 3),
        "branch_count": int(branch_count),
    }


def render_coral_scad(template: str, model_data: dict[str, Any], title: str) -> str:
    return (
        template
        .replace("{{TITLE}}", title)
        .replace("{{BASE_RADIUS}}", str(model_data["base_radius"]))
        .replace("{{CORE_HEIGHT}}", str(model_data["core_height"]))
        .replace("{{BRANCH_SCALE}}", str(model_data["branch_scale"]))
        .replace("{{BRANCH_COUNT}}", str(model_data["branch_count"]))
    )


def render_simple_scad(template: str, title: str, size_factor: float) -> str:
    return (
        template
        .replace("{{TITLE}}", title)
        .replace("{{SIZE_FACTOR}}", str(round(size_factor, 3)))
    )


def build_shape_scad(
    shape_family: str,
    title: str,
    model_data: dict[str, Any],
    total: int,
    source_max: int,
) -> str:
    if shape_family == "coral":
        return render_coral_scad(SCAD_CORAL, model_data, title=title)

    size_factor = scale_total(total, source_max, 0.85, 1.55)

    if shape_family == "starfish":
        return render_simple_scad(SCAD_STARFISH, title=title, size_factor=size_factor)
    if shape_family == "seaweed":
        return render_simple_scad(SCAD_SEAWEED, title=title, size_factor=size_factor)
    if shape_family == "clownfish":
        return render_simple_scad(SCAD_CLOWNFISH, title=title, size_factor=size_factor)

    return render_coral_scad(SCAD_CORAL, model_data, title=title)


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


def process_job(job_id: str, request_data: dict[str, Any]) -> None:
    try:
        update_job(
            job_id,
            status="running",
            message="Loading dataset...",
            progress=10,
            stage="loading_dataset",
            eta_seconds=20,
        )

        demo_file = request_data["demo_file"]
        export_mode = request_data["export_mode"]
        source_max = int(request_data["source_max"])
        base_radius_multiplier = float(request_data["base_radius_multiplier"])
        core_height_multiplier = float(request_data["core_height_multiplier"])
        branch_density_multiplier = float(request_data["branch_density_multiplier"])
        branch_thickness_multiplier = float(request_data["branch_thickness_multiplier"])
        shape_family = request_data["shape_family"]

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
            eta_seconds=18,
        )

        model_data = build_branch_data(
            agg=agg,
            source_max=source_max,
            base_radius_multiplier=base_radius_multiplier,
            core_height_multiplier=core_height_multiplier,
            branch_density_multiplier=branch_density_multiplier,
            branch_thickness_multiplier=branch_thickness_multiplier,
        )

        total = agg["total"]

        title = f"Ocean Reef Prototype - {demo_file} - {shape_family}"
        main_scad_name = f"reef_{job_id}.scad"
        main_stl_name = f"reef_{job_id}.stl"
        main_png_name = f"reef_{job_id}.png"

        main_scad_path = GENERATED_DIR / main_scad_name
        main_stl_path = OUTPUT_DIR / main_stl_name
        main_png_path = OUTPUT_DIR / main_png_name

        scad_code = build_shape_scad(
            shape_family=shape_family,
            title=title,
            model_data=model_data,
            total=total,
            source_max=source_max,
        )
        main_scad_path.write_text(scad_code, encoding="utf-8")

        result: dict[str, Any] = {
            "job_id": job_id,
            "dataset_name": demo_file,
            "summary": summary,
            "preset": request_data["preset"],
            "export_mode": export_mode,
            "shape_family": shape_family,
            "scad_url": f"/generated/{main_scad_name}",
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
                message="Rendering PNG preview...",
                progress=75,
                stage="rendering_png",
                eta_seconds=8,
            )

            ok, message = render_png_from_scad(main_scad_path, main_png_path)
            if ok:
                result["png_url"] = f"/output/{main_png_name}"
            else:
                result["png_warning"] = message

            update_job(
                job_id,
                status="done",
                message="SCAD generated.",
                result=result,
                summary=summary,
                progress=100,
                stage="done",
                eta_seconds=0,
            )
            return

        if export_mode == "single_stl":
            update_job(
                job_id,
                message="Rendering STL with OpenSCAD...",
                progress=45,
                stage="rendering_stl",
                eta_seconds=40,
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

            update_job(
                job_id,
                message="Rendering PNG preview...",
                progress=82,
                stage="rendering_png",
                eta_seconds=12,
            )

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
                eta_seconds=0,
            )
            return

        if export_mode == "separate_regions_zip":
            update_job(
                job_id,
                message="Rendering separate region files...",
                progress=35,
                stage="rendering_regions",
                eta_seconds=90,
            )

            region_files: list[dict[str, str | None]] = []
            zip_name = f"reef_bundle_{job_id}.zip"
            zip_path = OUTPUT_DIR / zip_name

            temp_dir = Path(tempfile.mkdtemp(prefix=f"reef_{job_id}_"))
            try:
                bundle_params = {
                    "job_id": job_id,
                    "dataset_name": demo_file,
                    "export_mode": export_mode,
                    "summary": summary,
                    "shape_family": shape_family,
                    "params": result["params"],
                }
                (temp_dir / "params.json").write_text(
                    json.dumps(bundle_params, indent=2, ensure_ascii=False),
                    encoding="utf-8",
                )
                shutil.copy2(main_scad_path, temp_dir / main_scad_name)

                if shape_family != "coral":
                    region_slug = "main"
                    region_scad_name = f"reef_{job_id}_{region_slug}.scad"
                    region_stl_name = f"reef_{job_id}_{region_slug}.stl"
                    region_png_name = f"reef_{job_id}_{region_slug}.png"

                    region_scad_path = GENERATED_DIR / region_scad_name
                    region_stl_path = OUTPUT_DIR / region_stl_name
                    region_png_path = OUTPUT_DIR / region_png_name

                    region_scad_path.write_text(scad_code, encoding="utf-8")

                    ok, message = run_openscad(region_scad_path, region_stl_path)
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

                    region_png_url = None
                    ok, _ = render_png_from_scad(region_scad_path, region_png_path)
                    if ok:
                        region_png_url = f"/output/{region_png_name}"

                    shutil.copy2(region_scad_path, temp_dir / region_scad_name)
                    shutil.copy2(region_stl_path, temp_dir / region_stl_name)
                    if region_png_url and region_png_path.exists():
                        shutil.copy2(region_png_path, temp_dir / region_png_name)

                    region_files.append({
                        "region": "Main",
                        "scad_url": f"/generated/{region_scad_name}",
                        "stl_url": f"/output/{region_stl_name}",
                        "png_url": region_png_url,
                    })
                else:
                    region_slug = "main"
                    region_scad_name = f"reef_{job_id}_{region_slug}.scad"
                    region_stl_name = f"reef_{job_id}_{region_slug}.stl"
                    region_png_name = f"reef_{job_id}_{region_slug}.png"

                    region_scad_path = GENERATED_DIR / region_scad_name
                    region_stl_path = OUTPUT_DIR / region_stl_name
                    region_png_path = OUTPUT_DIR / region_png_name

                    region_scad_path.write_text(scad_code, encoding="utf-8")

                    ok, message = run_openscad(region_scad_path, region_stl_path)
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

                    region_png_url = None
                    ok, _ = render_png_from_scad(region_scad_path, region_png_path)
                    if ok:
                        region_png_url = f"/output/{region_png_name}"

                    shutil.copy2(region_scad_path, temp_dir / region_scad_name)
                    shutil.copy2(region_stl_path, temp_dir / region_stl_name)
                    if region_png_url and region_png_path.exists():
                        shutil.copy2(region_png_path, temp_dir / region_png_name)

                    region_files.append({
                        "region": "Main",
                        "scad_url": f"/generated/{region_scad_name}",
                        "stl_url": f"/output/{region_stl_name}",
                        "png_url": region_png_url,
                    })

                update_job(
                    job_id,
                    message="Packaging ZIP...",
                    progress=95,
                    stage="packaging_zip",
                    eta_seconds=5,
                )

                with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                    for file_path in temp_dir.glob("*"):
                        zf.write(file_path, arcname=file_path.name)

                result["region_files"] = region_files
                result["zip_url"] = f"/output/{zip_name}"

                if region_files:
                    first_png = next((r["png_url"] for r in region_files if r.get("png_url")), None)
                    if first_png:
                        result["png_url"] = first_png

                update_job(
                    job_id,
                    status="done",
                    message="ZIP bundle generated.",
                    result=result,
                    summary=summary,
                    progress=100,
                    stage="done",
                    eta_seconds=0,
                )
                return
            finally:
                shutil.rmtree(temp_dir, ignore_errors=True)

        update_job(
            job_id,
            status="error",
            message=f"Unknown export mode: {export_mode}",
            stage="error",
            eta_seconds=None,
        )

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
    elif suffix == ".scad":
        media_type = "text/plain; charset=utf-8"
    else:
        guessed_type, _ = mimetypes.guess_type(str(path))
        media_type = guessed_type or "application/octet-stream"

    return FileResponse(path, media_type=media_type)