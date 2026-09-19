"""
Mineral Collection Database - Local Browser UI
Run with: python app.py
Access at: http://localhost:5000

Features:
- Browser-based UI for your existing MG-Sammlung.db
- CRUD operations for all tables
- Live filtering on all pages
- Chemical formula lookup for minerals (using mineral_formulas.py)
- Batch update for existing records
- Export to CSV
"""

from flask import Flask, render_template, request, jsonify, send_from_directory, redirect, url_for
import sqlite3
import os
from datetime import datetime
import csv
import subprocess
import platform
import shutil
from werkzeug.utils import secure_filename
from functools import lru_cache

# Import mineral formula lookup from separate file
from mineral_formulas import get_formula, COMMON_MINERALS

# ==================== CONFIGURATION ====================
DB_PATH = "MG-Sammlung.db"  # Your existing database file
UPLOAD_FOLDER = "static/uploads"
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'bmp'}

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB limit
app.secret_key = 'your-secret-key-here-change-in-production'

# Ensure upload folder exists
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# ==================== DATABASE HELPERS ====================

def get_db():
    """Get database connection to your existing MG-Sammlung.db"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def allowed_file(filename):
    """Check if file has allowed extension"""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def build_filter_clause(columns, filter_text, match_mode):
    """Build a WHERE clause matching filter_text across the given column expressions.

    Used by the list endpoints so that the 'All Columns' filter option actually
    narrows the result set instead of returning everything unchanged.
    Returns (where_fragment, params). An empty filter_text yields ('', []).
    """
    if not filter_text:
        return '', []
    if match_mode == 'startswith':
        pattern = f"{filter_text}%"
    elif match_mode == 'exact':
        pattern = filter_text
    else:  # contains
        pattern = f"%{filter_text}%"
    conditions = []
    params = []
    for col in columns:
        conditions.append(f"CAST({col} AS TEXT) LIKE ?")
        params.append(pattern)
    return " WHERE (" + " OR ".join(conditions) + ")", params

def add_formula_columns():
    """Add chemical formula columns to stufen table if they don't exist"""
    conn = get_db()
    cursor = conn.cursor()

    # Check if columns already exist
    cursor.execute("PRAGMA table_info(stufen)")
    columns = [column[1] for column in cursor.fetchall()]

    formula_columns = ['mineral_1_formula', 'mineral_2_formula', 'mineral_3_formula', 'mineral_4_formula']

    for col in formula_columns:
        if col not in columns:
            cursor.execute(f"ALTER TABLE stufen ADD COLUMN {col} TEXT")
            print(f"Added column: {col}")

    conn.commit()
    conn.close()

# Call this once when starting the app
add_formula_columns()

def add_image_type_column():
    """Add image_type column to images table if it doesn't exist"""
    conn = get_db()
    cursor = conn.cursor()

    # Check if column already exists
    cursor.execute("PRAGMA table_info(images)")
    columns = [column[1] for column in cursor.fetchall()]

    if 'image_type' not in columns:
        cursor.execute("ALTER TABLE images ADD COLUMN image_type TEXT DEFAULT 'stufen'")
        print("Added image_type column to images table")

        # Update existing images to be 'stufen' type
        cursor.execute("UPDATE images SET image_type = 'stufen' WHERE image_type IS NULL")
        print("Updated existing images to type 'stufen'")

    conn.commit()
    conn.close()

# Call this once when starting the app
add_image_type_column()

def add_fundstelle_id_column():
    """Add fundstelle_id column to images table if it doesn't exist"""
    conn = get_db()
    cursor = conn.cursor()

    # Check if column already exists
    cursor.execute("PRAGMA table_info(images)")
    columns = [column[1] for column in cursor.fetchall()]

    if 'fundstelle_id' not in columns:
        cursor.execute("ALTER TABLE images ADD COLUMN fundstelle_id INTEGER")
        print("Added fundstelle_id column to images table")

        # Add foreign key constraint (SQLite doesn't enforce this, but it's good for documentation)
        # Note: SQLite requires the referenced table to exist and have the column

    conn.commit()
    conn.close()

# Call this once when starting the app
add_fundstelle_id_column()

def get_formulas_for_stufe(mineral_1, mineral_2, mineral_3, mineral_4):
    """Get formulas for all non-empty mineral fields using the imported get_formula function"""
    formulas = {
        'mineral_1_formula': None,
        'mineral_2_formula': None,
        'mineral_3_formula': None,
        'mineral_4_formula': None
    }

    try:
        if mineral_1:
            formulas['mineral_1_formula'] = get_formula(mineral_1)
        if mineral_2:
            formulas['mineral_2_formula'] = get_formula(mineral_2)
        if mineral_3:
            formulas['mineral_3_formula'] = get_formula(mineral_3)
        if mineral_4:
            formulas['mineral_4_formula'] = get_formula(mineral_4)
    except Exception as e:
        print(f"Error in get_formulas_for_stufe: {e}")

    return formulas

# ==================== DROPDOWN OPTIONS ====================
TYP_OPTIONS = ["Aufschluss", "Steinbruch", "Tagebau", "Untertage", "Lesestein", "Halde", "Seife", "Unbekannt"]
STUFE_ART_OPTIONS = ["Artefakt", "Fossil", "Gestein", "Mineralstufe", "Erz", "Tektit o. Meteorit"]
GROESSE_OPTIONS = ["Mikromount (<2.5cm)", "Kleinststufe (<5cm)", "Kleinstufe (<10cm)", "Handstück (<20cm)", "Stufe (>20cm)", "Dünnschliff", "Bohrkern", "NA"]
HERKUNFT_OPTIONS = ["Eigenfund", "Kauf", "Tausch", "Geschenk", "Vater"]
IM_BESTAND_OPTIONS = ["Ja", "Nein (verkauft)", "Nein (verschenkt)", "Nein (verloren o. entsorgt)"]
ERDALTER_OPTIONS = ["Känozoikum", "Mesozoikum", "Paläozoikum", "Proterozoikum", "Archaikum", "Hadaikum"]
LAGERSTAETTENTYP_OPTIONS = [
    "Liquidmagmatische Lagerstätten", "Pegmatitische Lagerstätten", "Greisen", "Porphyrische Lagerstätten", "Skarne",
    "Gangförmige Zinn- und Wolframlagerstätten", "Gangförmige Silber- und Buntmetallagerstätten",
    "Mesothermale Goldlagerstätten", "Epithermale Lagerstätten", "Gangförmige Fluorit- und Barytlagerstätten",
    "Gangförmige Uran-Lagerstätten", "IOCG-Lagerstätten", "Carlin-Lagerstätten",
    "Hydrothermale Brekzien-Typ Lagerstätten", "SHMS (SEDEX)- Lagerstätten",
    "Schwarzschiefer-gebundene Uranlagerstätten", "stratiforme Kupferlagerstätten",
    "Carbonatgebundene Erz- und Minerallagerstätten", "Nickelhydrosilikatlagerstätten",
    "Bändererze (BIF)", "Seifen", "Evaporite", "Steinkohle",
    "Metamorphe und metamorphogene Lagerstätten"
]

# ==================== ROUTES ====================

@app.route('/')
def index():
    """Main page - redirect to start page"""
    return redirect(url_for('start_page'))

@app.route('/start')
def start_page():
    """Start page with functionality sidebar"""
    return render_template('start.html')

# --- Statistics API ---
@app.route('/api/stats')
def api_stats():
    """Get database statistics"""
    try:
        conn = get_db()
        cursor = conn.cursor()

        stats = {}

        # Count records in each table, exposing friendly aliases used by the UI
        table_aliases = {
            'geologischeprovinz': 'provinz_count',
            'revier': 'revier_count',
            'fundstellen': 'fundstellen_count',
            'stufen': 'stufen_count',
            'images': 'bilder_count',
        }
        for table, alias in table_aliases.items():
            cursor.execute(f"SELECT COUNT(*) FROM {table}")
            count = cursor.fetchone()[0]
            stats[f'{table}_count'] = count
            stats[alias] = count

        conn.close()
        return jsonify(stats)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# --- Recent activity API ---
@app.route('/api/recent-activity')
def api_recent_activity():
    """API: Most recently added records across the collection.

    The tables do not carry timestamps, so 'recent' is approximated by the
    highest primary-key values (auto-increment ids / newest snr).
    """
    try:
        conn = get_db()
        cursor = conn.cursor()
        activities = []

        cursor.execute(
            "SELECT snr, sammlungsstueck, fundstelle, art FROM stufen "
            "ORDER BY snr DESC LIMIT 5")
        for row in cursor.fetchall():
            r = dict(row)
            activities.append({
                'type': 'Stufe',
                'label': r.get('sammlungsstueck') or f"Stufe {r['snr']}",
                'detail': r.get('fundstelle') or r.get('art') or '',
                'url': f"/stufen?filter_col=snr&filter_text={r['snr']}&match_mode=exact",
            })

        cursor.execute(
            "SELECT fsid, fundstelle, ortschaft, land FROM fundstellen "
            "ORDER BY fsid DESC LIMIT 5")
        for row in cursor.fetchall():
            r = dict(row)
            activities.append({
                'type': 'Fundstelle',
                'label': r.get('fundstelle') or f"Fundstelle {r['fsid']}",
                'detail': ' '.join(x for x in [r.get('ortschaft'), r.get('land')] if x),
                'url': f"/fundstellen?filter_col=fsid&filter_text={r['fsid']}&match_mode=exact",
            })

        cursor.execute(
            "SELECT isnr, sammlungsstueck, photo, image_type FROM images "
            "ORDER BY isnr DESC LIMIT 5")
        for row in cursor.fetchall():
            r = dict(row)
            activities.append({
                'type': 'Bild',
                'label': r.get('sammlungsstueck') or r.get('photo') or f"Bild {r['isnr']}",
                'detail': r.get('image_type') or '',
                'url': "/bilder",
            })

        conn.close()
        return jsonify({'activities': activities})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# --- Fundstellen with coordinates API ---
