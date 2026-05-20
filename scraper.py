"""
scraper.py — Playwright async rank scraper for Naver Shopping and Coupang.

전략
----
캡차 우회를 자동화 코드로 시도하지 않는다. 대신 auth_setup.py 가 미리 만들어
둔 ./auth_session 디렉터리(사용자가 직접 캡차를 풀고 저장한 쿠키·세션)를
재사용하여, 봇 의심 점수가 낮은 상태로 단순히 페이지를 긁는다.

전제
----
실행 전 반드시 다음을 1회 수행:
    python auth_setup.py
→ ./auth_session 디렉터리가 생성되어야 한다.

Public API
----------
    result = asyncio.run(get_rank("naver",   keyword, target_id))
    result = asyncio.run(get_rank("coupang", keyword, target_id))

    RankResult.rank  : int  — 1-based absolute position; 0 = not found
    RankResult.page  : int  — result page number where found (None if not found)
"""

import asyncio
import logging
import pathlib
import random
import re
import sys
from dataclasses import dataclass
from datetime import datetime as _dt
from typing import Optional
from urllib.parse import quote

# Windows cp949 콘솔에서 박스 문자(═ 등) 출력이 터지지 않도록 UTF-8 재구성
if sys.platform == "win32":
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

from playwright.async_api import (
    async_playwright,
    BrowserContext,
    Page,
    Error as PWError,
    TimeoutError as PWTimeout,
)

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# 사전 인증 세션 디렉터리 — auth_setup.py 가 미리 만들어 둔 폴더를 그대로 사용
AUTH_SESSION_DIR = pathlib.Path(__file__).parent / "auth_session"

# Naver Shopping
NAVER_SEARCH_URL = (
    "https://search.shopping.naver.com/search/all"
    "?query={query}&pagingIndex={page}&pagingSize=40&sort=rel"
)
NAVER_ITEMS_PER_PAGE = 40

# Coupang
COUPANG_SEARCH_URL = (
    "https://www.coupang.com/np/search?q={query}&page={page}&listSize=36&sorter=scoreDesc"
)
COUPANG_ITEMS_PER_PAGE = 36

DEFAULT_MAX_PAGES = 5

# Product ID 추출 패턴 — href URL 과 data-* 속성에서 정규식으로 뽑음
_NAVER_ID_PATTERNS = [
    re.compile(r'/catalog/(\d{8,})'),
    re.compile(r'[?&]nvMid=(\d+)'),
    re.compile(r'[?&]productId=(\d+)'),
    re.compile(r'/products/(\d{8,})'),
    re.compile(r'itemId=(\d+)'),
]

_COUPANG_ID_PATTERNS = [
    re.compile(r'/vp/products/(\d+)'),
    re.compile(r'[?&]vendorItemId=(\d+)'),
    re.compile(r'data-product-id=["\'](\d+)["\']'),
    re.compile(r'data-vendor-item-id=["\'](\d+)["\']'),
    re.compile(r'"productId"\s*:\s*(\d+)'),
]

# 쿠팡 상품 컨테이너 셀렉터 — 페이지/키워드/AB 테스트에 따라 클래스가 자주 바뀌므로
# 알려진 변형을 모두 나열한다. wait_for_selector 와 _extract_coupang_ids 의
# JS 평가에서 공통으로 쓰인다.
_COUPANG_PRODUCT_SELECTORS = [
    "#productList li[data-product-id]",
    "ul#productList > li",
    "ul.search-product-list > li",
    "li.search-product",
    "li[class*='search-product']",
    "li[class*='searchProductList']",
    "li.baby-product",
    "li[class*='baby-product']",
    "div[class*='product-item']",
    "div[class*='ProductUnit']",
    "[data-product-id]",
    "[data-vendor-item-id]",
    "a[href*='/vp/products/']",
]


# ---------------------------------------------------------------------------
# Data types & exceptions
# ---------------------------------------------------------------------------

class AuthSessionMissingError(RuntimeError):
    """./auth_session 이 비어 있거나 없을 때 발생. 호출자가 잡아 복구해야 한다."""


