"""
scheduler.py — Morning rank report: scrape → DB → Slack notification.

Usage
-----
    # Run once immediately (cron / manual test)
    python3 scheduler.py --now

    # Run as an in-process daily daemon (기본 오전 8:00 KST)
    python3 scheduler.py --schedule
    python3 scheduler.py --schedule --hour 9 --minute 30

    # Override webhook URL at runtime
    python3 scheduler.py --now --webhook https://hooks.slack.com/services/XXX/YYY/ZZZ

Environment variables (fallback when CLI args are omitted)
    SLACK_WEBHOOK_URL   Slack Incoming Webhook URL
    REPORT_HOUR         스케줄 시각 (기본 8)
    REPORT_MINUTE       스케줄 분   (기본 0)
"""

import argparse
import asyncio
import logging
import os
import json
from dataclasses import dataclass
from datetime import date, datetime
from typing import Optional

import requests
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from dotenv import load_dotenv

import database as db
from scraper import get_all_ranks, RankResult, AuthSessionMissingError

# .env 파일 로드 — 이미 설정된 환경변수는 덮어쓰지 않음
load_dotenv(override=False)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL", "")

# ── 임시 비활성화 스위치 ──────────────────────────────────────
# 인터넷/방화벽 환경 이슈로 슬랙 전송이 막혀 있는 동안 기본 OFF.
# 환경변수 SLACK_ENABLED=true 로 설정하거나 아래 기본값을 "true" 로 바꾸면 재활성화된다.
# 영향 범위: 일일 리포트 발송 + auth_session 누락 알림 두 곳 모두에서 스킵.
SLACK_ENABLED = os.getenv("SLACK_ENABLED", "false").lower() == "true"

PLATFORM_DISPLAY = {"naver": "네이버", "coupang": "쿠팡"}
PLATFORM_EMOJI   = {"naver": "🟢", "coupang": "🟡"}


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class ReportItem:
    product_id:      int
    name:            str
    platform:        str
    keyword:         str
    today_rank:      int
    yesterday_rank:  Optional[int]
    delta:           Optional[int]   # positive = improved, negative = worsened
    scrape_error:    Optional[str] = None   # 스크래핑 자체가 실패한 경우의 사유 (None = 정상)


# ---------------------------------------------------------------------------
# Core report runner
# ---------------------------------------------------------------------------

def _build_report_item(
    product:       "dict | db.sqlite3.Row",
    today_rank:    int,
    today_page:    Optional[int],
    scrape_error:  Optional[str] = None,
    persist_today: bool = True,
    db_path=None,
) -> ReportItem:
    """
    Compute a ReportItem from a product row + today's scrape result.

    Why: 동일한 빌드 로직이 실시간 스크래핑 경로와 dry-run 미리보기 경로 양쪽에서
    필요했다. 분기 코드 중복을 막고 미래에 추가될 yesterday/delta 규칙을 한 곳에서
    유지하기 위해 헬퍼로 추출했다.

    - scrape_error 가 set 이면 today's rank 는 DB에 저장하지 않는다 (오염 방지).
    - persist_today=False 이면 dry-run/preview 모드로 DB에 쓰지 않는다.
    - db_path=None 이면 database 모듈의 기본 DB_PATH 사용 (운영). 테스트에서는
      임시 DB 경로를 명시해 격리할 수 있다.
    """
    if db_path is None:
        db_path = db.DB_PATH

    pid = product["id"]

    if persist_today and scrape_error is None:
        db.upsert_rank(
            product_id=pid,
            rank=today_rank,
            rank_date=date.today(),
            page=today_page,
            db_path=db_path,
        )

    history = db.get_rank_history(pid, days=2, db_path=db_path)
    yesterday_rank: Optional[int] = None
    delta: Optional[int] = None
    if len(history) >= 2:
        # 오늘이 upsert 되었으면 history[0]=today, history[1]=직전 기록
        yesterday_rank = history[1]["rank"]
        if today_rank > 0 and yesterday_rank > 0:
            delta = yesterday_rank - today_rank  # +값 = 순위 상승

    return ReportItem(
        product_id    = pid,
        name          = product["name"],
        platform      = product["platform"],
        keyword       = product["keyword"],
        today_rank    = today_rank,
        yesterday_rank= yesterday_rank,
        delta         = delta,
        scrape_error  = scrape_error,
    )


