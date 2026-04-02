# Ocean Reef Prototype UI — Phase D+

Phase D+ evolves the system into a **hybrid geometry pipeline** combining:
- OpenSCAD (robust previews + simple geometry)
- Blender (organic mesh generation)

---

## 🚀 What’s New (Updated)

### 🧩 Hybrid Shape Pipeline
- **OpenSCAD** → Starfish, Seaweed (fast + reliable previews)
- **Blender** → Clownfish, Coral (organic meshes)
- Automatic routing depending on shape

---

### 🖼 PNG Rendering (STABLE)
- All previews generated via OpenSCAD
- Blender PNG disabled (was producing grey images)
- STL → PNG via wrapper SCAD

---

### ⏱ Live Rendering Time (NEW)
- UI shows **live elapsed rendering time**
- Final **total render duration** shown after completion
- Improves transparency for long-running jobs (especially Seaweed)

---

### 🐢 Performance Improvements (Seaweed)
- Reduced `$fn`
- Fewer blade segments
- Reduced blade count

→ Result: **massively faster STL generation**

---

### 🔐 Basic Authentication (NEW)
- Simple HTTP Basic Auth added
- Prevents public access to the UI
- Suitable for quick internal deployments

---

### 🐟 Clownfish (Reworked)
- Fully Blender-based mesh
- Mirror + Subsurf workflow
- Proper mesh fins (no primitive cones)
- Still evolving stylistically

---

### ⚙️ Async Job System
- Thread-based processing
- `/generate` → immediate response
- `/job/{id}` → progress tracking

---

### 📊 Job Status Improvements
- progress (%)
- stage (pipeline step)
- live elapsed time
- final duration
- improved error visibility

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

## 🖼 Preview System

### Blender shapes
1. Blender → STL
2. OpenSCAD wrapper → PNG

### OpenSCAD shapes
SCAD → PNG directly

---

## 🔧 Known Issues

- Seaweed still heavier than other shapes
- Blender fish still stylistically evolving
- No persistence (jobs in RAM)

---

## 🔮 Next Steps

- Persist jobs
- Improve fish topology (Nemo-style)
- unify shading / preview look
- optional GLB export

---

## 💥 TL;DR

- Hybrid pipeline stable
- PNG previews reliable
- Live timing added
- Performance improved
- System feels like a real tool now