@dataclass
class RankResult:
    rank: int                # 0 = not found
    page: Optional[int]      # page number; None when rank == 0
    keyword: str
    platform: str
    target_id: str
    top5: list[dict] = None  # [{"rank": int, "name": str, "target_id": str}], page1 기준 Top 5

    def __post_init__(self):
        if self.top5 is None:
            self.top5 = []


# ---------------------------------------------------------------------------
# Browser / context factory
# ---------------------------------------------------------------------------

def _ensure_auth_session() -> None:
    """auth_session 디렉터리가 없거나 비어 있으면 AuthSessionMissingError를 던진다.

    Why: 이전에는 SystemExit으로 프로세스 자체를 죽였으나, scheduler 데몬에서 호출
    될 때 daemon 전체가 함께 죽어 다음 날 리포트도 실패했다. 호출자가 잡아서
    Slack 알림 등 복구 동작을 수행할 수 있도록 명시적 예외로 바꾼다.
    """
    if not AUTH_SESSION_DIR.exists() or not any(AUTH_SESSION_DIR.iterdir()):
        raise AuthSessionMissingError(
            "사전 인증 세션(./auth_session) 이 비어 있거나 없습니다. "
            "먼저 'python auth_setup.py' 로 수동 인증을 마쳐 주세요."
        )


async def _launch_persistent_context(
    pw,
    headless: bool,
    slow_mo: int = 0,
) -> BrowserContext:
    """
    auth_setup.py 가 만들어 둔 ./auth_session 을 그대로 사용해 영구 컨텍스트를 띄운다.
    수동으로 통과시킨 캡차/로그인 쿠키와 신뢰도를 그대로 상속받는다.
    """
    _ensure_auth_session()

    context = await pw.chromium.launch_persistent_context(
        user_data_dir=str(AUTH_SESSION_DIR),
        channel="chrome",            # 설치된 실제 Google Chrome 사용 (auth_setup 과 동일)
        headless=headless,
        slow_mo=slow_mo,
        args=[
            "--disable-blink-features=AutomationControlled",
            "--no-default-browser-check",
            "--no-first-run",
        ],
        ignore_default_args=["--enable-automation"],
        locale="ko-KR",
        timezone_id="Asia/Seoul",
        no_viewport=True,
    )
    return context


# ---------------------------------------------------------------------------
# Page helpers
# ---------------------------------------------------------------------------

async def _navigate_safe(page: Page, url: str, timeout: int = 40_000) -> bool:
    """
    Navigate and return True on success, False on timeout/error.
    'load' 이벤트까지 기다린 뒤 networkidle 까지 짧게 대기한다.
    """
    try:
        await page.goto(url, wait_until="load", timeout=timeout)
        try:
            await page.wait_for_load_state("networkidle", timeout=5_000)
        except PWTimeout:
            pass  # networkidle 미달성은 허용 — 이미 'load' 는 완료됨
        await page.wait_for_timeout(random.randint(1_500, 2_500))
        return True
    except PWTimeout:
        log.warning("Navigation timed out: %s", url)
        return False
    except PWError as e:
        log.warning("Navigation error (%s): %s", url, e)
        return False


async def _warm_up(page: Page, home_url: str) -> None:
    """검색 URL 로 콜드 진입 시 차단되는 케이스 방지를 위해 메인 페이지를 먼저 들름."""
    try:
        log.info("쿠키 워밍 중: %s", home_url)
        await page.goto(home_url, wait_until="load", timeout=30_000)
        await page.wait_for_timeout(random.randint(2_000, 3_500))
        log.info("쿠키 워밍 완료 — title: %r", await page.title())
    except Exception as e:
        log.debug("워밍 실패(무시): %s", e)


