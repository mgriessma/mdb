"""
Mineral Collection Database - Local Browser UI
Run with: python app.py
Access at: http://localhost:5000

Features:
- Browser-based UI for mineral collection management
- CRUD operations for all tables
- Live filtering on all pages
- Chemical formula lookup for minerals
- Batch update for existing records
- Export to CSV, JSON, PDF, and KML
"""

from flask import Flask, render_template, request, jsonify, send_from_directory, redirect, url_for, send_file
import sqlite3
import os
from datetime import datetime
import csv
import json
import subprocess
import platform
import shutil
from werkzeug.utils import secure_filename
from functools import lru_cache
import pandas as pd
from io import BytesIO, StringIO

# ==================== CONFIGURATION ====================
DB_PATH = "MG-Sammlung.db"  # SQLite database file
UPLOAD_FOLDER = "static/uploads"
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'bmp'}
EXPORT_FOLDER = "02_Exports"

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB limit
app.secret_key = 'mineral-collection-secret-key-change-in-production'

# Ensure folders exist
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(EXPORT_FOLDER, exist_ok=True)
os.makedirs("01_Bilder", exist_ok=True)

# ==================== DATABASE HELPERS ====================

def get_db():
    """Get database connection"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def init_db():
    """Initialize the database with required tables"""
    conn = get_db()
    cursor = conn.cursor()
    
    # Create tables if they don't exist
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS geologischeprovinz (
            gid INTEGER PRIMARY KEY AUTOINCREMENT,
            provinz TEXT NOT NULL,
            geologie_typ TEXT,
            gehoert_zu TEXT,
            erdalter TEXT
        )
    """)
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS revier (
            rid INTEGER PRIMARY KEY AUTOINCREMENT,
            bergbaurevier TEXT NOT NULL,
            rohstoffe TEXT,
            lagerstaettentyp1 TEXT,
            lagerstaettentyp2 TEXT,
            lagerstaettentyp3 TEXT,
            lagerstaettentyp4 TEXT,
            geologische_provinz TEXT,
            bergbauperiode TEXT,
            kommentar TEXT
        )
    """)
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS fundstellen (
            fsid INTEGER PRIMARY KEY AUTOINCREMENT,
            fundstelle TEXT NOT NULL,
            bergbaurevier TEXT,
            ortschaft TEXT,
            region TEXT,
            land TEXT,
            geologische_provinz TEXT,
            typ TEXT,
            kommentar TEXT,
            lat REAL,
            lon REAL
        )
    """)
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS stufen (
            snr INTEGER PRIMARY KEY AUTOINCREMENT,
            fundstelle TEXT,
            sammlungsstueck TEXT,
            art TEXT,
            groesse TEXT,
            mineral_1 TEXT,
            mineral_2 TEXT,
            mineral_3 TEXT,
            mineral_4 TEXT,
            gestein TEXT,
            beschreibung TEXT,
            fundjahr INTEGER,
            herkunft TEXT,
            im_bestand TEXT,
            mineral_1_formula TEXT,
            mineral_2_formula TEXT,
            mineral_3_formula TEXT,
            mineral_4_formula TEXT,
            ex_sammlung TEXT,
            ex_sammlung_nr TEXT
        )
    """)
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS images (
            isnr INTEGER PRIMARY KEY AUTOINCREMENT,
            snr INTEGER,
            sammlungsstueck TEXT,
            photo TEXT,
            image_type TEXT DEFAULT 'stufen',
            fundstelle_id INTEGER
        )
    """)
    
    # Add formula columns if they don't exist
    cursor.execute("PRAGMA table_info(stufen)")
    columns = [column[1] for column in cursor.fetchall()]
    formula_columns = ['mineral_1_formula', 'mineral_2_formula', 'mineral_3_formula', 'mineral_4_formula']
    for col in formula_columns:
        if col not in columns:
            cursor.execute(f"ALTER TABLE stufen ADD COLUMN {col} TEXT")
    
    # Add ex_sammlung columns if they don't exist
    if 'ex_sammlung' not in columns:
        cursor.execute("ALTER TABLE stufen ADD COLUMN ex_sammlung TEXT")
    if 'ex_sammlung_nr' not in columns:
        cursor.execute("ALTER TABLE stufen ADD COLUMN ex_sammlung_nr TEXT")
    
    # Add image_type column if it doesn't exist
    cursor.execute("PRAGMA table_info(images)")
    columns = [column[1] for column in cursor.fetchall()]
    if 'image_type' not in columns:
        cursor.execute("ALTER TABLE images ADD COLUMN image_type TEXT DEFAULT 'stufen'")
    
    if 'fundstelle_id' not in columns:
        cursor.execute("ALTER TABLE images ADD COLUMN fundstelle_id INTEGER")
    
    conn.commit()
    conn.close()

