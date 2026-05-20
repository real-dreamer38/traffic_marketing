"""
test_integration.py — 외부 의존성 없는 end-to-end 스모크 테스트.

검증 범위
---------
  1) database.py    : init_db / add_product / upsert_rank / get_rank_delta
  2) api_client.py  : create_traffic_order 발주서 생성 + traffic_logs 기록
  3) scheduler.py   : _build_report_item / build_slack_payload (정상/실패/auth-missing)

실행
----
    python test_integration.py

성공하면 모든 단계가 ✅ 로 표시되고 종료 코드 0, 어디서든 실패하면 ❌ 와 함께
종료 코드 1 을 리턴한다. 실제 Playwright/Slack 호출은 일절 하지 않는다.
"""

from __future__ import annotations

import json
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

# Windows cp949 콘솔에서 한글/이모지 출력이 깨지지 않도록 UTF-8 재구성
if sys.platform == "win32":
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

import database as db
from api_client import create_traffic_order, build_order_text
from scheduler import (
    ReportItem,
    _build_report_item,
    _build_auth_missing_payload,
    build_slack_payload,
)


# ---------------------------------------------------------------------------
# 미니 assert 헬퍼
# ---------------------------------------------------------------------------

_failures: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    if ok:
        print(f"  ✅ {label}")
    else:
        print(f"  ❌ {label}" + (f"  ({detail})" if detail else ""))
        _failures.append(label)


# ---------------------------------------------------------------------------
# 1) database layer
# ---------------------------------------------------------------------------

def test_database(db_path: Path) -> tuple[int, int]:
    """Return (naver_product_id, coupang_product_id) for downstream tests."""
    print("\n[1] database.py")
    db.init_db(db_path=db_path)

    naver_id = db.add_product(
        name="테스트 에어캡", platform="naver",
        keyword="친환경 에어캡", target_id="TEST_NAVER_001",
        db_path=db_path,
    )
    coupang_id = db.add_product(
        name="테스트 치약", platform="coupang",
        keyword="고체 치약", target_id="TEST_COUPANG_001",
        db_path=db_path,
    )
    check("상품 2건 추가",
          naver_id > 0 and coupang_id > 0,
          f"naver={naver_id} coupang={coupang_id}")

    products = db.list_products(active_only=True, db_path=db_path)
    check("list_products 2건 반환", len(products) == 2, f"len={len(products)}")

    # 어제 → 오늘 순위 upsert → delta 계산
    today     = date.today()
    yesterday = today - timedelta(days=1)
    db.upsert_rank(naver_id, rank=10, rank_date=yesterday, page=1, db_path=db_path)
    db.upsert_rank(naver_id, rank=7,  rank_date=today,     page=1, db_path=db_path)
    delta = db.get_rank_delta(naver_id, db_path=db_path)
    check("get_rank_delta 정상 (10→7 = +3)", delta == 3, f"delta={delta}")

    # 미노출(0) 케이스에서 delta 는 None 이어야 함
    db.upsert_rank(coupang_id, rank=0, rank_date=yesterday, db_path=db_path)
    db.upsert_rank(coupang_id, rank=5, rank_date=today,     page=1, db_path=db_path)
    delta_with_zero = db.get_rank_delta(coupang_id, db_path=db_path)
    check("미노출(0) 포함 시 delta=None",
          delta_with_zero is None,
          f"got {delta_with_zero}")

    return naver_id, coupang_id


# ---------------------------------------------------------------------------
# 2) api_client — 발주서 생성기 플로우
# ---------------------------------------------------------------------------

