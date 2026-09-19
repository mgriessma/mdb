#!/usr/bin/env python3
"""
One-time script to rename existing Bilder image files into the new scheme and
move them from 01_Bilder/Temporary back into the designated folder, updating
images.photo in the database to the bare new filename.

Rename scheme (matches the /api/bilder/upload endpoint in app.py):
  Stufen:     isnr-snr-fundstelle-mineral_1-gestein.<ext>
  Fundstellen: isnr-fsid-ortschaft-fundstelle.<ext>

Empty components are dropped. Path-unsafe characters are slugified to '_'.
Name collisions get a _N suffix. The script is DRY-RUN by default; pass --apply
to actually move files and update the database.

Usage:
    python rename_images.py                 # dry-run, prints a plan
    python rename_images.py --apply         # move files + update DB
    python rename_images.py --apply --db MG-Sammlung.db --root .

Options:
    --root   Application root dir containing 01_Bilder/ and the DB (default: .)
    --db     SQLite database filename (default: MG-Sammlung.db)
    --apply  Actually perform the rename/move and DB update (default: dry-run)
"""

import argparse
import os
import sqlite3
import sys

SOURCE_FOLDER = "01_Bilder/Temporary"
STUFEN_FOLDER = "01_Bilder/02_Stufen"
FUNDSTELLEN_FOLDER = "01_Bilder/01_Fundstellen"


def slug(value):
    if value is None:
        return ""
    s = str(value).strip()
    for ch in ' /\\:;,*?"<>|()[]{}#&=+!@`\'':
        s = s.replace(ch, '_')
    while '__' in s:
        s = s.replace('__', '_')
    return s.strip('_')


def build_name(parts, ext):
    parts = [p for p in parts if p]
    base = '-'.join(parts) if parts else ""
    return f"{base}.{ext}"


def unique_path(folder, filename):
    candidate = os.path.join(folder, filename)
    if not os.path.exists(candidate):
        return filename
    name, ext = filename.rsplit('.', 1)
    i = 1
    while os.path.exists(os.path.join(folder, f"{name}_{i}.{ext}")):
        i += 1
    return f"{name}_{i}.{ext}"


def main():
    parser = argparse.ArgumentParser(description="Rename existing Bilder images to the new scheme.")
    parser.add_argument('--root', default='.', help='Application root dir (default: .)')
    parser.add_argument('--db', default='MG-Sammlung.db', help='SQLite DB filename (default: MG-Sammlung.db)')
    parser.add_argument('--apply', action='store_true', help='Perform the rename/move + DB update (default: dry-run)')
    args = parser.parse_args()

    root = os.path.abspath(args.root)
    src = os.path.join(root, SOURCE_FOLDER)
    stufen_dest = os.path.join(root, STUFEN_FOLDER)
    fundstellen_dest = os.path.join(root, FUNDSTELLEN_FOLDER)
    db_path = os.path.join(root, args.db)

    if not os.path.isdir(src):
        print(f"ERROR: source folder not found: {src}")
        sys.exit(1)
    if not os.path.isfile(db_path):
        print(f"ERROR: database not found: {db_path}")
        sys.exit(1)

    os.makedirs(stufen_dest, exist_ok=True)
    os.makedirs(fundstellen_dest, exist_ok=True)

    mode = "APPLY" if args.apply else "DRY-RUN (no changes made)"
    print(f"Mode: {mode}")
    print(f"Source: {src}")
    print(f"Stufen dest:     {stufen_dest}")
    print(f"Fundstellen dest: {fundstellen_dest}")
    print(f"DB: {db_path}")
    print()

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # Join images with stufen (for stufen) or fundstellen (for fundstellen) context.
    cur.execute("""
        SELECT i.isnr, i.snr, i.fundstelle_id, i.image_type, i.photo,
               s.fundstelle AS s_fundstelle, s.mineral_1, s.gestein,
               f.fundstelle AS f_fundstelle, f.ortschaft
        FROM images i
        LEFT JOIN stufen s ON i.snr = s.snr AND i.image_type = 'stufen'
        LEFT JOIN fundstellen f ON i.fundstelle_id = f.fsid AND i.image_type = 'fundstellen'
        ORDER BY i.isnr
    """)
    rows = cur.fetchall()

    renamed = 0
    missing = 0
    skipped = 0
    plan = []

    for row in rows:
        isnr = row['isnr']
        image_type = row['image_type'] or 'stufen'
        old_photo = row['photo'] or ''
        if not old_photo:
            skipped += 1
            plan.append((isnr, image_type, '', '(no photo in DB) SKIPPED'))
            continue
        old_filename = os.path.basename(old_photo)
        if '.' not in old_filename:
            skipped += 1
            plan.append((isnr, image_type, old_filename, '(no extension) SKIPPED'))
            continue
        ext = old_filename.rsplit('.', 1)[1].lower()

        if image_type == 'fundstellen':
            parts = [slug(isnr), slug(row['fundstelle_id']), slug(row['ortschaft']), slug(row['f_fundstelle'])]
            dest_folder = fundstellen_dest
        else:
            parts = [slug(isnr), slug(row['snr']), slug(row['s_fundstelle']), slug(row['mineral_1']), slug(row['gestein'])]
            dest_folder = stufen_dest

        new_filename = build_name(parts, ext)
        src_path = os.path.join(src, old_filename)

        if not os.path.exists(src_path):
            missing += 1
            plan.append((isnr, image_type, old_filename, f'(NOT FOUND in source) new={new_filename}'))
            continue

        new_filename = unique_path(dest_folder, new_filename)
        dest_path = os.path.join(dest_folder, new_filename)

        plan.append((isnr, image_type, old_filename, f'-> {new_filename}'))

        if args.apply:
            try:
                if os.path.abspath(src_path) != os.path.abspath(dest_path):
                    os.replace(src_path, dest_path)
                cur.execute("UPDATE images SET photo = ? WHERE isnr = ?", (new_filename, isnr))
                renamed += 1
            except Exception as e:
                print(f"  ERROR isnr={isnr}: {e}")
                missing += 1
        else:
            renamed += 1

    if args.apply:
        conn.commit()
    conn.close()

    print(f"{'isnr':<6} {'type':<11} {'old filename':<55} action")
    print('-' * 110)
    for isnr, itype, old, action in plan:
        print(f"{isnr:<6} {itype:<11} {old:<55} {action}")
    print()
    print(f"Total images: {len(rows)}")
    print(f"{'Would rename' if not args.apply else 'Renamed'}: {renamed}")
    print(f"Source file missing: {missing}")
    print(f"Skipped (no photo/no extension): {skipped}")
    if not args.apply:
        print()
        print("Dry-run only. Re-run with --apply to move files and update the database.")


if __name__ == '__main__':
    main()