# Mineral formula lookup (simplified version)
COMMON_MINERALS = {
    'quarz': 'SiO2',
    'feldspat': 'KAlSi3O8',
    'calcit': 'CaCO3',
    'pyrit': 'FeS2',
    'hematit': 'Fe2O3',
    'magnetit': 'Fe3O4',
    'galenit': 'PbS',
    'sphalerit': 'ZnS',
    'chalcopyrit': 'CuFeS2',
    'bornit': 'Cu5FeS4',
    'malachit': 'Cu2CO3(OH)2',
    'azurit': 'Cu3(CO3)2(OH)2',
    'baryt': 'BaSO4',
    'fluorit': 'CaF2',
    'granat': '(Fe,Mg,Ca,Mn)3(Al,Cr,Fe)2(SiO4)3',
    'amphibol': '(Ca,Na)2(Mg,Fe,Al)5(Al,Si)8O22(OH)2',
    'biotit': 'K(Mg,Fe)3(AlSi3O10)(OH)2',
    'muskovit': 'KAl2(AlSi3O10)(OH)2',
    'orthoklas': 'KAlSi3O8',
    'albit': 'NaAlSi3O8',
    'anorthit': 'CaAl2Si2O8',
    'olivin': '(Mg,Fe)2SiO4',
    'augit': '(Ca,Na)(Mg,Fe,Al)(Si,Al)2O6',
    'hornblende': '(Ca,Na)2(Mg,Fe,Al)5(Al,Si)8O22(OH)2',
    'glimmer': 'KAl2(AlSi3O10)(OH)2',
    'gips': 'CaSO4·2H2O',
    'anhydrit': 'CaSO4',
    'halit': 'NaCl',
    'sylvin': 'KCl',
    'dolomit': 'CaMg(CO3)2',
    'siderit': 'FeCO3',
    'rhodochrosit': 'MnCO3',
    'smithsonit': 'ZnCO3',
    'cerussit': 'PbCO3',
    'aragonit': 'CaCO3',
    'turmalin': '(Ca,Na)(Mg,Al,Fe,Li)3Al6(BO3)3Si6O18(OH)4',
    'beryll': 'Be3Al2(SiO3)6',
    'topas': 'Al2SiO4(F,OH)2',
    'korund': 'Al2O3',
    'spinell': 'MgAl2O4',
    'apatit': 'Ca5(PO4)3(OH,F,Cl)',
    'zirkon': 'ZrSiO4',
    'rutile': 'TiO2',
    'anatase': 'TiO2',
    'brookite': 'TiO2',
    'ilmenit': 'FeTiO3',
    'chromit': 'FeCr2O4',
    'magnesit': 'MgCO3',
    'limonit': 'FeO(OH)·nH2O',
    'goethit': 'FeO(OH)',
    'lepidolith': 'K(Li,Al)2-3(Al,Si)4O10(OH,F)2',
    'spodumen': 'LiAlSi2O6',
    'petalit': 'LiAlSi4O10',
    'amblygonit': 'LiAlPO4F',
    'lithium': 'Li',
    'cobaltit': 'CoAsS',
    'arsenopyrit': 'FeAsS',
    'skutterudit': 'CoAs3',
    'erythrin': 'Co3(AsO4)2·8H2O',
    'annabergit': 'Ni3(AsO4)2·8H2O',
    'nickelin': 'NiAs',
    'pentlandit': '(Fe,Ni)9S8',
    'millerit': 'NiS',
    'covellin': 'CuS',
    'chalkosin': 'Cu2S',
    'bornit': 'Cu5FeS4',
    'tennantit': 'Cu12As4S13',
    'tetraedrit': 'Cu12Sb4S13',
    'enargit': 'Cu3AsS4',
    'proustit': 'Ag3AsS3',
    'pyrargyrit': 'Ag3SbS3',
    'polybasit': '(Ag,Cu)16Sb2S11',
    'pearceit': '(Ag,Cu)16As2S11',
    'argentit': 'Ag2S',
    'silber': 'Ag',
    'gold': 'Au',
    'platin': 'Pt',
    'palladium': 'Pd',
    'osmium': 'Os',
    'iridium': 'Ir',
    'rhodium': 'Rh',
    'ruthenium': 'Ru',
    'graphit': 'C',
    'diamant': 'C',
    'schwefel': 'S',
    'realgar': 'AsS',
    'auripigment': 'As2S3',
    'stibnit': 'Sb2S3',
    'cinnabarit': 'HgS',
    'molybdenit': 'MoS2',
    'wolframit': '(Fe,Mn)WO4',
    'scheelit': 'CaWO4',
    'columbit': '(Fe,Mn)(Nb,Ta)2O6',
    'tantalit': '(Fe,Mn)(Ta,Nb)2O6',
    'microlit': '(Ca,Na)2Ta2O6(O,OH,F)',
    'beryllonit': 'NaBePO4',
    'herderit': 'CaBePO4F',
    'eucriptit': 'LiAlSiO4',
    'monazit': '(Ce,La,Th)PO4',
    'xenotim': 'YPO4',
    'zirkon': 'ZrSiO4',
    'thorit': 'ThSiO4',
    'uraninit': 'UO2',
    'carnotit': 'K2(UO2)2(VO4)2·3H2O',
    'tyuyamunit': 'Ca(UO2)2(VO4)2·5-8H2O',
    'autunit': 'Ca(UO2)2(PO4)2·10-12H2O',
    'torbernit': 'Cu(UO2)2(PO4)2·8-12H2O',
    'zeunerit': 'Cu(UO2)2(AsO4)2·10-16H2O',
    'uranocircit': 'Ba(UO2)2(PO4)2·10H2O',
    'vanadinite': 'Pb5(VO4)3Cl',
    'descloizit': 'Pb(Zn,Cu)(VO4)(OH)',
    'mottramit': 'PbCu(VO4)(OH)',
    'wulfenit': 'PbMoO4',
    'powellit': 'CaMoO4',
}

def get_formula(mineral_name):
    """Get chemical formula for a mineral"""
    if not mineral_name:
        return None
    
    # Try exact match
    mineral_lower = mineral_name.strip().lower()
    if mineral_lower in COMMON_MINERALS:
        return COMMON_MINERALS[mineral_lower]
    
    # Try partial match
    for key, formula in COMMON_MINERALS.items():
        if key in mineral_lower or mineral_lower in key:
            return formula
    
    return None

def get_formulas_for_stufe(mineral_1, mineral_2, mineral_3, mineral_4):
    """Get formulas for all non-empty mineral fields"""
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


def format_text_for_pdf(text):
    """Format text for PDF to handle special characters, subscripts, and superscripts.
    
    ReportLab has limited Unicode support with default fonts. This function:
    1. Replaces subscript numbers with regular numbers (e.g., ₂ -> 2)
    2. Replaces superscript numbers with regular numbers (e.g., ² -> 2)
    3. Replaces special characters that may not render properly
    4. Handles common chemical formula characters
    
    For proper subscript/superscript rendering, we need to use a font that supports
    these characters or use ReportLab's subscript/superscript features.
    """
    if not text:
        return text
    
    # Convert to string if not already
    text = str(text)
    
    # Replace common subscript characters with regular equivalents
    subscript_map = {
        '\u2080': '0',  # ₀
        '\u2081': '1',  # ₁
        '\u2082': '2',  # ₂
        '\u2083': '3',  # ₃
        '\u2084': '4',  # ₄
        '\u2085': '5',  # ₅
        '\u2086': '6',  # ₆
        '\u2087': '7',  # ₇
        '\u2088': '8',  # ₈
        '\u2089': '9',  # ₉
        '\u208a': '+',  # ₊
        '\u208b': '-',  # ₋
        '\u208c': '=',  # ₌
        '\u208d': '(',  # ₍
        '\u208e': ')',  # ₎
    }
    
    # Replace common superscript characters with regular equivalents
    superscript_map = {
        '\u00b9': '1',  # ¹
        '\u00b2': '2',  # ²
        '\u00b3': '3',  # ³
        '\u2074': '4',  # ⁴
        '\u2075': '5',  # ⁵
        '\u2076': '6',  # ⁶
        '\u2077': '7',  # ⁷
        '\u2078': '8',  # ⁸
        '\u2079': '9',  # ⁹
        '\u2070': '0',  # ⁰
        '\u207a': '+',  # ⁺
        '\u207b': '-',  # ⁻
        '\u207c': '=',  # ⁼
        '\u207d': '(',  # ⁽
        '\u207e': ')',  # ⁾
    }
    
    # Replace special characters that might not render
    special_char_map = {
        '\u00b7': '*',  # Middle dot (·)
        '\u2212': '-',  # Minus sign (−)
        '\u2217': '*',  # Asterisk operator (∗)
        '\u00d7': 'x',  # Multiplication sign (×)
        '\u22c5': '*',  # Dot operator (⋅)
        '\u00b0': ' ',  # Degree sign (°) - keep as space for now
        '\u00a0': ' ',  # Non-breaking space
    }
    
    # Apply all replacements
    for char_map in [subscript_map, superscript_map, special_char_map]:
        for old, new in char_map.items():
            text = text.replace(old, new)
    
    return text

def allowed_file(filename):
    """Check if file has allowed extension"""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def build_filter_clause(columns, filter_text, match_mode='contains'):
    """Build a WHERE clause matching filter_text across the given column expressions"""
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

# ==================== DROPDOWN OPTIONS ====================
TYP_OPTIONS = ["Aufschluss", "Steinbruch", "Tagebau", "Untertage", "Lesestein", "Halde", "Seife", "Unbekannt"]
STUFE_ART_OPTIONS = ["Artefakt", "Fossil", "Gestein", "Mineralstufe", "Erz", "Tektit o. Meteorit"]
GROESSE_OPTIONS = ["Mikromount (<2.5cm)", "Kleinststufe (<5cm)", "Kleinstufe (<10cm)", "Handstueck (<20cm)", "Stufe (>20cm)", "Duennschliff", "Bohrkern", "NA"]
HERKUNFT_OPTIONS = ["Eigenfund", "Kauf", "Tausch", "Geschenk", "Vater"]
IM_BESTAND_OPTIONS = ["Ja", "Nein (verkauft)", "Nein (verschenkt)", "Nein (verloren o. entsorgt)"]
ERDALTER_OPTIONS = ["Kaenozoikum", "Mesozoikum", "Palaeozoikum", "Proterozoikum", "Archaikum", "Hadaikum"]
EX_SAMMLUNG_OPTIONS = ["", "P Grießmann", "M Klanthe", "W Favorat"]

