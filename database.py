"""
database.py — SQLite CRUD layer for the marketing automation dashboard.

Tables
------
  product_groups  — '품목'(상위 개념). 하위 상품 여러 개를 묶는 그룹.
                    예) 품목 '에코앤팩 친환경 에어캡' → 하위 '에어캡 10mm', '에어캡 20mm'
  products        — 등록 상품. 선택적으로 product_groups 에 소속(group_id).
  rank_history    — 일자별 순위 스냅샷 + 스크래핑 상태(status)
  competitor_ranks— 일자별 Top-N 경쟁사 스냅샷
  traffic_logs    — 외부 트래픽 API 호출 기록

스크래핑 상태(status)
---------------------
  ok        — 정상 추출 (rank > 0 또는 검색 후 미발견 0)
  not_found — 검색은 됐으나 N페이지 내 미노출
  blocked   — 차단/캡차 페이지 수신 (Access Denied 등) — 순위 신뢰 불가
  error     — 스크래퍼 예외 — 순위 측정 자체 실패
HTML 소스나 코드 블롭은 절대 DB 에 저장하지 않는다. 추출 실패는 status 로만 표현.
"""

import re
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
# Rank scrape status constants — scraper / scheduler / dashboard 공통 규약
# ---------------------------------------------------------------------------

RANK_STATUS_OK        = "ok"
RANK_STATUS_NOT_FOUND = "not_found"
RANK_STATUS_BLOCKED   = "blocked"
RANK_STATUS_ERROR     = "error"
VALID_RANK_STATUSES   = {
    RANK_STATUS_OK, RANK_STATUS_NOT_FOUND, RANK_STATUS_BLOCKED, RANK_STATUS_ERROR,
}


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

# '품목' — 하위 상품들을 묶는 상위 개념. 플랫폼 단위로 관리한다(상품 관리 UI 가
# 네이버/쿠팡 섹션을 분리하므로 그룹도 플랫폼에 귀속시킨다).
DDL_PRODUCT_GROUPS = """
CREATE TABLE IF NOT EXISTS product_groups (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT    NOT NULL,
    platform    TEXT    NOT NULL CHECK(platform IN ('naver', 'coupang')),
    created_at  TEXT    NOT NULL DEFAULT (datetime('now', 'localtime')),
    UNIQUE(platform, name)
);
"""

DDL_PRODUCTS = """
CREATE TABLE IF NOT EXISTS products (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT    NOT NULL,
    platform    TEXT    NOT NULL CHECK(platform IN ('naver', 'coupang')),
    keyword     TEXT    NOT NULL,
    target_id   TEXT,               -- platform-specific product/vendor item ID
    target_url  TEXT,               -- fallback: direct product URL
    group_id    INTEGER REFERENCES product_groups(id) ON DELETE SET NULL,
    active      INTEGER NOT NULL DEFAULT 1,
    created_at  TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
);
"""