async def _run_scrape_and_save() -> list[ReportItem]:
    """
    1. Load all active products from DB.
    2. Scrape current ranks via Playwright (failures isolated per product).
    3. Upsert today's ranks into rank_history (skipped for products that errored).
    4. Return ReportItem list with delta values.

    Raises AuthSessionMissingError if ./auth_session is missing — the caller is
    expected to catch this and notify Slack rather than let the daemon die.
    """
    products = db.list_products(active_only=True)
    if not products:
        log.warning("No active products found in DB.")
        return []

    product_dicts = [
        {
            "platform":  p["platform"],
            "keyword":   p["keyword"],
            "target_id": p["target_id"] or "",
            "name":      p["name"],
            "_id":       p["id"],
        }
        for p in products
    ]

    log.info("Starting rank scrape for %d products...", len(product_dicts))
    try:
        rank_results: list[RankResult] = await get_all_ranks(product_dicts)
    except AuthSessionMissingError:
        # 호출자(run_daily_report) 가 잡아 Slack 알림으로 전환한다.
        raise
    except Exception as e:
        # 스크래퍼 전체가 죽은 경우 — 컨텍스트 launch 실패, 네트워크 끊김 등.
        # 한 상품 실패는 _search_naver/_search_coupang 내부에서 이미 (0, None)으로 격리되므로
        # 여기까지 올라오는 예외는 모두 "전체 실패"로 간주하고 모든 상품에 scrape_error 마킹.
        log.error("Scraper crashed: %s", e, exc_info=True)
        err_msg = f"스크래퍼 실행 실패: {type(e).__name__}: {e}"
        return [
            _build_report_item(p, today_rank=0, today_page=None,
                               scrape_error=err_msg, persist_today=False)
            for p in products
        ]
    log.info("Scrape complete.")

    # keyword+platform 으로 매칭 — target_id 가 비어있는 상품이 여러 개 있어도 안전
    result_map: dict[tuple[str, str], RankResult] = {
        (r.platform, r.keyword): r for r in rank_results
    }

    report_items: list[ReportItem] = []
    for p in products:
        key = (p["platform"], p["keyword"])
        result = result_map.get(key)
        today_rank = result.rank if result else 0
        today_page = result.page if result else None
        report_items.append(
            _build_report_item(
                product       = p,
                today_rank    = today_rank,
                today_page    = today_page,
                scrape_error  = None,
                persist_today = True,
            )
        )

        # Top 5 경쟁사 스냅샷도 함께 저장 (있을 때만)
        if result and result.top5:
            try:
                db.upsert_competitor_ranks(
                    product_id=p["id"],
                    entries=result.top5,
                    rank_date=date.today(),
                )
            except Exception as e:
                log.warning("Competitor rank persist failed for product_id=%d: %s",
                            p["id"], e)

    return report_items


def _build_auth_missing_payload() -> dict:
    """auth_session 누락 시 보낼 Slack 알림 페이로드."""
    weekdays = ["월", "화", "수", "목", "금", "토", "일"]
    now = datetime.now()
    date_str = f"{now.strftime('%Y-%m-%d')} ({weekdays[now.weekday()]}) {now.strftime('%H:%M')}"
    text = (
        f"⚠️ *순위 리포트 중단* — {date_str}\n"
        f"사전 인증 세션(`./auth_session`) 이 만료되었거나 비어 있습니다.\n"
        f"서버에서 `python auth_setup.py` 를 다시 실행해 캡차 통과 후 세션을 갱신해 주세요."
    )
    return {
        "text": "⚠️ 순위 리포트 중단 — auth_session 만료 (수동 갱신 필요)",
        "blocks": [
            {"type": "header", "text": {"type": "plain_text", "text": "⚠️ 순위 리포트 중단", "emoji": True}},
            {"type": "section", "text": {"type": "mrkdwn", "text": text}},
        ],
    }


