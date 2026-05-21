"""
scheduler.py — Morning rank report: scrape → DB → Telegram notification.

Usage
-----
    # Run once immediately (cron / manual test)
    python scheduler.py --now

    # Run as an in-process daily daemon (기본 매일 오전 9:00 KST)
    python scheduler.py --schedule
    python scheduler.py --schedule --hour 9 --minute 30

    # Dry-run: DB 데이터만으로 텔레그램 메시지 미리보기 (전송 안 함)
    python scheduler.py --dry-run

Environment variables (.env)
    TELEGRAM_BOT_TOKEN   텔레그램 봇 API 토큰
    TELEGRAM_CHAT_ID     리포트를 받을 챗 ID
    REPORT_HOUR          스케줄 시각 (KST, 기본 9)
    REPORT_MINUTE        스케줄 분   (기본 0)

Timezone
    APScheduler 의 BlockingScheduler / CronTrigger 모두 timezone="Asia/Seoul"
    로 고정되어 있어 서버 OS 의 UTC/Local 시간대와 무관하게 한국 시간(KST)
    기준 09:00 에 정확히 실행됩니다.
"""

import argparse
import asyncio
import html
import logging
import os
from dataclasses import dataclass
from datetime import date, datetime
from typing import Optional

import requests
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from dotenv import load_dotenv

import database as db
from scraper import get_all_ranks, RankResult, AuthSessionMissingError

load_dotenv(override=False)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID", "")
TELEGRAM_API_URL   = "https://api.telegram.org/bot{token}/sendMessage"

PLATFORM_DISPLAY = {"naver": "네이버", "coupang": "쿠팡"}
PLATFORM_EMOJI   = {"naver": "🟢", "coupang": "🟡"}
WEEKDAYS_KR      = ["월", "화", "수", "목", "금", "토", "일"]


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
    delta:           Optional[int]
    scrape_error:    Optional[str] = None


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
        raise
    except Exception as e:
        log.error("Scraper crashed: %s", e, exc_info=True)
        err_msg = f"스크래퍼 실행 실패: {type(e).__name__}: {e}"
        return [
            _build_report_item(p, today_rank=0, today_page=None,
                               scrape_error=err_msg, persist_today=False)
            for p in products
        ]
    log.info("Scrape complete.")

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


# ---------------------------------------------------------------------------
# Telegram message formatting (HTML parse mode)
# ---------------------------------------------------------------------------

def _fmt_rank(rank: int) -> str:
    return "미노출" if rank == 0 else f"{rank}위"


def _fmt_delta(delta: Optional[int], today: int, yesterday: Optional[int]) -> str:
    """순위 변동 라벨 — 🔺 상승 / 🔻 하락 / ➖ 변동없음 / 신규 / 미노출"""
    if yesterday is None:
        return "🆕 신규"
    if today == 0:
        return "⛔ 미노출"
    if delta is None:
        return "➖"
    if delta > 0:
        return f"🔺 {delta}"
    if delta < 0:
        return f"🔻 {abs(delta)}"
    return "➖"


