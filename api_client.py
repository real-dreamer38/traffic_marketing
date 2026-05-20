"""
api_client.py — 트래픽 발주서 생성기.

업계 시행사 대다수는 공개 API 가 없고 카톡/텔레그램으로 오더를 받는다.
이 모듈은 사용자가 입력한 발주 정보로 시행사에 전달 가능한 텍스트 발주서를 만들고,
DB (traffic_logs) 에 우리의 요청 기록을 남기는 두 가지 역할을 한다.

Note
----
MVP 1차에서는 [트래픽 주입] UI 가 비활성화되어 있어 이 모듈은 직접 호출되지 않는다.
DB 스키마 호환과 향후 재개를 위해 코드만 유지한다.

Public API
----------
    result = create_traffic_order(
        product_id    = 3,
        product_name  = "친환경 에어캡",
        platform      = "naver",
        keyword       = "친환경 에어캡",
        target_url    = "https://smartstore.naver.com/...",
        target_id     = "N_AIRCAP_001",
        quantity      = 500,
        start_date    = date(2026, 5, 15),
    )
    print(result.order_text)        # 시행사에 보낼 텍스트
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional

from dotenv import load_dotenv

load_dotenv(override=False)

log = logging.getLogger(__name__)

PLATFORM_DISPLAY = {"naver": "네이버 (Naver Shopping)", "coupang": "쿠팡 (Coupang)"}
WEEKDAYS_KR      = ["월", "화", "수", "목", "금", "토", "일"]


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class OrderResult:
    success:       bool
    order_text:    str                = ""
    requested_at:  Optional[datetime] = None
    error:         Optional[str]      = None
    meta:          dict               = field(default_factory=dict)

    def to_json(self) -> str:
        payload = {
            "success":      self.success,
            "requested_at": self.requested_at.isoformat() if self.requested_at else None,
            "error":        self.error,
            "meta":         self.meta,
        }
        return json.dumps(payload, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Order text builder
# ---------------------------------------------------------------------------

def _format_qty(qty: int) -> str:
    return f"{qty:,} 회"


def build_order_text(
    *,
    product_name:  str,
    platform:      str,
    keyword:       str,
    target_url:    Optional[str],
    target_id:     Optional[str],
    quantity:      int,
    start_date:    date,
    requested_at:  Optional[datetime] = None,
) -> str:
    """시행사에 그대로 복사해 보낼 발주서 텍스트를 만든다."""
    if requested_at is None:
        requested_at = datetime.now()

    req_str   = (
        f"{requested_at.strftime('%Y-%m-%d')} "
        f"({WEEKDAYS_KR[requested_at.weekday()]}) "
        f"{requested_at.strftime('%H:%M')}"
    )
    start_str = (
        f"{start_date.strftime('%Y-%m-%d')} "
        f"({WEEKDAYS_KR[start_date.weekday()]})"
    )
    platform_str = PLATFORM_DISPLAY.get(platform.lower(), platform)
    target_url_s = (target_url or "").strip() or "-"
    target_id_s  = (target_id  or "").strip() or "-"

    rows = [
        ("요청일자",    req_str),
        ("시작일자",    start_str),
        ("상품명",      product_name),
        ("플랫폼",      platform_str),
        ("타겟 키워드", keyword),
        ("상품 URL",    target_url_s),
        ("상품 ID",     target_id_s),
        ("목표 수량",   _format_qty(quantity)),
    ]

    label_w = max(len(k) for k, _ in rows)
    body_lines = [f" {label:<{label_w}}  :  {value}" for label, value in rows]

    bar = "═" * 52
    return "\n".join([
        bar,
        "  📋 트래픽 발주서",
        bar,
        *body_lines,
        bar,
    ])


# ---------------------------------------------------------------------------
# Top-level orchestrator
# ---------------------------------------------------------------------------

def create_traffic_order(
    *,
    product_id:    int,
    product_name:  str,
    platform:      str,
    keyword:       str,
    target_url:    Optional[str],
    target_id:     Optional[str],
    quantity:      int,
    start_date:    date,
    db_path=None,
) -> OrderResult:
    """
    발주 1건의 전체 흐름:
      1) 입력 검증
      2) 발주서 텍스트 생성
      3) traffic_logs 에 기록
    """
    import database as db

    if db_path is None:
        db_path = db.DB_PATH

    if quantity <= 0:
        return OrderResult(
            success=False,
            error=f"수량은 1 이상이어야 합니다 (입력값: {quantity})",
            requested_at=datetime.now(),
        )
    if not (target_url and target_url.strip()) and not (target_id and target_id.strip()):
        return OrderResult(
            success=False,
            error="상품 URL 또는 상품 ID 중 하나는 반드시 입력해야 합니다.",
            requested_at=datetime.now(),
        )

    requested_at = datetime.now()
    order_text = build_order_text(
        product_name = product_name,
        platform     = platform,
        keyword      = keyword,
        target_url   = target_url,
        target_id    = target_id,
        quantity     = quantity,
        start_date   = start_date,
        requested_at = requested_at,
    )

    meta = {
        "start_date": start_date.isoformat(),
        "target_url": target_url or "",
        "target_id":  target_id  or "",
    }

    result = OrderResult(
        success      = True,
        order_text   = order_text,
        requested_at = requested_at,
        meta         = meta,
    )

    db.init_db(db_path=db_path)
    db.log_traffic(
        product_id    = product_id,
        traffic_qty   = quantity,
        api_status    = "success",
        api_response  = result.to_json(),
        error_message = None,
        db_path       = db_path,
    )

    return result


# ---------------------------------------------------------------------------
# CLI — 빠른 수동 테스트
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    parser = argparse.ArgumentParser(description="트래픽 발주서 생성기 — 수동 테스트")
    parser.add_argument("--product",   required=True, help="상품명")
    parser.add_argument("--platform",  required=True, choices=["naver", "coupang"])
    parser.add_argument("--keyword",   required=True, help="타겟 키워드")
    parser.add_argument("--url",       default="",    help="상품 URL")
    parser.add_argument("--target-id", default="",    help="상품 ID")
    parser.add_argument("--qty",       required=True, type=int, help="목표 수량")
    parser.add_argument("--start",     default=None,  help="시작일 YYYY-MM-DD (기본: 오늘)")
    args = parser.parse_args()

    start_date = (
        datetime.strptime(args.start, "%Y-%m-%d").date()
        if args.start else date.today()
    )

    text = build_order_text(
        product_name = args.product,
        platform     = args.platform,
        keyword      = args.keyword,
        target_url   = args.url,
        target_id    = args.target_id,
        quantity     = args.qty,
        start_date   = start_date,
    )
    print(text)