DDL_RANK_HISTORY = """
CREATE TABLE IF NOT EXISTS rank_history (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id    INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    rank_date     TEXT    NOT NULL,   -- ISO date: YYYY-MM-DD
    rank          INTEGER NOT NULL,   -- 0 = not found / not exposed
    page          INTEGER,            -- result page where the product was found
    status        TEXT    NOT NULL DEFAULT 'ok',  -- ok | not_found | blocked | error
    price         INTEGER,            -- 내 상품 노출가 (원) — 경쟁 분석용
    review_count  INTEGER,            -- 내 상품 리뷰 수 — 경쟁 분석용
    crawled_at    TEXT    NOT NULL DEFAULT (datetime('now', 'localtime')),
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

# 동일 키워드 검색결과의 1~5위 경쟁사를 일자별로 저장.
# AI 경쟁 분석을 위해 가격·리뷰수·평점·썸네일 보유 여부까지 함께 수집한다.
DDL_COMPETITOR_RANKS = """
CREATE TABLE IF NOT EXISTS competitor_ranks (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id    INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    rank_date     TEXT    NOT NULL,
    rank          INTEGER NOT NULL,         -- 1..5
    name          TEXT    NOT NULL,
    target_id     TEXT,
    price         INTEGER,                  -- 경쟁사 노출가 (원)
    review_count  INTEGER,                  -- 경쟁사 리뷰 수
    rating        REAL,                     -- 경쟁사 평점 (0~5)
    has_thumbnail INTEGER,                  -- 1 = 썸네일 이미지 보유
    crawled_at    TEXT    NOT NULL DEFAULT (datetime('now', 'localtime')),
    UNIQUE(product_id, rank_date, rank)
);
"""

DDL_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_rank_history_product_date ON rank_history(product_id, rank_date DESC);",
    "CREATE INDEX IF NOT EXISTS idx_traffic_logs_product      ON traffic_logs(product_id, requested_at DESC);",
    "CREATE INDEX IF NOT EXISTS idx_competitor_product_date   ON competitor_ranks(product_id, rank_date DESC, rank ASC);",
    "CREATE INDEX IF NOT EXISTS idx_products_group            ON products(group_id);",
]


def _migrate(conn: sqlite3.Connection) -> None:
    """기존 DB 에 새 컬럼을 점진적으로 추가한다 (idempotent).

    오래된 marketing.db 에는 products.group_id / rank_history.status 컬럼이
    없으므로 PRAGMA table_info 로 확인 후 ALTER TABLE 로 추가한다.
    """
    pcols = {r["name"] for r in conn.execute("PRAGMA table_info(products)").fetchall()}
    if "group_id" not in pcols:
        conn.execute(
            "ALTER TABLE products ADD COLUMN group_id INTEGER "
            "REFERENCES product_groups(id) ON DELETE SET NULL"
        )
        log.info("Migration: products.group_id 컬럼 추가")

    rcols = {r["name"] for r in conn.execute("PRAGMA table_info(rank_history)").fetchall()}
    if "status" not in rcols:
        conn.execute(
            "ALTER TABLE rank_history ADD COLUMN status TEXT NOT NULL DEFAULT 'ok'"
        )
        log.info("Migration: rank_history.status 컬럼 추가")
    if "price" not in rcols:
        conn.execute("ALTER TABLE rank_history ADD COLUMN price INTEGER")
        log.info("Migration: rank_history.price 컬럼 추가")
    if "review_count" not in rcols:
        conn.execute("ALTER TABLE rank_history ADD COLUMN review_count INTEGER")
        log.info("Migration: rank_history.review_count 컬럼 추가")

    # competitor_ranks — 경쟁사 가격/리뷰/평점/썸네일 지표 컬럼
    ccols = {r["name"] for r in conn.execute("PRAGMA table_info(competitor_ranks)").fetchall()}
    for col, decl in (("price", "INTEGER"), ("review_count", "INTEGER"),
                      ("rating", "REAL"), ("has_thumbnail", "INTEGER")):
        if col not in ccols:
            conn.execute(f"ALTER TABLE competitor_ranks ADD COLUMN {col} {decl}")
            log.info("Migration: competitor_ranks.%s 컬럼 추가", col)


def init_db(db_path: Path = DB_PATH) -> None:
    """Create tables and indexes if they do not already exist (+ run migrations)."""
    with get_conn(db_path) as conn:
        # product_groups 를 먼저 만들어야 products 의 FK 가 유효하다.
        conn.execute(DDL_PRODUCT_GROUPS)
        conn.execute(DDL_PRODUCTS)
        conn.execute(DDL_RANK_HISTORY)
        conn.execute(DDL_TRAFFIC_LOGS)
        conn.execute(DDL_COMPETITOR_RANKS)
        _migrate(conn)
        for idx_sql in DDL_INDEXES:
            conn.execute(idx_sql)
    log.info("Database initialised at %s", db_path)


# ---------------------------------------------------------------------------
# 텍스트 정제 헬퍼 — 스크래핑 garbage(HTML 태그·코드 블롭)가 DB 에 들어가는 것을 방지
# ---------------------------------------------------------------------------

_TAG_RE   = re.compile(r"<[^>]*>")
_WS_RE    = re.compile(r"\s+")
_CODE_HINTS = ("function(", "function ", "var ", "{", "}", "</", "/>",
               "window.", "document.", "=>", "();", "[]", "addeventlistener")


def clean_text(raw: Optional[str], *, max_len: int = 120, fallback: str = "(이름미상)") -> str:
    """스크래핑 텍스트를 안전한 한 줄 문자열로 정제한다.

    - HTML 태그 제거, 공백 정규화
    - 코드/스크립트 블롭으로 의심되면(중괄호·function 등 다수 포함) fallback 반환
    - max_len 초과 시 잘라낸다
    이렇게 해서 차단 페이지의 인라인 스크립트 텍스트가 상품명으로 저장되는
    'HTML/코드 노출' 버그를 원천 차단한다.
    """
    if not raw:
        return fallback
    txt = _TAG_RE.sub(" ", str(raw))
    txt = _WS_RE.sub(" ", txt).strip()
    if not txt:
        return fallback
    low = txt.lower()
    code_score = sum(low.count(h) for h in _CODE_HINTS)
    if code_score >= 2:
        return fallback
    if len(txt) > max_len:
        txt = txt[:max_len].rstrip() + "…"
    return txt


# ---------------------------------------------------------------------------
# URL → product ID 추출 헬퍼
# ---------------------------------------------------------------------------
# 대시보드 등록 폼에서 사용자가 상품 URL 만 붙여 넣어도 target_id 가 자동
# 채워지도록 도와준다. 스크래퍼의 매칭 로직(_NAVER_ID_PATTERNS / _COUPANG_ID_PATTERNS)
# 과 동일한 규약을 그대로 따른다.

_NAVER_URL_PATTERNS = [
    re.compile(r"/catalog/(\d{8,})"),
    re.compile(r"[?&]nvMid=(\d+)"),
    re.compile(r"[?&]productId=(\d+)"),
    re.compile(r"/products/(\d{6,})"),     # smartstore /products/12345
    re.compile(r"itemId=(\d+)"),
]

_COUPANG_URL_PATTERNS = [
    re.compile(r"/vp/products/(\d+)"),
    re.compile(r"[?&]vendorItemId=(\d+)"),
    re.compile(r"[?&]itemId=(\d+)"),
    re.compile(r"[?&]productId=(\d+)"),
]


def extract_product_id(platform: str, url: str) -> Optional[str]:
    """
    URL 에서 플랫폼별 상품 ID(MID / vendorItemId / productId 등)를 추출한다.
    매칭 실패 시 None.
    """
    if not url:
        return None
    platform = (platform or "").lower()
    patterns = _NAVER_URL_PATTERNS if platform == "naver" else _COUPANG_URL_PATTERNS
    for pat in patterns:
        m = pat.search(url)
        if m:
            return m.group(1)
    return None


def _validate_platform(platform: str) -> str:
    platform = (platform or "").lower()
    if platform not in ("naver", "coupang"):
        raise ValueError(f"platform must be 'naver' or 'coupang', got: {platform!r}")
    return platform


# ---------------------------------------------------------------------------
# product_groups CRUD — '품목'(상위 개념)
# ---------------------------------------------------------------------------

def add_group(name: str, platform: str, db_path: Path = DB_PATH) -> int:
    """새 품목을 생성하고 id 를 반환한다. 동일 (platform, name) 이 있으면 그 id 반환."""
    platform = _validate_platform(platform)
    name = (name or "").strip()
    if not name:
        raise ValueError("group name must not be empty")
    with get_conn(db_path) as conn:
        existing = conn.execute(
            "SELECT id FROM product_groups WHERE platform = ? AND name = ?",
            (platform, name),
        ).fetchone()
        if existing:
            return int(existing["id"])
        cur = conn.execute(
            "INSERT INTO product_groups (name, platform) VALUES (?, ?)",
            (name, platform),
        )
        new_id = cur.lastrowid
    log.info("Product group added: id=%d  name=%r  platform=%s", new_id, name, platform)
    return new_id


# 등록 폼에서 '새 품목 추가' 시 동일 이름 그룹이 이미 있으면 재사용하도록 alias 제공
get_or_create_group = add_group


def get_group(group_id: int, db_path: Path = DB_PATH) -> Optional[sqlite3.Row]:
    with get_conn(db_path) as conn:
        return conn.execute(
            "SELECT * FROM product_groups WHERE id = ?", (group_id,)
        ).fetchone()


def list_groups(
    platform: Optional[str] = None,
    db_path: Path = DB_PATH,
) -> list[sqlite3.Row]:
    """등록된 품목 목록 — 각 행에 product_count(소속 상품 수)를 포함한다."""
    sql = """
        SELECT g.*,
               (SELECT COUNT(*) FROM products p WHERE p.group_id = g.id) AS product_count
        FROM   product_groups g
    """
    params: list[object] = []
    if platform is not None:
        sql += " WHERE g.platform = ?"
        params.append(_validate_platform(platform))
    sql += " ORDER BY g.name"
    with get_conn(db_path) as conn:
        return conn.execute(sql, params).fetchall()


def rename_group(group_id: int, new_name: str, db_path: Path = DB_PATH) -> bool:
    new_name = (new_name or "").strip()
    if not new_name:
        return False
    with get_conn(db_path) as conn:
        cur = conn.execute(
            "UPDATE product_groups SET name = ? WHERE id = ?", (new_name, group_id)
        )
    return cur.rowcount > 0


def delete_group(group_id: int, db_path: Path = DB_PATH) -> bool:
    """품목을 삭제한다. 소속 상품의 group_id 는 NULL 로 풀린다(ON DELETE SET NULL)."""
    with get_conn(db_path) as conn:
        cur = conn.execute("DELETE FROM product_groups WHERE id = ?", (group_id,))
    deleted = cur.rowcount > 0
    if deleted:
        log.info("Product group id=%d deleted.", group_id)
    return deleted


def prune_empty_groups(db_path: Path = DB_PATH) -> int:
    """소속 상품이 0개인 품목을 정리한다 — 마지막 상품 삭제 후 호출하면 깔끔."""
    with get_conn(db_path) as conn:
        cur = conn.execute(
            "DELETE FROM product_groups "
            "WHERE id NOT IN (SELECT DISTINCT group_id FROM products WHERE group_id IS NOT NULL)"
        )
    if cur.rowcount:
        log.info("Pruned %d empty product group(s).", cur.rowcount)
    return cur.rowcount


# ---------------------------------------------------------------------------
# products CRUD
# ---------------------------------------------------------------------------

def add_product(
    name: str,
    platform: str,
    keyword: str,
    target_id: Optional[str] = None,
    target_url: Optional[str] = None,
    group_id: Optional[int] = None,
    db_path: Path = DB_PATH,
) -> int:
    """Insert a new product and return its new id."""
    platform = _validate_platform(platform)
    with get_conn(db_path) as conn:
        cur = conn.execute(
            "INSERT INTO products (name, platform, keyword, target_id, target_url, group_id) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (name, platform, keyword, target_id, target_url, group_id),
        )
        new_id = cur.lastrowid
    log.info("Product added: id=%d  name=%r  platform=%s  group_id=%s",
             new_id, name, platform, group_id)
    return new_id


def get_product(product_id: int, db_path: Path = DB_PATH) -> Optional[sqlite3.Row]:
    with get_conn(db_path) as conn:
        row = conn.execute(
            """
            SELECT p.*, g.name AS group_name
            FROM   products p
            LEFT   JOIN product_groups g ON p.group_id = g.id
            WHERE  p.id = ?
            """,
            (product_id,),
        ).fetchone()
    return row


def list_products(
    active_only: bool = True,
    platform: Optional[str] = None,
    group_id: Optional[int] = None,
    db_path: Path = DB_PATH,
) -> list[sqlite3.Row]:
    """
    Return registered products. 각 행에 group_name(품목명, 미분류면 NULL)을 포함한다.

    Parameters
    ----------
    active_only : bool       True 면 active=1 인 행만 반환.
    platform    : str|None   'naver'/'coupang' 지정 시 해당 플랫폼만.
    group_id    : int|None   지정 시 해당 품목 소속 상품만.
    """
    sql = """
        SELECT p.*, g.name AS group_name
        FROM   products p
        LEFT   JOIN product_groups g ON p.group_id = g.id
    """
    conditions: list[str] = []
    params: list[object] = []
    if active_only:
        conditions.append("p.active = 1")
    if platform is not None:
        conditions.append("p.platform = ?")
        params.append(_validate_platform(platform))
    if group_id is not None:
        conditions.append("p.group_id = ?")
        params.append(group_id)
    if conditions:
        sql += " WHERE " + " AND ".join(conditions)
    # 품목 단위 계층 표시를 위해 그룹명 기준 정렬(미분류는 맨 뒤), 그 안에서 상품명순.
    sql += " ORDER BY p.platform, (g.name IS NULL), g.name, p.name"
    with get_conn(db_path) as conn:
        rows = conn.execute(sql, params).fetchall()
    return rows


def update_product(
    product_id: int,
    *,
    name: Optional[str] = None,
    keyword: Optional[str] = None,
    target_id: Optional[str] = None,
    target_url: Optional[str] = None,
    group_id: Optional[int] = None,
    clear_group: bool = False,
    active: Optional[bool] = None,
    db_path: Path = DB_PATH,
) -> bool:
    """Partial update — only supplied fields are changed.

    group_id 를 명시하면 해당 품목으로 이동. clear_group=True 면 품목 소속을 해제(NULL).
    """
    fields: list[tuple[str, object]] = []
    if name is not None:
        fields.append(("name", name))
    if keyword is not None:
        fields.append(("keyword", keyword))
    if target_id is not None:
        fields.append(("target_id", target_id))
    if target_url is not None:
        fields.append(("target_url", target_url))
    if clear_group:
        fields.append(("group_id", None))
    elif group_id is not None:
        fields.append(("group_id", group_id))
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
    """Hard-delete (cascades to rank_history / competitor_ranks / traffic_logs)."""
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
    status: str = RANK_STATUS_OK,
    price: Optional[int] = None,
    review_count: Optional[int] = None,
    db_path: Path = DB_PATH,
) -> None:
    """Insert or replace today's rank for a product (one record per day).

    status 는 스크래핑 결과 상태(ok/not_found/blocked/error). 차단·오류 시에도
    rank=0 으로 기록하되 status 로 구분해, 대시보드가 'HTML' 대신 상태 칩을 띄운다.
    price / review_count 는 내 상품의 노출가·리뷰수(경쟁 분석용, 없으면 NULL).
    """
    if status not in VALID_RANK_STATUSES:
        status = RANK_STATUS_OK
    date_str = (rank_date or date.today()).isoformat()
    with get_conn(db_path) as conn:
        conn.execute(
            """
            INSERT INTO rank_history
                (product_id, rank_date, rank, page, status, price, review_count)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(product_id, rank_date)
            DO UPDATE SET rank=excluded.rank, page=excluded.page,
                          status=excluded.status,
                          price=COALESCE(excluded.price, rank_history.price),
                          review_count=COALESCE(excluded.review_count,
                                                rank_history.review_count),
                          crawled_at=datetime('now','localtime')
            """,
            (product_id, date_str, rank, page, status, price, review_count),
        )
    log.info("Rank upserted: product_id=%d  date=%s  rank=%d  status=%s",
             product_id, date_str, rank, status)


def get_rank_history(
    product_id: int,
    days: int = 30,
    db_path: Path = DB_PATH,
) -> list[sqlite3.Row]:
    """Return the last `days` rank records for a product, newest first."""
    with get_conn(db_path) as conn:
        rows = conn.execute(
            """
            SELECT rank_date, rank, page, status, price, review_count, crawled_at
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
            SELECT rank_date, rank, page, status, price, review_count
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
    None      → insufficient history / 한쪽이 미노출·차단.
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