# ---------------------------------------------------------------------------
# Slack message formatting
# ---------------------------------------------------------------------------

def _fmt_rank(rank: int) -> str:
    return "미노출" if rank == 0 else f"{rank}위"


def _fmt_delta(delta: Optional[int], today: int, yesterday: Optional[int]) -> str:
    """Return a compact delta string like ▲ 2 / ▼ 5 / - / 신규"""
    if yesterday is None:
        return "신규"
    if today == 0:
        return "미노출"
    if delta is None:
        return "-"
    if delta > 0:
        return f"▲ {delta}"
    if delta < 0:
        return f"▼ {abs(delta)}"
    return "-"


def build_slack_payload(items: list[ReportItem]) -> dict:
    """
    Build a Slack Block Kit payload.

    Visual structure:
    ┌─────────────────────────────────────┐
    │ 📊 데일리 순위 모니터링 리포트        │
    │ 2026-05-12 (화) 오전 8:00           │
    ├─────────────────────────────────────┤
    │ 🟢 네이버                           │
    │ • 친환경 에어캡  8위  ▲ 2           │
    │ • 천연 비누     34위  ▼ 5           │
    ├─────────────────────────────────────┤
    │ 🟡 쿠팡                             │
    │ • 고체 치약      5위  -             │
    │ • 대나무 칫솔   12위  ▲ 3           │
    └─────────────────────────────────────┘
    """
    now = datetime.now()
    weekdays = ["월", "화", "수", "목", "금", "토", "일"]
    date_str = f"{now.strftime('%Y-%m-%d')} ({weekdays[now.weekday()]}) {now.strftime('%H:%M')}"

    blocks: list[dict] = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": "📊 데일리 순위 모니터링 리포트",
                "emoji": True,
            },
        },
        {
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": f"*{date_str}*  |  총 {len(items)}개 상품"}],
        },
        {"type": "divider"},
    ]

    # Group by platform
    platforms = ["naver", "coupang"]
    for platform in platforms:
        platform_items = [it for it in items if it.platform == platform]
        if not platform_items:
            continue

        emoji   = PLATFORM_EMOJI[platform]
        display = PLATFORM_DISPLAY[platform]

        lines: list[str] = []
        for it in platform_items:
            # 스크래핑 자체가 실패한 경우 — 미노출(rank=0) 과 명확히 구분
            if it.scrape_error:
                lines.append(
                    f":warning:  *{it.name}*  —  *조회실패*  `{it.scrape_error[:60]}`"
                )
                continue

            rank_str  = _fmt_rank(it.today_rank)
            delta_str = _fmt_delta(it.delta, it.today_rank, it.yesterday_rank)

            if it.delta and it.delta > 0:
                indicator = ":chart_with_upwards_trend:"
            elif it.delta and it.delta < 0:
                indicator = ":chart_with_downwards_trend:"
            elif it.today_rank == 0:
                indicator = ":no_entry_sign:"
            else:
                indicator = ":white_circle:"

            lines.append(
                f"{indicator}  *{it.name}*  —  *{rank_str}*  `{delta_str}`"
            )

        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"{emoji} *{display}*\n" + "\n".join(lines),
                },
            }
        )
        blocks.append({"type": "divider"})

    # Footer — 스크래핑 실패는 분모에서 제외하고 별도 카운트로 표시
    scrape_ok = [it for it in items if not it.scrape_error]
    failed    = sum(1 for it in items if it.scrape_error)
    exposed   = sum(1 for it in scrape_ok if it.today_rank > 0)
    improved  = sum(1 for it in scrape_ok if it.delta and it.delta > 0)
    worsened  = sum(1 for it in scrape_ok if it.delta and it.delta < 0)

    footer_text = (
        f"노출 {exposed}/{len(scrape_ok)}  |  "
        f":chart_with_upwards_trend: 상승 {improved}  "
        f":chart_with_downwards_trend: 하락 {worsened}"
    )
    if failed:
        footer_text += f"  |  :warning: 조회실패 {failed}"

    blocks.append(
        {
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": footer_text}],
        }
    )

    # Plain-text fallback (for notification previews)
    fallback_lines = [f"[📊 데일리 순위 모니터링 리포트] — {date_str}"]
    for it in items:
        platform_kr = PLATFORM_DISPLAY[it.platform]
        if it.scrape_error:
            fallback_lines.append(f"- {it.name} ({platform_kr}): 조회실패 ({it.scrape_error[:60]})")
            continue
        rank_str    = _fmt_rank(it.today_rank)
        delta_str   = _fmt_delta(it.delta, it.today_rank, it.yesterday_rank)
        fallback_lines.append(f"- {it.name} ({platform_kr}): {rank_str} ({delta_str})")

    return {
        "text": "\n".join(fallback_lines),
        "blocks": blocks,
    }