@app.route('/api/fundstellen/with-coords')
def api_fundstellen_with_coords():
    """API: Get all fundstellen that have coordinates"""
    try:
        conn = get_db()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT fsid, fundstelle, bergbaurevier, ortschaft, region, land,
                   geologische_provinz, typ, kommentar, lat, lon
            FROM fundstellen
            WHERE lat IS NOT NULL AND lon IS NOT NULL
            ORDER BY fundstelle
        """)

        fundstellen = [dict(row) for row in cursor.fetchall()]
        conn.close()

        return jsonify({'fundstellen': fundstellen})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# --- Global search API ---
@app.route('/api/search')
def api_search():
    """Global search across all tables"""
    table = request.args.get('table', 'stufen')
    query = request.args.get('q', '')

    if not query or len(query) < 2:
        return jsonify({'results': []})

    try:
        conn = get_db()
        cursor = conn.cursor()

        results = []

        # Map table to primary key and display fields
        table_config = {
            'provinz': {'pk': 'gid', 'fields': ['provinz', 'geologie_typ']},
            'revier': {'pk': 'rid', 'fields': ['bergbaurevier', 'rohstoffe']},
            'fundstellen': {'pk': 'fsid', 'fields': ['fundstelle', 'bergbaurevier', 'land']},
            'stufen': {'pk': 'snr', 'fields': ['sammlungsstueck', 'fundstelle', 'art', 'mineral_1', 'mineral_2', 'mineral_3', 'mineral_4']},
            'bilder': {'pk': 'isnr', 'fields': ['snr', 'sammlungsstueck']}
        }

        if table in table_config:
            config = table_config[table]
            pk = config['pk']

            # Build search query
            search_conditions = []
            params = []

            for field in config['fields']:
                search_conditions.append(f"{field} LIKE ?")
                params.append(f"%{query}%")

            where_clause = " OR ".join(search_conditions)
            sql = f"SELECT * FROM {table} WHERE {where_clause} LIMIT 20"

            cursor.execute(sql, params)
            results = [dict(row) for row in cursor.fetchall()]

        conn.close()
        return jsonify({'results': results, 'primary_key': table_config[table]['pk']})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# --- PROVINZ ROUTES ---
@app.route('/provinz')
def provinz_page():
    """Geologische Provinz page"""
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM geologischeprovinz ORDER BY provinz")
        provinzen = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return render_template('provinz.html',
                             provinzen=provinzen,
                             erdalter_options=ERDALTER_OPTIONS)
    except Exception as e:
        return f"Error loading provinz page: {str(e)}", 500

@app.route('/api/provinz', methods=['GET'])
def api_get_provinz():
    """API: Get all geologische provinz data"""
    try:
        conn = get_db()
        cursor = conn.cursor()

        filter_col = request.args.get('filter_col', '')
        filter_text = request.args.get('filter_text', '')
        match_mode = request.args.get('match_mode', 'contains')

        query = "SELECT * FROM geologischeprovinz"
        params = []
        provinz_columns = ['gid', 'provinz', 'geologie_typ', 'gehoert_zu', 'erdalter']
        if filter_col and filter_text:
            if filter_col not in provinz_columns:
                return jsonify([])
            if match_mode == 'startswith':
                query += f" WHERE {filter_col} LIKE ?"
                params.append(f"{filter_text}%")
            elif match_mode == 'exact':
                query += f" WHERE {filter_col} = ?"
                params.append(filter_text)
            else:  # contains
                query += f" WHERE {filter_col} LIKE ?"
                params.append(f"%{filter_text}%")
        elif filter_text:
            where, p = build_filter_clause(provinz_columns, filter_text, match_mode)
            query += where
            params.extend(p)
        query += " ORDER BY provinz"

        cursor.execute(query, params)
        rows = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return jsonify(rows)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/provinz/<int:gid>', methods=['GET'])
def api_get_provinz_one(gid):
    """API: Get single geologische provinz by gid"""
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM geologischeprovinz WHERE gid = ?", (gid,))
        row = cursor.fetchone()
        conn.close()
        return jsonify(dict(row)) if row else jsonify({})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/provinz', methods=['POST'])
def api_create_provinz():
    """API: Create new geologische provinz"""
    try:
        data = request.get_json()
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO geologischeprovinz (provinz, geologie_typ, gehoert_zu, erdalter)
            VALUES (?, ?, ?, ?)
        """, (data.get('provinz'), data.get('geologie_typ'), data.get('gehoert_zu'), data.get('erdalter')))
        conn.commit()
        gid = cursor.lastrowid
        conn.close()
        return jsonify({'success': True, 'gid': gid})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/provinz/<int:gid>', methods=['PUT'])
def api_update_provinz(gid):
    """API: Update geologische provinz"""
    try:
        data = request.get_json()
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE geologischeprovinz
            SET provinz = ?, geologie_typ = ?, gehoert_zu = ?, erdalter = ?
            WHERE gid = ?
        """, (data.get('provinz'), data.get('geologie_typ'), data.get('gehoert_zu'), data.get('erdalter'), gid))
        conn.commit()
        conn.close()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/provinz/<int:gid>', methods=['DELETE'])
def api_delete_provinz(gid):
    """API: Delete geologische provinz"""
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM geologischeprovinz WHERE gid = ?", (gid,))
        conn.commit()
        conn.close()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

# --- REVIER ROUTES ---
@app.route('/revier')
def revier_page():
    """Revier page"""
    try:
        conn = get_db()
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM revier ORDER BY bergbaurevier")
        revier_list = [dict(row) for row in cursor.fetchall()]

        cursor.execute("SELECT provinz FROM geologischeprovinz ORDER BY provinz")
        provinz_options = [row[0] for row in cursor.fetchall()]

        conn.close()
        return render_template('revier.html',
                             revier_list=revier_list,
                             lagerstaettentyp_options=LAGERSTAETTENTYP_OPTIONS,
                             provinz_options=provinz_options)
    except Exception as e:
        return f"Error loading revier page: {str(e)}", 500

@app.route('/api/revier', methods=['GET'])
def api_get_revier():
    """API: Get all revier data"""
    try:
        conn = get_db()
        cursor = conn.cursor()

        filter_col = request.args.get('filter_col', '')
        filter_text = request.args.get('filter_text', '')
        match_mode = request.args.get('match_mode', 'contains')

        query = "SELECT * FROM revier"
        params = []
        revier_columns = ['rid', 'bergbaurevier', 'rohstoffe', 'lagerstaettentyp1',
                          'lagerstaettentyp2', 'lagerstaettentyp3', 'lagerstaettentyp4',
                          'geologische_provinz', 'bergbauperiode', 'kommentar']
        if filter_col and filter_text:
            if filter_col not in revier_columns:
                return jsonify([])
            if match_mode == 'startswith':
                query += f" WHERE {filter_col} LIKE ?"
                params.append(f"{filter_text}%")
            elif match_mode == 'exact':
                query += f" WHERE {filter_col} = ?"
                params.append(filter_text)
            else:
                query += f" WHERE {filter_col} LIKE ?"
                params.append(f"%{filter_text}%")
        elif filter_text:
            where, p = build_filter_clause(revier_columns, filter_text, match_mode)
            query += where
            params.extend(p)
        query += " ORDER BY bergbaurevier"

        cursor.execute(query, params)
        rows = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return jsonify(rows)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/revier/<int:rid>', methods=['GET'])
def api_get_revier_one(rid):
    """API: Get single revier by rid"""
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM revier WHERE rid = ?", (rid,))
        row = cursor.fetchone()
        conn.close()
        return jsonify(dict(row)) if row else jsonify({})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/revier', methods=['POST'])
def api_create_revier():
    """API: Create new revier"""
    try:
        data = request.get_json()
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO revier
            (bergbaurevier, rohstoffe, lagerstaettentyp1, lagerstaettentyp2,
             lagerstaettentyp3, lagerstaettentyp4, geologische_provinz, bergbauperiode, kommentar)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            data.get('bergbaurevier'), data.get('rohstoffe'), data.get('lagerstaettentyp1'),
            data.get('lagerstaettentyp2'), data.get('lagerstaettentyp3'), data.get('lagerstaettentyp4'),
            data.get('geologische_provinz'), data.get('bergbauperiode'), data.get('kommentar')
        ))
        conn.commit()
        rid = cursor.lastrowid
        conn.close()
        return jsonify({'success': True, 'rid': rid})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/revier/<int:rid>', methods=['PUT'])
def api_update_revier(rid):
    """API: Update revier"""
    try:
        data = request.get_json()
        conn = get_db()
        cursor = conn.cursor()

        new_bergbaurevier = data.get('bergbaurevier')
        cursor.execute("SELECT bergbaurevier FROM revier WHERE rid = ?", (rid,))
        row = cursor.fetchone()
        old_bergbaurevier = row['bergbaurevier'] if row else None

        if new_bergbaurevier and old_bergbaurevier and new_bergbaurevier != old_bergbaurevier:
            cursor.execute("PRAGMA foreign_keys = OFF")
            cursor.execute("""
                UPDATE revier
                SET bergbaurevier = ?, rohstoffe = ?, lagerstaettentyp1 = ?, lagerstaettentyp2 = ?,
                    lagerstaettentyp3 = ?, lagerstaettentyp4 = ?, geologische_provinz = ?,
                    bergbauperiode = ?, kommentar = ?
                WHERE rid = ?
            """, (
                new_bergbaurevier, data.get('rohstoffe'), data.get('lagerstaettentyp1'),
                data.get('lagerstaettentyp2'), data.get('lagerstaettentyp3'), data.get('lagerstaettentyp4'),
                data.get('geologische_provinz'), data.get('bergbauperiode'), data.get('kommentar'), rid
            ))
            cursor.execute("UPDATE fundstellen SET bergbaurevier = ? WHERE bergbaurevier = ?",
                           (new_bergbaurevier, old_bergbaurevier))
            cursor.execute("PRAGMA foreign_keys = ON")
            cursor.execute("PRAGMA foreign_key_check")
            violations = cursor.fetchall()
            if violations:
                conn.rollback()
                conn.close()
                return jsonify({'success': False, 'error': 'Fehlerhafte Referenzen nach Umbenennung'}), 500
        else:
            cursor.execute("""
                UPDATE revier
                SET bergbaurevier = ?, rohstoffe = ?, lagerstaettentyp1 = ?, lagerstaettentyp2 = ?,
                    lagerstaettentyp3 = ?, lagerstaettentyp4 = ?, geologische_provinz = ?,
                    bergbauperiode = ?, kommentar = ?
                WHERE rid = ?
            """, (
                new_bergbaurevier, data.get('rohstoffe'), data.get('lagerstaettentyp1'),
                data.get('lagerstaettentyp2'), data.get('lagerstaettentyp3'), data.get('lagerstaettentyp4'),
                data.get('geologische_provinz'), data.get('bergbauperiode'), data.get('kommentar'), rid
            ))

        conn.commit()
        conn.close()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/revier/<int:rid>', methods=['DELETE'])
def api_delete_revier(rid):
    """API: Delete revier"""
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM revier WHERE rid = ?", (rid,))
        conn.commit()
        conn.close()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

# --- FUNDSTELLEN ROUTES ---
@app.route('/fundstellen')
def fundstellen_page():
    """Fundstellen page"""
    try:
        conn = get_db()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT fs.*, r.bergbaurevier as revier_name
            FROM fundstellen fs
            LEFT JOIN revier r ON fs.bergbaurevier = r.bergbaurevier
            ORDER BY fs.fundstelle
        """)
        fundstellen_list = [dict(row) for row in cursor.fetchall()]

        cursor.execute("SELECT bergbaurevier FROM revier ORDER BY bergbaurevier")
        revier_options = [row[0] for row in cursor.fetchall()]

        cursor.execute("SELECT provinz FROM geologischeprovinz ORDER BY provinz")
        provinz_options = [row[0] for row in cursor.fetchall()]

        conn.close()
        return render_template('fundstellen.html',
                             fundstellen_list=fundstellen_list,
                             typ_options=TYP_OPTIONS,
                             revier_options=revier_options,
                             provinz_options=provinz_options)
    except Exception as e:
        return f"Error loading fundstellen page: {str(e)}", 500