# ==================== ROUTES ====================

@app.route('/')
def index():
    """Main page - redirect to start page"""
    return redirect(url_for('start_page'))

@app.route('/start')
def start_page():
    """Start page with functionality overview"""
    return render_template('start.html')

# --- Statistics API ---
@app.route('/api/stats')
def api_stats():
    """Get database statistics"""
    conn = get_db()
    cursor = conn.cursor()
    
    stats = {}
    
    # Count records in each table
    for table in ['geologischeprovinz', 'revier', 'fundstellen', 'stufen', 'images']:
        cursor.execute(f"SELECT COUNT(*) as count FROM {table}")
        stats[f'{table}_count'] = cursor.fetchone()['count']
    
    # Count specimens by mineral type
    cursor.execute("""
        SELECT mineral_1, COUNT(*) as count 
        FROM stufen 
        WHERE mineral_1 IS NOT NULL AND mineral_1 != ''
        GROUP BY mineral_1 
        ORDER BY count DESC 
        LIMIT 10
    """)
    stats['top_minerals'] = [{'mineral': row['mineral_1'], 'count': row['count']} for row in cursor.fetchall()]
    
    # Count specimens by location
    cursor.execute("""
        SELECT fundstelle, COUNT(*) as count 
        FROM stufen 
        WHERE fundstelle IS NOT NULL AND fundstelle != ''
        GROUP BY fundstelle 
        ORDER BY count DESC 
        LIMIT 10
    """)
    stats['top_locations'] = [{'fundstelle': row['fundstelle'], 'count': row['count']} for row in cursor.fetchall()]
    
    # Count specimens by size
    cursor.execute("""
        SELECT groesse, COUNT(*) as count 
        FROM stufen 
        WHERE groesse IS NOT NULL AND groesse != ''
        GROUP BY groesse 
        ORDER BY count DESC
    """)
    stats['by_size'] = [{'groesse': row['groesse'], 'count': row['count']} for row in cursor.fetchall()]
    
    # Count unique minerals across all mineral fields (mineral_1 to mineral_4)
    cursor.execute("""
        SELECT COUNT(DISTINCT mineral) as count 
        FROM (
            SELECT mineral_1 as mineral FROM stufen WHERE mineral_1 IS NOT NULL AND mineral_1 != ''
            UNION
            SELECT mineral_2 as mineral FROM stufen WHERE mineral_2 IS NOT NULL AND mineral_2 != ''
            UNION
            SELECT mineral_3 as mineral FROM stufen WHERE mineral_3 IS NOT NULL AND mineral_3 != ''
            UNION
            SELECT mineral_4 as mineral FROM stufen WHERE mineral_4 IS NOT NULL AND mineral_4 != ''
        )
    """)
    stats['unique_minerals_count'] = cursor.fetchone()['count']
    
    conn.close()
    return jsonify(stats)

# --- Geologische Provinzen ---
@app.route('/provinz')
def provinz_page():
    """List geological provinces"""
    conn = get_db()
    cursor = conn.cursor()
    
    filter_text = request.args.get('filter', '')
    match_mode = request.args.get('match_mode', 'contains')
    
    columns = ['gid', 'provinz', 'geologie_typ', 'gehoert_zu', 'erdalter']
    where_clause, params = build_filter_clause(columns, filter_text, match_mode)
    
    cursor.execute(f"SELECT * FROM geologischeprovinz {where_clause} ORDER BY provinz", params)
    provinces = [dict(row) for row in cursor.fetchall()]
    
    conn.close()
    return render_template('provinz.html', provinces=provinces, filter_text=filter_text, match_mode=match_mode)

@app.route('/api/provinz')
def api_provinz():
    """API endpoint for geological provinces"""
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM geologischeprovinz ORDER BY provinz")
    provinces = [dict(row) for row in cursor.fetchall()]
    
    conn.close()
    return jsonify(provinces)

@app.route('/api/provinz/<int:gid>', methods=['GET'])
def api_provinz_get(gid):
    """Get a single province"""
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM geologischeprovinz WHERE gid = ?", (gid,))
    province = cursor.fetchone()
    
    conn.close()
    if province:
        return jsonify(dict(province))
    return jsonify({'error': 'Not found'}), 404

@app.route('/api/provinz', methods=['POST'])
def api_provinz_create():
    """Create a new province"""
    data = request.json
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute(
        "INSERT INTO geologischeprovinz (provinz, geologie_typ, gehoert_zu, erdalter) VALUES (?, ?, ?, ?)",
        (data.get('provinz'), data.get('geologie_typ'), data.get('gehoert_zu'), data.get('erdalter'))
    )
    conn.commit()
    
    province_id = cursor.lastrowid
    cursor.execute("SELECT * FROM geologischeprovinz WHERE gid = ?", (province_id,))
    province = cursor.fetchone()
    
    conn.close()
    return jsonify(dict(province)), 201

@app.route('/api/provinz/<int:gid>', methods=['PUT'])
def api_provinz_update(gid):
    """Update a province"""
    data = request.json
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute(
        "UPDATE geologischeprovinz SET provinz = ?, geologie_typ = ?, gehoert_zu = ?, erdalter = ? WHERE gid = ?",
        (data.get('provinz'), data.get('geologie_typ'), data.get('gehoert_zu'), data.get('erdalter'), gid)
    )
    conn.commit()
    
    cursor.execute("SELECT * FROM geologischeprovinz WHERE gid = ?", (gid,))
    province = cursor.fetchone()
    
    conn.close()
    if province:
        return jsonify(dict(province))
    return jsonify({'error': 'Not found'}), 404

@app.route('/api/provinz/<int:gid>', methods=['DELETE'])
def api_provinz_delete(gid):
    """Delete a province"""
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute("DELETE FROM geologischeprovinz WHERE gid = ?", (gid,))
    conn.commit()
    
    conn.close()
    return jsonify({'message': 'Deleted'}), 200

# --- Revier ---
@app.route('/revier')
def revier_page():
    """List mining districts"""
    conn = get_db()
    cursor = conn.cursor()
    
    filter_text = request.args.get('filter', '')
    match_mode = request.args.get('match_mode', 'contains')
    
    columns = ['rid', 'bergbaurevier', 'rohstoffe', 'lagerstaettentyp1', 'lagerstaettentyp2', 'lagerstaettentyp3', 'lagerstaettentyp4', 'geologische_provinz', 'bergbauperiode', 'kommentar']
    where_clause, params = build_filter_clause(columns, filter_text, match_mode)
    
    cursor.execute(f"SELECT * FROM revier {where_clause} ORDER BY bergbaurevier", params)
    revier_list = [dict(row) for row in cursor.fetchall()]
    
    conn.close()
    return render_template('revier.html', revier_list=revier_list, filter_text=filter_text, match_mode=match_mode)

@app.route('/api/revier')
def api_revier():
    """API endpoint for mining districts"""
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM revier ORDER BY bergbaurevier")
    revier_list = [dict(row) for row in cursor.fetchall()]
    
    conn.close()
    return jsonify(revier_list)

@app.route('/api/revier/<int:rid>', methods=['GET'])
def api_revier_get(rid):
    """Get a single mining district"""
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM revier WHERE rid = ?", (rid,))
    revier = cursor.fetchone()
    
    conn.close()
    if revier:
        return jsonify(dict(revier))
    return jsonify({'error': 'Not found'}), 404