# ---------------------------------------------------------------------------
# Slack sender
# ---------------------------------------------------------------------------

def send_slack_report(webhook_url: str, items: list[ReportItem]) -> bool:
    """
    POST the report to a Slack Incoming Webhook.
    Returns True on HTTP 200, False otherwise.
    """
    if not webhook_url:
        log.error("SLACK_WEBHOOK_URL is not set. Cannot send report.")
        return False

    payload = build_slack_payload(items)
    log.info("Sending Slack report to webhook (%d items)...", len(items))

    try:
        resp = requests.post(
            webhook_url,
            data=json.dumps(payload),
            headers={"Content-Type": "application/json"},
            timeout=10,
        )
        resp.raise_for_status()
        log.info("Slack report sent successfully (status %d).", resp.status_code)
        return True
    except requests.exceptions.Timeout:
        log.error("Slack webhook timed out.")
    except requests.exceptions.HTTPError as e:
        log.error("Slack webhook HTTP error: %s  body: %s", e, resp.text[:200])
    except requests.exceptions.RequestException as e:
        log.error("Slack webhook request error: %s", e)

    return False


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

def run_daily_report(webhook_url: str = "") -> list[ReportItem]:
    """
    Full pipeline: scrape → save to DB → send Slack notification.
    Returns the list of ReportItems for inspection / testing.

    auth_session 누락 시에는 빈 리스트를 반환하고 대신 별도의 경고 메시지를
    Slack 으로 발송한다 (데몬은 계속 살아 있음).
    """
    webhook_url = webhook_url or SLACK_WEBHOOK_URL
    log.info("=== Daily rank report started ===")

    try:
        items = asyncio.run(_run_scrape_and_save())
    except AuthSessionMissingError as e:
        log.error("Auth session missing — sending alert and skipping scrape: %s", e)
        if SLACK_ENABLED and webhook_url:
            try:
                requests.post(
                    webhook_url,
                    data=json.dumps(_build_auth_missing_payload()),
                    headers={"Content-Type": "application/json"},
                    timeout=10,
                )
                log.info("Auth-missing alert sent to Slack.")
            except requests.exceptions.RequestException as req_err:
                log.error("Failed to send auth-missing alert: %s", req_err)
        else:
            log.warning("Slack 비활성화 또는 webhook URL 없음 — auth-missing 알림 스킵.")
        log.info("=== Daily rank report finished (auth missing) ===")
        return []

    if not items:
        log.warning("No items to report.")
        return []

    # Always log to console regardless of Slack result
    _log_report_to_console(items)

    if SLACK_ENABLED and webhook_url:
        send_slack_report(webhook_url, items)
    else:
        log.warning("Slack 비활성화(SLACK_ENABLED=%s) 또는 webhook URL 없음 — 슬랙 전송 스킵.",
                    SLACK_ENABLED)

    log.info("=== Daily rank report finished ===")
    return items