# --- FUNDSTELLEN VIEW ---
@app.route('/fundstellen/view/<int:fsid>')
def view_fundstellen(fsid):
    """View a single fundstelle with map, image gallery, and related stufen."""
    try:
        conn = get_db()
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM fundstellen WHERE fsid = ?", (fsid,))
        fundstelle_row = cursor.fetchone()
        if not fundstelle_row:
            conn.close()
            return "Fundstelle not found", 404
        fundstelle = dict(fundstelle_row)

        # Related stufen (linked by fundstelle name), newest snr first
        cursor.execute("""
            SELECT s.snr, s.sammlungsstueck, s.art, s.mineral_1, s.mineral_2, s.mineral_3, s.mineral_4,
                   s.groesse, s.im_bestand, s.fundjahr
            FROM stufen s
            WHERE s.fundstelle = ?
            ORDER BY s.snr
        """, (fundstelle['fundstelle'],))
        stufen_list = [dict(row) for row in cursor.fetchall()]

        # Fundstellen-type images for this fundstelle
        cursor.execute("""
            SELECT i.*,
                   CASE
                       WHEN i.photo LIKE '/01_Bilder/%' THEN i.photo
                       ELSE '/01_Bilder/01_Fundstellen/' || i.photo
                   END as photo_url
            FROM images i
            WHERE i.image_type = 'fundstellen' AND i.fundstelle_id = ?
            ORDER BY i.isnr
        """, (fsid,))
        images = [dict(row) for row in cursor.fetchall()]
        for img in images:
            if not img['photo_url'].startswith('/01_Bilder/'):
                img['photo_url'] = f"/01_Bilder/01_Fundstellen/{img['photo']}"

        # Previous and next fundstelle (in fsid order) for navigation
        cursor.execute("SELECT fsid FROM fundstellen WHERE fsid < ? ORDER BY fsid DESC LIMIT 1", (fsid,))
        prev_row = cursor.fetchone()
        prev_fsid = prev_row[0] if prev_row else None
        cursor.execute("SELECT fsid FROM fundstellen WHERE fsid > ? ORDER BY fsid ASC LIMIT 1", (fsid,))
        next_row = cursor.fetchone()
        next_fsid = next_row[0] if next_row else None

        conn.close()
        return render_template('fundstellen_view.html',
                             fundstelle=fundstelle,
                             stufen_list=stufen_list,
                             images=images,
                             prev_fsid=prev_fsid,
                             next_fsid=next_fsid)

    except Exception as e:
        return f"Error loading fundstelle view: {str(e)}", 500

@app.route('/api/fundstellen', methods=['GET'])
def api_get_fundstellen():
    """API: Get all fundstellen data"""
    try:
        conn = get_db()
        cursor = conn.cursor()

        filter_col = request.args.get('filter_col', '')
        filter_text = request.args.get('filter_text', '')
        match_mode = request.args.get('match_mode', 'contains')

        query = """
            SELECT fs.*, r.bergbaurevier as revier_name
            FROM fundstellen fs
            LEFT JOIN revier r ON fs.bergbaurevier = r.bergbaurevier
        """
        params = []

        fundstellen_columns = {
            'fsid': 'fs.fsid', 'fundstelle': 'fs.fundstelle',
            'bergbaurevier': 'fs.bergbaurevier', 'ortschaft': 'fs.ortschaft',
            'region': 'fs.region', 'land': 'fs.land',
            'geologische_provinz': 'fs.geologische_provinz', 'typ': 'fs.typ',
            'lat': 'fs.lat', 'lon': 'fs.lon', 'revier_name': 'r.bergbaurevier',
        }
        if filter_col and filter_text:
            filter_col = fundstellen_columns.get(filter_col)
            if filter_col is None:
                return jsonify([])

            if match_mode == 'startswith':
                query += f" WHERE {filter_col} LIKE ?"
                params.append(f"{filter_text}%")
            elif match_mode == 'exact':
                query += f" WHERE {filter_col} = ?"
                params.append(filter_text)
            else:
                query += f" WHERE {filter_col} LIKE ?"
                params.append(f"%{filter_text}%")
        elif filter_text:
            all_cols = list(fundstellen_columns.values())
            where, p = build_filter_clause(all_cols, filter_text, match_mode)
            query += where
            params.extend(p)
        query += " ORDER BY fs.fundstelle"

        cursor.execute(query, params)
        rows = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return jsonify(rows)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/fundstellen/<int:fsid>', methods=['GET'])
def api_get_fundstellen_one(fsid):
    """API: Get single fundstellen by fsid"""
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM fundstellen WHERE fsid = ?", (fsid,))
        row = cursor.fetchone()
        conn.close()
        return jsonify(dict(row)) if row else jsonify({})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/fundstellen', methods=['POST'])
def api_create_fundstellen():
    """API: Create new fundstellen"""
    try:
        data = request.get_json()
        conn = get_db()
        cursor = conn.cursor()

        lat = float(data.get('lat')) if data.get('lat') else None
        lon = float(data.get('lon')) if data.get('lon') else None

        cursor.execute("""
            INSERT INTO fundstellen
            (fundstelle, bergbaurevier, ortschaft, region, land, geologische_provinz, typ, kommentar, lat, lon)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            data.get('fundstelle'), data.get('bergbaurevier'), data.get('ortschaft'),
            data.get('region'), data.get('land'), data.get('geologische_provinz'),
            data.get('typ'), data.get('kommentar'), lat, lon
        ))
        conn.commit()
        fsid = cursor.lastrowid
        conn.close()
        return jsonify({'success': True, 'fsid': fsid})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/fundstellen/<int:fsid>', methods=['PUT'])
def api_update_fundstellen(fsid):
    """API: Update fundstellen"""
    try:
        data = request.get_json()
        conn = get_db()
        cursor = conn.cursor()

        lat = float(data.get('lat')) if data.get('lat') else None
        lon = float(data.get('lon')) if data.get('lon') else None

        cursor.execute("""
            UPDATE fundstellen
            SET fundstelle = ?, bergbaurevier = ?, ortschaft = ?, region = ?, land = ?,
                geologische_provinz = ?, typ = ?, kommentar = ?, lat = ?, lon = ?
            WHERE fsid = ?
        """, (
            data.get('fundstelle'), data.get('bergbaurevier'), data.get('ortschaft'),
            data.get('region'), data.get('land'), data.get('geologische_provinz'),
            data.get('typ'), data.get('kommentar'), lat, lon, fsid
        ))
        conn.commit()
        conn.close()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/fundstellen/<int:fsid>', methods=['DELETE'])
def api_delete_fundstellen(fsid):
    """API: Delete fundstellen"""
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM fundstellen WHERE fsid = ?", (fsid,))
        conn.commit()
        conn.close()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

# --- STUFEN ROUTES ---
@app.route('/stufen')
def stufen_page():
    """Stufen page"""
    try:
        conn = get_db()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT s.*, f.fundstelle as fundstelle_name, f.land, f.region, f.ortschaft
            FROM stufen s
            LEFT JOIN fundstellen f ON s.fundstelle = f.fundstelle
            ORDER BY s.snr
        """)
        stufen_list = [dict(row) for row in cursor.fetchall()]

        cursor.execute("""
            SELECT f.fundstelle, f.land, f.region, f.ortschaft
            FROM fundstellen f
            ORDER BY f.land, f.region, f.ortschaft, f.fundstelle
        """)
        fundstellen_options = []
        for row in cursor.fetchall():
            parts = [p for p in [row[1], row[2], row[3], row[0]] if p]
            fundstellen_options.append({
                'value': row[0],
                'display': " - ".join(parts)
            })

        conn.close()
        mineral_options = sorted(COMMON_MINERALS.keys(), key=str.lower)
        return render_template('stufen.html',
                             stufen_list=stufen_list,
                             art_options=STUFE_ART_OPTIONS,
                             groesse_options=GROESSE_OPTIONS,
                             herkunft_options=HERKUNFT_OPTIONS,
                             im_bestand_options=IM_BESTAND_OPTIONS,
                             fundstellen_options=fundstellen_options,
                             mineral_options=mineral_options)
    except Exception as e:
        return f"Error loading stufen page: {str(e)}", 500

