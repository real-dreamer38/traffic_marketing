"""
database.py — SQLite CRUD layer for the marketing automation dashboard.

Tables:
  products      — registered products with their platform, keyword, and target ID
  rank_history  — daily rank snapshots per product
  traffic_logs  — external traffic API call records per product
"""

import sqlite3
import logging
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path
from typing import Optional

DB_PATH = Path(__file__).parent / "marketing.db"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Connection helper
# ---------------------------------------------------------------------------

@contextmanager
def get_conn(db_path: Path = DB_PATH):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Schema bootstrap
# ---------------------------------------------------------------------------

DDL_PRODUCTS = """
CREATE TABLE IF NOT EXISTS products (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT    NOT NULL,
    platform    TEXT    NOT NULL CHECK(platform IN ('naver', 'coupang')),
    keyword     TEXT    NOT NULL,
    target_id   TEXT,               -- platform-specific product/vendor item ID
    target_url  TEXT,               -- fallback: direct product URL
    active      INTEGER NOT NULL DEFAULT 1,
    created_at  TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
);
"""

DDL_RANK_HISTORY = """
CREATE TABLE IF NOT EXISTS rank_history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id  INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    rank_date   TEXT    NOT NULL,   -- ISO date: YYYY-MM-DD
    rank        INTEGER NOT NULL,   -- 0 = not found / not exposed
    page        INTEGER,            -- result page where the product was found
    crawled_at  TEXT    NOT NULL DEFAULT (datetime('now', 'localtime')),
    UNIQUE(product_id, rank_date)
);
"""

DDL_TRAFFIC_LOGS = """
CREATE TABLE IF NOT EXISTS traffic_logs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id      INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    requested_at    TEXT    NOT NULL DEFAULT (datetime('now', 'localtime')),
    traffic_qty     INTEGER NOT NULL,
    api_status      TEXT,           -- 'success' | 'error' | 'timeout'
    api_response    TEXT,           -- raw JSON string from the API
    error_message   TEXT
);
"""

# 동일 키워드 검색결과의 1~5위 경쟁사를 일자별로 저장
DDL_COMPETITOR_RANKS = """
CREATE TABLE IF NOT EXISTS competitor_ranks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id  INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    rank_date   TEXT    NOT NULL,
    rank        INTEGER NOT NULL,           -- 1..5
    name        TEXT    NOT NULL,
    target_id   TEXT,
    crawled_at  TEXT    NOT NULL DEFAULT (datetime('now', 'localtime')),
    UNIQUE(product_id, rank_date, rank)
);
"""

DDL_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_rank_history_product_date ON rank_history(product_id, rank_date DESC);",
    "CREATE INDEX IF NOT EXISTS idx_traffic_logs_product      ON traffic_logs(product_id, requested_at DESC);",
    "CREATE INDEX IF NOT EXISTS idx_competitor_product_date   ON competitor_ranks(product_id, rank_date DESC, rank ASC);",
]


def init_db(db_path: Path = DB_PATH) -> None:
    """Create tables and indexes if they do not already exist."""
    with get_conn(db_path) as conn:
        conn.execute(DDL_PRODUCTS)
        conn.execute(DDL_RANK_HISTORY)
        conn.execute(DDL_TRAFFIC_LOGS)
        conn.execute(DDL_COMPETITOR_RANKS)
        for idx_sql in DDL_INDEXES:
            conn.execute(idx_sql)
    log.info("Database initialised at %s", db_path)


# ---------------------------------------------------------------------------
# products CRUD
# ---------------------------------------------------------------------------

def add_product(
    name: str,
    platform: str,
    keyword: str,
    target_id: Optional[str] = None,
    target_url: Optional[str] = None,
    db_path: Path = DB_PATH,
) -> int:
    """Insert a new product and return its new id."""
    platform = platform.lower()
    if platform not in ("naver", "coupang"):
        raise ValueError(f"platform must be 'naver' or 'coupang', got: {platform!r}")
    with get_conn(db_path) as conn:
        cur = conn.execute(
            "INSERT INTO products (name, platform, keyword, target_id, target_url) "
            "VALUES (?, ?, ?, ?, ?)",
            (name, platform, keyword, target_id, target_url),
        )
        new_id = cur.lastrowid
    log.info("Product added: id=%d  name=%r  platform=%s", new_id, name, platform)
    return new_id