def build_telegram_message(items: list[ReportItem]) -> str:
    """
    텔레그램 HTML 파스 모드 메시지를 생성한다.

    구조:
        📊 <b>데일리 순위 모니터링 리포트</b>
        🗓️ 2026-05-20 (수) 08:00

        🟢 <b>네이버</b>
          • <b>친환경 에어캡</b> — 8위  🔺 2
          • <b>천연 비누</b>    — 미노출  ⛔

        🟡 <b>쿠팡</b>
          • <b>고체 치약</b>   — 5위  ➖

        ─────────────
        📈 노출 3/4 · 🔺 상승 1 · 🔻 하락 0
    """
    now = datetime.now()
    date_str = (
        f"{now.strftime('%Y-%m-%d')} ({WEEKDAYS_KR[now.weekday()]}) "
        f"{now.strftime('%H:%M')}"
    )

    lines: list[str] = [
        "📊 <b>데일리 순위 모니터링 리포트</b>",
        f"🗓️ <i>{html.escape(date_str)}</i>",
        "",
    ]

    for platform in ("naver", "coupang"):
        platform_items = [it for it in items if it.platform == platform]
        if not platform_items:
            continue

        emoji   = PLATFORM_EMOJI[platform]
        display = PLATFORM_DISPLAY[platform]
        lines.append(f"{emoji} <b>{display}</b>")

        for it in platform_items:
            name_esc = html.escape(it.name)
            if it.scrape_error:
                err_esc = html.escape(it.scrape_error[:60])
                lines.append(f"  • <b>{name_esc}</b> — ⚠️ 조회실패  <code>{err_esc}</code>")
                continue

            rank_str  = _fmt_rank(it.today_rank)
            delta_str = _fmt_delta(it.delta, it.today_rank, it.yesterday_rank)
            lines.append(f"  • <b>{name_esc}</b> — <b>{rank_str}</b>  {delta_str}")

        lines.append("")

    scrape_ok = [it for it in items if not it.scrape_error]
    failed    = sum(1 for it in items if it.scrape_error)
    exposed   = sum(1 for it in scrape_ok if it.today_rank > 0)
    improved  = sum(1 for it in scrape_ok if it.delta and it.delta > 0)
    worsened  = sum(1 for it in scrape_ok if it.delta and it.delta < 0)

    lines.append("─────────────")
    footer = f"📈 노출 <b>{exposed}/{len(scrape_ok)}</b> · 🔺 상승 <b>{improved}</b> · 🔻 하락 <b>{worsened}</b>"
    if failed:
        footer += f" · ⚠️ 조회실패 <b>{failed}</b>"
    lines.append(footer)

    return "\n".join(lines)


def build_auth_missing_message() -> str:
    """auth_session 누락 시 보낼 텔레그램 알림 메시지."""
    now = datetime.now()
    date_str = (
        f"{now.strftime('%Y-%m-%d')} ({WEEKDAYS_KR[now.weekday()]}) "
        f"{now.strftime('%H:%M')}"
    )
    return (
        "⚠️ <b>순위 리포트 중단</b>\n"
        f"🗓️ <i>{html.escape(date_str)}</i>\n\n"
        "사전 인증 세션(<code>./auth_session</code>)이 만료되었거나 비어 있습니다.\n"
        "서버에서 <code>python auth_setup.py</code>를 다시 실행해 캡차 통과 후 세션을 갱신해 주세요."
    )


# ---------------------------------------------------------------------------
# Telegram sender
# ---------------------------------------------------------------------------

def send_telegram_message(
    text: str,
    bot_token: str = "",
    chat_id:  str = "",
    timeout:  int = 10,
) -> bool:
    """
    텔레그램 봇 API 의 sendMessage 로 메시지를 전송한다.
    HTTP 200 + ok=true 이면 True 반환, 아니면 False.
    """
    bot_token = bot_token or TELEGRAM_BOT_TOKEN
    chat_id   = chat_id   or TELEGRAM_CHAT_ID

    if not bot_token or not chat_id:
        log.error("TELEGRAM_BOT_TOKEN 또는 TELEGRAM_CHAT_ID 가 비어 있습니다.")
        return False

    url = TELEGRAM_API_URL.format(token=bot_token)
    payload = {
        "chat_id":                  chat_id,
        "text":                     text,
        "parse_mode":               "HTML",
        "disable_web_page_preview": True,
    }

    log.info("Sending Telegram message to chat_id=%s (%d bytes)...", chat_id, len(text))
    try:
        resp = requests.post(url, json=payload, timeout=timeout)
        resp.raise_for_status()
        body = resp.json()
        if not body.get("ok"):
            log.error("Telegram API 반환 오류: %s", body)
            return False
        log.info("Telegram 메시지 전송 완료 (message_id=%s).",
                 body.get("result", {}).get("message_id"))
        return True
    except requests.exceptions.Timeout:
        log.error("Telegram API 호출 타임아웃.")
    except requests.exceptions.HTTPError as e:
        body_txt = (getattr(e.response, "text", "") or "")[:300]
        log.error("Telegram HTTP 오류: %s  body=%s", e, body_txt)
    except requests.exceptions.RequestException as e:
        log.error("Telegram 요청 오류: %s", e)
    except ValueError:
        log.error("Telegram 응답 JSON 파싱 실패.")

    return False


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