async def _smooth_scroll(
    page: Page,
    steps: int = 10,
    pause_ms: int = 350,
) -> int:
    """
    페이지를 점진적으로 내리며 지연 로딩(lazy loading) 컨텐츠 렌더링을 유도한다.

    한 번에 끝까지 점프하지 않고 step 단위로 내려가며 매번 pause_ms 동안 쉰다.
    스크롤이 끝나면 마지막 documentScrollHeight 를 반환한다(디버깅·재시도 판단용).
    """
    last_height: int = 0
    try:
        last_height = await page.evaluate("() => document.body.scrollHeight") or 0
    except Exception:
        last_height = 6_000

    for i in range(1, steps + 1):
        try:
            target = int(last_height * (i / steps))
            await page.evaluate(
                "(y) => window.scrollTo({top: y, behavior: 'smooth'})", target
            )
        except Exception as e:
            log.debug("스크롤 step %d 실패(무시): %s", i, e)
        await page.wait_for_timeout(pause_ms + random.randint(80, 220))

        # 페이지가 늘어났는지 확인 — 새로 로딩된 콘텐츠가 있으면 height 갱신
        try:
            new_height = await page.evaluate("() => document.body.scrollHeight") or last_height
            if new_height > last_height:
                last_height = new_height
        except Exception:
            pass

    # 마지막에 확실히 맨 아래로
    try:
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    except Exception:
        pass
    await page.wait_for_timeout(700)

    # 추출 단계에서 viewport 기반 lazy load 가 다시 동작할 수도 있어 맨 위로 복귀
    try:
        await page.evaluate("window.scrollTo({top: 0, behavior: 'auto'})")
    except Exception:
        pass
    await page.wait_for_timeout(300)

    return last_height


# ---------------------------------------------------------------------------
# Naver Shopping extractor
# ---------------------------------------------------------------------------

async def _extract_naver_items(page: Page) -> list[dict]:
    """
    DOM 순서가 보존된 [{"id": str, "name": str}, ...] 를 반환.

    이전 _extract_naver_ids 의 상위호환 — id 와 함께 상품명을 같이 수집한다.
    name 추출 실패 시 빈 문자열을 채워 호출자가 폴백 처리하도록 한다.
    """
    items: list[dict] = []

    # Strategy 1: scoped JS evaluate
    try:
        raw: list[dict] = await page.evaluate("""
            () => {
                const container =
                    document.querySelector('[class*="product_list"]')  ||
                    document.querySelector('[class*="ProductList"]')   ||
                    document.querySelector('[class*="search_result"]') ||
                    document.querySelector('main')                     ||
                    document.body;

                // catalog 링크 우선 — 없으면 nvMid/productId 가 박힌 일반 링크 폴백
                let anchors = Array.from(container.querySelectorAll('a[href*="catalog/"]'));
                if (anchors.length === 0) {
                    anchors = Array.from(container.querySelectorAll('a[href]'))
                        .filter(a =>
                            a.href.includes('nvMid=')     ||
                            a.href.includes('productId=') ||
                            a.href.includes('smartstore.naver.com/') ||
                            a.href.includes('search.shopping.naver.com/')
                        );
                }

                const findTitle = (anchor) => {
                    // 1) 카드 컨테이너 위쪽에서 제목 후보 셀렉터 탐색
                    const card =
                        anchor.closest('li[class*="product"]') ||
                        anchor.closest('div[class*="product"]') ||
                        anchor.closest('li') ||
                        anchor.parentElement;
                    if (card) {
                        const titleEl =
                            card.querySelector('[class*="product_title"]') ||
                            card.querySelector('[class*="productTitle"]')  ||
                            card.querySelector('[class*="title"]')         ||
                            card.querySelector('[class*="name"]')          ||
                            card.querySelector('strong');
                        if (titleEl && titleEl.textContent) {
                            return titleEl.textContent.trim();
                        }
                    }
                    // 2) anchor 자체 텍스트 폴백
                    const txt = (anchor.textContent || '').trim();
                    return txt;
                };

                return anchors.map(a => ({ href: a.href, name: findTitle(a) }));
            }
        """)
        log.debug("[Naver] JS raw anchors count: %d", len(raw))
        for entry in raw:
            href = entry.get("href") or ""
            name = (entry.get("name") or "").strip()
            for pat in _NAVER_ID_PATTERNS:
                m = pat.search(href)
                if m:
                    items.append({"id": m.group(1), "name": name})
                    break
        items = _dedupe_items(items)
        if items:
            log.debug("[Naver] JS strategy: %d items — sample: %s",
                      len(items), [(i["id"], i["name"][:20]) for i in items[:5]])
            return items
        log.debug("[Naver] JS strategy returned 0 items (anchors found: %d)", len(raw))
    except Exception as e:
        log.debug("[Naver] JS strategy exception: %s", e)

    # Strategy 2: regex on raw HTML — ID 만 복구 (이름은 빈 문자열)
    try:
        html = await page.content()
        log.debug("[Naver] HTML length: %d chars", len(html))
        ids: list[str] = []
        for pat in _NAVER_ID_PATTERNS:
            ids.extend(pat.findall(html))
        seen: set[str] = set()
        for pid in ids:
            if pid and pid not in seen:
                seen.add(pid)
                items.append({"id": pid, "name": ""})
        if items:
            log.debug("[Naver] HTML regex strategy: %d items", len(items))
        else:
            log.debug("[Naver] HTML regex strategy also returned 0 items")
    except Exception as e:
        log.debug("[Naver] HTML strategy exception: %s", e)

    return items


