import sqlite3
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Any, List


SCHEMA_SQL_V1 = """
CREATE TABLE IF NOT EXISTS datasets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    dataset_name TEXT,
    dataset_type TEXT,
    theme TEXT,
    tile TEXT,
    version TEXT,
    min_lon REAL,
    max_lon REAL,
    min_lat REAL,
    max_lat REAL,
    resolution TEXT,
    format TEXT,
    source TEXT,
    file_path TEXT,
    original_filename TEXT,
    file_size INTEGER,
    file_hash TEXT,
    status TEXT DEFAULT 'PROCESSING',
    ingested_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    error_reason TEXT
);
"""

SCHEMA_SQL_V2 = """
CREATE TABLE IF NOT EXISTS dataset_files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    dataset_id INTEGER NOT NULL,
    relative_path TEXT NOT NULL,
    file_name TEXT NOT NULL,
    extension TEXT,
    file_role TEXT DEFAULT 'unknown',
    file_size INTEGER,
    file_hash TEXT,
    format TEXT,
    spatial BOOLEAN DEFAULT 0,
    crs TEXT,
    min_lon REAL,
    max_lon REAL,
    min_lat REAL,
    max_lat REAL,
    width INTEGER,
    height INTEGER,
    count INTEGER,
    dtype TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (dataset_id) REFERENCES datasets(id) ON DELETE CASCADE
);
"""

SCHEMA_SQL_V3 = """
CREATE TABLE IF NOT EXISTS metadata_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    dataset_id INTEGER NOT NULL,
    field TEXT NOT NULL,
    old_value TEXT,
    new_value TEXT NOT NULL,
    source TEXT DEFAULT 'manual',
    changed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (dataset_id) REFERENCES datasets(id) ON DELETE CASCADE
);
"""

SCHEMA_SQL_V4 = """
CREATE TABLE IF NOT EXISTS dataset_relationships (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    dataset_id INTEGER NOT NULL,
    related_dataset_id INTEGER NOT NULL,
    relationship_type TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (dataset_id) REFERENCES datasets(id) ON DELETE CASCADE,
    FOREIGN KEY (related_dataset_id) REFERENCES datasets(id) ON DELETE CASCADE
);
"""

SCHEMA_SQL_V5 = """
CREATE TABLE IF NOT EXISTS ingestion_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    dataset_id INTEGER NOT NULL,
    original_filename TEXT,
    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP,
    status TEXT DEFAULT 'running',
    parser_version TEXT,
    result_summary TEXT,
    FOREIGN KEY (dataset_id) REFERENCES datasets(id) ON DELETE CASCADE
);
"""