@app.route('/api/revier', methods=['POST'])
def api_revier_create():
    """Create a new mining district"""
    data = request.json
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute(
        """INSERT INTO revier 
           (bergbaurevier, rohstoffe, lagerstaettentyp1, lagerstaettentyp2, lagerstaettentyp3, lagerstaettentyp4, geologische_provinz, bergbauperiode, kommentar)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (data.get('bergbaurevier'), data.get('rohstoffe'), data.get('lagerstaettentyp1'),
         data.get('lagerstaettentyp2'), data.get('lagerstaettentyp3'), data.get('lagerstaettentyp4'),
         data.get('geologische_provinz'), data.get('bergbauperiode'), data.get('kommentar'))
    )
    conn.commit()
    
    revier_id = cursor.lastrowid
    cursor.execute("SELECT * FROM revier WHERE rid = ?", (revier_id,))
    revier = cursor.fetchone()
    
    conn.close()
    return jsonify(dict(revier)), 201

@app.route('/api/revier/<int:rid>', methods=['PUT'])
def api_revier_update(rid):
    """Update a mining district"""
    data = request.json
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute(
        """UPDATE revier SET bergbaurevier = ?, rohstoffe = ?, lagerstaettentyp1 = ?, 
           lagerstaettentyp2 = ?, lagerstaettentyp3 = ?, lagerstaettentyp4 = ?, 
           geologische_provinz = ?, bergbauperiode = ?, kommentar = ? WHERE rid = ?""",
        (data.get('bergbaurevier'), data.get('rohstoffe'), data.get('lagerstaettentyp1'),
         data.get('lagerstaettentyp2'), data.get('lagerstaettentyp3'), data.get('lagerstaettentyp4'),
         data.get('geologische_provinz'), data.get('bergbauperiode'), data.get('kommentar'), rid)
    )
    conn.commit()
    
    cursor.execute("SELECT * FROM revier WHERE rid = ?", (rid,))
    revier = cursor.fetchone()
    
    conn.close()
    if revier:
        return jsonify(dict(revier))
    return jsonify({'error': 'Not found'}), 404

@app.route('/api/revier/<int:rid>', methods=['DELETE'])
def api_revier_delete(rid):
    """Delete a mining district"""
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute("DELETE FROM revier WHERE rid = ?", (rid,))
    conn.commit()
    
    conn.close()
    return jsonify({'message': 'Deleted'}), 200

# --- Fundstellen ---
@app.route('/fundstellen')
def fundstellen_page():
    """List localities"""
    conn = get_db()
    cursor = conn.cursor()
    
    filter_text = request.args.get('filter', '')
    match_mode = request.args.get('match_mode', 'contains')
    
    columns = ['fsid', 'fundstelle', 'bergbaurevier', 'ortschaft', 'region', 'land', 'geologische_provinz', 'typ', 'kommentar', 'lat', 'lon']
    where_clause, params = build_filter_clause(columns, filter_text, match_mode)
    
    cursor.execute(f"SELECT * FROM fundstellen {where_clause} ORDER BY fundstelle", params)
    fundstellen = [dict(row) for row in cursor.fetchall()]
    
    conn.close()
    return render_template('fundstellen.html', fundstellen=fundstellen, filter_text=filter_text, match_mode=match_mode)

@app.route('/api/fundstellen')
def api_fundstellen():
    """API endpoint for localities"""
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM fundstellen ORDER BY fundstelle")
    fundstellen = [dict(row) for row in cursor.fetchall()]
    
    conn.close()
    return jsonify(fundstellen)

@app.route('/api/fundstellen/<int:fsid>', methods=['GET'])
def api_fundstellen_get(fsid):
    """Get a single locality"""
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM fundstellen WHERE fsid = ?", (fsid,))
    fundstelle = cursor.fetchone()
    
    conn.close()
    if fundstelle:
        return jsonify(dict(fundstelle))
    return jsonify({'error': 'Not found'}), 404

@app.route('/api/fundstellen', methods=['POST'])
def api_fundstellen_create():
    """Create a new locality"""
    data = request.json
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute(
        """INSERT INTO fundstellen 
           (fundstelle, bergbaurevier, ortschaft, region, land, geologische_provinz, typ, kommentar, lat, lon)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (data.get('fundstelle'), data.get('bergbaurevier'), data.get('ortschaft'),
         data.get('region'), data.get('land'), data.get('geologische_provinz'),
         data.get('typ'), data.get('kommentar'), data.get('lat'), data.get('lon'))
    )
    conn.commit()
    
    fundstelle_id = cursor.lastrowid
    cursor.execute("SELECT * FROM fundstellen WHERE fsid = ?", (fundstelle_id,))
    fundstelle = cursor.fetchone()
    
    conn.close()
    return jsonify(dict(fundstelle)), 201

@app.route('/api/fundstellen/<int:fsid>', methods=['PUT'])
def api_fundstellen_update(fsid):
    """Update a locality"""
    data = request.json
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute(
        """UPDATE fundstellen SET fundstelle = ?, bergbaurevier = ?, ortschaft = ?, 
           region = ?, land = ?, geologische_provinz = ?, typ = ?, kommentar = ?, 
           lat = ?, lon = ? WHERE fsid = ?""",
        (data.get('fundstelle'), data.get('bergbaurevier'), data.get('ortschaft'),
         data.get('region'), data.get('land'), data.get('geologische_provinz'),
         data.get('typ'), data.get('kommentar'), data.get('lat'), data.get('lon'), fsid)
    )
    conn.commit()
    
    cursor.execute("SELECT * FROM fundstellen WHERE fsid = ?", (fsid,))
    fundstelle = cursor.fetchone()
    
    conn.close()
    if fundstelle:
        return jsonify(dict(fundstelle))
    return jsonify({'error': 'Not found'}), 404

@app.route('/api/fundstellen/<int:fsid>', methods=['DELETE'])
def api_fundstellen_delete(fsid):
    """Delete a locality"""
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute("DELETE FROM fundstellen WHERE fsid = ?", (fsid,))
    conn.commit()
    
    conn.close()
    return jsonify({'message': 'Deleted'}), 200

# --- Stufen (Specimens) ---
@app.route('/stufen')
def stufen_page():
    """List specimens"""
    conn = get_db()
    cursor = conn.cursor()
    
    filter_text = request.args.get('filter', '')
    match_mode = request.args.get('match_mode', 'contains')
    
    columns = ['snr', 'fundstelle', 'sammlungsstueck', 'art', 'groesse', 'mineral_1', 'mineral_2', 'mineral_3', 'mineral_4', 'gestein', 'beschreibung', 'fundjahr', 'herkunft', 'im_bestand']
    where_clause, params = build_filter_clause(columns, filter_text, match_mode)
    
    cursor.execute(f"SELECT * FROM stufen {where_clause} ORDER BY snr", params)
    stufen = [dict(row) for row in cursor.fetchall()]
    
    # Add formulas to each specimen
    for stufe in stufen:
        formulas = get_formulas_for_stufe(
            stufe.get('mineral_1'),
            stufe.get('mineral_2'),
            stufe.get('mineral_3'),
            stufe.get('mineral_4')
        )
        for key, value in formulas.items():
            if value:
                stufe[key] = value
    
    conn.close()
    return render_template('stufen.html', stufen=stufen, filter_text=filter_text, match_mode=match_mode)