# ---------------------------------------------------------------------------
# Coupang extractor
# ---------------------------------------------------------------------------

async def _extract_coupang_items(page: Page) -> list[dict]:
    """
    DOM 순서가 보존된 [{"id": str, "name": str}, ...] 를 반환.
    """
    items: list[dict] = []

    # Strategy 1: scoped JS evaluate — 셀렉터 후보를 폭넓게 잡고 DOM 순서를 보존
    try:
        raw: list[dict] = await page.evaluate("""
            () => {
                const containerSelectors = [
                    '#productList',
                    'ul#productList',
                    'ul.search-product-list',
                    'ul[class*="search-product-list"]',
                    'ul[class*="searchProductList"]',
                    'div[class*="ProductList"]',
                    'div[class*="product-list"]',
                    'main',
                ];
                let listEl = null;
                for (const s of containerSelectors) {
                    const el = document.querySelector(s);
                    if (el) { listEl = el; break; }
                }
                if (!listEl) listEl = document.body;

                const findName = (el) => {
                    const titleEl =
                        el.querySelector('[class*="name"]')        ||
                        el.querySelector('[class*="title"]')       ||
                        el.querySelector('[class*="productName"]') ||
                        el.querySelector('div.name')               ||
                        el.querySelector('strong')                 ||
                        el.querySelector('a');
                    return (titleEl && titleEl.textContent) ? titleEl.textContent.trim() : '';
                };

                // 1) data-product-id 속성 보유 컨테이너
                let nodes = Array.from(listEl.querySelectorAll('[data-product-id]'));
                if (nodes.length) {
                    return nodes.map(el => ({
                        id: el.getAttribute('data-product-id') || '',
                        name: findName(el),
                    })).filter(x => x.id);
                }

                // 2) data-vendor-item-id 폴백
                nodes = Array.from(listEl.querySelectorAll('[data-vendor-item-id]'));
                if (nodes.length) {
                    return nodes.map(el => ({
                        id: el.getAttribute('data-vendor-item-id') || '',
                        name: findName(el),
                    })).filter(x => x.id);
                }

                // 3) /vp/products/<id> 링크 — DOM 순서 그대로 수집
                return Array.from(
                    listEl.querySelectorAll('a[href*="/vp/products/"]')
                ).map(a => {
                    const m = a.href.match(/\\/vp\\/products\\/(\\d+)/);
                    if (!m) return null;
                    const card = a.closest('li') || a.parentElement;
                    return {
                        id: m[1],
                        name: card ? findName(card) : (a.textContent || '').trim(),
                    };
                }).filter(Boolean);
            }
        """)
        log.debug("[Coupang] JS raw items count: %d", len(raw))
        for entry in raw:
            pid = (entry.get("id") or "").strip()
            if not pid:
                continue
            items.append({"id": pid, "name": (entry.get("name") or "").strip()})
        items = _dedupe_items(items)
        if items:
            log.debug("[Coupang] JS strategy: %d items — sample: %s",
                      len(items), [(i["id"], i["name"][:20]) for i in items[:5]])
            return items
        log.debug("[Coupang] JS strategy returned 0 items")
    except Exception as e:
        log.debug("[Coupang] JS strategy exception: %s", e)

    # Strategy 2: regex on raw HTML — ID 만 복구 (이름은 빈 문자열)
    try:
        html = await page.content()
        log.debug("[Coupang] HTML length: %d chars", len(html))
        ids: list[str] = []
        for pat in _COUPANG_ID_PATTERNS:
            ids.extend(pat.findall(html))
        seen: set[str] = set()
        for pid in ids:
            if pid and pid not in seen:
                seen.add(pid)
                items.append({"id": pid, "name": ""})
        if items:
            log.debug("[Coupang] HTML regex strategy: %d items", len(items))
        else:
            log.debug("[Coupang] HTML regex strategy also returned 0 items")
    except Exception as e:
        log.debug("[Coupang] HTML strategy exception: %s", e)

    return items