@app.route('/api/stufen', methods=['GET'])
def api_get_stufen():
    """API: Get all stufen data including formulas"""
    try:
        conn = get_db()
        cursor = conn.cursor()

        filter_col = request.args.get('filter_col', '')
        filter_text = request.args.get('filter_text', '')
        match_mode = request.args.get('match_mode', 'contains')

        query = """
            SELECT s.*, f.fundstelle as fundstelle_name
            FROM stufen s
            LEFT JOIN fundstellen f ON s.fundstelle = f.fundstelle
        """
        params = []

        stufen_columns = {
            'snr': 's.snr', 'sammlungsstueck': 's.sammlungsstueck',
            'fundstelle': 's.fundstelle', 'art': 's.art', 'groesse': 's.groesse',
            'mineral_1': 's.mineral_1', 'mineral_2': 's.mineral_2',
            'mineral_3': 's.mineral_3', 'mineral_4': 's.mineral_4',
            'mineral_1_formula': 's.mineral_1_formula', 'mineral_2_formula': 's.mineral_2_formula',
            'mineral_3_formula': 's.mineral_3_formula', 'mineral_4_formula': 's.mineral_4_formula',
            'gestein': 's.gestein', 'beschreibung': 's.beschreibung',
            'fundjahr': 's.fundjahr', 'herkunft': 's.herkunft', 'im_bestand': 's.im_bestand',
            'fundstelle_name': 'f.fundstelle',
        }
        if filter_col and filter_text:
            filter_col = stufen_columns.get(filter_col)
            if filter_col is None:
                return jsonify([])

            if match_mode == 'startswith':
                query += f" WHERE {filter_col} LIKE ?"
                params.append(f"{filter_text}%")
            elif match_mode == 'exact':
                query += f" WHERE {filter_col} = ?"
                params.append(filter_text)
            else:
                query += f" WHERE {filter_col} LIKE ?"
                params.append(f"%{filter_text}%")
        elif filter_text:
            all_cols = list(stufen_columns.values())
            where, p = build_filter_clause(all_cols, filter_text, match_mode)
            query += where
            params.extend(p)
        query += " ORDER BY s.snr"

        cursor.execute(query, params)
        rows = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return jsonify(rows)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/stufen/<int:snr>', methods=['GET'])
def api_get_stufen_one(snr):
    """API: Get single stufen by snr"""
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM stufen WHERE snr = ?", (snr,))
        row = cursor.fetchone()
        conn.close()
        return jsonify(dict(row)) if row else jsonify({})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/stufen', methods=['POST'])
def api_create_stufen():
    """API: Create new stufen with automatic formula lookup"""
    try:
        data = request.get_json()
        conn = get_db()
        cursor = conn.cursor()

        fundstelle = data.get('fundstelle')
        if ' - ' in fundstelle:
            fundstelle = fundstelle.split(' - ')[-1]

        formulas = get_formulas_for_stufe(
            data.get('mineral_1'),
            data.get('mineral_2'),
            data.get('mineral_3'),
            data.get('mineral_4')
        )

        cursor.execute("""
            INSERT INTO stufen
            (fundstelle, sammlungsstueck, art, groesse, mineral_1, mineral_2, mineral_3, mineral_4,
             gestein, beschreibung, fundjahr, herkunft, im_bestand,
             mineral_1_formula, mineral_2_formula, mineral_3_formula, mineral_4_formula)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            fundstelle, data.get('sammlungsstueck'), data.get('art'), data.get('groesse'),
            data.get('mineral_1'), data.get('mineral_2'), data.get('mineral_3'), data.get('mineral_4'),
            data.get('gestein'), data.get('beschreibung'), data.get('fundjahr'),
            data.get('herkunft'), data.get('im_bestand'),
            formulas.get('mineral_1_formula'), formulas.get('mineral_2_formula'),
            formulas.get('mineral_3_formula'), formulas.get('mineral_4_formula')
        ))
        conn.commit()
        snr = cursor.lastrowid
        conn.close()
        return jsonify({'success': True, 'snr': snr})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/stufen/<int:snr>', methods=['PUT'])
def api_update_stufen(snr):
    """API: Update stufen with automatic formula lookup"""
    try:
        data = request.get_json()
        conn = get_db()
        cursor = conn.cursor()

        fundstelle = data.get('fundstelle')
        if ' - ' in fundstelle:
            fundstelle = fundstelle.split(' - ')[-1]

        formulas = get_formulas_for_stufe(
            data.get('mineral_1'),
            data.get('mineral_2'),
            data.get('mineral_3'),
            data.get('mineral_4')
        )

        cursor.execute("""
            UPDATE stufen
            SET fundstelle = ?, sammlungsstueck = ?, art = ?, groesse = ?, mineral_1 = ?,
                mineral_2 = ?, mineral_3 = ?, mineral_4 = ?, gestein = ?, beschreibung = ?,
                fundjahr = ?, herkunft = ?, im_bestand = ?,
                mineral_1_formula = ?, mineral_2_formula = ?, mineral_3_formula = ?, mineral_4_formula = ?
            WHERE snr = ?
        """, (
            fundstelle, data.get('sammlungsstueck'), data.get('art'), data.get('groesse'),
            data.get('mineral_1'), data.get('mineral_2'), data.get('mineral_3'), data.get('mineral_4'),
            data.get('gestein'), data.get('beschreibung'), data.get('fundjahr'),
            data.get('herkunft'), data.get('im_bestand'),
            formulas.get('mineral_1_formula'), formulas.get('mineral_2_formula'),
            formulas.get('mineral_3_formula'), formulas.get('mineral_4_formula'),
            snr
        ))
        conn.commit()
        conn.close()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/stufen/<int:snr>', methods=['DELETE'])
def api_delete_stufen(snr):
    """API: Delete stufen"""
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM stufen WHERE snr = ?", (snr,))
        conn.commit()
        conn.close()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/stufen/view/<int:snr>')
def view_stufen(snr):
    """View a single stufen item with map and image gallery"""
    try:
        conn = get_db()
        cursor = conn.cursor()

        # Get stufen data
        cursor.execute("""
            SELECT s.*
            FROM stufen s
            WHERE s.snr = ?
        """, (snr,))
        stufen = cursor.fetchone()

        if not stufen:
            conn.close()
            return "Stufen not found", 404

        stufen = dict(stufen)

        # Get fundstelle info with coordinates
        cursor.execute("""
            SELECT f.*,
                   CASE
                       WHEN f.land IS NOT NULL AND f.region IS NOT NULL AND f.ortschaft IS NOT NULL AND f.fundstelle IS NOT NULL
                       THEN f.land || ' - ' || f.region || ' - ' || f.ortschaft || ' - ' || f.fundstelle
                       WHEN f.land IS NOT NULL AND f.region IS NOT NULL AND f.fundstelle IS NOT NULL
                       THEN f.land || ' - ' || f.region || ' - ' || f.fundstelle
                       WHEN f.land IS NOT NULL AND f.fundstelle IS NOT NULL
                       THEN f.land || ' - ' || f.fundstelle
                       ELSE f.fundstelle
                   END as display_name
            FROM fundstellen f
            WHERE f.fundstelle = ?
        """, (stufen['fundstelle'],))
        fundstelle_row = cursor.fetchone()

        if fundstelle_row:
            fundstelle_info = dict(fundstelle_row)
        else:
            fundstelle_info = {
                'fundstelle': stufen['fundstelle'],
                'display_name': stufen['fundstelle'] or 'Unknown',
                'lat': None,
                'lon': None
            }

        # Get images for this stufen item
        cursor.execute("""
            SELECT i.*,
                   CASE
                       WHEN i.photo LIKE '/01_Bilder/%' THEN i.photo
                       ELSE '/01_Bilder/02_Stufen/' || i.photo
                   END as photo_url
            FROM images i
            WHERE i.snr = ? AND i.image_type = 'stufen'
            ORDER BY i.isnr
        """, (snr,))
        images = [dict(row) for row in cursor.fetchall()]

        # Fix photo URLs
        for img in images:
            if not img['photo_url'].startswith('/01_Bilder/'):
                img['photo_url'] = f"/01_Bilder/02_Stufen/{img['photo']}"
            if 'photo' not in img:
                img['photo'] = img.get('photo_url', '')

        # Determine previous and next stufen (in DB snr order) for navigation
        cursor.execute("SELECT s.snr FROM stufen s WHERE s.snr < ? ORDER BY s.snr DESC LIMIT 1", (snr,))
        prev_row = cursor.fetchone()
        prev_snr = prev_row[0] if prev_row else None
        cursor.execute("SELECT s.snr FROM stufen s WHERE s.snr > ? ORDER BY s.snr ASC LIMIT 1", (snr,))
        next_row = cursor.fetchone()
        next_snr = next_row[0] if next_row else None

        conn.close()

        return render_template('view_stufen.html',
                             stufen=stufen,
                             fundstelle_info=fundstelle_info,
                             images=images,
                             prev_snr=prev_snr,
                             next_snr=next_snr)

    except Exception as e:
        return f"Error loading view: {str(e)}", 500

@app.route('/api/stufen/<int:snr>/images')
def api_get_stufen_images(snr):
    """API: Get images for a specific stufen item"""
    try:
        conn = get_db()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT i.*,
                   CASE
                       WHEN i.photo LIKE '/01_Bilder/%' THEN i.photo
                       ELSE '/01_Bilder/02_Stufen/' || i.photo
                   END as photo_url
            FROM images i
            WHERE i.snr = ? AND i.image_type = 'stufen'
            ORDER BY i.isnr
        """, (snr,))

        images = []
        for row in cursor.fetchall():
            img = dict(row)
            if not img['photo_url'].startswith('/01_Bilder/'):
                img['photo_url'] = f"/01_Bilder/02_Stufen/{img['photo']}"
            images.append(img)

        conn.close()
        return jsonify(images)

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/stufen/update-formulas', methods=['POST'])
def api_update_all_formulas():
    """API: Update formulas for all existing stufen"""
    try:
        conn = get_db()
        cursor = conn.cursor()

        # Get count of records to process
        cursor.execute("""
            SELECT COUNT(*)
            FROM stufen
            WHERE mineral_1 IS NOT NULL OR mineral_2 IS NOT NULL OR mineral_3 IS NOT NULL OR mineral_4 IS NOT NULL
        """)
        total_count = cursor.fetchone()[0]

        # Get all stufen that need formula updates
        cursor.execute("""
            SELECT snr, mineral_1, mineral_2, mineral_3, mineral_4
            FROM stufen
            WHERE mineral_1 IS NOT NULL OR mineral_2 IS NOT NULL OR mineral_3 IS NOT NULL OR mineral_4 IS NOT NULL
        """)

        stufen = cursor.fetchall()

        updated_count = 0

        for i, (snr, m1, m2, m3, m4) in enumerate(stufen):
            try:
                formulas = get_formulas_for_stufe(m1, m2, m3, m4)

                # Only update if we have at least one formula
                if any(f is not None for f in formulas.values()):
                    cursor.execute("""
                        UPDATE stufen
                        SET mineral_1_formula = ?, mineral_2_formula = ?, mineral_3_formula = ?, mineral_4_formula = ?
                        WHERE snr = ?
                    """, (
                        formulas.get('mineral_1_formula'), formulas.get('mineral_2_formula'),
                        formulas.get('mineral_3_formula'), formulas.get('mineral_4_formula'),
                        snr
                    ))
                    updated_count += 1

                # Commit periodically to avoid long transactions
                if i % 20 == 0:
                    conn.commit()

            except Exception as e:
                print(f"Error updating snr {snr}: {e}")
                continue

        conn.commit()
        conn.close()

        return jsonify({
            'success': True,
            'updated_count': updated_count,
            'total_count': total_count
        })

    except Exception as e:
        # Ensure we always return valid JSON
        return jsonify({
            'success': False,
            'error': str(e),
            'updated_count': 0,
            'total_count': 0
        }), 500