def _log_report_to_console(items: list[ReportItem]) -> None:
    weekdays = ["월", "화", "수", "목", "금", "토", "일"]
    now = datetime.now()
    print(f"\n[📊 데일리 순위 모니터링 리포트] — {now.strftime('%Y-%m-%d')} ({weekdays[now.weekday()]})")
    print("-" * 50)
    for it in items:
        platform_kr = PLATFORM_DISPLAY[it.platform]
        if it.scrape_error:
            print(f"  - {it.name} ({platform_kr}): 조회실패 ({it.scrape_error[:60]})")
            continue
        rank_str    = _fmt_rank(it.today_rank)
        delta_str   = _fmt_delta(it.delta, it.today_rank, it.yesterday_rank)
        print(f"  - {it.name} ({platform_kr}): {rank_str} ({delta_str})")
    print("-" * 50)


# ---------------------------------------------------------------------------
# Scheduler daemon
# ---------------------------------------------------------------------------

def start_scheduler(
    webhook_url: str = "",
    hour: int = 8,
    minute: int = 0,
) -> None:
    """
    Start a blocking APScheduler that fires run_daily_report every day
    at the specified KST time.  Ctrl-C to stop.
    """
    webhook_url = webhook_url or SLACK_WEBHOOK_URL
    scheduler = BlockingScheduler(timezone="Asia/Seoul")
    scheduler.add_job(
        func=run_daily_report,
        trigger=CronTrigger(hour=hour, minute=minute, timezone="Asia/Seoul"),
        kwargs={"webhook_url": webhook_url},
        id="daily_rank_report",
        name="Daily Rank Report",
        misfire_grace_time=300,   # allow up to 5-min late start
        coalesce=True,
    )

    next_run = scheduler.get_job("daily_rank_report").next_run_time
    log.info(
        "Scheduler started — daily report at %02d:%02d KST.  Next run: %s",
        hour, minute, next_run,
    )
    print(f"\n스케줄러 실행 중 (매일 {hour:02d}:{minute:02d} KST)  |  Ctrl-C 로 종료\n")

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        log.info("Scheduler stopped.")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Marketing dashboard — daily rank report & Slack notifier"
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--now",
        action="store_true",
        help="Run the report immediately and exit.",
    )
    mode.add_argument(
        "--schedule",
        action="store_true",
        help="Start the daily scheduler daemon.",
    )
    mode.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the Slack payload JSON without sending (uses DB data, no scraping).",
    )
    parser.add_argument(
        "--webhook",
        default="",
        metavar="URL",
        help="Slack Incoming Webhook URL (overrides SLACK_WEBHOOK_URL env var).",
    )
    parser.add_argument("--hour",   type=int, default=int(os.getenv("REPORT_HOUR",   "8")))
    parser.add_argument("--minute", type=int, default=int(os.getenv("REPORT_MINUTE", "0")))
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()

    if args.now:
        run_daily_report(webhook_url=args.webhook)

    elif args.schedule:
        start_scheduler(webhook_url=args.webhook, hour=args.hour, minute=args.minute)

    elif args.dry_run:
        # Build a report from DB data only (no live scraping) to preview Slack payload
        db.init_db()
        products = db.list_products(active_only=True)
        preview_items: list[ReportItem] = []
        for p in products:
            latest = db.get_latest_rank(p["id"])
            today_rank = latest["rank"] if latest else 0
            today_page = latest["page"] if latest else None
            preview_items.append(
                _build_report_item(
                    product       = p,
                    today_rank    = today_rank,
                    today_page    = today_page,
                    scrape_error  = None,
                    persist_today = False,   # dry-run: DB에 쓰지 않음
                )
            )

        _log_report_to_console(preview_items)
        payload = build_slack_payload(preview_items)
        print("\n--- Slack JSON payload preview ---")
        print(json.dumps(payload, ensure_ascii=False, indent=2))
