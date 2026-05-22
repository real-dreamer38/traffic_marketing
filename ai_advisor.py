"""
ai_advisor.py — 상품 순위 'AI 전략 분석' 엔진 (Beta).

대시보드의 [네이버 전략] / [쿠팡 전략] 카드 하단 'AI 전략 분석' 섹션에
표시할 [분석 결과] 와 [권장 액션플랜] 을 생성한다.

설계 의도 — 이후 LLM API 연동
------------------------------
현재 analyze_product() 는 순위/등락/상태를 입력받아 규칙 기반(rule-based)으로
조언을 만든다. 향후 Claude API 등 LLM 연동 시에는:

  1. _build_prompt() 로 동일 입력을 프롬프트 문자열로 직렬화하고
  2. _analyze_with_llm() 안에서 LLM 을 호출해 JSON 응답을 받은 뒤
  3. analyze_product() 의 분기에서 _analyze_with_rules() 대신 그 결과를 쓴다.

반환 타입(AIAnalysis)·호출 시그니처는 그대로 유지되므로, 대시보드 코드는
한 줄도 바꾸지 않고 규칙 기반 → LLM 으로 전환할 수 있다.
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
    """AI 전략 분석 결과 — 대시보드 카드의 'AI 전략 분석' 섹션에 그대로 매핑된다."""
    summary: str                       # [분석 결과] 본문
    action_plan: list[str]             # [권장 액션플랜] 항목들
    tone: str = "neutral"              # good | warn | bad | neutral — UI 색상 힌트
    generated_by: str = "rule-based"   # 향후 "llm" 으로 교체

    def __post_init__(self):
        if self.action_plan is None:
            self.action_plan = []


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
    history: Optional[list] = None,
) -> AIAnalysis:
    """한 상품의 순위 상황을 분석해 AIAnalysis 를 반환한다.

    Parameters
    ----------
    name     : 상품명
    platform : 'naver' | 'coupang'
    keyword  : 타겟 키워드
    rank     : 현재 순위 (0 = 미노출)
    delta    : 전일 대비 등락 (+상승 / -하락 / 0 유지 / None 데이터부족)
    status   : 스크래핑 상태 (ok | not_found | blocked | error)
    history  : 순위 이력 (옵션, 추세 분석용 — 현재 규칙 엔진은 미사용)

    LLM 연동 시 USE_LLM_ADVISOR 환경변수가 켜져 있으면 _analyze_with_llm 을 쓴다.
    """
    if os.getenv("USE_LLM_ADVISOR", "").lower() in ("1", "true", "yes"):
        try:
            return _analyze_with_llm(
                name=name, platform=platform, keyword=keyword,
                rank=rank, delta=delta, status=status, history=history,
            )
        except NotImplementedError:
            pass  # LLM 미구현 — 규칙 기반으로 폴백
    return _analyze_with_rules(
        name=name, platform=platform, keyword=keyword,
        rank=rank, delta=delta, status=status,
    )


# ---------------------------------------------------------------------------
# 규칙 기반 엔진 (현행 기본값)
# ---------------------------------------------------------------------------

def _analyze_with_rules(
    *,
    name: str,
    platform: str,
    keyword: str,
    rank: int,
    delta: Optional[int],
    status: str,
) -> AIAnalysis:
    platform_kr = PLATFORM_KR.get(platform, platform)
    is_naver = platform == "naver"

    # ── 1) 스크래핑이 실패한 경우 — 순위 자체를 신뢰할 수 없음 ──────────────
    if status == STATUS_BLOCKED:
        return AIAnalysis(
            summary=(
                f"{platform_kr}가 차단·캡차 페이지를 반환해 '{keyword}' 키워드의 "
                "순위를 측정하지 못했습니다. 표시된 순위는 신뢰할 수 없는 상태입니다."
            ),
            action_plan=[
                "auth_session 재인증 점검 — `python auth_setup.py` 재실행",
                "스크래핑 주기·시간대 분산으로 봇 탐지 신호 완화",
                "차단 지속 시 프록시 IP 교체 검토",
            ],
            tone="bad",
        )
    if status == STATUS_ERROR:
        return AIAnalysis(
            summary=(
                f"스크래퍼 오류로 '{keyword}' 키워드의 순위 측정에 실패했습니다. "
                "네트워크 또는 페이지 구조 변경 가능성을 점검해야 합니다."
            ),
            action_plan=[
                "debug_screenshots/ 폴더의 진단 스크린샷 확인",
                "스크래퍼 셀렉터(상품 컨테이너) 최신화 검토",
                "재시도 후에도 반복되면 로그 레벨 DEBUG 로 원인 추적",
            ],
            tone="bad",
        )

    # ── 2) 미노출 — 검색 상위에 아예 없음 ─────────────────────────────────
    if rank == 0 or status == STATUS_NOT_FOUND:
        seo_action = (
            "네이버 SEO 점검 필요 — 상품명·태그·카테고리 적합도 재검토"
            if is_naver else
            "쿠팡 노출 점검 필요 — 카테고리 매칭·상품명 키워드 정합성 재검토"
        )
        title_action = (
            "타이틀 키워드 수정 권장 — 대표 키워드를 상품명 앞쪽으로 배치"
            if is_naver else
            "썸네일·가격 경쟁력 점검 — 로켓배송 전환 시 노출 가산 검토"
        )
        return AIAnalysis(
            summary=(
                f"'{keyword}' 검색 상위 노출에서 벗어나 있습니다. 노출 자체가 안 되어 "
                "유입이 발생하지 않는 상태로, 가장 시급한 조치 대상입니다."
            ),
            action_plan=[
                seo_action,
                title_action,
                "리뷰·구매 지표 단기 부스팅으로 랭킹 진입 모멘텀 확보",
            ],
            tone="bad",
        )

    # ── 3) 노출 중 — 등락 기반 분석 ───────────────────────────────────────
    if delta is None:
        return AIAnalysis(
            summary=(
                f"현재 '{keyword}' 기준 {rank}위로 노출 중입니다. 전일 데이터가 없어 "
                "추세 판단은 보류하며, 며칠간 데이터가 쌓이면 변동 분석이 가능합니다."
            ),
            action_plan=[
                "최소 3일 이상 순위 데이터 누적 후 추세 재평가",
                f"경쟁사 Top5 대비 {name} 의 가격·리뷰 포지션 점검",
            ],
            tone="neutral",
        )

    if delta < 0:  # 하락
        return AIAnalysis(
            summary=(
                f"'{keyword}' 순위가 전일 대비 {abs(delta)}계단 하락해 현재 {rank}위입니다. "
                "경쟁사의 노출 강화 또는 자사 지표 둔화가 의심됩니다."
            ),
            action_plan=[
                ("네이버 SEO 점검 필요 — 최근 변경된 상품정보 원복 검토"
                 if is_naver else
                 "쿠팡 광고(CPC) 입찰가 점검 — 하락 구간 단기 방어"),
                "경쟁사 Top5 가격·프로모션 변화 모니터링",
                "리뷰·문의 응대 속도 개선으로 품질 지표 회복",
            ],
            tone="warn",
        )

    if delta > 0:  # 상승
        return AIAnalysis(
            summary=(
                f"'{keyword}' 순위가 전일 대비 {delta}계단 상승해 현재 {rank}위입니다. "
                "현재 마케팅 액션이 효과를 내고 있어 모멘텀 유지가 핵심입니다."
            ),
            action_plan=[
                "상승 요인(광고·리뷰·가격) 식별 후 동일 액션 유지",
                f"{'상위 10위권' if rank > 10 else '상위권'} 안착까지 트래픽 집행 지속",
                "재고 충분 여부 확인 — 품절은 순위 급락의 직접 원인",
            ],
            tone="good",
        )

    # delta == 0 — 유지
    if rank <= 5:
        return AIAnalysis(
            summary=(
                f"'{keyword}' 기준 {rank}위를 안정적으로 유지 중입니다. 상위권 방어 "
                "단계로, 무리한 변경보다 현 상태 유지가 유리합니다."
            ),
            action_plan=[
                "상품정보·가격 급격한 변경 자제 — 상위권 안정성 우선",
                "경쟁사 신규 진입 모니터링으로 방어 태세 유지",
            ],
            tone="good",
        )
    return AIAnalysis(
        summary=(
            f"'{keyword}' 기준 {rank}위로 순위 변동 없이 정체 중입니다. 상위권 진입을 "
            "위해서는 추가 동력이 필요합니다."
        ),
        action_plan=[
            ("타이틀 키워드 수정 권장 — 세부 키워드 조합 실험"
             if is_naver else
             "쿠팡 광고 노출 확대 — 정체 구간 돌파용 단기 집행"),
            "경쟁사 Top5 대비 차별화 포인트(가격·옵션·배송) 강화",
        ],
        tone="neutral",
    )


# ---------------------------------------------------------------------------
# LLM 연동 진입점 (미구현 — 향후 교체)
# ---------------------------------------------------------------------------

def _build_prompt(
    *,
    name: str,
    platform: str,
    keyword: str,
    rank: int,
    delta: Optional[int],
    status: str,
    history: Optional[list],
) -> str:
    """LLM 호출용 프롬프트 직렬화 — _analyze_with_llm 에서 사용할 예정."""
    platform_kr = PLATFORM_KR.get(platform, platform)
    delta_txt = "데이터없음" if delta is None else f"{delta:+d}"
    hist_txt = ""
    if history:
        pairs = [f"{getattr(h, 'rank_date', h['rank_date'])}:{getattr(h, 'rank', h['rank'])}"
                 for h in history[:14]]
        hist_txt = " / ".join(str(p) for p in pairs)
    return (
        "당신은 이커머스 검색 순위 전략 컨설턴트입니다. 아래 상품의 순위 상황을 "
        "분석해 [분석 결과] 1~2문장과 [권장 액션플랜] 2~3개를 한국어로 제시하세요.\n"
        f"- 플랫폼: {platform_kr}\n"
        f"- 상품명: {name}\n"
        f"- 키워드: {keyword}\n"
        f"- 현재 순위: {rank if rank else '미노출'}\n"
        f"- 전일 대비 등락: {delta_txt}\n"
        f"- 스크래핑 상태: {status}\n"
        f"- 최근 순위 이력: {hist_txt or '없음'}\n"
    )


def _analyze_with_llm(**kwargs) -> AIAnalysis:
    """LLM API 연동 지점 — 현재 미구현.

    구현 시:
        prompt = _build_prompt(**kwargs)
        resp   = <Claude API 호출>(prompt)
        data   = json.loads(resp)
        return AIAnalysis(summary=data["summary"],
                          action_plan=data["action_plan"],
                          tone=data.get("tone", "neutral"),
                          generated_by="llm")
    """
    raise NotImplementedError("LLM advisor 미연동 — 규칙 기반 엔진을 사용합니다.")


__all__ = ["AIAnalysis", "analyze_product"]
