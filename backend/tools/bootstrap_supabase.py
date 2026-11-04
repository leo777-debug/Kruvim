"""Render a fresh, isolated Supabase schema without reading application secrets."""
import json

from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex, CreateTable

from app.models import Base


def schema_sql():
    dialect = postgresql.dialect()
    mapping = {None: "kruvim"}
    sql = ["CREATE SCHEMA IF NOT EXISTS kruvim;", "SET LOCAL search_path = kruvim, public, extensions;"]
    for table in Base.metadata.sorted_tables:
        sql.append(str(CreateTable(table).compile(dialect=dialect, schema_translate_map=mapping, render_schema_translate=True)) + ";")
        for index in table.indexes:
            sql.append(str(CreateIndex(index).compile(dialect=dialect, schema_translate_map=mapping, render_schema_translate=True)) + ";")
        sql.append(f'ALTER TABLE kruvim."{table.name}" ENABLE ROW LEVEL SECURITY;')
        sql.append(f'REVOKE ALL ON kruvim."{table.name}" FROM anon, authenticated, PUBLIC;')
    sql += ["CREATE TABLE kruvim.alembic_version (version_num varchar(32) PRIMARY KEY);",
            "INSERT INTO kruvim.alembic_version VALUES ('0017');"]
    for table in ("library_folders", "library_entries"):
        sql += [f"ALTER TABLE kruvim.{table} ALTER COLUMN id SET DEFAULT replace(gen_random_uuid()::text, '-', '');",
                f"ALTER TABLE kruvim.{table} ALTER COLUMN created_at SET DEFAULT now();"]
    for table, values in {"library_folders": {"enabled": "true", "watch_enabled": "true", "sync_status": "'{}'::json"},
        "library_entries": {"source_key": "'manual:' || gen_random_uuid()::text", "region": "'*'", "language": "''",
                            "tags": "''", "filename": "''", "revision": "1"}}.items():
        for column, value in values.items():
            sql.append(f"ALTER TABLE kruvim.{table} ALTER COLUMN {column} SET DEFAULT {value};")
    sql += ["REVOKE ALL ON SCHEMA kruvim FROM PUBLIC, anon, authenticated;",
        "INSERT INTO storage.buckets (id, name, public, file_size_limit) VALUES ('kruvim-data','kruvim-data',false,52428800) ON CONFLICT (id) DO NOTHING;"]
    return "\n".join(sql)


if __name__ == "__main__":
    print(json.dumps({"sql": schema_sql(), "tables": len(Base.metadata.tables)}))