# ---------------------------------------------------------------------------
# Per-platform rank search
# ---------------------------------------------------------------------------

def _id_matches(target_id: str, candidate_id: str) -> bool:
    """Exact match OR one contains the other (handles 0-padded variants)."""
    t, c = target_id.strip(), candidate_id.strip()
    return t == c or t in c or c in t


async def _diagnose_page(page: Page, platform: str, page_num: int) -> None:
    """추출 실패 시 진단 정보 로깅 + 스크린샷 저장."""
    try:
        title   = await page.title()
        url     = page.url
        html    = await page.content()
        snippet = html[:1500].replace("\n", " ")

        log.warning(
            "[%s] ── 진단 정보 (page %d) ──\n"
            "  URL   : %s\n"
            "  Title : %s\n"
            "  본문에 captcha=%s  robot=%s  blocked=%s\n"
            "  HTML 앞 1500자: %s",
            platform.upper(), page_num,
            url, title,
            "captcha" in html.lower(),
            "robot"   in html.lower(),
            "blocked" in html.lower(),
            snippet,
        )

        ss_dir = pathlib.Path(__file__).parent / "debug_screenshots"
        ss_dir.mkdir(exist_ok=True)
        fname = ss_dir / f"{platform}_p{page_num}_{_dt.now().strftime('%H%M%S')}.png"
        await page.screenshot(path=str(fname), full_page=False)
        log.warning("[%s] 스크린샷 저장: %s", platform.upper(), fname)
    except Exception as e:
        log.debug("진단 중 오류: %s", e)


async def _search_naver(
    context: BrowserContext,
    keyword: str,
    target_id: str,
    max_pages: int,
) -> tuple[int, Optional[int], list[dict]]:
    """
    Returns (rank, page_num, top5).
    top5: [{"rank": int, "name": str, "target_id": str}] — 1페이지 첫 5개 (실패 시 [])
    """
    page = await context.new_page()
    global_rank = 0
    top5: list[dict] = []
    found_rank: int = 0
    found_page: Optional[int] = None

    # 쿠키 워밍 — auth_session 의 쿠키가 갱신되도록 메인 먼저 방문
    await _warm_up(page, "https://shopping.naver.com/")

    try:
        for page_num in range(1, max_pages + 1):
            url = NAVER_SEARCH_URL.format(query=quote(keyword), page=page_num)
            log.info("[Naver] keyword=%r  page=%d  URL: %s", keyword, page_num, url)

            if not await _navigate_safe(page, url):
                break

            # 상품 목록 렌더링 대기 — 여러 셀렉터 순차 시도
            waited = False
            for sel in (
                "li[class*='product']",
                "ul[class*='product']",
                "div[class*='product_list']",
                "a[href*='catalog/']",
                "main",
            ):
                try:
                    await page.wait_for_selector(sel, timeout=6_000)
                    log.debug("[Naver] 셀렉터 감지됨: %r", sel)
                    waited = True
                    break
                except PWTimeout:
                    continue

            if not waited:
                log.warning("[Naver] 상품 목록 셀렉터를 찾지 못함 — 추가 3초 대기")
                await page.wait_for_timeout(3_000)

            items = await _extract_naver_items(page)

            if not items:
                log.warning("[Naver] page %d: 상품 ID 추출 실패 (0건)", page_num)
                await _diagnose_page(page, "naver", page_num)
                break

            # 1페이지 첫 5개를 경쟁사 스냅샷으로 저장
            if page_num == 1 and not top5:
                top5 = [
                    {
                        "rank": idx + 1,
                        "name": it.get("name") or "(이름없음)",
                        "target_id": it.get("id") or "",
                    }
                    for idx, it in enumerate(items[:5])
                ]
                log.info("[Naver] Top5 수집: %s", [(t["rank"], t["name"][:20]) for t in top5])

            log.info("[Naver] page %d: %d개 상품 추출 — 앞 5개: %s",
                     page_num, len(items), [i["id"] for i in items[:5]])

            for local_idx, item in enumerate(items, start=1):
                global_rank += 1
                if found_rank == 0 and _id_matches(target_id, item["id"]):
                    log.info(
                        "[Naver] ★ FOUND target_id=%r → rank=%d (page %d, local #%d)",
                        target_id, global_rank, page_num, local_idx,
                    )
                    found_rank, found_page = global_rank, page_num

            # 1페이지를 처리한 뒤 이미 발견했고 top5 도 확보했으면 조기 종료
            if found_rank and top5:
                return found_rank, found_page, top5

            await page.wait_for_timeout(random.randint(1_000, 2_000))

    except Exception as e:
        log.error("[Naver] 처리되지 않은 예외: %s", e, exc_info=True)
    finally:
        await page.close()

    if found_rank:
        return found_rank, found_page, top5
    log.info("[Naver] target_id=%r — %d페이지 내 미발견", target_id, max_pages)
    return 0, None, top5


