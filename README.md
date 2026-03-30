# Ocean Reef Prototype UI --- Phase D

Phase D transforms the system from a single-object generator into a
**multi-shape ocean motif generator** with preview rendering, async
jobs, and improved UX.

------------------------------------------------------------------------

## 🚀 What's New in Phase D

### 🧩 Shape Families (Motif Generator)

Instead of generating only one coral structure, the system now supports
multiple **printable shape families**:

-   Coral (improved, still organic)
-   Starfish (printable, solid)
-   Seaweed (connected organic structure)
-   Shell (spiral-based geometry)
-   Clownfish (stylized printable fish)

👉 Goal: generate **printable, connected meshes**, not just abstract
blobs.

------------------------------------------------------------------------

### 🖼 PNG Preview Rendering

-   Automatic preview image (`.png`) for every generated model
-   Works **headless via `xvfb-run`**
-   No browser 3D support required

------------------------------------------------------------------------

### ⚙️ Async Job System

-   Background processing via threads
-   `/generate` returns immediately
-   `/job/{id}` provides live status

Includes: - progress (%) - stage (pipeline step) - ETA estimation

------------------------------------------------------------------------

### 📊 Improved UI

-   Progress bar + ETA
-   Reduced polling noise
-   Retry logic for unstable connections
-   Cleaned "raw response" panel
-   Region-based preview selection (for ZIP mode)

------------------------------------------------------------------------

### 🔁 Smart Polling (NEW)

Frontend now: - retries polling on failure - avoids instant "Polling
failed" - handles temporary server hiccups

------------------------------------------------------------------------

## ⚠️ Important Runtime Note

For long jobs **DO NOT use `--reload`**

❌ Bad:

``` bash
uvicorn app.main:app --reload
```

✅ Good:

``` bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Reason: - jobs are stored in memory - reload restarts the server → job
state lost

------------------------------------------------------------------------

## 📦 Requirements

-   Python 3.11+
-   OpenSCAD (CLI)
-   xvfb (for PNG rendering)

Install system dependencies:

``` bash
sudo apt-get install -y openscad xvfb
```

------------------------------------------------------------------------

## 🛠 Install

``` bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

------------------------------------------------------------------------

## ▶️ Run

``` bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Open:

    http://127.0.0.1:8000

------------------------------------------------------------------------

## 🎛 Export Modes

### 1. Single STL

Generates: - `.stl` - `.scad` - `.png` preview

------------------------------------------------------------------------

### 2. Separate Regions ZIP

Generates: - master `.scad` - per-region `.scad` - per-region `.stl` -
per-region `.png` - `params.json` - bundled `.zip`

------------------------------------------------------------------------

### 3. SCAD Only

Generates: - `.scad` - `.png` preview

------------------------------------------------------------------------

## 🖼 Preview System

-   Server renders PNG using OpenSCAD
-   Uses virtual framebuffer (xvfb)
-   No GPU required

------------------------------------------------------------------------

## 🧠 Data Processing

Each dataset is aggregated into:

-   total signatures
-   per-region counts
-   recent (24h) activity

These drive: - geometry size - density - distribution

------------------------------------------------------------------------

## 🧾 Minimal Input Schema

``` json
{
  "id": "sig-1",
  "region": "Europe",
  "timestamp": "2026-03-20T08:00:00Z"
}
```

------------------------------------------------------------------------

## 🔧 Known Limitations

-   Some shapes still evolving (especially coral aesthetics)
-   No persistent job storage yet (RAM only)
-   PNG rendering depends on OpenSCAD stability

------------------------------------------------------------------------

## 🔮 Next Steps (Phase E)

-   Persistent job storage (JSON / DB)
-   Better geometry merging for all shapes
-   Blender pipeline (optional)
-   Multi-object scenes (reef compositions)

------------------------------------------------------------------------

## 💥 TL;DR

-   You now generate **printable ocean objects**
-   You get **PNG previews automatically**
-   The UI is **stable + async + user-friendly**
-   The system is now a **motif generator, not just coral**