@app.route('/api/stufen')
def api_stufen():
    """API endpoint for specimens"""
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM stufen ORDER BY snr")
    stufen = [dict(row) for row in cursor.fetchall()]
    
    # Add formulas to each specimen
    for stufe in stufen:
        formulas = get_formulas_for_stufe(
            stufe.get('mineral_1'),
            stufe.get('mineral_2'),
            stufe.get('mineral_3'),
            stufe.get('mineral_4')
        )
        for key, value in formulas.items():
            stufe[key] = value
    
    conn.close()
    return jsonify(stufen)

@app.route('/api/stufen/<int:snr>', methods=['GET'])
def api_stufen_get(snr):
    """Get a single specimen"""
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM stufen WHERE snr = ?", (snr,))
    stufe = cursor.fetchone()
    
    if stufe:
        stufe_dict = dict(stufe)
        formulas = get_formulas_for_stufe(
            stufe_dict.get('mineral_1'),
            stufe_dict.get('mineral_2'),
            stufe_dict.get('mineral_3'),
            stufe_dict.get('mineral_4')
        )
        for key, value in formulas.items():
            stufe_dict[key] = value
    
    conn.close()
    if stufe:
        return jsonify(stufe_dict)
    return jsonify({'error': 'Not found'}), 404

@app.route('/api/stufen', methods=['POST'])
def api_stufen_create():
    """Create a new specimen"""
    data = request.json
    
    # Calculate formulas
    formulas = get_formulas_for_stufe(
        data.get('mineral_1'),
        data.get('mineral_2'),
        data.get('mineral_3'),
        data.get('mineral_4')
    )
    
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute(
        """INSERT INTO stufen 
           (fundstelle, sammlungsstueck, art, groesse, mineral_1, mineral_2, mineral_3, mineral_4, 
            gestein, beschreibung, fundjahr, herkunft, im_bestand, 
            mineral_1_formula, mineral_2_formula, mineral_3_formula, mineral_4_formula,
            ex_sammlung, ex_sammlung_nr)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (data.get('fundstelle'), data.get('sammlungsstueck'), data.get('art'),
         data.get('groesse'), data.get('mineral_1'), data.get('mineral_2'),
         data.get('mineral_3'), data.get('mineral_4'), data.get('gestein'),
         data.get('beschreibung'), data.get('fundjahr'), data.get('herkunft'),
         data.get('im_bestand'),
         formulas.get('mineral_1_formula'), formulas.get('mineral_2_formula'),
         formulas.get('mineral_3_formula'), formulas.get('mineral_4_formula'),
         data.get('ex_sammlung'), data.get('ex_sammlung_nr'))
    )
    conn.commit()
    
    stufe_id = cursor.lastrowid
    cursor.execute("SELECT * FROM stufen WHERE snr = ?", (stufe_id,))
    stufe = cursor.fetchone()
    
    conn.close()
    return jsonify(dict(stufe)), 201

@app.route('/api/stufen/<int:snr>', methods=['PUT'])
def api_stufen_update(snr):
    """Update a specimen"""
    data = request.json
    
    # Calculate formulas
    formulas = get_formulas_for_stufe(
        data.get('mineral_1'),
        data.get('mineral_2'),
        data.get('mineral_3'),
        data.get('mineral_4')
    )
    
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute(
        """UPDATE stufen SET fundstelle = ?, sammlungsstueck = ?, art = ?, groesse = ?, 
           mineral_1 = ?, mineral_2 = ?, mineral_3 = ?, mineral_4 = ?, gestein = ?, 
           beschreibung = ?, fundjahr = ?, herkunft = ?, im_bestand = ?, 
           mineral_1_formula = ?, mineral_2_formula = ?, mineral_3_formula = ?, mineral_4_formula = ?,
           ex_sammlung = ?, ex_sammlung_nr = ?
           WHERE snr = ?""",
        (data.get('fundstelle'), data.get('sammlungsstueck'), data.get('art'),
         data.get('groesse'), data.get('mineral_1'), data.get('mineral_2'),
         data.get('mineral_3'), data.get('mineral_4'), data.get('gestein'),
         data.get('beschreibung'), data.get('fundjahr'), data.get('herkunft'),
         data.get('im_bestand'),
         formulas.get('mineral_1_formula'), formulas.get('mineral_2_formula'),
         formulas.get('mineral_3_formula'), formulas.get('mineral_4_formula'),
         data.get('ex_sammlung'), data.get('ex_sammlung_nr'), snr)
    )
    conn.commit()
    
    cursor.execute("SELECT * FROM stufen WHERE snr = ?", (snr,))
    stufe = cursor.fetchone()
    
    conn.close()
    if stufe:
        return jsonify(dict(stufe))
    return jsonify({'error': 'Not found'}), 404

@app.route('/api/stufen/<int:snr>', methods=['DELETE'])
def api_stufen_delete(snr):
    """Delete a specimen"""
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute("DELETE FROM stufen WHERE snr = ?", (snr,))
    conn.commit()
    
    conn.close()
    return jsonify({'message': 'Deleted'}), 200

@app.route('/view_stufen/<int:snr>')
def view_stufen(snr):
    """View a single specimen with details"""
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM stufen WHERE snr = ?", (snr,))
    stufe = cursor.fetchone()
    
    if stufe:
        stufe_dict = dict(stufe)
        formulas = get_formulas_for_stufe(
            stufe_dict.get('mineral_1'),
            stufe_dict.get('mineral_2'),
            stufe_dict.get('mineral_3'),
            stufe_dict.get('mineral_4')
        )
        for key, value in formulas.items():
            stufe_dict[key] = value
        
        # Get related images
        cursor.execute("SELECT * FROM images WHERE snr = ? AND image_type = 'stufen'", (snr,))
        images = [dict(row) for row in cursor.fetchall()]
        
        conn.close()
        return render_template('view_stufen.html', stufe=stufe_dict, images=images)
    
    conn.close()
    return redirect(url_for('stufen_page'))

# --- Bilder (Images) ---
@app.route('/bilder')
def bilder_page():
    """List images"""
    conn = get_db()
    cursor = conn.cursor()
    
    filter_text = request.args.get('filter', '')
    match_mode = request.args.get('match_mode', 'contains')
    
    columns = ['isnr', 'snr', 'sammlungsstueck', 'photo', 'image_type', 'fundstelle_id']
    where_clause, params = build_filter_clause(columns, filter_text, match_mode)
    
    cursor.execute(f"SELECT * FROM images {where_clause} ORDER BY isnr", params)
    images = [dict(row) for row in cursor.fetchall()]
    
    conn.close()
    return render_template('bilder.html', images=images, filter_text=filter_text, match_mode=match_mode)

@app.route('/api/bilder')
def api_bilder():
    """API endpoint for images"""
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM images ORDER BY isnr")
    images = [dict(row) for row in cursor.fetchall()]
    
    conn.close()
    return jsonify(images)

@app.route('/api/bilder', methods=['POST'])
def api_bilder_create():
    """Create a new image record"""
    data = request.json
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute(
        "INSERT INTO images (snr, sammlungsstueck, photo, image_type, fundstelle_id) VALUES (?, ?, ?, ?, ?)",
        (data.get('snr'), data.get('sammlungsstueck'), data.get('photo'),
         data.get('image_type', 'stufen'), data.get('fundstelle_id'))
    )
    conn.commit()
    
    image_id = cursor.lastrowid
    cursor.execute("SELECT * FROM images WHERE isnr = ?", (image_id,))
    image = cursor.fetchone()
    
    conn.close()
    return jsonify(dict(image)), 201

@app.route('/api/bilder/<int:isnr>', methods=['DELETE'])
def api_bilder_delete(isnr):
    """Delete an image"""
    conn = get_db()
    cursor = conn.cursor()
    
    # First get the image to delete the file
    cursor.execute("SELECT * FROM images WHERE isnr = ?", (isnr,))
    image = cursor.fetchone()
    
    if image and image['photo']:
        # Delete the file if it exists
        for folder in ['static/uploads', '01_Bilder']:
            file_path = os.path.join(folder, image['photo'])
            if os.path.exists(file_path):
                os.remove(file_path)
    
    cursor.execute("DELETE FROM images WHERE isnr = ?", (isnr,))
    conn.commit()
    
    conn.close()
    return jsonify({'message': 'Deleted'}), 200

@app.route('/upload_image', methods=['POST'])
def upload_image():
    """Upload an image file"""
    if 'file' not in request.files:
        return jsonify({'error': 'No file part'}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No selected file'}), 400
    
    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        
        # Get parameters
        image_type = request.form.get('image_type', 'stufen')
        snr = request.form.get('snr', None)
        sammlungsstueck = request.form.get('sammlungsstueck', None)
        fundstelle_id = request.form.get('fundstelle_id', None)
        
        # Save file
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        unique_filename = f"{timestamp}_{filename}"
        
        # Save to both uploads folder and 01_Bilder
        for folder in ['static/uploads', '01_Bilder']:
            os.makedirs(folder, exist_ok=True)
            file_path = os.path.join(folder, unique_filename)
            file.save(file_path)
        
        # Save to database
        conn = get_db()
        cursor = conn.cursor()
        
        # Convert snr to int if possible
        snr_int = None
        if snr and snr.isdigit():
            snr_int = int(snr)
        
        # Convert fundstelle_id to int if possible
        fundstelle_id_int = None
        if fundstelle_id and fundstelle_id.isdigit():
            fundstelle_id_int = int(fundstelle_id)
        
        cursor.execute(
            "INSERT INTO images (snr, sammlungsstueck, photo, image_type, fundstelle_id) VALUES (?, ?, ?, ?, ?)",
            (snr_int, sammlungsstueck, unique_filename, image_type, fundstelle_id_int)
        )
        conn.commit()
        
        image_id = cursor.lastrowid
        cursor.execute("SELECT * FROM images WHERE isnr = ?", (image_id,))
        image = cursor.fetchone()
        
        conn.close()
        return jsonify(dict(image)), 201
    
    return jsonify({'error': 'File type not allowed'}), 400

@app.route('/uploads/<filename>')
def uploaded_file(filename):
    """Serve uploaded files"""
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

@app.route('/bilder/<filename>')
def bilder_file(filename):
    """Serve image files from 01_Bilder"""
    return send_from_directory('01_Bilder', filename)

# --- Fundstellen View ---
@app.route('/fundstellen_view/<int:fsid>')
def fundstellen_view(fsid):
    """View a single locality with details"""
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM fundstellen WHERE fsid = ?", (fsid,))
    fundstelle = cursor.fetchone()
    
    if fundstelle:
        fundstelle_dict = dict(fundstelle)
        
        # Get related specimens
        cursor.execute("SELECT * FROM stufen WHERE fundstelle = ?", (fundstelle_dict['fundstelle'],))
        stufen = [dict(row) for row in cursor.fetchall()]
        
        # Get related images
        cursor.execute("SELECT * FROM images WHERE fundstelle_id = ?", (fsid,))
        images = [dict(row) for row in cursor.fetchall()]
        
        conn.close()
        return render_template('fundstellen_view.html', fundstelle=fundstelle_dict, stufen=stufen, images=images)
    
    conn.close()
    return redirect(url_for('fundstellen_page'))

# --- Normalize ---
@app.route('/normalize')
def normalize_page():
    """Page for normalizing/updating data"""
    return render_template('normalize.html')

# --- Export ---
@app.route('/export/csv')
def export_csv():
    """Export all data to CSV files"""
    conn = get_db()
    cursor = conn.cursor()
    
    # Create timestamped folder
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    export_dir = os.path.join(EXPORT_FOLDER, f'export_csv_{timestamp}')
    os.makedirs(export_dir, exist_ok=True)
    
    tables = ['geologischeprovinz', 'revier', 'fundstellen', 'stufen', 'images']
    
    for table in tables:
        cursor.execute(f"SELECT * FROM {table}")
        rows = cursor.fetchall()
        
        if rows:
            # Get column names
            column_names = [description[0] for description in cursor.description]
            
            # Write to CSV
            csv_path = os.path.join(export_dir, f'{table}.csv')
            with open(csv_path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=column_names)
                writer.writeheader()
                for row in rows:
                    writer.writerow(dict(zip(column_names, row)))
    
    conn.close()
    
    # Create a zip file
    zip_filename = f'export_csv_{timestamp}.zip'
    zip_path = os.path.join(EXPORT_FOLDER, zip_filename)
    
    if platform.system() == 'Windows':
        # Use PowerShell on Windows
        subprocess.run(['powershell', 'Compress-Archive', '-Path', f'{export_dir}/*', '-DestinationPath', zip_path], check=True)
    else:
        # Use zip on Unix-like systems
        subprocess.run(['zip', '-r', zip_path, export_dir], check=True)
    
    # Return the zip file for download
    return send_file(zip_path, as_attachment=True, download_name=zip_filename)

@app.route('/export/json')
def export_json():
    """Export all data to JSON files"""
    conn = get_db()
    cursor = conn.cursor()
    
    # Create timestamped folder
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    export_dir = os.path.join(EXPORT_FOLDER, f'export_json_{timestamp}')
    os.makedirs(export_dir, exist_ok=True)
    
    tables = ['geologischeprovinz', 'revier', 'fundstellen', 'stufen', 'images']
    
    for table in tables:
        cursor.execute(f"SELECT * FROM {table}")
        rows = cursor.fetchall()
        
        if rows:
            # Get column names
            column_names = [description[0] for description in cursor.description]
            
            # Convert to list of dicts
            data = [dict(zip(column_names, row)) for row in rows]
            
            # Write to JSON
            json_path = os.path.join(export_dir, f'{table}.json')
            with open(json_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
    
    conn.close()
    
    # Create a zip file
    zip_filename = f'export_json_{timestamp}.zip'
    zip_path = os.path.join(EXPORT_FOLDER, zip_filename)
    
    if platform.system() == 'Windows':
        subprocess.run(['powershell', 'Compress-Archive', '-Path', f'{export_dir}/*', '-DestinationPath', zip_path], check=True)
    else:
        subprocess.run(['zip', '-r', zip_path, export_dir], check=True)
    
    return send_file(zip_path, as_attachment=True, download_name=zip_filename)

@app.route('/export/excel')
def export_excel():
    """Export all data to Excel files"""
    conn = get_db()
    
    # Create timestamped folder
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    export_dir = os.path.join(EXPORT_FOLDER, f'export_excel_{timestamp}')
    os.makedirs(export_dir, exist_ok=True)
    
    tables = ['geologischeprovinz', 'revier', 'fundstellen', 'stufen', 'images']
    
    for table in tables:
        df = pd.read_sql_query(f"SELECT * FROM {table}", conn)
        excel_path = os.path.join(export_dir, f'{table}.xlsx')
        df.to_excel(excel_path, index=False)
    
    conn.close()
    
    # Create a zip file
    zip_filename = f'export_excel_{timestamp}.zip'
    zip_path = os.path.join(EXPORT_FOLDER, zip_filename)
    
    if platform.system() == 'Windows':
        subprocess.run(['powershell', 'Compress-Archive', '-Path', f'{export_dir}/*', '-DestinationPath', zip_path], check=True)
    else:
        subprocess.run(['zip', '-r', zip_path, export_dir], check=True)
    
    return send_file(zip_path, as_attachment=True, download_name=zip_filename)

@app.route('/export/kml')
def export_kml():
    """Export localities to KML format"""
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM fundstellen WHERE lat IS NOT NULL AND lon IS NOT NULL")
    fundstellen = cursor.fetchall()
    
    conn.close()
    
    # Create KML content
    kml_content = '''<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <name>Mineral Collection Localities</name>
    <description>Export of mineral collection localities</description>
'''
    
    for fs in fundstellen:
        fs_dict = dict(zip([d[0] for d in cursor.description], fs))
        kml_content += f'''    <Placemark>
      <name>{fs_dict.get('fundstelle', '')}</name>
      <description>
        <![CDATA[
        <b>Fundstelle:</b> {fs_dict.get('fundstelle', '')}<br/>
        <b>Ort:</b> {fs_dict.get('ortschaft', '')}<br/>
        <b>Region:</b> {fs_dict.get('region', '')}<br/>
        <b>Land:</b> {fs_dict.get('land', '')}<br/>
        <b>Typ:</b> {fs_dict.get('typ', '')}<br/>
        <b>Bergbaurevier:</b> {fs_dict.get('bergbaurevier', '')}
        ]]>
      </description>
      <Point>
        <coordinates>{fs_dict.get('lon', 0)},{fs_dict.get('lat', 0)}</coordinates>
      </Point>
    </Placemark>
'''
    
    kml_content += '''  </Document>
</kml>
'''
    
    # Save to file
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    kml_filename = f'fundstellen_{timestamp}.kml'
    kml_path = os.path.join(EXPORT_FOLDER, kml_filename)
    
    with open(kml_path, 'w', encoding='utf-8') as f:
        f.write(kml_content)
    
    return send_file(kml_path, as_attachment=True, download_name=kml_filename)

@app.route('/export/shp')
def export_shp():
    """Export specimens to Shapefile format"""
    try:
        import shapefile
    except ImportError:
        return jsonify({'error': 'pyshp not installed'}), 500
    
    conn = get_db()
    cursor = conn.cursor()
    
    # Get specimens with location data
    cursor.execute("""
        SELECT s.snr, s.fundstelle, s.mineral_1, s.mineral_2, s.mineral_3, s.mineral_4, 
               s.groesse, s.art, s.fundjahr, f.lat, f.lon
        FROM stufen s
        LEFT JOIN fundstellen f ON s.fundstelle = f.fundstelle
        WHERE f.lat IS NOT NULL AND f.lon IS NOT NULL
    """)
    specimens = cursor.fetchall()
    
    conn.close()
    
    if not specimens:
        return jsonify({'error': 'No specimens with location data'}), 404
    
    # Create Shapefile
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    shp_dir = os.path.join(EXPORT_FOLDER, f'export_shp_{timestamp}')
    os.makedirs(shp_dir, exist_ok=True)
    shp_path = os.path.join(shp_dir, 'stufen')
    
    # Create shapefile writer
    w = shapefile.Writer(shapefile.POINT)
    
    # Add fields
    w.field('snr', 'N')
    w.field('fundstelle', 'C', 100)
    w.field('mineral_1', 'C', 50)
    w.field('mineral_2', 'C', 50)
    w.field('mineral_3', 'C', 50)
    w.field('mineral_4', 'C', 50)
    w.field('groesse', 'C', 50)
    w.field('art', 'C', 50)
    w.field('fundjahr', 'N')
    
    # Add records
    for spec in specimens:
        w.point(spec[10], spec[9])  # lon, lat
        w.record(
            spec[0],  # snr
            spec[1] or '',  # fundstelle
            spec[2] or '',  # mineral_1
            spec[3] or '',  # mineral_2
            spec[4] or '',  # mineral_3
            spec[5] or '',  # mineral_4
            spec[6] or '',  # groesse
            spec[7] or '',  # art
            spec[8] or 0    # fundjahr
        )
    
    # Save shapefile
    w.save(shp_path)
    
    # Create zip file
    zip_filename = f'export_shp_{timestamp}.zip'
    zip_path = os.path.join(EXPORT_FOLDER, zip_filename)
    
    if platform.system() == 'Windows':
        subprocess.run(['powershell', 'Compress-Archive', '-Path', f'{shp_dir}/*', '-DestinationPath', zip_path], check=True)
    else:
        subprocess.run(['zip', '-r', zip_path, shp_dir], check=True)
    
    return send_file(zip_path, as_attachment=True, download_name=zip_filename)

@app.route('/export/pdf')
def export_pdf():
    """Export specimens to PDF format"""
    try:
        from reportlab.lib.pagesizes import letter
        from reportlab.lib import colors
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import inch
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
        from reportlab.lib.enums import TA_CENTER, TA_LEFT
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        import os
    except ImportError:
        return jsonify({'error': 'reportlab not installed'}), 500
    
    # Register Vera font for better Unicode support
    try:
        vera_path = os.path.join(os.path.dirname(__import__('reportlab').__file__), 'fonts', 'Vera.ttf')
        vera_bd_path = os.path.join(os.path.dirname(__import__('reportlab').__file__), 'fonts', 'VeraBd.ttf')
        vera_it_path = os.path.join(os.path.dirname(__import__('reportlab').__file__), 'fonts', 'VeraIt.ttf')
        vera_bi_path = os.path.join(os.path.dirname(__import__('reportlab').__file__), 'fonts', 'VeraBI.ttf')
        
        if os.path.exists(vera_path):
            pdfmetrics.registerFont(TTFont('Vera', vera_path))
            pdfmetrics.registerFont(TTFont('Vera-Bold', vera_bd_path))
            pdfmetrics.registerFont(TTFont('Vera-Italic', vera_it_path))
            pdfmetrics.registerFont(TTFont('Vera-BoldItalic', vera_bi_path))
    except Exception as e:
        print(f"Could not register Vera fonts: {e}")
    
    conn = get_db()
    cursor = conn.cursor()
    
    # Get all specimens
    cursor.execute("SELECT * FROM stufen ORDER BY snr")
    specimens = cursor.fetchall()
    
    # Get all localities
    cursor.execute("SELECT * FROM fundstellen ORDER BY fundstelle")
    fundstellen = cursor.fetchall()
    
    # Get all minerals
    cursor.execute("""
        SELECT mineral_1, COUNT(*) as count 
        FROM stufen 
        WHERE mineral_1 IS NOT NULL AND mineral_1 != ''
        GROUP BY mineral_1 
        ORDER BY count DESC
    """)
    minerals = cursor.fetchall()
    
    conn.close()
    
    # Create PDF
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    pdf_filename = f'export_{timestamp}.pdf'
    pdf_path = os.path.join(EXPORT_FOLDER, pdf_filename)
    
    doc = SimpleDocTemplate(pdf_path, pagesize=letter)
    story = []
    styles = getSampleStyleSheet()
    
    # Title
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=24,
        textColor=colors.HexColor('#2c3e50'),
        spaceAfter=30,
        alignment=TA_CENTER
    )
    story.append(Paragraph("Mineral Collection Catalog", title_style))
    story.append(Spacer(1, 0.2*inch))
    
    # Statistics
    story.append(Paragraph(f"Total Specimens: {len(specimens)}", styles['Normal']))
    story.append(Paragraph(f"Total Localities: {len(fundstellen)}", styles['Normal']))
    story.append(Paragraph(f"Total Mineral Types: {len(minerals)}", styles['Normal']))
    story.append(Spacer(1, 0.3*inch))
    
    # Top minerals
    story.append(Paragraph("Top 10 Minerals:", styles['Heading2']))
    mineral_data = [['Mineral', 'Count']]
    for mineral, count in minerals[:10]:
        mineral_data.append([format_text_for_pdf(mineral[0]), count[1]])
    
    mineral_table = Table(mineral_data, colWidths=[4*inch, 1*inch])
    mineral_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#3498db')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (-1, 0), 'Vera-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 12),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
        ('GRID', (0, 0), (-1, -1), 1, colors.black)
    ]))
    story.append(mineral_table)
    story.append(Spacer(1, 0.3*inch))
    
    # Localities
    story.append(Paragraph("Localities:", styles['Heading2']))
    fundstellen_data = [['ID', 'Fundstelle', 'Ort', 'Region', 'Land']]
    for fs in fundstellen[:20]:  # Limit to first 20
        fs_dict = dict(zip([d[0] for d in cursor.description], fs))
        fundstellen_data.append([
            format_text_for_pdf(fs_dict.get('fsid', '')),
            format_text_for_pdf(fs_dict.get('fundstelle', '')),
            format_text_for_pdf(fs_dict.get('ortschaft', '')),
            format_text_for_pdf(fs_dict.get('region', '')),
            format_text_for_pdf(fs_dict.get('land', ''))
        ])
    
    fundstellen_table = Table(fundstellen_data, colWidths=[0.5*inch, 2*inch, 1.5*inch, 1.5*inch, 1*inch])
    fundstellen_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#3498db')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (-1, 0), 'Vera-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 10),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
        ('GRID', (0, 0), (-1, -1), 1, colors.black)
    ]))
    story.append(fundstellen_table)
    
    doc.build(story)
    
    return send_file(pdf_path, as_attachment=True, download_name=pdf_filename)


@app.route('/export/pdf/stufen')
def export_pdf_stufen():
    """Export stufen (specimens) to PDF format sorted by snr"""
    try:
        from reportlab.lib.pagesizes import letter, A4
        from reportlab.lib import colors
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import inch, mm
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak
        from reportlab.lib.enums import TA_CENTER, TA_LEFT
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        import os
    except ImportError:
        return jsonify({'error': 'reportlab not installed'}), 500
    
    # Register Vera font for better Unicode support
    try:
        reportlab_path = os.path.dirname(__import__('reportlab').__file__)
        vera_path = os.path.join(reportlab_path, 'fonts', 'Vera.ttf')
        vera_bd_path = os.path.join(reportlab_path, 'fonts', 'VeraBd.ttf')
        vera_it_path = os.path.join(reportlab_path, 'fonts', 'VeraIt.ttf')
        vera_bi_path = os.path.join(reportlab_path, 'fonts', 'VeraBI.ttf')
        
        if os.path.exists(vera_path):
            pdfmetrics.registerFont(TTFont('Vera', vera_path))
            pdfmetrics.registerFont(TTFont('Vera-Bold', vera_bd_path))
            pdfmetrics.registerFont(TTFont('Vera-Italic', vera_it_path))
            pdfmetrics.registerFont(TTFont('Vera-BoldItalic', vera_bi_path))
    except Exception as e:
        print(f"Could not register Vera fonts: {e}")
    
    conn = get_db()
    cursor = conn.cursor()
    
    # Get all specimens sorted by snr
    cursor.execute("SELECT * FROM stufen ORDER BY snr")
    specimens = cursor.fetchall()
    
    # Get column names
    column_names = [description[0] for description in cursor.description]
    
    conn.close()
    
    # Create PDF
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    pdf_filename = f'stufen_export_{timestamp}.pdf'
    pdf_path = os.path.join(EXPORT_FOLDER, pdf_filename)
    
    # Use A4 for better international compatibility
    doc = SimpleDocTemplate(pdf_path, pagesize=A4)
    story = []
    styles = getSampleStyleSheet()
    
    # Custom styles
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontName='Vera-Bold',
        fontSize=20,
        textColor=colors.HexColor('#2c3e50'),
        spaceAfter=20,
        alignment=TA_CENTER
    )
    
    heading_style = ParagraphStyle(
        'CustomHeading',
        parent=styles['Heading2'],
        fontName='Vera-Bold',
        fontSize=14,
        textColor=colors.HexColor('#2c3e50'),
        spaceAfter=12,
        spaceBefore=12
    )
    
    normal_style = ParagraphStyle(
        'CustomNormal',
        parent=styles['Normal'],
        fontName='Vera',
        fontSize=10,
        spaceAfter=6
    )
    
    # Title
    story.append(Paragraph("Stufen (Specimens) Catalog", title_style))
    story.append(Paragraph(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", normal_style))
    story.append(Paragraph(f"Total Specimens: {len(specimens)}", normal_style))
    story.append(Spacer(1, 0.3*inch))
    
    # Prepare specimen data for table
    # Select relevant columns to display
    display_columns = ['snr', 'fundstelle', 'sammlungsstueck', 'art', 'groesse', 
                      'mineral_1', 'mineral_2', 'mineral_3', 'mineral_4', 
                      'gestein', 'fundjahr', 'herkunft', 'im_bestand',
                      'ex_sammlung', 'ex_sammlung_nr']
    
    # Get indices of display columns
    col_indices = [column_names.index(col) for col in display_columns if col in column_names]
    
    # Create table headers
    headers = ['ID', 'Locality', 'Collection Piece', 'Type', 'Size', 
               'Mineral 1', 'Mineral 2', 'Mineral 3', 'Mineral 4',
               'Rock Type', 'Year', 'Origin', 'In Collection',
               'Ex-Sammlung', 'Ex-Sammlung Nr']
    
    # Filter headers to match available columns
    available_headers = []
    for i, col in enumerate(display_columns):
        if col in column_names:
            available_headers.append(headers[i])
    
    # Build table data
    table_data = [available_headers]
    for spec in specimens:
        row = []
        for col_idx in col_indices:
            value = spec[col_idx]
            if value is None:
                value = ''
            row.append(format_text_for_pdf(str(value)))
        table_data.append(row)
    
    # Create table with appropriate column widths
    col_widths = [0.5*inch, 1.5*inch, 1.2*inch, 0.8*inch, 0.8*inch,
                  1*inch, 1*inch, 1*inch, 1*inch,
                  1*inch, 0.6*inch, 1*inch, 1*inch,
                  1*inch, 1*inch]
    
    # Filter col_widths to match available columns
    available_col_widths = col_widths[:len(available_headers)]
    
    # Create table
    specimens_table = Table(table_data, colWidths=available_col_widths)
    specimens_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#3498db')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (-1, 0), 'Vera-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
        ('GRID', (0, 0), (-1, -1), 1, colors.black),
        ('WORDWRAP', (0, 0), (-1, -1), True)
    ]))
    
    story.append(specimens_table)
    
    doc.build(story)
    
    return send_file(pdf_path, as_attachment=True, download_name=pdf_filename)

# --- Sidebar ---
@app.route('/sidebar')
def sidebar():
    """Sidebar with navigation"""
    return render_template('sidebar.html')

# ==================== MAIN ====================

if __name__ == '__main__':
    # Initialize database
    init_db()
    
    # Check if database exists and has data
    if not os.path.exists(DB_PATH):
        print("Database created. Please add data through the web interface.")
    else:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM stufen")
        count = cursor.fetchone()[0]
        conn.close()
        if count > 0:
            print(f"Database loaded with {count} specimens.")
        else:
            print("Database exists but is empty.")
    
    print("Starting Mineral Collection Database...")
    print("Access at: http://localhost:5000")
    app.run(debug=True, host='0.0.0.0', port=5000)