async def _search_coupang(
    context: BrowserContext,
    keyword: str,
    target_id: str,
    max_pages: int,
) -> tuple[int, Optional[int], list[dict]]:
    """
    Returns (rank, page_num, top5).
    top5: [{"rank": int, "name": str, "target_id": str}]
    """
    page = await context.new_page()
    global_rank = 0
    top5: list[dict] = []
    found_rank: int = 0
    found_page: Optional[int] = None

    await _warm_up(page, "https://www.coupang.com/")

    # 모든 알려진 상품 셀렉터를 콤마로 합쳐 한 번에 OR 검사 — 어느 하나라도
    # 등장하면 wait_for_selector 가 통과한다.
    selector_union = ", ".join(_COUPANG_PRODUCT_SELECTORS)

    try:
        for page_num in range(1, max_pages + 1):
            url = COUPANG_SEARCH_URL.format(query=quote(keyword), page=page_num)
            log.info("[Coupang] keyword=%r  page=%d  URL: %s", keyword, page_num, url)

            if not await _navigate_safe(page, url):
                break

            # (1) networkidle 까지 더 길게 대기 — 2페이지 이후 비동기 로딩이 더 느림
            try:
                await page.wait_for_load_state("networkidle", timeout=15_000)
            except PWTimeout:
                log.debug("[Coupang] networkidle 15s 미달성 — 계속 진행")

            # (2) 다중 셀렉터 OR 로 상품 컨테이너 하나라도 나타날 때까지 대기
            try:
                await page.wait_for_selector(selector_union, timeout=15_000)
                log.debug("[Coupang] 상품 셀렉터 감지됨 (union)")
            except PWTimeout:
                log.warning("[Coupang] 다중 셀렉터 15s 대기 후에도 미감지 — 스크롤 시도")

            # (3) 점진적 스크롤 — 지연 로딩 컨텐츠를 모두 렌더링시킨다
            scroll_height = await _smooth_scroll(page, steps=10, pause_ms=350)
            log.debug("[Coupang] 스크롤 완료 — 최종 height=%d", scroll_height)

            # (4) 스크롤 후 마지막 안정화 — 새로 로딩된 콘텐츠가 DOM 에 붙을 시간 확보
            try:
                await page.wait_for_load_state("networkidle", timeout=8_000)
            except PWTimeout:
                pass
            await page.wait_for_timeout(random.randint(1_200, 2_000))

            items = await _extract_coupang_items(page)

            if not items:
                log.warning("[Coupang] page %d: 상품 추출 실패 (0건) — 한 번 더 스크롤+재시도", page_num)
                await _smooth_scroll(page, steps=8, pause_ms=450)
                await page.wait_for_timeout(2_000)
                items = await _extract_coupang_items(page)

            if not items:
                log.warning("[Coupang] page %d: 재시도 후에도 0건 — 진단 로그 저장", page_num)
                await _diagnose_page(page, "coupang", page_num)
                break

            if page_num == 1 and not top5:
                top5 = [
                    {
                        "rank": idx + 1,
                        "name": it.get("name") or "(이름없음)",
                        "target_id": it.get("id") or "",
                    }
                    for idx, it in enumerate(items[:5])
                ]
                log.info("[Coupang] Top5 수집: %s", [(t["rank"], t["name"][:20]) for t in top5])

            log.info("[Coupang] page %d: %d개 상품 추출 — 앞 5개: %s",
                     page_num, len(items), [i["id"] for i in items[:5]])

            for local_idx, item in enumerate(items, start=1):
                global_rank += 1
                if found_rank == 0 and _id_matches(target_id, item["id"]):
                    log.info(
                        "[Coupang] ★ FOUND target_id=%r → rank=%d (page %d, local #%d)",
                        target_id, global_rank, page_num, local_idx,
                    )
                    found_rank, found_page = global_rank, page_num

            if found_rank and top5:
                return found_rank, found_page, top5

            await page.wait_for_timeout(random.randint(1_500, 2_500))

    except Exception as e:
        log.error("[Coupang] 처리되지 않은 예외: %s", e, exc_info=True)
    finally:
        await page.close()

    if found_rank:
        return found_rank, found_page, top5
    log.info("[Coupang] target_id=%r — %d페이지 내 미발견", target_id, max_pages)
    return 0, None, top5


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def get_rank(
    platform: str,
    keyword: str,
    target_id: str,
    max_pages: int = DEFAULT_MAX_PAGES,
    headless: bool = True,
    slow_mo: int = 0,
) -> RankResult:
    """
    Search `keyword` on `platform` and return the rank of `target_id`.

    auth_session 디렉터리(사용자가 미리 수동 인증해 둔 세션) 가 필요하다.
    """
    platform = platform.lower()
    if platform not in ("naver", "coupang"):
        raise ValueError(f"platform must be 'naver' or 'coupang', got: {platform!r}")

    async with async_playwright() as pw:
        context = await _launch_persistent_context(pw, headless=headless, slow_mo=slow_mo)
        try:
            if platform == "naver":
                rank, page_num, top5 = await _search_naver(context, keyword, target_id, max_pages)
            else:
                rank, page_num, top5 = await _search_coupang(context, keyword, target_id, max_pages)
        finally:
            await context.close()

    return RankResult(
        rank=rank,
        page=page_num,
        keyword=keyword,
        platform=platform,
        target_id=target_id,
        top5=top5,
    )


