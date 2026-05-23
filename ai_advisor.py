"""
ai_advisor.py — 'AI 전략 분석' 엔진 (Beta) · 경쟁사 비교 기반 초정밀 분석.

대시보드 [네이버/쿠팡 전략] 카드의 'AI 전략 분석' 섹션에 표시할
[분석 결과] · [경쟁 지표 비교] · [권장 액션플랜] 을 생성한다.

핵심 — 경쟁사 데이터 기반 분석
------------------------------
scraper.py 가 수집한 Top5 경쟁사의 가격·리뷰수·평점·썸네일 지표와, 내 상품의
노출가·리뷰수를 비교해 "경쟁사 평균가 15,000원 대비 당사 18,000원(+20%),
리뷰는 평균 1,200개 대비 340개" 같은 구체적 수치 기반 액션플랜을 도출한다.
경쟁사 데이터가 없으면 순위/등락 기반 분석으로 자연스럽게 폴백한다.

이후 LLM API 연동
-----------------
analyze_product() → _analyze_with_rules() 가 현재 기본 엔진이다. LLM 연동 시:
  1. _build_prompt() 로 동일 입력(경쟁사 데이터 포함)을 프롬프트로 직렬화
  2. _analyze_with_llm() 안에서 LLM 호출 → JSON 응답 파싱
  3. analyze_product() 분기에서 그 결과를 사용
반환 타입(AIAnalysis)·시그니처는 그대로라 대시보드 코드는 수정 불필요.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Optional

# database.py 의 RANK_STATUS_* 와 동일한 문자열 규약
STATUS_OK        = "ok"
STATUS_NOT_FOUND = "not_found"
STATUS_BLOCKED   = "blocked"
STATUS_ERROR     = "error"

PLATFORM_KR = {"naver": "네이버", "coupang": "쿠팡"}


# ---------------------------------------------------------------------------
# 반환 타입
# ---------------------------------------------------------------------------

@dataclass
class AIAnalysis:
    """AI 전략 분석 결과 — 대시보드 카드의 'AI 전략 분석' 섹션에 매핑된다."""
    summary: str                       # [분석 결과] 본문
    action_plan: list[str]             # [권장 액션플랜] 항목 (우선순위 순)
    tone: str = "neutral"              # good | warn | bad | neutral — UI 색상 힌트
    metrics: dict = field(default_factory=dict)   # 경쟁 비교 수치 (대시보드 표시용)
    generated_by: str = "rule-based"   # 향후 "llm" 으로 교체

    def __post_init__(self):
        if self.action_plan is None:
            self.action_plan = []
        if self.metrics is None:
            self.metrics = {}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def analyze_product(
    *,
    name: str,
    platform: str,
    keyword: str,
    rank: int,
    delta: Optional[int],
    status: str = STATUS_OK,
    my_price: Optional[int] = None,
    my_review_count: Optional[int] = None,
    competitors: Optional[list] = None,
    history: Optional[list] = None,
) -> AIAnalysis:
    """한 상품의 순위·경쟁 상황을 분석해 AIAnalysis 를 반환한다.

    Parameters
    ----------
    name, platform, keyword : 상품 식별 정보
    rank                    : 현재 순위 (0 = 미노출)
    delta                   : 전일 대비 등락 (+상승 / -하락 / 0 유지 / None)
    status                  : 스크래핑 상태 (ok | not_found | blocked | error)
    my_price                : 내 상품 노출가 (원)
    my_review_count         : 내 상품 리뷰 수
    competitors             : Top5 경쟁사 [{rank, name, price, review_count,
                              rating, has_thumbnail, target_id}, ...]
    history                 : 순위 이력 (옵션, LLM 프롬프트용)
    """
    if os.getenv("USE_LLM_ADVISOR", "").lower() in ("1", "true", "yes"):
        try:
            return _analyze_with_llm(
                name=name, platform=platform, keyword=keyword, rank=rank,
                delta=delta, status=status, my_price=my_price,
                my_review_count=my_review_count, competitors=competitors,
                history=history,
            )
        except NotImplementedError:
            pass  # LLM 미구현 — 규칙 기반으로 폴백

    metrics = _compute_metrics(competitors or [], my_price, my_review_count)
    return _analyze_with_rules(
        name=name, platform=platform, keyword=keyword, rank=rank,
        delta=delta, status=status, metrics=metrics,
    )


# ---------------------------------------------------------------------------
# 경쟁 지표 계산
# ---------------------------------------------------------------------------

def _avg(nums: list) -> Optional[float]:
    vals = [n for n in nums if n is not None]
    return sum(vals) / len(vals) if vals else None


def _compute_metrics(
    competitors: list,
    my_price: Optional[int],
    my_review_count: Optional[int],
) -> dict:
    """Top5 경쟁사 vs 당사 비교 수치를 계산한다."""
    prices  = [c.get("price") for c in competitors if c.get("price")]
    reviews = [c.get("review_count") for c in competitors if c.get("review_count")]
    ratings = [c.get("rating") for c in competitors if c.get("rating")]
    thumbs  = [c.get("has_thumbnail") for c in competitors
               if c.get("has_thumbnail") is not None]

    comp_avg_price   = _avg(prices)
    comp_avg_reviews = _avg(reviews)
    comp_avg_rating  = _avg(ratings)

    price_gap = price_gap_pct = None
    if my_price and comp_avg_price:
        price_gap = my_price - comp_avg_price
        price_gap_pct = (price_gap / comp_avg_price) * 100.0

    review_gap = None
    if my_review_count is not None and comp_avg_reviews is not None:
        review_gap = my_review_count - comp_avg_reviews

    return {
        "my_price":          my_price,
        "my_reviews":        my_review_count,
        "comp_avg_price":    int(comp_avg_price) if comp_avg_price else None,
        "comp_min_price":    min(prices) if prices else None,
        "comp_max_price":    max(prices) if prices else None,
        "comp_avg_reviews":  int(comp_avg_reviews) if comp_avg_reviews else None,
        "comp_max_reviews":  max(reviews) if reviews else None,
        "comp_avg_rating":   round(comp_avg_rating, 1) if comp_avg_rating else None,
        "price_gap":         int(price_gap) if price_gap is not None else None,
        "price_gap_pct":     round(price_gap_pct, 1) if price_gap_pct is not None else None,
        "review_gap":        int(review_gap) if review_gap is not None else None,
        "thumb_coverage":    (sum(1 for t in thumbs if t) / len(thumbs)) if thumbs else None,
        "comp_count":        len(competitors),
        "has_price_data":    bool(prices),
        "has_review_data":   bool(reviews),
    }


# ---------------------------------------------------------------------------
# 규칙 기반 엔진 (현행 기본값) — 경쟁사 데이터가 있으면 초정밀 분석
# ---------------------------------------------------------------------------

def _won(n) -> str:
    return f"{int(n):,}원" if n is not None else "—"


def _analyze_with_rules(
    *,
    name: str,
    platform: str,
    keyword: str,
    rank: int,
    delta: Optional[int],
    status: str,
    metrics: dict,
) -> AIAnalysis:
    platform_kr = PLATFORM_KR.get(platform, platform)
    is_naver = platform == "naver"

    # ── 1) 스크래핑 실패 — 순위·경쟁 분석 불가 ───────────────────────────
    if status == STATUS_BLOCKED:
        return AIAnalysis(
            summary=(
                f"{platform_kr}가 차단·캡차 페이지를 반환해 '{keyword}' 키워드의 "
                "순위·경쟁사 데이터를 수집하지 못했습니다. 표시 지표는 신뢰할 수 없습니다."
            ),
            action_plan=[
                "auth_session 재인증 — `python auth_setup.py` 재실행",
                "스크래핑 주기를 분산해 봇 탐지 신호 완화 (차단 재시도 자동 동작 중)",
                "차단 지속 시 프록시 IP 교체 검토",
            ],
            tone="bad", metrics=metrics,
        )
    if status == STATUS_ERROR:
        return AIAnalysis(
            summary=(
                f"스크래퍼 오류로 '{keyword}' 키워드의 순위·경쟁 데이터 수집에 "
                "실패했습니다. 페이지 구조 변경 또는 네트워크 문제를 점검하세요."
            ),
            action_plan=[
                "debug_screenshots/ 의 진단 스크린샷 확인",
                "스크래퍼 셀렉터(상품 컨테이너) 최신화 검토",
            ],
            tone="bad", metrics=metrics,
        )

    # ── 경쟁 지표 인사이트 조립 ──────────────────────────────────────────
    insights: list[str] = []     # summary 에 들어갈 데이터 문장
    actions:  list[str] = []     # 액션플랜 후보 (우선순위 순으로 추가)
    has_comp = metrics.get("has_price_data") or metrics.get("has_review_data")

    avg_price = metrics.get("comp_avg_price")
    my_price  = metrics.get("my_price")
    gap       = metrics.get("price_gap")
    gap_pct   = metrics.get("price_gap_pct")

    if avg_price and my_price and gap is not None:
        if gap > 0 and gap_pct >= 5:
            insights.append(
                f"경쟁사 Top5 평균가 {_won(avg_price)} 대비 당사 {_won(my_price)}으로 "
                f"{_won(gap)}({gap_pct:.0f}%) 비쌉니다"
            )
            actions.append(
                f"가격 재검토 — 경쟁사 평균 {_won(avg_price)} 수준까지 인하하거나, "
                f"묶음구성·사은품으로 {_won(gap)} 격차의 가치를 상세페이지에서 정당화"
            )
        elif gap < 0 and abs(gap_pct) >= 5:
            insights.append(
                f"경쟁사 평균가 {_won(avg_price)} 대비 당사 {_won(my_price)}으로 "
                f"{_won(abs(gap))} 저렴해 가격 경쟁력은 확보된 상태입니다"
            )
            actions.append(
                "가격 우위를 살려 썸네일·타이틀에 '최저가/가성비' 소구 문구를 노출"
            )
        else:
            insights.append(
                f"가격은 경쟁사 평균({_won(avg_price)})과 대등한 수준입니다"
            )
    elif avg_price and not my_price:
        insights.append(
            f"경쟁사 Top5 평균가는 {_won(avg_price)}입니다 (당사 노출가 미수집)"
        )

    avg_rv = metrics.get("comp_avg_reviews")
    my_rv  = metrics.get("my_reviews")
    rv_gap = metrics.get("review_gap")
    if avg_rv is not None and my_rv is not None and rv_gap is not None:
        if rv_gap < 0 and avg_rv > 0:
            shortfall = abs(rv_gap)
            insights.append(
                f"리뷰는 경쟁사 평균 {avg_rv:,}개 대비 당사 {my_rv:,}개로 "
                f"{shortfall:,}개 부족합니다"
            )
            actions.append(
                f"리뷰 부스팅 시급 — 리뷰 이벤트·체험단으로 최소 {shortfall:,}개 확보해 "
                "경쟁사 평균 수준까지 신뢰도 격차 해소"
            )
        elif rv_gap > 0:
            insights.append(
                f"리뷰는 경쟁사 평균 {avg_rv:,}개 대비 당사 {my_rv:,}개로 우위입니다"
            )
            actions.append("리뷰 우위를 상세페이지 상단·썸네일에 수치로 강조해 전환율 제고")
    elif avg_rv is not None and my_rv is None:
        insights.append(f"경쟁사 평균 리뷰는 {avg_rv:,}개입니다 (당사 리뷰 미수집)")

    # ── 2) 미노출 — 검색 상위에 없음 ─────────────────────────────────────
    if rank == 0 or status == STATUS_NOT_FOUND:
        seo = ("타이틀 앞단에 '" + keyword + "' 키워드를 전면 배치하고 "
               "태그·카테고리 적합도를 재정비"
               if is_naver else
               "상품명·카테고리 매칭을 '" + keyword + "' 기준으로 재정비")
        plan = [seo + " — 노출 진입이 최우선 과제"]
        plan += actions[:2]
        plan.append("리뷰·구매 지표 단기 부스팅으로 랭킹 진입 모멘텀 확보")
        comp_txt = (" " + ". ".join(insights) + ".") if insights else ""
        return AIAnalysis(
            summary=(
                f"'{keyword}' 검색 상위 노출에서 벗어나 있어 유입이 발생하지 않는 "
                f"상태입니다.{comp_txt} 노출 확보가 가장 시급한 과제입니다."
            ),
            action_plan=plan[:4], tone="bad", metrics=metrics,
        )

    # ── 3) 노출 중 — 순위 + 경쟁 지표 종합 ───────────────────────────────
    # 등락 문장
    if delta is None:
        trend_txt = "전일 데이터가 없어 추세는 보류"
    elif delta > 0:
        trend_txt = f"전일 대비 {delta}계단 상승"
    elif delta < 0:
        trend_txt = f"전일 대비 {abs(delta)}계단 하락"
    else:
        trend_txt = "전일과 동일한 순위 유지"

    # SEO 액션 (등락·순위 기반)
    if delta is not None and delta < 0:
        actions.append(
            ("타이틀·상품정보 최근 변경분을 점검하고 핵심 키워드 노출을 복원"
             if is_naver else
             "쿠팡 광고(CPC) 입찰가를 점검해 하락 구간을 단기 방어"))
    elif rank > 10:
        actions.append(
            ("타이틀 앞단에 '" + keyword + "' 키워드를 배치하고 세부 키워드 조합을 실험"
             if is_naver else
             "쿠팡 광고 노출을 확대해 10위권 진입 모멘텀 확보"))

    # 우선순위: 경쟁 지표 액션이 앞, SEO 가 뒤. 중복 제거.
    seen: set[str] = set()
    plan: list[str] = []
    for a in actions:
        if a not in seen:
            seen.add(a)
            plan.append(a)
    if not plan:
        plan.append("현 순위·가격·리뷰 경쟁력이 안정적 — 지표 모니터링 유지")

    # tone 판정
    score = 0
    if delta is not None:
        score += 1 if delta > 0 else (-1 if delta < 0 else 0)
    if gap is not None and gap_pct is not None and gap_pct >= 10:
        score -= 1
    if rv_gap is not None and avg_rv and rv_gap < -avg_rv * 0.3:
        score -= 1
    if rank <= 5:
        score += 1
    tone = "good" if score >= 1 else ("bad" if score <= -1 else "warn")

    comp_txt = (" " + ". ".join(insights) + ".") if insights else (
        " 경쟁사 지표는 다음 스크래핑에서 수집됩니다." if not has_comp else "")
    summary = (
        f"'{keyword}' 키워드에서 현재 {rank}위, {trend_txt} 상태입니다.{comp_txt}"
    )

    return AIAnalysis(
        summary=summary, action_plan=plan[:4], tone=tone, metrics=metrics,
    )


# ---------------------------------------------------------------------------
# LLM 연동 진입점 (미구현 — 향후 교체)
# ---------------------------------------------------------------------------

def _build_prompt(
    *, name, platform, keyword, rank, delta, status,
    my_price, my_review_count, competitors, history,
) -> str:
    """LLM 호출용 프롬프트 직렬화 — _analyze_with_llm 에서 사용할 예정."""
    platform_kr = PLATFORM_KR.get(platform, platform)
    comp_lines = []
    for c in (competitors or [])[:5]:
        comp_lines.append(
            f"  {c.get('rank')}위 {c.get('name')} | 가격 {c.get('price')} | "
            f"리뷰 {c.get('review_count')} | 평점 {c.get('rating')}"
        )
    return (
        "당신은 이커머스 검색 순위·경쟁 전략 컨설턴트입니다. 아래 데이터를 근거로 "
        "[분석 결과] 2~3문장과 [권장 액션플랜] 2~4개를 한국어로, 반드시 구체적 수치를 "
        "인용해 제시하세요.\n"
        f"- 플랫폼/키워드: {platform_kr} / {keyword}\n"
        f"- 내 상품: {name} | 순위 {rank or '미노출'} | 등락 {delta} | "
        f"가격 {my_price} | 리뷰 {my_review_count} | 상태 {status}\n"
        f"- Top5 경쟁사:\n" + ("\n".join(comp_lines) or "  (수집 데이터 없음)") + "\n"
    )


def _analyze_with_llm(**kwargs) -> AIAnalysis:
    """LLM API 연동 지점 — 현재 미구현.

    구현 시:
        prompt = _build_prompt(**kwargs)
        resp   = <Claude API 호출>(prompt)
        data   = json.loads(resp)
        return AIAnalysis(summary=data["summary"], action_plan=data["action_plan"],
                          tone=data.get("tone","neutral"), generated_by="llm")
    """
    raise NotImplementedError("LLM advisor 미연동 — 규칙 기반 엔진을 사용합니다.")


__all__ = ["AIAnalysis", "analyze_product"]
