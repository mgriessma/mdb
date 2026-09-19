# Mineral Collection Database (mdb)

A Python + SQLite application for managing a mineral collection. It provides a
browser-based UI (Flask) for browsing, entering, and editing records, plus
multi-format export of the collection.

This repository previously only stored dated `Mineral_DB_*.zip` snapshots. The
checked-in source below is materialized from `Mineral_DB_20260915.zip` so the app
can be run directly from the repo instead of unpacking a zip.

## What's inside

- `app.py` — Flask web app: CRUD for every table, live filtering, and export.
- `mineral_formulas.py` — chemical-formula lookup used by the specimen views.
- `rename_images.py` — one-time helper to normalize image filenames.
- `templates/` — Jinja2 templates for the browser UI.
- `MG-Sammlung.db` — the SQLite database holding the collection data.
- `01_Bilder/` — image storage (specimens + localities), populated by uploads.
- `02_Exports/` — generated export files (gitignored except the placeholder).
- `requirements.txt` — pinned dependencies.

## Database schema

| Table                | Purpose                                              |
|----------------------|------------------------------------------------------|
| `geologischeprovinz` | Geological provinces                                 |
| `revier`             | Mining districts                                     |
| `fundstellen`        | Localities (with lat/lon)                            |
| `stufen`             | Specimens (minerals, size, origin, year, etc.)      |
| `images`             | Images linked to a specimen or locality             |

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

Then open <http://localhost:5000>.

## Data entry

Every table has a page with create / edit / delete via JSON APIs:

- Geological provinces: `/provinz`
- Mining districts: `/revier`
- Localities: `/fundstellen`
- Specimens: `/stufen`
- Specimen images: `/bilder` (upload via the specimen/locality detail pages)

Specimens automatically look up chemical formulas for their mineral fields using
`mineral_formulas.py`.

## Export

Exports are written into timestamped folders under `02_Exports/`:

| Route          | Format | Content                                   |
|----------------|--------|-------------------------------------------|
| `/export/csv`  | CSV    | One file per table (all tables)          |
| `/export/pdf`  | PDF    | Specimens, localities, and minerals lists |
| `/export/kml`  | KML    | Localities with coordinates               |
| `/export/shp`  | Shapefile | Specimens                              |

Links to the export endpoints are on the `/start` page.