async def get_all_ranks(
    products: list[dict],
    max_pages: int = DEFAULT_MAX_PAGES,
    headless: bool = True,
) -> list[RankResult]:
    """
    여러 상품의 순위를 한 번의 브라우저 세션으로 순차 처리.

    Why 순차 실행:
        auth_session 디렉터리는 동시에 두 프로세스가 잠글 수 없어 BrowserContext 는
        반드시 하나만 띄워야 한다. 과거에는 같은 컨텍스트 안에서 네이버/쿠팡 두 작업을
        asyncio.gather 로 병렬 처리했는데, 한쪽 _search_*() 가 끝나며 finally 절에서
        page.close() 를 호출할 때 다른쪽의 in-flight 호출이 'Target page, context or
        browser has been closed' 로 죽는 사례가 재현되었다. 같은 컨텍스트의 페이지
        라이프사이클이 서로 영향을 주는 구조라 안전한 직렬 실행으로 전환한다.
    """
    naver_items   = [p for p in products if p["platform"].lower() == "naver"]
    coupang_items = [p for p in products if p["platform"].lower() == "coupang"]

    async def _run_platform_in_ctx(
        items: list[dict],
        platform: str,
        ctx: BrowserContext,
    ) -> list[RankResult]:
        results: list[RankResult] = []
        for item in items:
            if platform == "naver":
                rank, pg, top5 = await _search_naver(
                    ctx, item["keyword"], item["target_id"], max_pages
                )
            else:
                rank, pg, top5 = await _search_coupang(
                    ctx, item["keyword"], item["target_id"], max_pages
                )
            results.append(
                RankResult(
                    rank=rank,
                    page=pg,
                    keyword=item["keyword"],
                    platform=platform,
                    target_id=item["target_id"],
                    top5=top5,
                )
            )
            await asyncio.sleep(random.uniform(2.0, 4.0))
        return results

    async with async_playwright() as pw:
        context = await _launch_persistent_context(pw, headless=headless)
        try:
            # 순차 실행 — 네이버 먼저(빠름) → 플랫폼 간 휴식 → 쿠팡(느림) 순.
            log.info("[get_all_ranks] 네이버 %d건 시작", len(naver_items))
            naver_res = await _run_platform_in_ctx(naver_items, "naver", context)

            if naver_items and coupang_items:
                # 플랫폼 전환 시 짧은 휴식 — 동일 IP 에서 연속 검색 패턴을 완화
                pause = random.uniform(3.0, 6.0)
                log.info("[get_all_ranks] 플랫폼 전환 휴식 %.1fs", pause)
                await asyncio.sleep(pause)

            log.info("[get_all_ranks] 쿠팡 %d건 시작", len(coupang_items))
            coupang_res = await _run_platform_in_ctx(coupang_items, "coupang", context)
        finally:
            await context.close()

    return naver_res + coupang_res


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _dedupe_ordered(seq: list[str]) -> list[str]:
    """Remove duplicates preserving insertion order."""
    seen: set[str] = set()
    out: list[str] = []
    for x in seq:
        if x and x not in seen:
            seen.add(x)
            out.append(x)
    return out


