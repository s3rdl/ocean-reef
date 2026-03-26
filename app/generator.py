import json
import math
import shutil
import subprocess
import zipfile
from collections import defaultdict
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
GENERATED_DIR = PROJECT_ROOT / "generated"
OUTPUT_DIR = PROJECT_ROOT / "output"
SCAD_TEMPLATE_PATH = PROJECT_ROOT / "templates" / "reef_template.scad"

GENERATED_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

REGION_ORDER = [
    "Europe",
    "Africa",
    "Asia-Pacific",
    "North America",
    "South America",
    "Oceania",
]

REGION_COLORS = {
    "Europe": [0.15, 0.55, 0.85],
    "Africa": [0.90, 0.75, 0.35],
    "Asia-Pacific": [0.20, 0.75, 0.65],
    "North America": [0.75, 0.40, 0.85],
    "South America": [0.35, 0.75, 0.35],
    "Oceania": [0.95, 0.45, 0.45],
}

PRESETS = {
    "balanced": {
        "label": "Balanced",
        "branch_density": 1.0,
        "branch_thickness": 1.0,
        "height_boost": 1.0,
        "base_scale": 1.0,
    },
    "x1c_safe": {
        "label": "Bambu X1C Safe Print",
        "branch_density": 0.9,
        "branch_thickness": 1.15,
        "height_boost": 0.95,
        "base_scale": 1.08,
    },
    "dramatic": {
        "label": "Dramatic Growth",
        "branch_density": 1.2,
        "branch_thickness": 0.95,
        "height_boost": 1.2,
        "base_scale": 1.0,
    },
}

EXPORT_MODES = {
    "stl": "Single STL",
    "separate_regions": "Separate regions ZIP",
    "scad_only": "SCAD only",
}


class GeneratorError(Exception):
    pass


@dataclass
class GeneratorParams:
    source_max: int = 100000
    branch_density: float = 1.0
    branch_thickness: float = 1.0
    height_boost: float = 1.0
    base_scale: float = 1.0
    export_mode: str = "stl"
    render_stl: bool = True


@dataclass
class GenerationResult:
    run_id: str
    title: str
    summary: dict[str, Any]
    params: dict[str, Any]
    scad_filename: str
    stl_filename: str | None
    scad_path: str
    stl_path: str | None
    openscad_available: bool
    bundle_filename: str | None = None
    bundle_path: str | None = None
    region_outputs: list[dict[str, str]] | None = None