def get_product(product_id: int, db_path: Path = DB_PATH) -> Optional[sqlite3.Row]:
    with get_conn(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM products WHERE id = ?", (product_id,)
        ).fetchone()
    return row


def list_products(active_only: bool = True, db_path: Path = DB_PATH) -> list[sqlite3.Row]:
    sql = "SELECT * FROM products"
    if active_only:
        sql += " WHERE active = 1"
    sql += " ORDER BY platform, name"
    with get_conn(db_path) as conn:
        rows = conn.execute(sql).fetchall()
    return rows


def update_product(
    product_id: int,
    *,
    name: Optional[str] = None,
    keyword: Optional[str] = None,
    target_id: Optional[str] = None,
    target_url: Optional[str] = None,
    active: Optional[bool] = None,
    db_path: Path = DB_PATH,
) -> bool:
    """Partial update — only supplied fields are changed."""
    fields: list[tuple[str, object]] = []
    if name is not None:
        fields.append(("name", name))
    if keyword is not None:
        fields.append(("keyword", keyword))
    if target_id is not None:
        fields.append(("target_id", target_id))
    if target_url is not None:
        fields.append(("target_url", target_url))
    if active is not None:
        fields.append(("active", int(active)))

    if not fields:
        return False

    set_clause = ", ".join(f"{col} = ?" for col, _ in fields)
    values = [v for _, v in fields] + [product_id]

    with get_conn(db_path) as conn:
        cur = conn.execute(
            f"UPDATE products SET {set_clause} WHERE id = ?", values
        )
    updated = cur.rowcount > 0
    if updated:
        log.info("Product id=%d updated: %s", product_id, dict(fields))
    return updated


def delete_product(product_id: int, db_path: Path = DB_PATH) -> bool:
    """Hard-delete (cascades to rank_history and traffic_logs)."""
    with get_conn(db_path) as conn:
        cur = conn.execute("DELETE FROM products WHERE id = ?", (product_id,))
    deleted = cur.rowcount > 0
    if deleted:
        log.info("Product id=%d deleted (cascade).", product_id)
    return deleted


# ---------------------------------------------------------------------------
# rank_history CRUD
# ---------------------------------------------------------------------------

def upsert_rank(
    product_id: int,
    rank: int,
    rank_date: Optional[date] = None,
    page: Optional[int] = None,
    db_path: Path = DB_PATH,
) -> None:
    """Insert or replace today's rank for a product (one record per day)."""
    date_str = (rank_date or date.today()).isoformat()
    with get_conn(db_path) as conn:
        conn.execute(
            """
            INSERT INTO rank_history (product_id, rank_date, rank, page)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(product_id, rank_date)
            DO UPDATE SET rank=excluded.rank, page=excluded.page,
                          crawled_at=datetime('now','localtime')
            """,
            (product_id, date_str, rank, page),
        )
    log.info("Rank upserted: product_id=%d  date=%s  rank=%d", product_id, date_str, rank)


def get_rank_history(
    product_id: int,
    days: int = 30,
    db_path: Path = DB_PATH,
) -> list[sqlite3.Row]:
    """Return the last `days` rank records for a product, newest first."""
    with get_conn(db_path) as conn:
        rows = conn.execute(
            """
            SELECT rank_date, rank, page, crawled_at
            FROM   rank_history
            WHERE  product_id = ?
            ORDER  BY rank_date DESC
            LIMIT  ?
            """,
            (product_id, days),
        ).fetchall()
    return rows


def get_latest_rank(product_id: int, db_path: Path = DB_PATH) -> Optional[sqlite3.Row]:
    with get_conn(db_path) as conn:
        row = conn.execute(
            """
            SELECT rank_date, rank, page
            FROM   rank_history
            WHERE  product_id = ?
            ORDER  BY rank_date DESC
            LIMIT  1
            """,
            (product_id,),
        ).fetchone()
    return row