def _dedupe_items(seq: list[dict]) -> list[dict]:
    """id 기준으로 중복 제거, 순서 보존."""
    seen: set[str] = set()
    out: list[dict] = []
    for item in seq:
        pid = (item.get("id") or "").strip()
        if pid and pid not in seen:
            seen.add(pid)
            out.append({"id": pid, "name": (item.get("name") or "").strip()})
    return out


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="순위 스크래퍼 — 단일 상품 순위를 즉시 조회합니다.\n"
                    "전제: 'python auth_setup.py' 로 사전 인증을 마쳐 ./auth_session 이 있어야 합니다.",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument("platform",  choices=["naver", "coupang"], help="검색 플랫폼")
    parser.add_argument("keyword",   help="검색 키워드 (예: '고체치약')")
    parser.add_argument("target_id", help="타겟 상품 ID (예: 10839806076)")
    parser.add_argument("--pages",   type=int, default=DEFAULT_MAX_PAGES,
                        help=f"최대 탐색 페이지 수 (기본: {DEFAULT_MAX_PAGES})")
    parser.add_argument("--show",    action="store_true",
                        help="브라우저 창 표시 (headless=False, 로컬 PC 전용)")
    parser.add_argument("--debug",   action="store_true",
                        help="DEBUG 레벨 로그 출력 (파싱 실패 분석용)")
    args = parser.parse_args()

    log_level = logging.DEBUG if args.debug else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )
    for _noisy in ("playwright", "websockets", "asyncio"):
        logging.getLogger(_noisy).setLevel(logging.WARNING)

    PLATFORM_KR = {"naver": "네이버", "coupang": "쿠팡"}
    pk = PLATFORM_KR[args.platform]

    print(f"\n{'═'*55}")
    print(f"  플랫폼  : {pk} ({args.platform.upper()})")
    print(f"  키워드  : {args.keyword!r}")
    print(f"  타겟ID  : {args.target_id}")
    print(f"  최대페이지: {args.pages}   headless={not args.show}")
    print(f"{'═'*55}")

    try:
        result = asyncio.run(
            get_rank(
                platform  = args.platform,
                keyword   = args.keyword,
                target_id = args.target_id,
                max_pages = args.pages,
                headless  = not args.show,
                slow_mo   = 200 if args.show else 0,
            )
        )
    except AuthSessionMissingError as e:
        print(f"\n❌ {e}\n")
        sys.exit(1)

    print(f"\n{'═'*55}")
    if result.rank == 0:
        print(f"  ❌ {pk} | {args.keyword!r} | ID {args.target_id}")
        print(f"     → 미노출 ({args.pages}페이지 내 미발견)")
        print(f"     → debug_screenshots/ 폴더의 스크린샷을 확인하세요.")
    else:
        print(f"  ✅ {pk} | {args.keyword!r} | ID {args.target_id}")
        print(f"     → {result.rank}위  (검색결과 {result.page}페이지)")
    print(f"{'═'*55}\n")