def test_api_client_stub(db_path: Path, product_id: int) -> None:
    print("\n[2] api_client.py — 발주서 생성기")

    # 발주서 텍스트만 생성 (DB·Slack 미관여)
    text = build_order_text(
        product_name = "친환경 에어캡",
        platform     = "naver",
        keyword      = "친환경 에어캡",
        target_url   = "https://smartstore.naver.com/x/p/1",
        target_id    = "N_AIRCAP_001",
        quantity     = 300,
        start_date   = date.today(),
    )
    check("발주서 텍스트 생성",      "트래픽 발주서" in text)
    check("상품명 포함",             "친환경 에어캡" in text)
    check("플랫폼(네이버) 포함",     "네이버" in text)
    check("키워드 포함",             "친환경 에어캡" in text)
    check("수량 표기 (300 회)",      "300 회" in text)

    # End-to-end: create_traffic_order — DB 기록까지 검증 (Slack 미설정)
    result = create_traffic_order(
        product_id   = product_id,
        product_name = "테스트 상품",
        platform     = "naver",
        keyword      = "테스트 키워드",
        target_url   = "https://example.com/products/1",
        target_id    = "TEST_001",
        quantity     = 300,
        start_date   = date.today(),
        slack_webhook= None,
        db_path      = db_path,
    )
    check("발주서 생성 성공",        result.success is True,       f"err={result.error}")
    check("order_text 비어있지 않음", bool(result.order_text))
    check("Slack 미설정 → 푸시 안함", result.slack_pushed is False)
    check("requested_at 채워짐",     result.requested_at is not None)

    logs = db.get_traffic_logs(product_id, limit=5, db_path=db_path)
    check("traffic_logs 기록됨",     len(logs) == 1,               f"len={len(logs)}")
    if logs:
        check("api_status='success'", logs[0]["api_status"] == "success",
              f"got {logs[0]['api_status']}")
        check("traffic_qty 일치",     logs[0]["traffic_qty"] == 300,
              f"got {logs[0]['traffic_qty']}")

    # 잘못된 수량 → 에러 케이스
    bad = create_traffic_order(
        product_id   = product_id,
        product_name = "x", platform = "naver", keyword = "x",
        target_url   = "https://x", target_id = "",
        quantity     = 0, start_date = date.today(),
        db_path      = db_path,
    )
    check("quantity<=0 거부",        bad.success is False,         f"err={bad.error}")

    # URL/ID 둘 다 비면 거부
    no_target = create_traffic_order(
        product_id   = product_id,
        product_name = "x", platform = "naver", keyword = "x",
        target_url   = "", target_id = "",
        quantity     = 50, start_date = date.today(),
        db_path      = db_path,
    )
    check("URL/ID 모두 비면 거부",   no_target.success is False,   f"err={no_target.error}")


# ---------------------------------------------------------------------------
# 3) scheduler ReportItem & Slack payload
# ---------------------------------------------------------------------------

def test_report_payload(db_path: Path, naver_id: int, coupang_id: int) -> None:
    print("\n[3] scheduler.py — ReportItem & Slack payload")

    products = db.list_products(active_only=True, db_path=db_path)
    prod_map = {p["id"]: p for p in products}

    # 정상 케이스 — 어제 10위 → 오늘 7위 (▲ 3)
    item_ok = _build_report_item(
        product       = prod_map[naver_id],
        today_rank    = 7,
        today_page    = 1,
        scrape_error  = None,
        persist_today = False,
        db_path       = db_path,
    )
    check("정상: today_rank=7",          item_ok.today_rank == 7)
    check("정상: yesterday_rank=10",     item_ok.yesterday_rank == 10,
          f"got {item_ok.yesterday_rank}")
    check("정상: delta=+3",              item_ok.delta == 3,
          f"got {item_ok.delta}")
    check("정상: scrape_error 없음",     item_ok.scrape_error is None)

    # 스크래핑 실패 케이스
    item_err = _build_report_item(
        product       = prod_map[coupang_id],
        today_rank    = 0,
        today_page    = None,
        scrape_error  = "TimeoutError: navigation timed out",
        persist_today = False,
        db_path       = db_path,
    )
    check("실패: scrape_error 보존",
          bool(item_err.scrape_error) and "Timeout" in item_err.scrape_error,
          f"got {item_err.scrape_error}")

    # Slack 페이로드 빌드 — 정상 + 실패 혼합
    payload = build_slack_payload([item_ok, item_err])
    payload_json = json.dumps(payload, ensure_ascii=False)

    check("payload 'text' 존재",      "text" in payload)
    check("payload 'blocks' 존재",    "blocks" in payload and len(payload["blocks"]) > 0)
    check("페이로드에 :warning: 포함",
          ":warning:" in payload_json,
          "실패 인디케이터가 누락됨")
    check("페이로드에 조회실패 1건 표기",
          "조회실패 1" in payload_json,
          "푸터의 실패 카운트가 누락됨")
    check("정상 항목 ▲ 3 렌더링",
          "▲ 3" in payload_json,
          "delta 표시 누락")

    # auth_session 누락 페이로드
    auth_payload = _build_auth_missing_payload()
    check("auth-missing: header 블록",
          auth_payload["blocks"][0]["type"] == "header")
    check("auth-missing: 본문에 auth_session 언급",
          "auth_session" in json.dumps(auth_payload, ensure_ascii=False))


# ---------------------------------------------------------------------------
# Entry
# ---------------------------------------------------------------------------

def main() -> int:
    print("═" * 60)
    print("  traffic_marketing — integration smoke test")
    print("═" * 60)

    with tempfile.TemporaryDirectory(prefix="tm_test_") as tmp:
        db_path = Path(tmp) / "test.db"
        print(f"  임시 DB: {db_path}")

        naver_id, coupang_id = test_database(db_path)
        test_api_client_stub(db_path, product_id=naver_id)
        test_report_payload(db_path, naver_id=naver_id, coupang_id=coupang_id)

    print("\n" + "═" * 60)
    if _failures:
        print(f"  ❌ 실패 {len(_failures)}건:")
        for f in _failures:
            print(f"     - {f}")
        print("═" * 60)
        return 1
    print("  ✅ 모든 통합 테스트 통과")
    print("═" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