def run_daily_report(
    bot_token: str = "",
    chat_id:  str = "",
) -> list[ReportItem]:
    """
    Full pipeline: scrape → save to DB → send Telegram notification.
    Returns the list of ReportItems for inspection / testing.
    """
    bot_token = bot_token or TELEGRAM_BOT_TOKEN
    chat_id   = chat_id   or TELEGRAM_CHAT_ID

    log.info("=== Daily rank report started ===")

    try:
        items = asyncio.run(_run_scrape_and_save())
    except AuthSessionMissingError as e:
        log.error("Auth session missing — sending alert and skipping scrape: %s", e)
        if bot_token and chat_id:
            send_telegram_message(build_auth_missing_message(), bot_token, chat_id)
        else:
            log.warning("Telegram 설정 없음 — auth-missing 알림 스킵.")
        log.info("=== Daily rank report finished (auth missing) ===")
        return []

    if not items:
        log.warning("No items to report.")
        return []

    _log_report_to_console(items)

    if bot_token and chat_id:
        send_telegram_message(build_telegram_message(items), bot_token, chat_id)
    else:
        log.warning("Telegram 설정(TELEGRAM_BOT_TOKEN/CHAT_ID) 누락 — 알림 스킵.")

    log.info("=== Daily rank report finished ===")
    return items


def _log_report_to_console(items: list[ReportItem]) -> None:
    now = datetime.now()
    print(f"\n[📊 데일리 순위 모니터링 리포트] — {now.strftime('%Y-%m-%d')} ({WEEKDAYS_KR[now.weekday()]})")
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
    bot_token: str = "",
    chat_id:  str = "",
    hour:     int = 9,
    minute:   int = 0,
) -> None:
    """
    매일 KST 기준 hour:minute 에 run_daily_report 를 실행하는 데몬.

    BlockingScheduler 와 CronTrigger 모두 timezone="Asia/Seoul" 로 명시되어
    있어 서버의 시스템 시간이 UTC 든 다른 지역이든 상관없이 한국 시간 기준
    오전 9시에 정확히 발화한다. (오라클/AWS Ubuntu 기본은 UTC)
    """
    bot_token = bot_token or TELEGRAM_BOT_TOKEN
    chat_id   = chat_id   or TELEGRAM_CHAT_ID

    scheduler = BlockingScheduler(timezone="Asia/Seoul")
    scheduler.add_job(
        func=run_daily_report,
        trigger=CronTrigger(hour=hour, minute=minute, timezone="Asia/Seoul"),
        kwargs={"bot_token": bot_token, "chat_id": chat_id},
        id="daily_rank_report",
        name="Daily Rank Report",
        misfire_grace_time=300,
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
        description="Marketing dashboard — daily rank report & Telegram notifier"
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--now",      action="store_true", help="Run the report immediately and exit.")
    mode.add_argument("--schedule", action="store_true", help="Start the daily scheduler daemon.")
    mode.add_argument("--dry-run",  action="store_true",
                      help="Build the Telegram message from DB data and print it (no scraping, no send).")
    parser.add_argument("--token",  default="", metavar="TOKEN",
                        help="Telegram bot token (overrides TELEGRAM_BOT_TOKEN env var).")
    parser.add_argument("--chat",   default="", metavar="CHAT_ID",
                        help="Telegram chat ID (overrides TELEGRAM_CHAT_ID env var).")
    parser.add_argument("--hour",   type=int, default=int(os.getenv("REPORT_HOUR",   "9")),
                        help="KST 기준 실행 시각 (기본 9)")
    parser.add_argument("--minute", type=int, default=int(os.getenv("REPORT_MINUTE", "0")),
                        help="KST 기준 실행 분 (기본 0)")
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()

    if args.now:
        run_daily_report(bot_token=args.token, chat_id=args.chat)

    elif args.schedule:
        start_scheduler(
            bot_token=args.token,
            chat_id=args.chat,
            hour=args.hour,
            minute=args.minute,
        )

    elif args.dry_run:
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
                    persist_today = False,
                )
            )

        _log_report_to_console(preview_items)
        print("\n--- Telegram HTML message preview ---")
        print(build_telegram_message(preview_items))
