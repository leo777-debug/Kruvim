"""Export local application rows as bounded SQL batches for the connected Supabase tool."""
import json
import secrets
import sqlite3
import tempfile
from pathlib import Path

from sqlalchemy import JSON, Boolean

from app.core.security import hash_password
from app.models import Base


def export():
    source = sqlite3.connect("data/kruvim.db")
    source.row_factory = sqlite3.Row
    present = {r[0] for r in source.execute("select name from sqlite_master where type='table'")}
    destination = Path(tempfile.mkdtemp(prefix="kruvim-supabase-transfer-"))
    files, counts = [], {}
    def write(table, rows):
        payload = json.dumps(rows, ensure_ascii=False, separators=(",", ":"))
        # A generated delimiter cannot occur inside the serialized rows.
        delimiter = "$import_" + secrets.token_hex(12) + "$"
        sql = (f'INSERT INTO kruvim."{table}" SELECT * FROM json_populate_recordset(NULL::kruvim."{table}", '
               + delimiter + payload + delimiter + ") ON CONFLICT DO NOTHING;")
        path = destination / f"{len(files):04}.json"
        path.write_text(json.dumps({"sql": sql}), encoding="utf-8")
        files.append(str(path))
    for table in Base.metadata.sorted_tables:
        if table.name not in present:
            continue
        data, size, count = [], 0, 0
        for original in source.execute(f'SELECT * FROM "{table.name}"'):
            row = dict(original)
            for column in table.columns:
                if column.name not in row:
                    default = column.default
                    row[column.name] = default.arg(None) if default and default.is_callable else default.arg if default else None
                value = row[column.name]
                if isinstance(column.type, JSON) and isinstance(value, str):
                    row[column.name] = json.loads(value)
                if isinstance(column.type, Boolean) and value is not None:
                    row[column.name] = bool(value)
                if hasattr(row[column.name], "isoformat"):
                    row[column.name] = row[column.name].isoformat()
            if table.name == "users" and row.get("email") == "demo@kruvim.local":
                # Never publish the repository's well-known demo administrator login.
                row["password_hash"], row["is_superuser"] = hash_password(secrets.token_urlsafe(48)), False
            record_size = len(json.dumps(row))
            if data and size + record_size > 180000:
                write(table.name, data)
                data, size = [], 0
            data.append(row)
            size += record_size
            count += 1
        if data:
            write(table.name, data)
        if count:
            counts[table.name] = count
    sequence_sql = []
    for table in Base.metadata.sorted_tables:
        column = table._autoincrement_column
        if column is not None:
            sequence_sql.append(f"SELECT setval(pg_get_serial_sequence('kruvim.{table.name}', '{column.name}'), "
                f'COALESCE(MAX("{column.name}"),1), MAX("{column.name}") IS NOT NULL) FROM kruvim."{table.name}";')
    path = destination / f"{len(files):04}.json"
    path.write_text(json.dumps({"sql": "\n".join(sequence_sql)}), encoding="utf-8")
    files.append(str(path))
    return {"directory": str(destination), "files": files, "counts": counts}


if __name__ == "__main__":
    print(json.dumps(export()))