# ==================== IMAGE FOLDER CONFIGURATION ====================
# Using YOUR exact folder structure
FUNDSTELLEN_IMAGES_FOLDER = "01_Bilder/01_Fundstellen"
STUFEN_IMAGES_FOLDER = "01_Bilder/02_Stufen"

# Ensure folders exist
os.makedirs(FUNDSTELLEN_IMAGES_FOLDER, exist_ok=True)
os.makedirs(STUFEN_IMAGES_FOLDER, exist_ok=True)

# ==================== BILDER ROUTES ====================

@app.route('/bilder')
def bilder_page():
    """Bilder page with tabs for Stufen and Fundstellen"""
    try:
        conn = get_db()
        cursor = conn.cursor()

        # Get stufen for dropdown
        cursor.execute("SELECT snr, sammlungsstueck FROM stufen ORDER BY snr")
        stufen_options = [f"{row[0]}: {row[1]}" for row in cursor.fetchall()]

        # Get fundstellen for dropdown
        cursor.execute("SELECT fsid, fundstelle FROM fundstellen ORDER BY fundstelle")
        fundstellen_options = [f"{row[0]}: {row[1]}" for row in cursor.fetchall()]

        # Get ALL images (both types)
        cursor.execute("""
            SELECT i.*, s.sammlungsstueck, f.fundstelle
            FROM images i
            LEFT JOIN stufen s ON i.snr = s.snr
            LEFT JOIN fundstellen f ON i.fundstelle_id = f.fsid
            ORDER BY i.isnr
        """)
        bilder_list = [dict(row) for row in cursor.fetchall()]

        conn.close()
        return render_template('bilder.html',
                             bilder_list=bilder_list,
                             stufen_options=stufen_options,
                             fundstellen_options=fundstellen_options)
    except Exception as e:
        return f"Error loading bilder page: {str(e)}", 500

@app.route('/api/bilder', methods=['GET'])
def api_get_bilder():
    """API: Get all bilder data with optional type filter"""
    try:
        image_type = request.args.get('type', None)  # 'stufen' or 'fundstellen'
        filter_col = request.args.get('filter_col', '')
        filter_text = request.args.get('filter_text', '')
        match_mode = request.args.get('match_mode', 'contains')

        conn = get_db()
        cursor = conn.cursor()

        query = """
            SELECT i.*, s.sammlungsstueck, f.fundstelle
            FROM images i
            LEFT JOIN stufen s ON i.snr = s.snr
            LEFT JOIN fundstellen f ON i.fundstelle_id = f.fsid
        """
        params = []

        # Add type filter if specified
        if image_type:
            query += " WHERE i.image_type = ?"
            params.append(image_type)

        # Add additional filters
        if image_type == 'stufen':
            bilder_columns = {
                'isnr': 'i.isnr', 'snr': 'i.snr',
                'sammlungsstueck': 's.sammlungsstueck', 'photo': 'i.photo',
            }
        else:  # fundstellen (default columns used when no type selected)
            bilder_columns = {
                'isnr': 'i.isnr', 'fundstelle_id': 'i.fundstelle_id',
                'fundstelle': 'f.fundstelle', 'photo': 'i.photo',
            }
        if filter_col and filter_text:
            filter_col = bilder_columns.get(filter_col)
            if filter_col is None:
                return jsonify([])

            if match_mode == 'startswith':
                query += f" AND {filter_col} LIKE ?"
                params.append(f"{filter_text}%")
            elif match_mode == 'exact':
                query += f" AND {filter_col} = ?"
                params.append(filter_text)
            else:
                query += f" AND {filter_col} LIKE ?"
                params.append(f"%{filter_text}%")
        elif filter_text:
            where, p = build_filter_clause(list(bilder_columns.values()), filter_text, match_mode)
            # build_filter_clause returns a " WHERE ..." fragment; combine with any
            # existing type filter using AND instead.
            if image_type:
                query += " AND" + where[len(" WHERE"):]
            else:
                query += where
            params.extend(p)
        query += " ORDER BY i.isnr"

        cursor.execute(query, params)
        rows = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return jsonify(rows)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/bilder/<int:isnr>', methods=['GET'])
def api_get_bilder_one(isnr):
    """API: Get single bilder by isnr"""
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM images WHERE isnr = ?", (isnr,))
        row = cursor.fetchone()
        conn.close()
        return jsonify(dict(row)) if row else jsonify({})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/bilder', methods=['POST'])
def api_create_bilder():
    """API: Create new bilder - saves to YOUR exact folder structure"""
    try:
        data = request.get_json()
        image_type = data.get('image_type', 'stufen')  # Default to stufen
        conn = get_db()
        cursor = conn.cursor()

        # Determine which reference to use and which folder
        if image_type == 'stufen':
            snr_display = data.get('snr')
            snr = int(snr_display.split(':')[0]) if snr_display else None
            fundstelle_id = None
            folder = STUFEN_IMAGES_FOLDER

            cursor.execute("SELECT sammlungsstueck FROM stufen WHERE snr = ?", (snr,))
            result = cursor.fetchone()
            sammlungsstueck = result[0] if result else ""

        else:  # fundstellen
            fundstelle_display = data.get('fundstelle')
            fundstelle_id = int(fundstelle_display.split(':')[0]) if fundstelle_display else None
            snr = None
            sammlungsstueck = ""
            folder = FUNDSTELLEN_IMAGES_FOLDER

        # Handle the photo file
        photo_filename = data.get('photo')
        if photo_filename:
            # If it's a full path, extract just the filename
            photo_filename = os.path.basename(photo_filename)

            # Check if file exists in uploads folder
            upload_path = os.path.join('static/uploads', photo_filename)
            if os.path.exists(upload_path):
                # Move to YOUR exact folder
                dest_path = os.path.join(folder, photo_filename)
                shutil.move(upload_path, dest_path)
                # Store relative path from mineral_web root
                photo_path = f"01_Bilder/{image_type == 'fundstellen' and '01' or '02'}_{image_type}/{photo_filename}"
            else:
                # Assume it's already in the correct folder
                photo_path = f"01_Bilder/{image_type == 'fundstellen' and '01' or '02'}_{image_type}/{photo_filename}"
        else:
            photo_path = ''

        cursor.execute("""
            INSERT INTO images (snr, fundstelle_id, sammlungsstueck, photo, image_type)
            VALUES (?, ?, ?, ?, ?)
        """, (snr, fundstelle_id, sammlungsstueck, photo_path, image_type))

        conn.commit()
        isnr = cursor.lastrowid
        conn.close()
        return jsonify({'success': True, 'isnr': isnr, 'image_type': image_type})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/bilder/<int:isnr>', methods=['PUT'])