def _safe_int(val) -> Optional[int]:
    """문자열/숫자에서 정수를 안전하게 뽑는다 ('18,000원' → 18000). 실패 시 None."""
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return int(val)
    digits = re.sub(r"[^\d]", "", str(val))
    return int(digits) if digits else None


def _safe_float(val) -> Optional[float]:
    if val is None:
        return None
    try:
        return float(str(val).strip())
    except (ValueError, TypeError):
        return None


def upsert_competitor_ranks(
    product_id: int,
    entries: list[dict],
    rank_date: Optional[date] = None,
    db_path: Path = DB_PATH,
) -> None:
    """
    하루치 Top-N 경쟁사 스냅샷을 저장한다 (가격·리뷰·평점·썸네일 포함).

    entries: [{"rank": int, "name": str, "target_id": str,
               "price": int|None, "review_count": int|None,
               "rating": float|None, "has_thumbnail": bool|None}, ...]
    name 은 clean_text 로 정제 — 차단 페이지의 HTML/코드 텍스트가 경쟁사명으로
    저장되지 않도록 방어한다. 같은 (product_id, rank_date) 의 기존 레코드는
    모두 삭제 후 새로 삽입한다.
    """
    date_str = (rank_date or date.today()).isoformat()
    rows = [
        (
            product_id, date_str, int(e["rank"]),
            clean_text(e.get("name"), max_len=100), e.get("target_id"),
            _safe_int(e.get("price")), _safe_int(e.get("review_count")),
            _safe_float(e.get("rating")),
            (1 if e.get("has_thumbnail") else 0) if e.get("has_thumbnail") is not None else None,
        )
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
                "INSERT INTO competitor_ranks "
                "(product_id, rank_date, rank, name, target_id, "
                " price, review_count, rating, has_thumbnail) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
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
            SELECT rank_date, rank, name, target_id,
                   price, review_count, rating, has_thumbnail
            FROM   competitor_ranks
            WHERE  product_id = ?
              AND  rank_date >= date('now', ?)
            ORDER  BY rank_date ASC, rank ASC
            """,
            (product_id, f"-{int(days)} days"),
        ).fetchall()
    return rows


def get_latest_competitors(
    product_id: int,
    db_path: Path = DB_PATH,
) -> list[sqlite3.Row]:
    """
    가장 최근 일자의 Top-N 경쟁사 스냅샷(가격·리뷰·평점·썸네일 포함)을 반환.
    AI 경쟁 분석과 대시보드 비교 테이블에서 사용한다.
    """
    with get_conn(db_path) as conn:
        latest = conn.execute(
            "SELECT MAX(rank_date) AS d FROM competitor_ranks WHERE product_id = ?",
            (product_id,),
        ).fetchone()
        if not latest or not latest["d"]:
            return []
        rows = conn.execute(
            """
            SELECT rank_date, rank, name, target_id,
                   price, review_count, rating, has_thumbnail
            FROM   competitor_ranks
            WHERE  product_id = ? AND rank_date = ?
            ORDER  BY rank ASC
            """,
            (product_id, latest["d"]),
        ).fetchall()
    return rows


# ---------------------------------------------------------------------------
# Seed data helper
# ---------------------------------------------------------------------------

# (그룹명, 상품명, 키워드, target_id) — 품목 계층을 보여주기 위한 샘플
SAMPLE_GROUPS = {
    "naver": [
        ("에코앤팩 친환경 에어캡", [
            ("에어캡 10mm",  "친환경 에어캡",   "N_AIRCAP_10"),
            ("에어캡 20mm",  "친환경 에어캡 대형", "N_AIRCAP_20"),
        ]),
        ("내추럴 비누 라인", [
            ("천연 비누",    "천연 비누",       "N_SOAP_001"),
        ]),
    ],
    "coupang": [
        ("덴탈케어 묶음", [
            ("고체 치약",    "고체 치약",       "C_TOOTHPASTE_001"),
            ("대나무 칫솔",  "대나무 칫솔",     "C_BAMBOOBRUSH_001"),
        ]),
    ],
}


def _sample_competitors(seed: int) -> list[dict]:
    """샘플 Top5 경쟁사 — 가격/리뷰/평점/썸네일 포함 (AI 비교 분석 시연용)."""
    import random as _rnd
    rng = _rnd.Random(seed)
    out = []
    for r in range(1, 6):
        out.append({
            "rank": r,
            "name": f"경쟁사 상품 {r}",
            "target_id": f"COMP_{seed}_{r}",
            "price": rng.choice([12900, 13900, 14900, 15900, 16900]),
            "review_count": rng.choice([320, 580, 1240, 2100, 4300]),
            "rating": round(rng.uniform(4.4, 4.9), 1),
            "has_thumbnail": True,
        })
    return out


def seed_sample_data(db_path: Path = DB_PATH) -> None:
    """Insert sample groups/products + dummy rank/competitor data for local testing."""
    existing = {row["name"] for row in list_products(active_only=False, db_path=db_path)}

    inserted_ids: list[int] = []
    for platform, groups in SAMPLE_GROUPS.items():
        for group_name, products in groups:
            gid = add_group(group_name, platform, db_path=db_path)
            for name, keyword, target_id in products:
                if name in existing:
                    log.info("Sample product %r already exists, skipping.", name)
                    continue
                pid = add_product(
                    name=name,
                    platform=platform,
                    keyword=keyword,
                    target_id=target_id,
                    group_id=gid,
                    db_path=db_path,
                )
                inserted_ids.append(pid)

    # Seed two days of rank history + 경쟁사 스냅샷 for newly inserted products
    from datetime import timedelta
    today = date.today()
    yesterday = today - timedelta(days=1)

    sample_ranks      = [8, 22, 34, 5, 12]   # today
    sample_ranks_yday = [10, 19, 29, 5, 15]  # yesterday
    sample_prices     = [18000, 21000, 9900, 14500, 17900]   # 내 상품 노출가
    sample_reviews    = [340, 120, 890, 2400, 510]           # 내 상품 리뷰 수

    for i, pid in enumerate(inserted_ids):
        upsert_rank(pid, sample_ranks_yday[i % len(sample_ranks_yday)],
                    rank_date=yesterday, db_path=db_path)
        upsert_rank(pid, sample_ranks[i % len(sample_ranks)],
                    rank_date=today,
                    price=sample_prices[i % len(sample_prices)],
                    review_count=sample_reviews[i % len(sample_reviews)],
                    db_path=db_path)
        upsert_competitor_ranks(pid, _sample_competitors(seed=pid),
                                rank_date=today, db_path=db_path)
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
        print(f"{'ID':<4} {'Platform':<10} {'Group':<22} {'Name':<18} {'Keyword':<18} {'TargetID'}")
        print("-" * 95)
        for p in products:
            print(
                f"{p['id']:<4} {p['platform']:<10} {str(p['group_name'] or '(미분류)'):<22} "
                f"{p['name']:<18} {p['keyword']:<18} {p['target_id']}"
            )

    elif cmd == "groups":
        init_db()
        for g in list_groups():
            print(f"[{g['id']}] {g['platform']:<8} {g['name']}  ({g['product_count']}개 상품)")

    elif cmd == "history":
        product_id = int(sys.argv[2])
        rows = get_rank_history(product_id)
        print(f"Rank history for product_id={product_id}:")
        for r in rows:
            print(f"  {r['rank_date']}  rank={r['rank']}  page={r['page']}  status={r['status']}")

    else:
        print(f"Unknown command: {cmd}")
        print("Usage: python database.py [init|seed|list|groups|history <id>]")