SCHEMA_SQL_V6 = """
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY,
    applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""

MIGRATIONS = [
    ("ALTER TABLE datasets ADD COLUMN platform TEXT", "add platform column"),
    ("ALTER TABLE datasets ADD COLUMN sensor TEXT", "add sensor column"),
    ("ALTER TABLE datasets ADD COLUMN bits_per_pixel TEXT", "add bits_per_pixel column"),
    ("ALTER TABLE datasets ADD COLUMN updated_at TIMESTAMP", "add updated_at column"),
    ("ALTER TABLE datasets ADD COLUMN deleted_at TIMESTAMP", "add deleted_at column"),
    ("ALTER TABLE datasets ADD COLUMN acquisition_date TIMESTAMP", "add acquisition_date column"),
    ("ALTER TABLE datasets ADD COLUMN start_date TIMESTAMP", "add start_date column"),
    ("ALTER TABLE datasets ADD COLUMN end_date TIMESTAMP", "add end_date column"),
    ("ALTER TABLE datasets ADD COLUMN temporal_resolution TEXT", "add temporal_resolution column"),
]


SCHEMA_SQL = "\n".join([
    SCHEMA_SQL_V1,
    SCHEMA_SQL_V2,
    SCHEMA_SQL_V3,
    SCHEMA_SQL_V4,
    SCHEMA_SQL_V5,
])


def _get_current_version(conn: sqlite3.Connection) -> int:
    try:
        row = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()
        return row[0] or 0
    except sqlite3.OperationalError:
        return 0


def _apply_migrations(conn: sqlite3.Connection, target_version: int) -> None:
    current = _get_current_version(conn)
    migration_index = 0
    for migration_index, (sql, description) in enumerate(MIGRATIONS[current:], start=current):
        try:
            conn.execute(sql)
            conn.execute("INSERT INTO schema_version (version) VALUES (?)", (migration_index + 1,))
            conn.commit()
        except sqlite3.OperationalError:
            pass


def init_db(base_dir: str):
    db_path = Path(base_dir) / "data" / "catalog" / "spatial_catalog.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA_SQL)
    conn.executescript(SCHEMA_SQL_V6)
    conn.commit()
    _apply_migrations(conn, target_version=len(MIGRATIONS))
    conn.close()


def get_conn(base_dir: str):
    db_path = Path(base_dir) / "data" / "catalog" / "spatial_catalog.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def insert_dataset(base_dir: str, record: Dict[str, Any]) -> int:
    init_db(base_dir)
    conn = get_conn(base_dir)
    cursor = conn.execute(
        """
        INSERT INTO datasets (
            dataset_name, dataset_type, theme, tile, version,
            min_lon, max_lon, min_lat, max_lat,
            resolution, format, source, platform, sensor, bits_per_pixel,
            file_path, original_filename, file_size, file_hash,
            status, error_reason
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            record.get("dataset_name"),
            record.get("dataset_type"),
            record.get("theme"),
            record.get("tile"),
            record.get("version"),
            record.get("min_lon"),
            record.get("max_lon"),
            record.get("min_lat"),
            record.get("max_lat"),
            record.get("resolution"),
            record.get("format"),
            record.get("source"),
            record.get("platform"),
            record.get("sensor"),
            record.get("bits_per_pixel"),
            record.get("file_path"),
            record.get("original_filename"),
            record.get("file_size"),
            record.get("file_hash"),
            record.get("status", "PROCESSING"),
            record.get("error_reason"),
        ),
    )
    conn.commit()
    dataset_id = cursor.lastrowid
    conn.close()
    return dataset_id


def update_status(base_dir: str, dataset_id: int, status: str, error_reason: Optional[str] = None, file_path: Optional[str] = None):
    conn = get_conn(base_dir)
    fields = ["status = ?", "updated_at = ?"]
    params: list = [status, datetime.utcnow().isoformat()]
    if error_reason is not None:
        fields.append("error_reason = ?")
        params.append(error_reason)
    if file_path is not None:
        fields.append("file_path = ?")
        params.append(file_path)
    params.append(dataset_id)
    conn.execute(f"UPDATE datasets SET {', '.join(fields)} WHERE id = ?", params)
    conn.commit()
    conn.close()


def update_dataset(base_dir: str, dataset_id: int, record: Dict[str, Any]):
    conn = get_conn(base_dir)
    fields = []
    params: list = []
    allowed = [
        "dataset_name", "dataset_type", "theme", "tile", "version",
        "min_lon", "max_lon", "min_lat", "max_lat",
        "resolution", "format", "source", "platform", "sensor", "bits_per_pixel",
        "file_path", "original_filename", "file_size", "file_hash",
        "status", "error_reason", "deleted_at",
    ]
    for key in allowed:
        if key in record:
            fields.append(f"{key} = ?")
            params.append(record[key])
    if fields:
        fields.append("updated_at = ?")
        params.append(datetime.utcnow().isoformat())
        params.append(dataset_id)
        conn.execute(f"UPDATE datasets SET {', '.join(fields)} WHERE id = ?", params)
        conn.commit()
    conn.close()


