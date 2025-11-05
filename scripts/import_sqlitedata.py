import os
import json
import sqlite3

DB_PATH = "db.sqlite3"  # change to your filename if needed
OUTPUT_DIR = "exported_tables"

def export_sqlite_to_json(db_path: str, output_dir: str):
    """Export each SQLite table to a separate JSON file."""
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row  # return rows as dict-like objects
    cursor = conn.cursor()

    # get list of tables
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%';")
    tables = [row[0] for row in cursor.fetchall()]

    print(f"Found {len(tables)} tables: {tables}")

    for table in tables:
        print(f"Exporting table: {table}")
        cursor.execute(f"SELECT * FROM {table}")
        rows = cursor.fetchall()

        # convert row objects to dicts
        data = [dict(row) for row in rows]

        # write JSON file
        out_path = os.path.join(output_dir, f"{table}.json")
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)

        print(f"✅ Saved {len(data)} records → {out_path}")

    conn.close()
    print("\n🎉 Export complete!")

if __name__ == "__main__":
    export_sqlite_to_json(DB_PATH, OUTPUT_DIR)