def load_signatures(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as file:
        data = json.load(file)
    if not isinstance(data, list):
        raise GeneratorError("Signature data must be a JSON list.")
    return data


def parse_timestamp(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(timezone.utc)


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def scale_total(total: int, source_max: int, out_min: float, out_max: float) -> float:
    if source_max <= 0:
        return out_min
    ratio = clamp(total / source_max, 0.0, 1.0)
    return out_min + (out_max - out_min) * ratio


def slugify(value: str) -> str:
    allowed = []
    for ch in value.lower():
        if ch.isalnum():
            allowed.append(ch)
        else:
            allowed.append("_")
    slug = "".join(allowed)
    while "__" in slug:
        slug = slug.replace("__", "_")
    return slug.strip("_") or "item"


def summarize_signatures(signatures: list[dict[str, Any]]) -> dict[str, Any]:
    counts_by_region: dict[str, int] = defaultdict(int)
    recent_by_region: dict[str, int] = defaultdict(int)
    timestamps: list[datetime] = []

    for signature in signatures:
        region = signature.get("region", "Unknown")
        counts_by_region[region] += 1
        ts = signature.get("timestamp")
        if ts:
            try:
                timestamps.append(parse_timestamp(ts))
            except ValueError:
                continue

    latest_ts = max(timestamps) if timestamps else None
    earliest_ts = min(timestamps) if timestamps else None

    if latest_ts is not None:
        for signature in signatures:
            ts = signature.get("timestamp")
            if not ts:
                continue
            try:
                dt = parse_timestamp(ts)
            except ValueError:
                continue
            age_hours = (latest_ts - dt).total_seconds() / 3600.0
            if age_hours <= 24:
                recent_by_region[signature.get("region", "Unknown")] += 1

    total = len(signatures)
    ranked_regions = sorted(counts_by_region.items(), key=lambda item: (-item[1], item[0]))

    return {
        "total": total,
        "counts_by_region": dict(counts_by_region),
        "recent_by_region": dict(recent_by_region),
        "top_regions": ranked_regions,
        "earliest_timestamp": earliest_ts.isoformat() if earliest_ts else None,
        "latest_timestamp": latest_ts.isoformat() if latest_ts else None,
    }


def build_branch_data(summary: dict[str, Any], params: GeneratorParams) -> dict[str, Any]:
    total = summary["total"]
    counts_by_region = summary["counts_by_region"]
    recent_by_region = summary["recent_by_region"]

    base_radius = scale_total(total, params.source_max, 28.0, 48.0) * params.base_scale
    core_height = scale_total(total, params.source_max, 35.0, 90.0) * params.height_boost

    branches = []

    for index, region in enumerate(REGION_ORDER):
        count = counts_by_region.get(region, 0)
        recent = recent_by_region.get(region, 0)
        region_ratio = (count / total) if total > 0 else 0.0

        if count == 0:
            branch_count = 1
            branch_height = 18.0 * params.height_boost
            branch_radius = 2.4 * params.branch_thickness
            twist = 0.0
        else:
            branch_count = max(2, min(10, math.ceil(region_ratio * 18 * params.branch_density)))
            branch_height = (28.0 + region_ratio * 95.0) * params.height_boost
            branch_radius = (2.6 + region_ratio * 6.0) * params.branch_thickness
            twist = min(18.0, recent * 1.2)

        sector_start = index * (360.0 / len(REGION_ORDER))
        sector_end = (index + 1) * (360.0 / len(REGION_ORDER))

        branches.append(
            {
                "region": region,
                "color": REGION_COLORS[region],
                "count": int(branch_count),
                "height": round(branch_height, 2),
                "radius": round(branch_radius, 2),
                "sector_start": round(sector_start, 2),
                "sector_end": round(sector_end, 2),
                "twist": round(twist, 2),
                "has_signatures": count > 0,
                "signature_count": count,
            }
        )

    return {
        "base_radius": round(base_radius, 2),
        "core_height": round(core_height, 2),
        "branches": branches,
    }


def render_branch_block(branch: dict[str, Any]) -> str:
    return f"""
regional_cluster(
    region_name=\"{branch['region']}\",
    cluster_count={branch['count']},
    branch_height={branch['height']},
    branch_radius={branch['radius']},
    sector_start={branch['sector_start']},
    sector_end={branch['sector_end']},
    twist={branch['twist']},
    rgb=[{branch['color'][0]}, {branch['color'][1]}, {branch['color'][2]}]
);
"""


def render_scad(template: str, model_data: dict[str, Any], title: str, region_filter: str | None = None) -> str:
    branch_blocks = []

    for branch in model_data["branches"]:
        if region_filter is not None and branch["region"] != region_filter:
            continue
        branch_blocks.append(render_branch_block(branch))

    return (
        template.replace("{{TITLE}}", title)
        .replace("{{BASE_RADIUS}}", str(model_data["base_radius"]))
        .replace("{{CORE_HEIGHT}}", str(model_data["core_height"]))
        .replace("{{BRANCH_BLOCKS}}", "\n".join(branch_blocks))
    )


def openscad_available() -> bool:
    return shutil.which("openscad") is not None


def render_stl(scad_path: Path, stl_path: Path) -> None:
    command = ["openscad", "-o", str(stl_path), str(scad_path)]
    completed = subprocess.run(command, capture_output=True, text=True)
    if completed.returncode != 0:
        raise GeneratorError(
            "OpenSCAD render failed:\n"
            f"STDOUT:\n{completed.stdout}\n\nSTDERR:\n{completed.stderr}"
        )


def build_metadata_payload(
    title: str,
    run_id: str,
    summary: dict[str, Any],
    params: GeneratorParams,
    region_outputs: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    return {
        "title": title,
        "run_id": run_id,
        "summary": summary,
        "params": asdict(params),
        "region_outputs": region_outputs or [],
    }


def write_bundle_zip(bundle_path: Path, files_to_add: list[tuple[Path, str]], metadata: dict[str, Any]) -> None:
    with zipfile.ZipFile(bundle_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path, arcname in files_to_add:
            zf.write(path, arcname)
        zf.writestr("params.json", json.dumps(metadata, indent=2, ensure_ascii=False))


def generate_from_signatures(
    signatures: list[dict[str, Any]],
    title: str,
    run_id: str,
    params: GeneratorParams,
) -> GenerationResult:
    if params.export_mode not in EXPORT_MODES:
        raise GeneratorError(f"Unsupported export mode: {params.export_mode}")

    summary = summarize_signatures(signatures)
    model_data = build_branch_data(summary, params)
    template = SCAD_TEMPLATE_PATH.read_text(encoding="utf-8")
    has_openscad = openscad_available()

    scad_filename = f"{run_id}.scad"
    scad_path = GENERATED_DIR / scad_filename
    scad_content = render_scad(template, model_data, title)
    scad_path.write_text(scad_content, encoding="utf-8")

    region_outputs: list[dict[str, str]] = []
    bundle_filename: str | None = None
    bundle_path: Path | None = None
    stl_filename: str | None = None
    stl_path: Path | None = None

    if params.export_mode == "stl":
        stl_filename = f"{run_id}.stl"
        stl_path = OUTPUT_DIR / stl_filename
        if params.render_stl:
            if not has_openscad:
                raise GeneratorError(
                    "SCAD was generated, but STL render was skipped because OpenSCAD is not available in PATH."
                )
            render_stl(scad_path, stl_path)

    elif params.export_mode == "separate_regions":
        if params.render_stl and not has_openscad:
            raise GeneratorError(
                "Separate-region export needs OpenSCAD in PATH because it renders one STL per region."
            )

        files_for_zip: list[tuple[Path, str]] = [(scad_path, f"{run_id}/{scad_filename}")]

        for branch in model_data["branches"]:
            if not branch["has_signatures"]:
                continue

            region_slug = slugify(branch["region"])
            region_scad_filename = f"{run_id}_{region_slug}.scad"
            region_stl_filename = f"{run_id}_{region_slug}.stl"
            region_scad_path = GENERATED_DIR / region_scad_filename
            region_stl_path = OUTPUT_DIR / region_stl_filename

            region_scad_content = render_scad(template, model_data, f"{title} - {branch['region']}", branch["region"])
            region_scad_path.write_text(region_scad_content, encoding="utf-8")

            if params.render_stl:
                render_stl(region_scad_path, region_stl_path)
                files_for_zip.append((region_stl_path, f"{run_id}/regions/{region_stl_filename}"))

            files_for_zip.append((region_scad_path, f"{run_id}/regions/{region_scad_filename}"))
            region_outputs.append(
                {
                    "region": branch["region"],
                    "scad_filename": region_scad_filename,
                    "stl_filename": region_stl_filename,
                }
            )

        bundle_filename = f"{run_id}_regions.zip"
        bundle_path = OUTPUT_DIR / bundle_filename
        metadata = build_metadata_payload(title, run_id, summary, params, region_outputs)
        write_bundle_zip(bundle_path, files_for_zip, metadata)

    elif params.export_mode == "scad_only":
        bundle_filename = f"{run_id}_scad_bundle.zip"
        bundle_path = OUTPUT_DIR / bundle_filename
        metadata = build_metadata_payload(title, run_id, summary, params, region_outputs)
        write_bundle_zip(bundle_path, [(scad_path, f"{run_id}/{scad_filename}")], metadata)

    return GenerationResult(
        run_id=run_id,
        title=title,
        summary=summary,
        params=asdict(params),
        scad_filename=scad_filename,
        stl_filename=stl_filename,
        scad_path=str(scad_path),
        stl_path=str(stl_path) if stl_path else None,
        openscad_available=has_openscad,
        bundle_filename=bundle_filename,
        bundle_path=str(bundle_path) if bundle_path else None,
        region_outputs=region_outputs,
    )
