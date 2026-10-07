"""Show that Litefuse's traces, spans and scores live in VeloDB.

Connects straight to the VeloDB warehouse over the MySQL protocol (no Litefuse API
involved), lists the Litefuse tables and prints row counts plus the latest traces.

    uv run python -m demo.verify_velodb
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

import pymysql
from rich.console import Console
from rich.table import Table

from demo.config import env

console = Console()


def connect():
    host = urlparse(env("DORIS_FE_HTTP_URL")).hostname
    return pymysql.connect(
        host=host,
        port=int(env("DORIS_FE_QUERY_PORT", "9030")),
        user=env("DORIS_USER", "admin"),
        password=env("DORIS_PASSWORD"),
        database=env("DORIS_DB", "litefuse"),
        connect_timeout=15,
    )


def pick(tables: list[str], base: str, project: str) -> tuple[str | None, bool]:
    """Return (table, is_split). Litefuse may use per-project split tables (base_<pid>)."""
    pid = re.sub(r"[^0-9a-zA-Z_]", "_", project)
    for t in tables:
        if t.startswith(base + "_") and pid in t:
            return t, True
    return (base, False) if base in tables else (None, False)


def main() -> None:
    project = env("LITEFUSE_INIT_PROJECT_ID", "agent_demo")
    with connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT version()")
        console.print(f"Connected to VeloDB [bold]{env('DORIS_FE_HTTP_URL')}[/bold] ({cur.fetchone()[0]})")
        cur.execute("SHOW TABLES")
        tables = sorted(r[0] for r in cur.fetchall())

        counts = Table(title=f"Litefuse tables in `{env('DORIS_DB', 'litefuse')}`")
        counts.add_column("table")
        counts.add_column("rows", justify="right")
        for t in tables:
            try:
                cur.execute(f"SELECT COUNT(*) FROM `{t}`")
                counts.add_row(t, f"{cur.fetchone()[0]:,}")
            except pymysql.MySQLError as exc:
                counts.add_row(t, f"[dim]{exc.args[-1][:40]}[/dim]")
        console.print(counts)

        traces, t_split = pick(tables, "traces_scalar", project)
        spans, s_split = pick(tables, "spans", project)
        if not (traces and spans):
            console.print("[yellow]No trace tables yet - run `make simulate` first.[/yellow]")
            return
        where_t = "" if t_split else "AND t.project_id = %(p)s"
        where_s = "" if s_split else "AND s.project_id = %(p)s"
        cur.execute(
            f"""
            SELECT t.start_time, t.name, t.user_id, t.session_id,
                   COUNT(s.span_id)                       AS observations,
                   SUM(CASE WHEN s.type = 'GENERATION' THEN 1 ELSE 0 END) AS llm_calls,
                   SUM(CASE WHEN s.level = 'ERROR' THEN 1 ELSE 0 END)     AS errors,
                   ROUND(SUM(s.total_cost), 5)             AS cost_usd
            FROM `{traces}` t
            JOIN `{spans}` s ON s.trace_id = t.id {where_s}
            WHERE 1 = 1 {where_t}
            GROUP BY t.id, t.start_time, t.name, t.user_id, t.session_id
            ORDER BY t.start_time DESC
            LIMIT 8
            """,
            {"p": project},
        )
        latest = Table(title="Latest traces (joined from VeloDB)")
        for col in ("start_time", "name", "user", "session", "obs", "llm", "err", "cost $"):
            latest.add_column(col)
        for row in cur.fetchall():
            latest.add_row(*[str(v) if v is not None else "" for v in row])
        console.print(latest)


if __name__ == "__main__":
    main()
