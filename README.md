# Ocean Reef Prototype UI — Phase C

Phase C erweitert die Phase-B-UI um produktivere Exportwege.

## Neu in Phase C

- Single STL Export
- Separate Regions Export als ZIP
- SCAD-only Export als ZIP
- `params.json` im Bundle
- X1C-safe Preset für robustere Drucke
- Übersicht der aktiven Regions-Dateien im Result-Panel

## Requirements

- Python 3.11+
- OpenSCAD in `PATH` für STL-basierte Exporte

## Install

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Run

```bash
uvicorn app.main:app --reload
```

Dann öffnen:

```text
http://127.0.0.1:8000
```

## Export-Modi

### Single STL
Erzeugt eine einzelne `.stl` plus `.scad`.

### Separate regions ZIP
Erzeugt:
- Master-SCAD
- pro aktiver Region eine eigene `.scad`
- pro aktiver Region eine eigene `.stl`
- `params.json`
- alles als ZIP-Bundle

### SCAD only
Erzeugt ein ZIP mit:
- Master-SCAD
- `params.json`

## Minimal schema per item

```json
{
  "id": "sig-1",
  "region": "Europe",
  "timestamp": "2026-03-20T08:00:00Z"
}
```