def get_rank_delta(product_id: int, db_path: Path = DB_PATH) -> Optional[int]:
    """
    Return (yesterday_rank - today_rank).
    Positive  → rank improved (moved up).
    Negative  → rank worsened.
    None      → insufficient history.
    """
    with get_conn(db_path) as conn:
        rows = conn.execute(
            """
            SELECT rank FROM rank_history
            WHERE  product_id = ?
            ORDER  BY rank_date DESC
            LIMIT  2
            """,
            (product_id,),
        ).fetchall()
    if len(rows) < 2:
        return None
    today_rank, yesterday_rank = rows[0]["rank"], rows[1]["rank"]
    if today_rank == 0 or yesterday_rank == 0:
        return None
    return yesterday_rank - today_rank


# ---------------------------------------------------------------------------
# traffic_logs CRUD
# ---------------------------------------------------------------------------

def log_traffic(
    product_id: int,
    traffic_qty: int,
    api_status: str,
    api_response: Optional[str] = None,
    error_message: Optional[str] = None,
    db_path: Path = DB_PATH,
) -> int:
    """Record one traffic API call; returns new log id."""
    with get_conn(db_path) as conn:
        cur = conn.execute(
            """
            INSERT INTO traffic_logs
                (product_id, traffic_qty, api_status, api_response, error_message)
            VALUES (?, ?, ?, ?, ?)
            """,
            (product_id, traffic_qty, api_status, api_response, error_message),
        )
        new_id = cur.lastrowid
    log.info(
        "Traffic log id=%d: product_id=%d  qty=%d  status=%s",
        new_id, product_id, traffic_qty, api_status,
    )
    return new_id


def get_traffic_logs(
    product_id: int,
    limit: int = 50,
    db_path: Path = DB_PATH,
) -> list[sqlite3.Row]:
    with get_conn(db_path) as conn:
        rows = conn.execute(
            """
            SELECT id, requested_at, traffic_qty, api_status, api_response, error_message
            FROM   traffic_logs
            WHERE  product_id = ?
            ORDER  BY requested_at DESC
            LIMIT  ?
            """,
            (product_id, limit),
        ).fetchall()
    return rows


def get_total_traffic_qty(product_id: int, db_path: Path = DB_PATH) -> int:
    """성공한 트래픽 호출의 누적 수량 합계를 반환."""
    with get_conn(db_path) as conn:
        row = conn.execute(
            """
            SELECT COALESCE(SUM(traffic_qty), 0) AS total
            FROM   traffic_logs
            WHERE  product_id = ? AND api_status = 'success'
            """,
            (product_id,),
        ).fetchone()
    return int(row["total"]) if row else 0


# ---------------------------------------------------------------------------
# competitor_ranks CRUD
# ---------------------------------------------------------------------------

def upsert_competitor_ranks(
    product_id: int,
    entries: list[dict],
    rank_date: Optional[date] = None,
    db_path: Path = DB_PATH,
) -> None:
    """
    하루치 Top-N 경쟁사 스냅샷을 저장한다.

    entries: [{"rank": int, "name": str, "target_id": Optional[str]}, ...]
    같은 (product_id, rank_date) 의 기존 레코드는 모두 삭제 후 새로 삽입한다.
    """
    date_str = (rank_date or date.today()).isoformat()
    rows = [
        (product_id, date_str, int(e["rank"]), str(e.get("name") or "(이름없음)"),
         e.get("target_id"))
        for e in entries
        if e.get("rank") is not None
    ]
    with get_conn(db_path) as conn:
        conn.execute(
            "DELETE FROM competitor_ranks WHERE product_id = ? AND rank_date = ?",
            (product_id, date_str),
        )
        if rows:
            conn.executemany(
                "INSERT INTO competitor_ranks (product_id, rank_date, rank, name, target_id) "
                "VALUES (?, ?, ?, ?, ?)",
                rows,
            )
    log.info("Competitor ranks upserted: product_id=%d  date=%s  count=%d",
             product_id, date_str, len(rows))


