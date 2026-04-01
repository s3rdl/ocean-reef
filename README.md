# Ocean Reef Prototype UI — Phase D+

Phase D+ evolves the system into a **hybrid geometry pipeline** combining:
- OpenSCAD (robust previews + simple geometry)
- Blender (organic mesh generation)

---

## 🚀 What’s New (Extended)

### 🧩 Hybrid Shape Pipeline
- **OpenSCAD** → Starfish, Seaweed (fast + reliable previews)
- **Blender** → Clownfish, Coral (organic meshes)
- Automatic routing depending on shape

---

### 🖼 PNG Rendering (FIXED)
- **All previews now generated via OpenSCAD**
- Blender PNG rendering disabled (was producing grey images)
- STL → PNG via wrapper SCAD

---

### 🐟 Clownfish (Reworked)
- Fully Blender-based mesh
- Mirror + Subsurf workflow
- No more primitive cones → proper mesh fins
- Still WIP but now clearly “fish-like”

---

### ⚙️ Async Job System
- Thread-based processing
- `/generate` → immediate response
- `/job/{id}` → progress tracking

---

### 📊 Job Status Improvements
- progress (%)
- stage (pipeline step)
- better error visibility

---

## ⚠️ Critical Notes

### DO NOT use reload
```bash
uvicorn app.main:app --reload
```
→ breaks jobs

Use:
```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

---

## 📦 Requirements

```bash
sudo apt-get install -y openscad xvfb blender
```

Python:
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

---

## ▶️ Run

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

---

## 🎛 Export Modes

### Single STL
- STL
- PNG (OpenSCAD)
- optional SCAD

### ZIP Bundle
- STL + PNG + params
- packaged output

### SCAD Only
- SCAD + PNG preview

---

## 🖼 Preview System (Important)

### Blender shapes
1. Blender → STL
2. OpenSCAD wrapper → PNG

### OpenSCAD shapes
SCAD → PNG directly

---

## 🔧 Known Issues

- Seaweed/Starfish depend on SCAD pipeline consistency
- Blender shapes still stylistically evolving
- No persistence (jobs in RAM)

---

## 🔮 Next Steps

- Persist jobs
- Improve fish topology (Nemo-style)
- unify shading / preview look
- optional GLB export again

---

## 💥 TL;DR

- Hybrid pipeline works
- PNG previews stable again
- Blender only used for geometry
- System finally predictable again
