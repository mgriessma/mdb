# Mineral Collection Database

A comprehensive Python + SQLite application for managing a mineral collection. This application provides a browser-based UI (Flask) for browsing, entering, and editing records, plus multi-format export of the collection.

## Features

- **Browser-based UI**: Access your collection through a web interface at `http://localhost:5000`
- **CRUD Operations**: Create, Read, Update, and Delete operations for all tables
- **Live Filtering**: Filter data across all columns with different match modes (contains, starts with, exact match)
- **Chemical Formula Lookup**: Automatic chemical formula lookup for minerals
- **Image Management**: Upload and manage images for specimens and localities
- **Multi-format Export**: Export your data to CSV, JSON, Excel, PDF, KML, and Shapefile formats

## Database Schema

The application uses an SQLite database (`MG-Sammlung.db`) with the following tables:

| Table | Purpose |
|-------|---------|
| `geologischeprovinz` | Geological provinces with geological age information |
| `revier` | Mining districts with deposit types and raw materials |
| `fundstellen` | Localities (with latitude/longitude coordinates) |
| `stufen` | Specimens (minerals, size, origin, year, etc.) |
| `images` | Images linked to specimens or localities |

## Setup

### Prerequisites

- Python 3.7+
- pip (Python package manager)

### Installation

1. Clone or download this repository
2. Create a virtual environment:
   ```bash
   python3 -m venv .venv
   ```

3. Activate the virtual environment:
   - On Windows:
     ```bash
     .venv\Scripts\activate
     ```
   - On macOS/Linux:
     ```bash
     source .venv/bin/activate
     ```

4. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

### Running the Application

Start the Flask development server:
```bash
python app.py
```

Then open your browser and navigate to: [http://localhost:5000](http://localhost:5000)

## Usage

### Data Entry

Every table has a page with create/edit/delete functionality:

- **Geological provinces**: `/provinz`
- **Mining districts**: `/revier`
- **Localities**: `/fundstellen`
- **Specimens**: `/stufen`
- **Images**: Upload via the specimen/locality detail pages or `/bilder`

### Filtering

All list pages support filtering:
- **Contains**: Search for text anywhere in the column
- **Starts with**: Search for text at the beginning of the column
- **Exact match**: Search for exact text matches

### Chemical Formulas

Specimens automatically look up chemical formulas for their mineral fields. The application includes a comprehensive database of common minerals and their chemical formulas.

### Image Upload

Images can be uploaded:
- Through the specimen detail page (`/view_stufen/<id>`)
- Through the locality detail page (`/fundstellen_view/<id>`)
- Supported formats: PNG, JPG, JPEG, GIF, BMP
- Maximum file size: 16MB

## Export

Exports are written into timestamped folders under `02_Exports/`:

| Route | Format | Content |
|-------|--------|---------|
| `/export/csv` | CSV | One file per table (all tables) |
| `/export/json` | JSON | One file per table (all tables) |
| `/export/excel` | Excel | One file per table (all tables) |
| `/export/pdf` | PDF | Specimens, localities, and minerals lists |
| `/export/kml` | KML | Localities with coordinates (for Google Earth) |
| `/export/shp` | Shapefile | Specimens with location data (GIS compatible) |

Links to the export endpoints are available on the `/start` page and in the sidebar.

## Project Structure

```
mineral_collection/
├── app.py                  # Main Flask application
├── requirements.txt         # Python dependencies
├── MG-Sammlung.db          # SQLite database (created on first run)
├── 01_Bilder/              # Image storage for specimens and localities
├── 02_Exports/            # Generated export files
├── static/
│   └── uploads/            # Temporary upload storage
└── templates/              # Jinja2 templates
    ├── base.html           # Base template with layout and styles
    ├── start.html          # Home page with statistics
    ├── stufen.html         # Specimens list
    ├── view_stufen.html    # Single specimen view
    ├── fundstellen.html    # Localities list
    ├── fundstellen_view.html # Single locality view
    ├── revier.html         # Mining districts list
    ├── provinz.html        # Geological provinces list
    ├── bilder.html          # Images list
    └── normalize.html       # Data normalization tools
```

## Configuration

The main configuration is in `app.py`:

- `DB_PATH`: Path to the SQLite database file
- `UPLOAD_FOLDER`: Folder for temporary uploads
- `ALLOWED_EXTENSIONS`: Allowed image file extensions
- `EXPORT_FOLDER`: Folder for export files
- `app.secret_key`: Flask secret key (change in production!)

## Customization

### Adding Mineral Formulas

The chemical formula lookup is built into the `app.py` file. You can extend the `COMMON_MINERALS` dictionary to add more minerals:

```python
COMMON_MINERALS = {
    'quarz': 'SiO2',
    'feldspat': 'KAlSi3O8',
    # Add more minerals here
    'your_mineral': 'Chemical Formula',
}
```

### Adding Dropdown Options

Dropdown options for fields like type, size, origin, etc. are defined at the top of `app.py`:

```python
TYP_OPTIONS = [...]
STUFE_ART_OPTIONS = [...]
GROESSE_OPTIONS = [...]
HERKUNFT_OPTIONS = [...]
IM_BESTAND_OPTIONS = [...]
ERDALTER_OPTIONS = [...]
```

## Troubleshooting

### Database not found

If the database file doesn't exist, it will be created automatically on first run. Make sure the application has write permissions in the directory.

### Missing dependencies

If you get import errors, make sure you've installed all dependencies:
```bash
pip install -r requirements.txt
```

### Port already in use

If port 5000 is already in use, you can change it in `app.py`:
```python
app.run(debug=True, host='0.0.0.0', port=5001)  # Change to a different port
```

## License

This application is provided as-is for personal use. Feel free to modify and extend it for your own mineral collection management needs.

## Contributing

Contributions are welcome! Please feel free to submit issues or pull requests.