def api_update_bilder(isnr):
    """API: Update bilder - handles both types in YOUR folders"""
    try:
        data = request.get_json()
        image_type = data.get('image_type', 'stufen')
        conn = get_db()
        cursor = conn.cursor()

        # Determine which reference to use and which folder
        if image_type == 'stufen':
            snr_display = data.get('snr')
            snr = int(snr_display.split(':')[0]) if snr_display else None
            fundstelle_id = None
            folder = STUFEN_IMAGES_FOLDER

            cursor.execute("SELECT sammlungsstueck FROM stufen WHERE snr = ?", (snr,))
            result = cursor.fetchone()
            sammlungsstueck = result[0] if result else ""

        else:  # fundstellen
            fundstelle_display = data.get('fundstelle')
            fundstelle_id = int(fundstelle_display.split(':')[0]) if fundstelle_display else None
            snr = None
            sammlungsstueck = ""
            folder = FUNDSTELLEN_IMAGES_FOLDER

        # Handle the photo file
        photo_filename = data.get('photo')
        if photo_filename:
            photo_filename = os.path.basename(photo_filename)

            # Check if file exists in uploads folder
            upload_path = os.path.join('static/uploads', photo_filename)
            if os.path.exists(upload_path):
                # Move to YOUR exact folder
                dest_path = os.path.join(folder, photo_filename)
                shutil.move(upload_path, dest_path)
                photo_path = f"01_Bilder/{image_type == 'fundstellen' and '01' or '02'}_{image_type}/{photo_filename}"
            else:
                photo_path = f"01_Bilder/{image_type == 'fundstellen' and '01' or '02'}_{image_type}/{photo_filename}"
        else:
            photo_path = None

        cursor.execute("""
            UPDATE images
            SET snr = ?, fundstelle_id = ?, sammlungsstueck = ?, photo = ?, image_type = ?
            WHERE isnr = ?
        """, (snr, fundstelle_id, sammlungsstueck, photo_path, image_type, isnr))

        conn.commit()
        conn.close()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/bilder/<int:isnr>', methods=['DELETE'])
def api_delete_bilder(isnr):
    """API: Delete bilder - removes from YOUR exact folders"""
    try:
        conn = get_db()
        cursor = conn.cursor()

        # First get the image to delete the file
        cursor.execute("SELECT photo, image_type FROM images WHERE isnr = ?", (isnr,))
        row = cursor.fetchone()

        if row:
            photo_path, image_type = row
            if photo_path:
                # Extract filename from stored path
                filename = os.path.basename(photo_path)

                # Determine which folder based on image_type
                if image_type == 'fundstellen':
                    folder_path = FUNDSTELLEN_IMAGES_FOLDER
                else:
                    folder_path = STUFEN_IMAGES_FOLDER

                full_path = os.path.join(folder_path, filename)
                if os.path.exists(full_path):
                    os.remove(full_path)

        # Delete from database
        cursor.execute("DELETE FROM images WHERE isnr = ?", (isnr,))
        conn.commit()
        conn.close()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/bilder/upload', methods=['POST'])
def api_upload_bilder():
    """API: Upload an image, rename it, and store it in the correct folder.
    Stufen rename: isnr-snr-fundstelle-mineral_1-gestein.<ext>
    Fundstellen rename: isnr-fsid-ortschaft-fundstelle.<ext>
    Updates images.photo for the given isnr."""
    try:
        if 'file' not in request.files:
            return jsonify({'success': False, 'error': 'Keine Datei hochgeladen'}), 400
        file = request.files['file']
        if not file or file.filename == '':
            return jsonify({'success': False, 'error': 'Keine Datei ausgewählt'}), 400
        if not allowed_file(file.filename):
            return jsonify({'success': False, 'error': 'Dateityp nicht erlaubt'}), 400

        isnr = request.form.get('isnr')
        image_type = request.form.get('image_type', 'stufen')
        ext = file.filename.rsplit('.', 1)[1].lower()

        if not isnr:
            return jsonify({'success': False, 'error': 'isnr fehlt'}), 400

        conn = get_db()
        cursor = conn.cursor()

        def slug(value):
            if value is None:
                return ''
            s = str(value).strip()
            for ch in ' /\\:;,*?"<>|()[]{}#&=+!@`\'':
                s = s.replace(ch, '_')
            while '__' in s:
                s = s.replace('__', '_')
            return s.strip('_')

        if image_type == 'fundstellen':
            fsid = request.form.get('fsid')
            fundstelle = ''
            ortschaft = ''
            if fsid:
                cursor.execute("SELECT fundstelle, ortschaft FROM fundstellen WHERE fsid = ?", (fsid,))
                row = cursor.fetchone()
                if row:
                    fundstelle = row['fundstelle'] or ''
                    ortschaft = row['ortschaft'] or ''
            parts = [slug(isnr), slug(fsid), slug(ortschaft), slug(fundstelle)]
            folder = FUNDSTELLEN_IMAGES_FOLDER
        else:
            snr = request.form.get('snr')
            fundstelle = ''
            mineral_1 = ''
            gestein = ''
            if snr:
                cursor.execute("SELECT fundstelle, mineral_1, gestein FROM stufen WHERE snr = ?", (snr,))
                row = cursor.fetchone()
                if row:
                    fundstelle = row['fundstelle'] or ''
                    mineral_1 = row['mineral_1'] or ''
                    gestein = row['gestein'] or ''
            parts = [slug(isnr), slug(snr), slug(fundstelle), slug(mineral_1), slug(gestein)]
            folder = STUFEN_IMAGES_FOLDER

        parts = [p for p in parts if p]
        base = '-'.join(parts) if parts else slug(isnr)
        new_filename = f"{base}.{ext}"
        dest_path = os.path.join(folder, new_filename)
        # Avoid collisions
        if os.path.exists(dest_path):
            i = 1
            while os.path.exists(os.path.join(folder, f"{base}_{i}.{ext}")):
                i += 1
            new_filename = f"{base}_{i}.{ext}"
            dest_path = os.path.join(folder, new_filename)

        file.save(dest_path)

        cursor.execute("UPDATE images SET photo = ? WHERE isnr = ?", (new_filename, isnr))
        conn.commit()
        conn.close()
        return jsonify({'success': True, 'photo': new_filename})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/01_Bilder/<type>/<filename>')
def serve_image(type, filename):
    """Serve images from YOUR exact folder structure: 01_Bilder/01_Fundstellen/ or 01_Bilder/02_Stufen/"""
    try:
        if type == '01_Fundstellen':
            return send_from_directory(FUNDSTELLEN_IMAGES_FOLDER, filename)
        elif type == '02_Stufen':
            return send_from_directory(STUFEN_IMAGES_FOLDER, filename)
        else:
            # Try both folders as fallback
            for folder in [FUNDSTELLEN_IMAGES_FOLDER, STUFEN_IMAGES_FOLDER]:
                if os.path.exists(os.path.join(folder, filename)):
                    return send_from_directory(folder, filename)
            return "Image not found", 404
    except Exception as e:
        return f"Error serving image: {str(e)}", 404

@app.route('/images/<filename>')
def serve_image_direct(filename):
    """Serve images directly by filename - fallback for when images are in static/ or root"""
    try:
        # Try static folder first
        if os.path.exists(os.path.join('static', filename)):
            return send_from_directory('static', filename)

        # Try 01_Bilder/02_Stufen
        if os.path.exists(os.path.join(STUFEN_IMAGES_FOLDER, filename)):
            return send_from_directory(STUFEN_IMAGES_FOLDER, filename)

        # Try 01_Bilder/01_Fundstellen
        if os.path.exists(os.path.join(FUNDSTELLEN_IMAGES_FOLDER, filename)):
            return send_from_directory(FUNDSTELLEN_IMAGES_FOLDER, filename)

        return "Image not found", 404
    except Exception as e:
        return f"Error serving image: {str(e)}", 404

# ==================== EXPORT ROUTES ====================

# ==================== EXPORT ROUTES (FIXED WITH CHUNKING) ====================

# Ensure export folder exists at the root
EXPORT_FOLDER = "02_Exports"
os.makedirs(EXPORT_FOLDER, exist_ok=True)

def get_osm_link(fundstelle_raw):
    """Helper function to get OSM link for a fundstelle"""
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT lat, lon FROM fundstellen WHERE fundstelle=?", (fundstelle_raw,))
        hit = cursor.fetchone()
        conn.close()

        if hit and hit[0] is not None and hit[1] is not None:
            lat, lon = hit
            return f"https://www.openstreetmap.org/?mlat={lat}&mlon={lon}&zoom=15", lat, lon
        return None, None, None
    except Exception as e:
        print(f"Error in get_osm_link: {e}")
        return None, None, None