def get_competitor_history(
    product_id: int,
    days: int = 30,
    db_path: Path = DB_PATH,
) -> list[sqlite3.Row]:
    """
    최근 `days` 일치 경쟁사 순위 이력. 날짜 오름차순으로 반환.
    """
    with get_conn(db_path) as conn:
        rows = conn.execute(
            """
            SELECT rank_date, rank, name, target_id
            FROM   competitor_ranks
            WHERE  product_id = ?
              AND  rank_date >= date('now', ?)
            ORDER  BY rank_date ASC, rank ASC
            """,
            (product_id, f"-{int(days)} days"),
        ).fetchall()
    return rows


# ---------------------------------------------------------------------------
# Seed data helper
# ---------------------------------------------------------------------------

SAMPLE_PRODUCTS = [
    {
        "name": "친환경 에어캡",
        "platform": "naver",
        "keyword": "친환경 에어캡",
        "target_id": "N_AIRCAP_001",
        "target_url": None,
    },
    {
        "name": "고체 치약",
        "platform": "coupang",
        "keyword": "고체 치약",
        "target_id": "C_TOOTHPASTE_001",
        "target_url": None,
    },
    {
        "name": "천연 비누",
        "platform": "naver",
        "keyword": "천연 비누",
        "target_id": "N_SOAP_001",
        "target_url": None,
    },
    {
        "name": "대나무 칫솔",
        "platform": "coupang",
        "keyword": "대나무 칫솔",
        "target_id": "C_BAMBOOBRUSH_001",
        "target_url": None,
    },
]


def seed_sample_data(db_path: Path = DB_PATH) -> None:
    """Insert sample products + dummy rank/traffic data for local testing."""
    existing = {row["name"] for row in list_products(active_only=False, db_path=db_path)}

    inserted_ids: list[int] = []
    for p in SAMPLE_PRODUCTS:
        if p["name"] in existing:
            log.info("Sample product %r already exists, skipping.", p["name"])
            continue
        pid = add_product(
            name=p["name"],
            platform=p["platform"],
            keyword=p["keyword"],
            target_id=p["target_id"],
            target_url=p["target_url"],
            db_path=db_path,
        )
        inserted_ids.append(pid)

    # Seed two days of rank history for newly inserted products
    from datetime import timedelta
    today = date.today()
    yesterday = today - timedelta(days=1)

    sample_ranks = [8, 5, 34, 12]   # today
    sample_ranks_yday = [10, 5, 29, 15]  # yesterday

    for i, pid in enumerate(inserted_ids):
        upsert_rank(pid, sample_ranks_yday[i], rank_date=yesterday, db_path=db_path)
        upsert_rank(pid, sample_ranks[i], rank_date=today, db_path=db_path)
        log_traffic(
            product_id=pid,
            traffic_qty=200,
            api_status="success",
            api_response='{"message": "ok", "queued": 200}',
            db_path=db_path,
        )

    log.info("Seed complete. %d new products inserted.", len(inserted_ids))


# ---------------------------------------------------------------------------
# CLI convenience entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    cmd = sys.argv[1] if len(sys.argv) > 1 else "init"

    if cmd == "init":
        init_db()
        print("DB initialised.")

    elif cmd == "seed":
        init_db()
        seed_sample_data()
        print("Sample data seeded.")

    elif cmd == "list":
        init_db()
        products = list_products(active_only=False)
        print(f"{'ID':<4} {'Platform':<10} {'Name':<20} {'Keyword':<20} {'TargetID'}")
        print("-" * 75)
        for p in products:
            print(
                f"{p['id']:<4} {p['platform']:<10} {p['name']:<20} "
                f"{p['keyword']:<20} {p['target_id']}"
            )

    elif cmd == "history":
        product_id = int(sys.argv[2])
        rows = get_rank_history(product_id)
        print(f"Rank history for product_id={product_id}:")
        for r in rows:
            print(f"  {r['rank_date']}  rank={r['rank']}  page={r['page']}")

    else:
        print(f"Unknown command: {cmd}")
        print("Usage: python database.py [init|seed|list|history <id>]")
