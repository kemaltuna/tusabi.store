from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable, Optional, Sequence


# NOTE: These are regex patterns, not string literals. Keep them unescaped.
_QMARK_RE = re.compile(r"\?")
_INSERT_OR_IGNORE_RE = re.compile(r"\bINSERT\s+OR\s+IGNORE\s+INTO\b", re.IGNORECASE)
_IS_QMARK_RE = re.compile(r"\bIS\s+\?", re.IGNORECASE)


def is_postgres_dsn(dsn: str | None) -> bool:
    if not dsn or not isinstance(dsn, str):
        return False
    dsn = dsn.strip().lower()
    return dsn.startswith("postgres://") or dsn.startswith("postgresql://")


def _translate_sql(sql: str) -> str:
    """
    Translate a small subset of SQLite-flavored SQL to something psycopg can run.

    We intentionally keep this small and explicit:
    - qmark params: ? -> %s
    - null-safe equality in SQLite: `col IS ?` -> `col IS NOT DISTINCT FROM %s`
    - `INSERT OR IGNORE` -> `INSERT ...` (call sites should prefer ON CONFLICT DO NOTHING)
    """
    if not sql:
        return sql

    out = sql

    # SQLite null-safe equality: `x IS ?` is commonly used to match NULL values too.
    # Postgres uses `IS NOT DISTINCT FROM` for the same behavior.
    # We only apply this for qmark placeholders to avoid changing `IS NULL` etc.
    out = _IS_QMARK_RE.sub("IS NOT DISTINCT FROM ?", out)

    # Avoid SQLite-only syntax.
    out = _INSERT_OR_IGNORE_RE.sub("INSERT INTO", out)

    # qmark params -> psycopg params
    out = _QMARK_RE.sub("%s", out)

    return out


class CompatRow(dict):
    """
    Dict-like row that also supports positional indexing (row[0]) similar to sqlite3.Row.

    A lot of the existing codebase mixes `row["col"]` and `row[0]`.
    """

    __slots__ = ("_values",)

    def __init__(self, mapping: dict[str, Any], values: Sequence[Any]):
        super().__init__(mapping)
        self._values = tuple(values)

    def __getitem__(self, key: Any) -> Any:
        if isinstance(key, int):
            return self._values[key]
        return super().__getitem__(key)


def compat_row_factory(cursor: Any):
    """psycopg row_factory that returns CompatRow objects."""
    from psycopg.rows import dict_row

    base_maker = dict_row(cursor)

    def make(values: Sequence[Any]) -> CompatRow:
        return CompatRow(base_maker(values), values)

    return make


@dataclass
class _CompatCursor:
    _cursor: Any

    def execute(self, sql: str, params: Sequence[Any] | None = None) -> Any:
        translated = _translate_sql(sql)
        if params is None:
            return self._cursor.execute(translated)
        return self._cursor.execute(translated, params)

    def executemany(self, sql: str, seq_of_params: Iterable[Sequence[Any]]) -> Any:
        translated = _translate_sql(sql)
        return self._cursor.executemany(translated, seq_of_params)

    def fetchone(self) -> Any:
        return self._cursor.fetchone()

    def fetchall(self) -> Any:
        return self._cursor.fetchall()

    @property
    def rowcount(self) -> int:
        return int(getattr(self._cursor, "rowcount", 0) or 0)

    def close(self) -> None:
        try:
            self._cursor.close()
        except Exception:
            pass


class PostgresCompatConnection:
    """
    Connection wrapper that keeps most of our existing sqlite3-style call sites working:
    - Supports qmark param style (`?`)
    - Returns dict-like rows (via psycopg dict_row)
    - `conn.row_factory = ...` becomes a no-op (some code toggles it)

    Callers should still close() the connection.
    """

    def __init__(self, raw_conn: Any):
        self._conn = raw_conn
        self.row_factory = None  # for sqlite compatibility; ignored

    def cursor(self) -> _CompatCursor:
        return _CompatCursor(self._conn.cursor())

    def execute(self, sql: str, params: Optional[Sequence[Any]] = None) -> Any:
        cur = self.cursor()
        cur.execute(sql, params)
        return cur

    def commit(self) -> None:
        self._conn.commit()

    def rollback(self) -> None:
        self._conn.rollback()

    def close(self) -> None:
        self._conn.close()