def get_dataset(base_dir: str, dataset_id: int) -> Optional[Dict[str, Any]]:
    init_db(base_dir)
    conn = get_conn(base_dir)
    row = conn.execute("SELECT * FROM datasets WHERE id = ? AND deleted_at IS NULL", (dataset_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def list_datasets(base_dir: str, limit: int = 100, offset: int = 0, filters: Dict[str, Any] = None) -> List[Dict[str, Any]]:
    init_db(base_dir)
    conn = get_conn(base_dir)
    query = "SELECT * FROM datasets WHERE deleted_at IS NULL"
    params: list = []
    if filters:
        if filters.get("dataset_type"):
            query += " AND dataset_type = ?"
            params.append(filters["dataset_type"])
        if filters.get("theme"):
            query += " AND theme = ?"
            params.append(filters["theme"])
        if filters.get("tile"):
            query += " AND tile = ?"
            params.append(filters["tile"])
        if filters.get("version"):
            query += " AND version = ?"
            params.append(filters["version"])
        if filters.get("platform"):
            query += " AND platform = ?"
            params.append(filters["platform"])
        if filters.get("sensor"):
            query += " AND sensor = ?"
            params.append(filters["sensor"])
        if filters.get("status"):
            query += " AND status = ?"
            params.append(filters["status"])
        if filters.get("dataset_name"):
            query += " AND dataset_name LIKE ?"
            params.append(f"%{filters['dataset_name']}%")
    query += " ORDER BY ingested_at DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])
    rows = conn.execute(query, params).fetchall()
    conn.close()
    results = []
    for row in rows:
        ds = dict(row)
        file_path = ds.get("file_path")
        if file_path:
            ds_path = Path(base_dir) / file_path
            file_count = 0
            if ds_path.exists() and ds_path.is_dir():
                file_count = len([p for p in ds_path.iterdir() if p.is_file() and p.name != "manifest.json"])
            ds["file_count"] = file_count
        else:
            ds["file_count"] = 0
        results.append(ds)
    return results


def search_datasets(base_dir: str, query_params: Dict[str, Any]) -> List[Dict[str, Any]]:
    limit = int(query_params.get("limit", 100))
    offset = int(query_params.get("offset", 0))
    filters = {k: v for k, v in query_params.items() if k in {
        "dataset_type", "theme", "tile", "version", "platform", "sensor", "status", "dataset_name"
    } and v}
    return list_datasets(base_dir, limit=limit, offset=offset, filters=filters)


def soft_delete_dataset(base_dir: str, dataset_id: int) -> Dict[str, Any]:
    conn = get_conn(base_dir)
    row = conn.execute("SELECT * FROM datasets WHERE id = ?", (dataset_id,)).fetchone()
    conn.close()
    if not row:
        return {"deleted": False, "reason": "not_found"}

    conn = get_conn(base_dir)
    conn.execute(
        "UPDATE datasets SET deleted_at = ?, status = ?, updated_at = ? WHERE id = ?",
        (datetime.utcnow().isoformat(), "DELETED", datetime.utcnow().isoformat(), dataset_id),
    )
    conn.commit()
    conn.close()
    return {"deleted": True, "dataset_id": dataset_id, "mode": "soft"}


def permanent_delete_dataset(base_dir: str, dataset_id: int) -> Dict[str, Any]:
    conn = get_conn(base_dir)
    row = conn.execute("SELECT * FROM datasets WHERE id = ?", (dataset_id,)).fetchone()
    conn.close()
    if not row:
        return {"deleted": False, "reason": "not_found"}

    ds = dict(row)
    file_path = ds.get("file_path")
    deleted_files = []

    if file_path:
        full_path = Path(base_dir) / file_path
        base_data_dir = Path(base_dir) / "data" / "raw"
        try:
            full_path.resolve().relative_to(base_data_dir.resolve())
        except ValueError:
            return {"deleted": False, "reason": "path_escape", "file_path": file_path}

        if full_path.exists() and full_path.is_dir():
            for item in full_path.rglob("*"):
                if item.is_file():
                    deleted_files.append(str(item.relative_to(Path(base_dir))))
                    item.unlink()
            for item in sorted(full_path.rglob("*"), reverse=True):
                if item.is_dir():
                    item.rmdir()
            if full_path.exists():
                full_path.rmdir()

    conn = get_conn(base_dir)
    conn.execute("DELETE FROM dataset_files WHERE dataset_id = ?", (dataset_id,))
    conn.execute("DELETE FROM metadata_history WHERE dataset_id = ?", (dataset_id,))
    conn.execute("DELETE FROM dataset_relationships WHERE dataset_id = ? OR related_dataset_id = ?", (dataset_id, dataset_id))
    conn.execute("DELETE FROM ingestion_runs WHERE dataset_id = ?", (dataset_id,))
    conn.execute("DELETE FROM datasets WHERE id = ?", (dataset_id,))
    conn.commit()
    conn.close()

    return {
        "deleted": True,
        "dataset_id": dataset_id,
        "file_path": file_path,
        "deleted_files": deleted_files,
        "mode": "permanent",
    }


def delete_dataset(base_dir: str, dataset_id: int, permanent: bool = False) -> Dict[str, Any]:
    if permanent:
        return permanent_delete_dataset(base_dir, dataset_id)
    return soft_delete_dataset(base_dir, dataset_id)


def restore_dataset(base_dir: str, dataset_id: int) -> Dict[str, Any]:
    conn = get_conn(base_dir)
    row = conn.execute("SELECT * FROM datasets WHERE id = ? AND deleted_at IS NOT NULL", (dataset_id,)).fetchone()
    conn.close()
    if not row:
        return {"restored": False, "reason": "not_found_or_not_deleted"}

    conn = get_conn(base_dir)
    conn.execute(
        "UPDATE datasets SET deleted_at = NULL, status = ?, updated_at = ? WHERE id = ?",
        ("READY", datetime.utcnow().isoformat(), dataset_id),
    )
    conn.commit()
    conn.close()
    return {"restored": True, "dataset_id": dataset_id}


def insert_dataset_file(base_dir: str, dataset_id: int, file_meta: Dict[str, Any]) -> int:
    conn = get_conn(base_dir)
    cursor = conn.execute(
        """
        INSERT INTO dataset_files (
            dataset_id, relative_path, file_name, extension, file_role,
            file_size, file_hash, format, spatial, crs,
            min_lon, max_lon, min_lat, max_lat, width, height, count, dtype
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            dataset_id,
            file_meta.get("relative_path"),
            file_meta.get("file_name"),
            file_meta.get("extension"),
            file_meta.get("file_role", "unknown"),
            file_meta.get("file_size"),
            file_meta.get("file_hash"),
            file_meta.get("format"),
            1 if file_meta.get("spatial") else 0,
            file_meta.get("crs"),
            file_meta.get("min_lon"),
            file_meta.get("max_lon"),
            file_meta.get("min_lat"),
            file_meta.get("max_lat"),
            file_meta.get("width"),
            file_meta.get("height"),
            file_meta.get("count"),
            file_meta.get("dtype"),
        ),
    )
    conn.commit()
    file_id = cursor.lastrowid
    conn.close()
    return file_id


def get_dataset_files(base_dir: str, dataset_id: int) -> List[Dict[str, Any]]:
    conn = get_conn(base_dir)
    rows = conn.execute("SELECT * FROM dataset_files WHERE dataset_id = ?", (dataset_id,)).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def delete_dataset_file(base_dir: str, dataset_id: int, file_id: int) -> Dict[str, Any]:
    conn = get_conn(base_dir)
    row = conn.execute("SELECT * FROM dataset_files WHERE id = ? AND dataset_id = ?", (file_id, dataset_id)).fetchone()
    conn.close()
    if not row:
        return {"deleted": False, "reason": "file_not_found"}

    conn = get_conn(base_dir)
    conn.execute("DELETE FROM dataset_files WHERE id = ?", (file_id,))
    conn.commit()
    conn.close()
    return {"deleted": True, "file_id": file_id}


def update_dataset_file(base_dir: str, dataset_id: int, file_id: int, updates: Dict[str, Any]) -> Dict[str, Any]:
    conn = get_conn(base_dir)
    row = conn.execute("SELECT * FROM dataset_files WHERE id = ? AND dataset_id = ?", (file_id, dataset_id)).fetchone()
    conn.close()
    if not row:
        return {"updated": False, "reason": "file_not_found"}

    allowed = ["file_role", "format", "spatial"]
    fields = []
    params: list = []
    for key in allowed:
        if key in updates:
            fields.append(f"{key} = ?")
            params.append(updates[key])
    if fields:
        params.extend([file_id])
        conn = get_conn(base_dir)
        conn.execute(f"UPDATE dataset_files SET {', '.join(fields)} WHERE id = ?", params)
        conn.commit()
        conn.close()
    return {"updated": True, "file_id": file_id}


def record_metadata_history(base_dir: str, dataset_id: int, field: str, old_value: str, new_value: str, source: str = "manual"):
    conn = get_conn(base_dir)
    conn.execute(
        "INSERT INTO metadata_history (dataset_id, field, old_value, new_value, source) VALUES (?, ?, ?, ?, ?)",
        (dataset_id, field, old_value, new_value, source),
    )
    conn.commit()
    conn.close()


def get_metadata_history(base_dir: str, dataset_id: int) -> List[Dict[str, Any]]:
    conn = get_conn(base_dir)
    rows = conn.execute("SELECT * FROM metadata_history WHERE dataset_id = ? ORDER BY changed_at DESC", (dataset_id,)).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def insert_dataset_relationship(base_dir: str, dataset_id: int, related_dataset_id: int, relationship_type: str) -> int:
    conn = get_conn(base_dir)
    cursor = conn.execute(
        "INSERT INTO dataset_relationships (dataset_id, related_dataset_id, relationship_type) VALUES (?, ?, ?)",
        (dataset_id, related_dataset_id, relationship_type),
    )
    conn.commit()
    rel_id = cursor.lastrowid
    conn.close()
    return rel_id


def get_dataset_relationships(base_dir: str, dataset_id: int) -> List[Dict[str, Any]]:
    conn = get_conn(base_dir)
    rows = conn.execute(
        """
        SELECT dr.*, d.dataset_name as related_dataset_name
        FROM dataset_relationships dr
        JOIN datasets d ON d.id = dr.related_dataset_id
        WHERE dr.dataset_id = ?
        """,
        (dataset_id,),
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def start_ingestion_run(base_dir: str, dataset_id: int, original_filename: str, parser_version: str = "1.0") -> int:
    conn = get_conn(base_dir)
    cursor = conn.execute(
        "INSERT INTO ingestion_runs (dataset_id, original_filename, parser_version, status) VALUES (?, ?, ?, ?)",
        (dataset_id, original_filename, parser_version, "running"),
    )
    conn.commit()
    run_id = cursor.lastrowid
    conn.close()
    return run_id


def complete_ingestion_run(base_dir: str, run_id: int, status: str, result_summary: str = None):
    conn = get_conn(base_dir)
    conn.execute(
        "UPDATE ingestion_runs SET completed_at = ?, status = ?, result_summary = ? WHERE id = ?",
        (datetime.utcnow().isoformat(), status, result_summary, run_id),
    )
    conn.commit()
    conn.close()


def get_ingestion_runs(base_dir: str, dataset_id: int) -> List[Dict[str, Any]]:
    conn = get_conn(base_dir)
    rows = conn.execute("SELECT * FROM ingestion_runs WHERE dataset_id = ? ORDER BY started_at DESC", (dataset_id,)).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def check_spatial_overlap(base_dir: str, dataset_type: str, bounds: Dict[str, float], exclude_dataset_id: int = None) -> List[Dict[str, Any]]:
    if not bounds or not all(k in bounds for k in ["west", "south", "east", "north"]):
        return []

    west = bounds["west"]
    south = bounds["south"]
    east = bounds["east"]
    north = bounds["north"]

    conn = get_conn(base_dir)
    query = """
        SELECT * FROM datasets
        WHERE dataset_type = ? AND deleted_at IS NULL
        AND min_lon < ? AND max_lon > ? AND min_lat < ? AND max_lat > ?
    """
    params = [dataset_type, east, west, north, south]
    if exclude_dataset_id:
        query += " AND id != ?"
        params.append(exclude_dataset_id)
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def query_one(base_dir: str, dataset_name: str = None, dataset_type: str = None, tile: str = None, version: str = None, file_hash: str = None, original_filename: str = None) -> Optional[Dict[str, Any]]:
    conn = get_conn(base_dir)
    row = None
    if file_hash:
        row = conn.execute(
            "SELECT * FROM datasets WHERE file_hash = ? AND deleted_at IS NULL LIMIT 1",
            (file_hash,),
        ).fetchone()
    elif original_filename:
        row = conn.execute(
            "SELECT * FROM datasets WHERE original_filename = ? AND deleted_at IS NULL LIMIT 1",
            (original_filename,),
        ).fetchone()
    elif all([dataset_name, dataset_type, tile, version]):
        row = conn.execute(
            """
            SELECT * FROM datasets
            WHERE dataset_name = ? AND dataset_type = ? AND tile = ? AND version = ? AND deleted_at IS NULL
            LIMIT 1
            """,
            (dataset_name, dataset_type, tile, version),
        ).fetchone()
    conn.close()
    return dict(row) if row else None