@app.route('/export/csv')
def export_csv():
    """Export all data to CSV files in 02_Exports/"""
    try:
        from datetime import datetime
        date_str = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        export_folder = os.path.join(EXPORT_FOLDER, date_str)
        os.makedirs(export_folder, exist_ok=True)

        conn = get_db()
        cursor = conn.cursor()

        tables = ["geologischeprovinz", "revier", "fundstellen", "stufen", "images"]
        for table in tables:
            cursor.execute(f"SELECT * FROM {table}")
            rows = cursor.fetchall()
            headers = [d[0] for d in cursor.description]
            csv_path = os.path.join(export_folder, f"{table}.csv")
            with open(csv_path, "w", newline='', encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(headers)
                w.writerows(rows)

        conn.close()
        return f"CSV files exported to: {export_folder}<br><a href='/start'>Back</a>"
    except Exception as e:
        return f"CSV export error: {str(e)}<br><a href='/start'>Back</a>", 500

@app.route('/export/pdf')
def export_pdf():
    """Export data to PDF files in 02_Exports/ with chunking to prevent overflow"""
    try:
        from datetime import datetime
        from reportlab.lib.pagesizes import A3, landscape
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, PageBreak, Spacer
        from reportlab.lib import colors
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.platypus import KeepTogether

        date_str = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        export_folder = os.path.join(EXPORT_FOLDER, date_str)
        os.makedirs(export_folder, exist_ok=True)

        conn = get_db()
        cursor = conn.cursor()
        styles = getSampleStyleSheet()

        # Smaller font sizes to prevent overflow
        wrap7 = ParagraphStyle("wrap7", parent=styles["Normal"], fontSize=5, leading=6)
        wrap7_center = ParagraphStyle("wrap7c", parent=wrap7, alignment=1)

        # ===== PDF 1: Sammlungsstücke =====
        filename1 = os.path.join(export_folder, f"01_Sammlungsstuecke_{date_str}.pdf")
        doc1 = SimpleDocTemplate(filename1, pagesize=landscape(A3), topMargin=30, bottomMargin=30)
        elements1 = []

        cursor.execute("""
            SELECT s.snr, s.sammlungsstueck, s.fundstelle, f.bergbaurevier,
                   s.art, s.groesse, s.mineral_1, s.mineral_2, s.mineral_3, s.mineral_4,
                   s.beschreibung, s.fundjahr, s.herkunft, s.im_bestand,
                   s.mineral_1_formula, s.mineral_2_formula, s.mineral_3_formula, s.mineral_4_formula,
                   f.land, f.region, f.ortschaft, f.lat, f.lon
            FROM stufen s
            LEFT JOIN fundstellen f ON s.fundstelle = f.fundstelle
            ORDER BY COALESCE(s.mineral_1,''), COALESCE(s.fundstelle,'')
        """)

        rows = cursor.fetchall()
        headers = [
            "snr", "Sammlungsstück", "Fundstelle", "Revier", "Art", "Größe",
            "Minerale", "Formeln", "Beschreibung", "Fundjahr", "Herkunft", "Im Bestand"
        ]
        data = [[Paragraph(h, wrap7_center) for h in headers]]

        for r in rows:
            (snr, sammlungsstueck, fundstelle_raw, revier,
             art, groesse, m1, m2, m3, m4,
             beschreibung, fundjahr, herkunft, im_bestand,
             f1, f2, f3, f4,
             land, region, ortschaft, lat, lon) = r

            concatenated = " - ".join([x for x in [land, region, ortschaft, fundstelle_raw] if x])
            minerals = " / ".join([x for x in [m1, m2, m3, m4] if x])
            formulas = " / ".join([x for x in [f1, f2, f3, f4] if x])

            data.append([
                Paragraph(str(snr or ""), wrap7),
                Paragraph(str(sammlungsstueck or ""), wrap7),
                Paragraph(str(concatenated or ""), wrap7),
                Paragraph(str(revier or ""), wrap7),
                Paragraph(str(art or ""), wrap7),
                Paragraph(str(groesse or ""), wrap7),
                Paragraph(str(minerals or ""), wrap7),
                Paragraph(str(formulas or ""), wrap7),
                Paragraph(str(beschreibung or ""), wrap7),
                Paragraph(str(fundjahr or ""), wrap7),
                Paragraph(str(herkunft or ""), wrap7),
                Paragraph(str(im_bestand or ""), wrap7),
            ])

        table = Table(data, repeatRows=1)
        table.setStyle(TableStyle([
            ("BACKGROUND", (0,0), (-1,0), colors.lightgrey),
            ("GRID", (0,0), (-1,-1), 0.25, colors.black),
            ("VALIGN", (0,0), (-1,-1), "TOP"),
            ("FONTSIZE", (0,0), (-1,-1), 5),
            ("TOPPADDING", (0,0), (-1,-1), 1),
            ("BOTTOMPADDING", (0,0), (-1,-1), 1),
        ]))
        elements1.append(table)
        doc1.build(elements1)

        # ===== PDF 2: Fundstellen =====
        filename2 = os.path.join(export_folder, f"02_Fundstellen_{date_str}.pdf")
        doc2 = SimpleDocTemplate(filename2, pagesize=landscape(A3), topMargin=30, bottomMargin=30)
        elements2 = []

        cursor.execute("""
            SELECT fsid, fundstelle, bergbaurevier, ortschaft, region, land, geologische_provinz,
                   typ, kommentar, lat, lon
            FROM fundstellen
            ORDER BY fundstelle
        """)
        fs_rows = cursor.fetchall()

        headers2 = [
            "fsid", "Fundstelle", "Revier", "Ortschaft", "Region", "Land",
            "Geologische Provinz", "Typ", "Kommentar", "Lat", "Lon"
        ]
        data2 = [[Paragraph(h, wrap7_center) for h in headers2]]

        for fsid, fundstelle, revier, ortschaft, region, land, provinz, typ, kommentar, lat, lon in fs_rows:
            data2.append([
                Paragraph(str(fsid or ""), wrap7),
                Paragraph(str(fundstelle or ""), wrap7),
                Paragraph(str(revier or ""), wrap7),
                Paragraph(str(ortschaft or ""), wrap7),
                Paragraph(str(region or ""), wrap7),
                Paragraph(str(land or ""), wrap7),
                Paragraph(str(provinz or ""), wrap7),
                Paragraph(str(typ or ""), wrap7),
                Paragraph(str(kommentar or ""), wrap7),
                Paragraph(str(lat or ""), wrap7),
                Paragraph(str(lon or ""), wrap7),
            ])

        table2 = Table(data2, repeatRows=1)
        table2.setStyle(TableStyle([
            ("BACKGROUND", (0,0), (-1,0), colors.lightgrey),
            ("GRID", (0,0), (-1,-1), 0.25, colors.black),
            ("VALIGN", (0,0), (-1,-1), "TOP"),
            ("FONTSIZE", (0,0), (-1,-1), 5),
            ("TOPPADDING", (0,0), (-1,-1), 1),
            ("BOTTOMPADDING", (0,0), (-1,-1), 1),
        ]))
        elements2.append(table2)
        doc2.build(elements2)

        # ===== PDF 3: Minerale (WITH CHUNKING TO PREVENT OVERFLOW) =====
        filename3 = os.path.join(export_folder, f"03_Minerale_{date_str}.pdf")
        doc3 = SimpleDocTemplate(filename3, pagesize=landscape(A3), topMargin=30, bottomMargin=30)
        elements3 = []

        # Get all unique minerals
        cursor.execute("""
            SELECT DISTINCT mineral_1 FROM stufen WHERE mineral_1 IS NOT NULL AND mineral_1!=''
            UNION SELECT DISTINCT mineral_2 FROM stufen WHERE mineral_2 IS NOT NULL AND mineral_2!=''
            UNION SELECT DISTINCT mineral_3 FROM stufen WHERE mineral_3 IS NOT NULL AND mineral_3!=''
            UNION SELECT DISTINCT mineral_4 FROM stufen WHERE mineral_4 IS NOT NULL AND mineral_4!=''
        """)
        all_minerals = sorted({m[0] for m in cursor.fetchall() if m[0]})

        # Split into chunks of 10 minerals per table to prevent overflow
        mineral_chunks = [all_minerals[i:i+10] for i in range(0, len(all_minerals), 10)]

        for chunk in mineral_chunks:
            headers3 = ["Mineral", "Fundstellen", "Sammlungsstücke"]
            data3 = [[Paragraph(h, wrap7_center) for h in headers3]]

            for mineral in chunk:
                # Get fundstellen for this mineral
                cursor.execute("""
                    SELECT DISTINCT s.fundstelle
                    FROM stufen s
                    WHERE s.mineral_1=? OR s.mineral_2=? OR s.mineral_3=? OR s.mineral_4=?
                    ORDER BY s.fundstelle
                """, (mineral, mineral, mineral, mineral))
                fs_raw_list = [row[0] for row in cursor.fetchall() if row[0]]

                fs_links = []
                for raw in fs_raw_list:
                    url, lat, lon = get_osm_link(raw)
                    if url:
                        fs_links.append(Paragraph(f'<link href="{url}">{raw}</link>', wrap7))
                    else:
                        fs_links.append(Paragraph(raw, wrap7))

                # Get stufen for this mineral
                cursor.execute("""
                    SELECT s.snr, s.sammlungsstueck, s.im_bestand
                    FROM stufen s
                    WHERE s.mineral_1=? OR s.mineral_2=? OR s.mineral_3=? OR s.mineral_4=?
                    ORDER BY s.snr
                """, (mineral, mineral, mineral, mineral))
                st_rows = cursor.fetchall()

                st_list = []
                for snr, name, im_bestand in st_rows:
                    label = f"{snr} {name or ''}".strip()
                    if (im_bestand or "").strip().lower().startswith("ja"):
                        st_list.append(Paragraph(f"<b><font color='blue'>{label}</font></b>", wrap7))
                    else:
                        st_list.append(Paragraph(f"<font color='red'>{label}</font>", wrap7))

                data3.append([
                    Paragraph(mineral, wrap7),
                    fs_links,
                    st_list
                ])

            # Create table for this chunk
            t = Table(data3, repeatRows=1)
            t.setStyle(TableStyle([
                ("BACKGROUND", (0,0), (-1,0), colors.lightgrey),
                ("GRID", (0,0), (-1,-1), 0.25, colors.black),
                ("VALIGN", (0,0), (-1,-1), "TOP"),
                ("FONTSIZE", (0,0), (-1,-1), 5),
                ("TOPPADDING", (0,0), (-1,-1), 1),
                ("BOTTOMPADDING", (0,0), (-1,-1), 1),
                ("ROWHEIGHTS", (0,0), (-1,-1), 80),  # Limit row height
            ]))
            elements3.append(t)
            elements3.append(Spacer(1, 12))  # Add some space between tables

        doc3.build(elements3)
        conn.close()

        return f"""
        <div class="container mt-5">
            <h2>PDF Export Successful</h2>
            <p>PDF files exported to: <code>{export_folder}</code></p>
            <div class="mt-3">
                <a href="/start" class="btn btn-primary">Back to Start</a>
                <a href="/02_Exports/{date_str}" class="btn btn-secondary ms-2">View Files</a>
            </div>
            <div class="mt-4">
                <h4>Files:</h4>
                <ul>
                    <li><a href="/02_Exports/{date_str}/01_Sammlungsstuecke_{date_str}.pdf">Sammlungsstücke PDF</a></li>
                    <li><a href="/02_Exports/{date_str}/02_Fundstellen_{date_str}.pdf">Fundstellen PDF</a></li>
                    <li><a href="/02_Exports/{date_str}/03_Minerale_{date_str}.pdf">Minerale PDF</a></li>
                </ul>
            </div>
        </div>
        """

    except Exception as e:
        import traceback
        error_details = str(e) + "<br>" + traceback.format_exc()
        return f"""
        <div class="container mt-5">
            <h2 class="text-danger">PDF Export Failed</h2>
            <p>Error: {error_details}</p>
            <div class="mt-3">
                <a href="/start" class="btn btn-primary">Back to Start</a>
            </div>
        </div>
        """, 500

@app.route('/export/kml')
def export_kml():
    """Export fundstellen to KML file in 02_Exports/"""
    try:
        from datetime import datetime
        date_str = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        export_folder = os.path.join(EXPORT_FOLDER, date_str)
        os.makedirs(export_folder, exist_ok=True)

        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT fundstelle, kommentar, lat, lon FROM fundstellen WHERE lat IS NOT NULL AND lon IS NOT NULL")
        rows = cursor.fetchall()

        kml_path = os.path.join(export_folder, "fundstellen.kml")
        with open(kml_path, "w", encoding="utf-8") as f:
            f.write('<?xml version="1.0" encoding="UTF-8"?>\n<kml xmlns="http://www.opengis.net/kml/2.2">\n<Document>\n')
            for fundstelle, kommentar, lat, lon in rows:
                desc = (kommentar or '').replace("&", "&amp;")
                f.write(
                    f"<Placemark><name>{fundstelle}</name>"
                    f"<description>{desc}</description>"
                    f"<Point><coordinates>{lon},{lat},0</coordinates></Point></Placemark>\n"
                )
            f.write("</Document></kml>")

        conn.close()
        return f"""
        <div class="container mt-5">
            <h2>KML Export Successful</h2>
            <p>KML file exported to: <code>{kml_path}</code></p>
            <div class="mt-3">
                <a href="/start" class="btn btn-primary">Back to Start</a>
                <a href="/02_Exports/{date_str}/fundstellen.kml" class="btn btn-secondary ms-2" download>Download KML</a>
            </div>
        </div>
        """
    except Exception as e:
        return f"""
        <div class="container mt-5">
            <h2 class="text-danger">KML Export Failed</h2>
            <p>Error: {str(e)}</p>
            <div class="mt-3">
                <a href="/start" class="btn btn-primary">Back to Start</a>
            </div>
        </div>
        """, 500

@app.route('/export/shp')
def export_shp():
    """Export stufen with coordinates to SHP file in 02_Exports/"""
    try:
        from datetime import datetime
        import shapefile

        date_str = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        export_folder = os.path.join(EXPORT_FOLDER, date_str)
        os.makedirs(export_folder, exist_ok=True)

        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT s.snr, s.sammlungsstueck, s.fundstelle, f.lat, f.lon
            FROM stufen s
            LEFT JOIN fundstellen f ON s.fundstelle = f.fundstelle
            WHERE f.lat IS NOT NULL AND f.lon IS NOT NULL
        """)
        shp_rows = cursor.fetchall()

        if shp_rows:
            shp_path = os.path.join(export_folder, "stufen")
            with shapefile.Writer(shp_path, shapefile.POINT) as shp:
                shp.autoBalance = 1
                shp.field("snr", "N")
                shp.field("fundst", "C", size=80)
                shp.field("name", "C", size=120)

                for snr, name, fundst, lat, lon in shp_rows:
                    shp.point(float(lon), float(lat))
                    shp.record(int(snr), str(fundst or ""), str(name or ""))

        conn.close()
        return f"""
        <div class="container mt-5">
            <h2>SHP Export Successful</h2>
            <p>SHP files exported to: <code>{export_folder}</code></p>
            <div class="mt-3">
                <a href="/start" class="btn btn-primary">Back to Start</a>
            </div>
            <div class="mt-2 alert alert-info">
                <i class="bi bi-info-circle"></i> SHP files require multiple files (.shp, .shx, .dbf).
                All files are in: <code>{export_folder}/stufen.*</code>
            </div>
        </div>
        """
    except Exception as e:
        return f"""
        <div class="container mt-5">
            <h2 class="text-danger">SHP Export Failed</h2>
            <p>Error: {str(e)}</p>
            <div class="mt-3">
                <a href="/start" class="btn btn-primary">Back to Start</a>
            </div>
        </div>
        """, 500

@app.route('/02_Exports/<path:subpath>')
def serve_exports(subpath):
    """Serve files from 02_Exports folder"""
    try:
        return send_from_directory(EXPORT_FOLDER, subpath)
    except Exception:
        return "File not found", 404
# ==================== NORMALIZE FUNDSTELLEN ====================

@app.route('/normalize', methods=['GET'])
def normalize_page():
    """Normalize Fundstellen: preview data-quality issues (whitespace, orphan stufen references)."""
    try:
        conn = get_db()
        cursor = conn.cursor()

        # 1) Fundstellen with leading/trailing whitespace or doubled internal spaces
        cursor.execute("""
            SELECT fsid, fundstelle
            FROM fundstellen
            WHERE fundstelle != TRIM(fundstelle)
               OR fundstelle != REPLACE(REPLACE(fundstelle, '  ', ' <'), '< ', '')
        """)
        whitespace_rows = [dict(r) for r in cursor.fetchall()]

        # 2) Stufen referencing fundstelle values that don't exist in the fundstellen table
        cursor.execute("""
            SELECT DISTINCT s.fundstelle, COUNT(*) AS stufen_count
            FROM stufen s
            LEFT JOIN fundstellen f ON s.fundstelle = f.fundstelle
            WHERE s.fundstelle IS NOT NULL AND s.fundstelle != ''
              AND f.fundstelle IS NULL
            GROUP BY s.fundstelle
            ORDER BY stufen_count DESC, s.fundstelle
        """)
        orphan_rows = [dict(r) for r in cursor.fetchall()]

        # 3) Possible duplicate fundstellen (same name ignoring case & whitespace)
        cursor.execute("""
            SELECT fundstelle, fsid
            FROM fundstellen
            ORDER BY LOWER(TRIM(fundstelle)), fsid
        """)
        seen = {}
        duplicate_groups = []
        for r in cursor.fetchall():
            key = r[0].strip().lower() if r[0] else ''
            if not key:
                continue
            seen.setdefault(key, []).append({'fsid': r[1], 'fundstelle': r[0]})
        for key, group in seen.items():
            if len(group) > 1:
                duplicate_groups.append(group)

        # Existing fundstellen names for the mapping dropdown
        cursor.execute("SELECT fundstelle FROM fundstellen ORDER BY fundstelle")
        fundstelle_options = [row[0] for row in cursor.fetchall() if row[0]]

        conn.close()
        return render_template('normalize.html',
                             whitespace_rows=whitespace_rows,
                             orphan_rows=orphan_rows,
                             duplicate_groups=duplicate_groups,
                             fundstelle_options=fundstelle_options)
    except Exception as e:
        return f"Error loading normalize page: {str(e)}", 500


@app.route('/api/normalize', methods=['POST'])
def api_normalize():
    """Apply normalization fixes: trim whitespace and re-map orphan stufen.fundstelle references."""
    try:
        data = request.get_json() or {}
        action = data.get('action', '')
        conn = get_db()
        cursor = conn.cursor()
        results = {'trimmed': 0, 'remapped': 0, 'errors': []}

        if action == 'trim_whitespace':
            cursor.execute("SELECT fsid, fundstelle FROM fundstellen WHERE fundstelle != TRIM(fundstelle)")
            for fsid, fundstelle in cursor.fetchall():
                cleaned = ' '.join(fundstelle.split())
                cursor.execute("UPDATE fundstellen SET fundstelle = ? WHERE fsid = ?", (cleaned, fsid))
                results['trimmed'] += 1

        elif action == 'remap_orphans':
            mappings = data.get('mappings', {}) or {}
            for orphan_name, target_name in mappings.items():
                if not target_name:
                    continue
                cursor.execute("SELECT fsid FROM fundstellen WHERE fundstelle = ?", (target_name,))
                hit = cursor.fetchone()
                if not hit:
                    results['errors'].append(f"Ziel-Fundstelle nicht gefunden: {target_name}")
                    continue
                cursor.execute("UPDATE stufen SET fundstelle = ? WHERE fundstelle = ?",
                               (target_name, orphan_name))
                results['remapped'] += cursor.rowcount

        else:
            conn.close()
            return jsonify({'success': False, 'error': 'Unbekannte Aktion'}), 400

        conn.commit()
        conn.close()
        return jsonify({'success': True, **results})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500



# --- STATIC FILES ---
@app.route('/static/<path:filename>')
def static_file(filename):
    """Serve static files"""
    return send_from_directory('static', filename)

@app.route('/static/uploads/<filename>')
def uploaded_file(filename):
    """Serve uploaded files"""
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

# ==================== RUN SERVER ====================
if __name__ == '__main__':
    # Verify database exists
    if not os.path.exists(DB_PATH):
        print(f"Error: Database file not found at {DB_PATH}")
        print("Please copy your MG-Sammlung.db file to this directory")
        exit(1)

    print("\n" + "="*60)
    print("  MINERAL COLLECTION DATABASE - LOCAL BROWSER UI")
    print("="*60)
    print(f"\nUsing database: {DB_PATH}")
    print("\nStarting server...")
    print("\nOpen your browser and navigate to: http://localhost:5000")
    print("\nPress Ctrl+C to stop the server\n")

    app.run(debug=True, host='0.0.0.0', port=5000)