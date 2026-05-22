"""
dashboard.py — 비즈니스 전략 관제 대시보드 (Streamlit).

Run:
    streamlit run dashboard.py

구성 (st.sidebar 네비게이션)
---------------------------
  [대시보드 홈]   전사 KPI · 플랫폼 현황 · 주의 상품
  [네이버 전략]   카드형 순위 전략 — 순위 트렌드 아코디언 + AI 전략 분석
  [쿠팡 전략]     동일 구조
  [상품 관리]     네이버/쿠팡 독립 섹션 · '품목'(상위개념) 기준 계층형 관리

디자인 시스템 — 라이트 미니멀 SaaS (Vercel / Linear 톤)
-------------------------------------------------------
  bg       #ffffff      surface  #f8fafc      border  #e5e7eb
  text     #0f172a      muted    #64748b      accent  #4f46e5
  카드     14px radius · 1px border · 미세 box-shadow
  상태칩   파스텔 Pill — green(상승) / red(하락·오류) / slate(유지·미노출) /
           blue(신규) / amber(차단)

HTML 노출 방지
--------------
스크래핑 garbage 가 화면에 새지 않도록 모든 외부 문자열은 _safe() 로 escape +
절단하며, 순위 추출 실패는 rank 값이 아니라 status(차단/오류/미노출) 칩으로만
렌더링한다.
"""

from __future__ import annotations

import html as _html
import os
from datetime import datetime
from typing import Optional

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from dotenv import load_dotenv

load_dotenv(override=False)

import database as db
import ai_advisor

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="비즈니스 전략 관제",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

db.init_db()

PLATFORM_KR    = {"naver": "네이버", "coupang": "쿠팡"}
PLATFORM_EMOJI = {"naver": "🟢", "coupang": "🔴"}
UNGROUPED_LABEL = "(미분류)"

# 사이드바 네비게이션 항목 — (key, 라벨, 아이콘)
NAV_ITEMS = [
    ("home",    "대시보드 홈", "🏠"),
    ("naver",   "네이버 전략", "🟢"),
    ("coupang", "쿠팡 전략",   "🔴"),
    ("manage",  "상품 관리",   "🗂️"),
]

# 플랫폼별 등록 폼 안내문
PLATFORM_FORM_HINTS = {
    "naver": {
        "name_placeholder":    "예) 에어캡 10mm",
        "keyword_placeholder": "예) 친환경 에어캡",
        "group_placeholder":   "예) 에코앤팩 친환경 에어캡",
        "id_label":            "네이버 상품 ID (catalog ID / nvMid)",
        "id_placeholder":      "예) 40155252748",
        "id_help":             "catalog/40155252748, nvMid, productId 중 하나. URL 만 넣으면 자동 추출됩니다.",
        "url_label":           "스마트스토어 / 네이버쇼핑 URL",
        "url_placeholder":     "https://smartstore.naver.com/.../products/12345",
        "url_help":            "스마트스토어 상품 URL 또는 search.shopping.naver.com/catalog/... URL.",
    },
    "coupang": {
        "name_placeholder":    "예) 고체 치약 3p",
        "keyword_placeholder": "예) 고체 치약",
        "group_placeholder":   "예) 덴탈케어 묶음",
        "id_label":            "쿠팡 상품 ID (productId / vendorItemId)",
        "id_placeholder":      "예) 1234567890",
        "id_help":             "/vp/products/<id> 의 productId 또는 vendorItemId. URL 만 넣으면 자동 추출됩니다.",
        "url_label":           "쿠팡 상품 URL",
        "url_placeholder":     "https://www.coupang.com/vp/products/1234567890?...",
        "url_help":            "쿠팡 상품 상세 URL. productId/vendorItemId 가 자동 추출됩니다.",
    },
}

# ---------------------------------------------------------------------------
# Global CSS
# ---------------------------------------------------------------------------

CSS = """<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');

html, body, [class*="css"], [class*="st-"] {
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, system-ui, sans-serif !important;
}
.stApp { background: #ffffff !important; color: #0f172a; }

/* CRITICAL: Streamlit Material 아이콘은 위 Inter 강제(!important)에서 반드시 제외한다.
   아이콘 <span> 도 st-emotion-cache-* 클래스를 달고 있어 Inter 가 덮이면
   아이콘 글리프 대신 ligature 텍스트('keyboard_arrow_down' 등)가 그대로
   노출된다(아코디언 세모·사이드바 아이콘 깨짐). 아이콘 폰트를 재지정해 막는다. */
span[data-testid="stIconMaterial"],
[data-testid="stExpanderToggleIcon"],
[data-testid="stIconMaterial"],
.material-icons, .material-symbols-rounded, .material-symbols-outlined,
[class*="material-symbols"], [class*="material-icons"] {
    font-family: 'Material Symbols Rounded', 'Material Symbols Outlined',
                 'Material Icons' !important;
}

#MainMenu, footer, header[data-testid="stHeader"] { visibility: hidden; height: 0; }
[data-testid="stMetricDeltaIcon-Up"],
[data-testid="stMetricDeltaIcon-Down"] { display: none !important; }

.block-container {
    padding-top: 2.2rem !important;
    padding-bottom: 3rem !important;
    max-width: 1240px;
}

/* ── Page header ───────────────────────────────────────────── */
.page-title {
    font-size: 1.7rem; font-weight: 800; letter-spacing: -0.03em;
    color: #0f172a; margin: 0 0 0.3rem 0; line-height: 1.2;
}
.page-sub {
    color: #64748b; font-size: 0.93rem; font-weight: 400;
    margin: 0 0 1.6rem 0;
}
.greeting {
    font-size: 1.5rem; font-weight: 800; letter-spacing: -0.03em;
    color: #0f172a; margin: 0 0 0.25rem 0;
}
.greeting-sub { color: #64748b; font-size: 0.92rem; margin: 0 0 1.6rem 0; }

/* ── Section title ─────────────────────────────────────────── */
.section-title {
    font-size: 0.95rem; font-weight: 700; color: #0f172a;
    margin: 0 0 1rem 0; letter-spacing: -0.01em;
}

/* ── Sidebar ───────────────────────────────────────────────── */
[data-testid="stSidebar"] {
    background: #f8fafc !important;
    border-right: 1px solid #e5e7eb;
}
[data-testid="stSidebar"] .block-container { padding-top: 1.4rem !important; }
.sb-brand {
    font-size: 1.05rem; font-weight: 800; color: #0f172a;
    letter-spacing: -0.02em; display: flex; align-items: center; gap: 7px;
    margin-bottom: 2px;
}
.sb-brand-sub { font-size: 0.74rem; color: #94a3b8; font-weight: 500; margin-bottom: 14px; }
.sb-label {
    font-size: 0.7rem; font-weight: 700; color: #94a3b8;
    text-transform: uppercase; letter-spacing: 0.08em; margin: 14px 0 8px 2px;
}
[data-testid="stSidebar"] hr { border-color: #e5e7eb; opacity: 1; margin: 1rem 0; }

/* sidebar nav buttons */
[data-testid="stSidebar"] .stButton > button {
    width: 100%; text-align: left; justify-content: flex-start;
    border-radius: 9px; padding: 9px 13px; font-size: 0.92rem; font-weight: 600;
    border: 1px solid transparent; background: transparent; color: #475569;
    box-shadow: none; transition: background .12s ease, border-color .12s ease;
}
[data-testid="stSidebar"] .stButton > button:hover {
    background: #ffffff; border-color: #e5e7eb; color: #0f172a;
}
[data-testid="stSidebar"] .stButton > button[kind="primary"] {
    background: #0f172a; border-color: #0f172a; color: #ffffff; font-weight: 700;
}
[data-testid="stSidebar"] .stButton > button[kind="primary"]:hover {
    background: #1e293b; border-color: #1e293b;
}

/* ── Card wrapper ─────────────────────────────────────────── */
[data-testid="stVerticalBlockBorderWrapper"] {
    background: #ffffff;
    border: 1px solid #e5e7eb !important;
    border-radius: 14px !important;
    padding: 22px 24px !important;
    box-shadow: 0 1px 2px rgba(15,23,42,0.04), 0 4px 14px rgba(15,23,42,0.035);
    margin-bottom: 16px;
}

/* ── KPI grid ─────────────────────────────────────────────── */
.kpi-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 14px; }
.kpi-card {
    background: #f8fafc; border: 1px solid #e5e7eb; border-radius: 12px;
    padding: 18px 20px; transition: border-color .15s ease, transform .15s ease;
}
.kpi-card:hover { border-color: #cbd5e1; transform: translateY(-1px); }
.kpi-label { font-size: 0.8rem; color: #64748b; font-weight: 500; margin-bottom: 8px; }
.kpi-value {
    font-size: 1.95rem; font-weight: 800; color: #0f172a;
    letter-spacing: -0.03em; line-height: 1.1;
}
.kpi-value .kpi-suffix { font-size: 0.95rem; font-weight: 600; color: #64748b; margin-left: 4px; }
.kpi-foot { font-size: 0.78rem; color: #94a3b8; font-weight: 500; margin-top: 7px; }
@media (max-width: 900px) { .kpi-grid { grid-template-columns: repeat(2, 1fr); } }

/* ── Pastel pill tags ─────────────────────────────────────── */
.pill {
    display: inline-flex; align-items: center; gap: 3px;
    padding: 3px 10px; border-radius: 999px;
    font-size: 0.78rem; font-weight: 600; letter-spacing: -0.005em; line-height: 1.3;
}
.pill-green { background: #dcfce7; color: #166534; }
.pill-red   { background: #fee2e2; color: #991b1b; }
.pill-slate { background: #f1f5f9; color: #475569; }
.pill-blue  { background: #dbeafe; color: #1e40af; }
.pill-amber { background: #fef3c7; color: #92400e; }

/* ── Strategy card ────────────────────────────────────────── */
.strat-head {
    display: flex; align-items: flex-start; justify-content: space-between;
    gap: 16px; margin-bottom: 4px;
}
.strat-meta {
    font-size: 0.76rem; font-weight: 600; color: #64748b;
    margin-bottom: 5px; letter-spacing: -0.005em;
}
.strat-name {
    font-size: 1.05rem; font-weight: 700; color: #0f172a;
    letter-spacing: -0.015em; line-height: 1.35;
}
.strat-head-right { text-align: right; white-space: nowrap; }
.strat-rank {
    font-size: 1.95rem; font-weight: 800; color: #0f172a;
    letter-spacing: -0.03em; line-height: 1; margin-bottom: 6px;
}
.strat-rank.dimmed { color: #94a3b8; font-size: 1.35rem; }
.strat-rank .unit { font-size: 0.95rem; font-weight: 600; color: #64748b; margin-left: 2px; }

/* ── AI 전략 분석 box ─────────────────────────────────────── */
.ai-box {
    background: #f8fafc; border: 1px solid #e5e7eb; border-radius: 11px;
    padding: 15px 17px; margin-top: 14px;
}
.ai-box.ai-good { background: #f0fdf4; border-color: #bbf7d0; }
.ai-box.ai-warn { background: #fffbeb; border-color: #fde68a; }
.ai-box.ai-bad  { background: #fef2f2; border-color: #fecaca; }
.ai-head {
    font-size: 0.84rem; font-weight: 700; color: #0f172a;
    display: flex; align-items: center; gap: 6px; margin-bottom: 10px;
}
.ai-beta {
    font-size: 0.64rem; font-weight: 700; color: #4f46e5;
    background: #e0e7ff; border-radius: 5px; padding: 1px 6px; letter-spacing: 0.03em;
}
.ai-label {
    font-size: 0.74rem; font-weight: 800; color: #4f46e5;
    text-transform: uppercase; letter-spacing: 0.04em; margin: 9px 0 4px 0;
}
.ai-text { font-size: 0.88rem; color: #334155; line-height: 1.55; }
.ai-actions { margin: 4px 0 0 0; padding-left: 18px; }
.ai-actions li { font-size: 0.86rem; color: #334155; line-height: 1.6; margin-bottom: 2px; }

/* ── Group header (계층형) ────────────────────────────────── */
.group-head {
    display: flex; align-items: center; gap: 8px;
    font-size: 0.95rem; font-weight: 700; color: #0f172a; margin: 2px 0 2px 0;
}
.group-count {
    font-size: 0.74rem; font-weight: 600; color: #64748b;
    background: #f1f5f9; border-radius: 999px; padding: 2px 9px;
}

/* ── Inline product table rows ────────────────────────────── */
.prod-table-head {
    font-size: 0.72rem; font-weight: 700; color: #94a3b8;
    text-transform: uppercase; letter-spacing: 0.05em; padding: 2px 4px;
}
.tr-cell {
    padding: 5px 4px; font-size: 0.88rem; color: #0f172a;
    display: flex; align-items: center; min-height: 38px;
}
.tr-cell.center { justify-content: center; text-align: center; }
.tr-cell.muted { color: #64748b; font-size: 0.84rem; }
.tr-cell.strong { font-weight: 600; }
.tr-cell.mono { font-variant-numeric: tabular-nums; }
[data-testid="stHorizontalBlock"] .stButton > button {
    padding: 6px 8px; font-size: 0.82rem; min-height: 34px; line-height: 1;
}

/* ── Buttons ───────────────────────────────────────────────── */
.stButton > button {
    border-radius: 8px; border: 1px solid #e5e7eb; background: #ffffff;
    color: #0f172a; padding: 8px 16px; font-weight: 600; font-size: 0.89rem;
    box-shadow: none; transition: background .12s ease, border-color .12s ease;
}
.stButton > button:hover { background: #f8fafc; border-color: #cbd5e1; }
.stButton > button[kind="primary"] {
    background: #0f172a; border: 1px solid #0f172a; color: #ffffff; font-weight: 700;
}
.stButton > button[kind="primary"]:hover { background: #1e293b; border-color: #1e293b; }

/* ── Inputs ────────────────────────────────────────────────── */
.stTextInput input, .stTextArea textarea,
.stNumberInput input, .stDateInput input,
[data-baseweb="select"] > div {
    background: #ffffff !important; border: 1px solid #e5e7eb !important;
    border-radius: 8px !important; color: #0f172a !important; font-size: 0.9rem;
}
.stTextInput input:focus, .stTextArea textarea:focus,
.stNumberInput input:focus, .stDateInput input:focus {
    border-color: #4f46e5 !important;
    box-shadow: 0 0 0 3px rgba(79,70,229,0.14) !important; outline: none !important;
}
.stTextInput label, .stSelectbox label, .stNumberInput label,
.stDateInput label, .stTextArea label, .stRadio label {
    color: #334155 !important; font-size: 0.84rem !important; font-weight: 600 !important;
}
.stSlider [data-baseweb="slider"] > div > div > div { background: #4f46e5; }
.stRadio [role="radiogroup"] label {
    background: #ffffff; border: 1px solid #e5e7eb; border-radius: 8px;
    padding: 6px 12px; margin-right: 6px; font-size: 0.86rem; font-weight: 500;
}
.stRadio [role="radiogroup"] label:hover { border-color: #cbd5e1; background: #f8fafc; }

/* ── Dataframe — center aligned ───────────────────────────── */
[data-testid="stDataFrame"] {
    border: 1px solid #e5e7eb; border-radius: 10px; overflow: hidden; box-shadow: none;
}
[data-testid="stDataFrame"] [data-testid="stDataFrameResizable"] { background: #ffffff; }

/* ── Alerts / Expander ────────────────────────────────────── */
[data-testid="stAlert"] {
    border-radius: 10px; border: 1px solid #e5e7eb; background: #f8fafc;
}
[data-testid="stExpander"] details {
    border: 1px solid #e5e7eb !important; border-radius: 10px !important;
    background: #ffffff !important;
}
[data-testid="stExpander"] details > summary {
    font-weight: 600 !important; color: #334155 !important; font-size: 0.88rem !important;
    padding: 9px 13px !important;
}
[data-testid="stExpander"] details > summary:hover { color: #0f172a !important; }

hr { border-color: #e5e7eb !important; opacity: 1; margin: 1.4rem 0; }

.status-pill {
    display: inline-flex; align-items: center; gap: 6px;
    background: #ffffff; border: 1px solid #e5e7eb; border-radius: 999px;
    padding: 4px 10px; font-size: 0.78rem; color: #334155; font-weight: 600;
}
.status-pill .dot { width: 6px; height: 6px; border-radius: 50%; background: #22c55e; }
.status-pill.warn .dot { background: #f59e0b; }
.stCaption, [data-testid="stCaptionContainer"] { color: #64748b !important; font-weight: 400; }

.delete-dialog-msg { font-size: 1rem; color: #0f172a; line-height: 1.5; margin-bottom: 6px; }
.delete-dialog-name {
    background: #fef2f2; border: 1px solid #fecaca; border-radius: 8px;
    padding: 10px 14px; margin: 12px 0 14px 0; font-size: 0.95rem;
    color: #991b1b; font-weight: 600;
}
.delete-dialog-warn { font-size: 0.85rem; color: #64748b; margin-bottom: 16px; line-height: 1.5; }
</style>"""

st.markdown(CSS, unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Safety helpers — HTML/코드 노출 방지
# ---------------------------------------------------------------------------

def _safe(text: object, max_len: int = 90) -> str:
    """외부/스크래핑 문자열을 화면에 넣기 전 escape + 절단한다.

    스크래핑 garbage(HTML 태그·코드 블롭)가 unsafe_allow_html 영역으로 새어
    'HTML 소스코드'처럼 노출되는 것을 원천 차단하는 마지막 방어선이다.
    """
    if text is None:
        return ""
    s = str(text).replace("\n", " ").replace("\r", " ").strip()
    if len(s) > max_len:
        s = s[:max_len].rstrip() + "…"
    return _html.escape(s)


# ---------------------------------------------------------------------------
# Cached data helpers
# ---------------------------------------------------------------------------

@st.cache_data(ttl=60)
def load_products(platform: Optional[str] = None) -> list[dict]:
    return [dict(r) for r in db.list_products(active_only=True, platform=platform)]


@st.cache_data(ttl=30)
def load_all_products(platform: Optional[str] = None) -> list[dict]:
    return [dict(r) for r in db.list_products(active_only=False, platform=platform)]


@st.cache_data(ttl=30)
def load_groups(platform: Optional[str] = None) -> list[dict]:
    return [dict(r) for r in db.list_groups(platform=platform)]


@st.cache_data(ttl=60)
def load_rank_history(product_id: int, days: int) -> pd.DataFrame:
    rows = db.get_rank_history(product_id, days=days)
    if not rows:
        return pd.DataFrame(columns=["rank_date", "rank", "status"])
    df = pd.DataFrame([dict(r) for r in rows])
    df["rank_date"] = pd.to_datetime(df["rank_date"])
    df = df.sort_values("rank_date")
    df["rank_display"] = df["rank"].apply(lambda x: None if x == 0 else x)
    return df


@st.cache_data(ttl=60)
def load_competitor_history(product_id: int, days: int) -> pd.DataFrame:
    rows = db.get_competitor_history(product_id, days=days)
    if not rows:
        return pd.DataFrame(columns=["rank_date", "rank", "name"])
    df = pd.DataFrame([dict(r) for r in rows])
    df["rank_date"] = pd.to_datetime(df["rank_date"])
    df = df.sort_values(["rank_date", "rank"])
    return df


# ---------------------------------------------------------------------------
# Status / pill helpers
# ---------------------------------------------------------------------------

def _rank_state(latest: Optional[dict]) -> tuple[int, str]:
    """(rank, status) 를 안전하게 반환. 이력이 없으면 (0, 'none')."""
    if not latest:
        return 0, "none"
    return int(latest.get("rank") or 0), str(latest.get("status") or "ok")


def _rank_pill(rank: int, status: str) -> str:
    """현재 순위/상태를 나타내는 Pill HTML — 추출 실패 시 코드 대신 상태 칩."""
    if status == "blocked":
        return '<span class="pill pill-amber">⛔ 차단</span>'
    if status == "error":
        return '<span class="pill pill-red">⚠️ 오류</span>'
    if rank > 0:
        return f'<span class="pill pill-blue">{rank}위</span>'
    if status == "none":
        return '<span class="pill pill-slate">데이터 없음</span>'
    return '<span class="pill pill-slate">미노출</span>'


def _delta_pill(delta: Optional[int], rank: int, status: str) -> str:
    """전일 대비 등락 Pill — +1 / -2 / 유지 / 신규 / 미노출."""
    if status in ("blocked", "error"):
        return '<span class="pill pill-slate">측정 불가</span>'
    if status == "none":
        return '<span class="pill pill-slate">데이터 없음</span>'
    if rank == 0:
        return '<span class="pill pill-slate">미노출</span>'
    if delta is None:
        return '<span class="pill pill-blue">신규</span>'
    if delta > 0:
        return f'<span class="pill pill-green">▲ +{delta}</span>'
    if delta < 0:
        return f'<span class="pill pill-red">▼ -{abs(delta)}</span>'
    return '<span class="pill pill-slate">유지</span>'


def _rank_big_html(rank: int, status: str) -> tuple[str, str]:
    """전략 카드 우측의 큰 순위 표기 — (html, css_class)."""
    if status == "blocked":
        return "차단", "strat-rank dimmed"
    if status == "error":
        return "오류", "strat-rank dimmed"
    if rank > 0:
        return f'{rank}<span class="unit">위</span>', "strat-rank"
    if status == "none":
        return "—", "strat-rank dimmed"
    return "미노출", "strat-rank dimmed"


def _center_styled(df: pd.DataFrame):
    """가운데 정렬된 pandas Styler — 본문 + 헤더 모두 가운데."""
    return (
        df.style
          .set_properties(**{"text-align": "center"})
          .set_table_styles([
              {"selector": "th", "props": [("text-align", "center"),
                                           ("font-weight", "700"),
                                           ("color", "#0f172a")]},
              {"selector": "td", "props": [("text-align", "center"),
                                           ("color", "#0f172a")]},
          ])
    )


# ---------------------------------------------------------------------------
# Plotly trend chart
# ---------------------------------------------------------------------------

COMPETITOR_COLORS = ["#fb7185", "#fbbf24", "#a3e635", "#34d399", "#22d3ee"]


def build_trend_chart(
    df: pd.DataFrame,
    competitors_df: Optional[pd.DataFrame] = None,
) -> go.Figure:
    fig = go.Figure()
    has_my_data = not df.empty and not df["rank_display"].isna().all()

    if competitors_df is not None and not competitors_df.empty:
        for rank_pos in sorted(competitors_df["rank"].unique()):
            sub = competitors_df[competitors_df["rank"] == rank_pos].sort_values("rank_date")
            color = COMPETITOR_COLORS[(int(rank_pos) - 1) % len(COMPETITOR_COLORS)]
            fig.add_trace(
                go.Scatter(
                    x=sub["rank_date"], y=sub["rank"],
                    mode="lines+markers", name=f"경쟁사 {int(rank_pos)}위",
                    line=dict(color=color, width=1.3, dash="dot"),
                    marker=dict(size=4, color=color),
                    customdata=sub["name"].fillna("").to_numpy().reshape(-1, 1),
                    hovertemplate=("<b>%{x|%Y-%m-%d}</b><br>경쟁사 %{y}위<br>"
                                   "%{customdata[0]}<extra></extra>"),
                    opacity=0.7,
                )
            )

    if has_my_data:
        fig.add_trace(
            go.Scatter(
                x=df["rank_date"], y=df["rank_display"],
                mode="lines+markers", name="내 상품",
                line=dict(color="#4f46e5", width=2.8),
                marker=dict(size=8, color="#4f46e5", line=dict(color="#ffffff", width=1.5)),
                hovertemplate="<b>%{x|%Y-%m-%d}</b><br>내 순위: %{y}위<extra></extra>",
                connectgaps=False,
            )
        )

    if not has_my_data and (competitors_df is None or competitors_df.empty):
        fig.add_annotation(
            text="순위 데이터 없음 — 다음 스크래핑 후 채워집니다",
            xref="paper", yref="paper", x=0.5, y=0.5, showarrow=False,
            font=dict(size=13, color="#94a3b8"),
        )

    valid_my = df["rank_display"].dropna() if has_my_data else pd.Series(dtype=float)
    valid_comp = (
        competitors_df["rank"] if (competitors_df is not None and not competitors_df.empty)
        else pd.Series(dtype=float)
    )
    pool = pd.concat([valid_my, valid_comp], ignore_index=True)
    y_max = int(pool.max()) + 5 if not pool.empty else 50

    fig.update_layout(
        height=340,
        margin=dict(l=10, r=10, t=24, b=10),
        paper_bgcolor="#ffffff", plot_bgcolor="#ffffff",
        font=dict(color="#334155", family="Inter, sans-serif", size=12),
        yaxis=dict(
            title=dict(text="순위", font=dict(size=12, color="#64748b")),
            autorange="reversed", range=[y_max, 0],
            gridcolor="#f1f5f9", linecolor="#e5e7eb", zeroline=False, ticksuffix="위",
        ),
        xaxis=dict(title="", gridcolor="#f1f5f9", linecolor="#e5e7eb", zeroline=False),
        showlegend=True,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1,
                    bgcolor="rgba(255,255,255,0)", font=dict(size=11, color="#64748b")),
    )
    return fig


# ---------------------------------------------------------------------------
# KPI grid
# ---------------------------------------------------------------------------

def render_kpi_grid(cells: list[tuple[str, str, str]]) -> None:
    """cells: [(label, value_html, foot), ...] — 최대 4칸."""
    html_cards = "".join(
        f"""<div class="kpi-card">
                <div class="kpi-label">{label}</div>
                <div class="kpi-value">{value}</div>
                <div class="kpi-foot">{foot}</div>
            </div>"""
        for label, value, foot in cells
    )
    st.markdown(f'<div class="kpi-grid">{html_cards}</div>', unsafe_allow_html=True)


def _platform_stats(products: list[dict]) -> dict:
    """플랫폼 상품 리스트의 노출/상승/하락/차단 집계."""
    total = len(products)
    exposed = improved = worsened = blocked = errored = 0
    for p in products:
        latest = db.get_latest_rank(p["id"])
        rank, status = _rank_state(dict(latest) if latest else None)
        delta = db.get_rank_delta(p["id"])
        if status == "blocked":
            blocked += 1
        elif status == "error":
            errored += 1
        if rank > 0:
            exposed += 1
        if delta is not None and delta > 0:
            improved += 1
        elif delta is not None and delta < 0:
            worsened += 1
    return {"total": total, "exposed": exposed, "improved": improved,
            "worsened": worsened, "blocked": blocked, "errored": errored}


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

if "nav" not in st.session_state:
    st.session_state.nav = "home"

with st.sidebar:
    st.markdown('<div class="sb-brand">📊 전략 관제 시스템</div>', unsafe_allow_html=True)
    st.markdown('<div class="sb-brand-sub">네이버 · 쿠팡 순위 모니터링</div>',
                unsafe_allow_html=True)

    st.markdown('<div class="sb-label">메뉴</div>', unsafe_allow_html=True)
    for key, label, icon in NAV_ITEMS:
        is_active = st.session_state.nav == key
        if st.button(f"{icon}  {label}", key=f"nav_{key}", use_container_width=True,
                     type="primary" if is_active else "secondary"):
            st.session_state.nav = key
            st.rerun()

    st.divider()

    st.markdown('<div class="sb-label">알림 채널</div>', unsafe_allow_html=True)
    tg_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    tg_chat  = os.getenv("TELEGRAM_CHAT_ID", "")
    if tg_token and tg_chat:
        st.markdown('<span class="status-pill"><span class="dot"></span>Telegram 연결됨</span>',
                    unsafe_allow_html=True)
        st.caption(f"chat_id: {tg_chat} · 플랫폼별 분리 발송")
    else:
        st.markdown('<span class="status-pill warn"><span class="dot"></span>Telegram 미설정</span>',
                    unsafe_allow_html=True)
        st.caption(".env 의 TELEGRAM_BOT_TOKEN / CHAT_ID 확인")

    st.divider()
    st.markdown('<div class="sb-label">조회 옵션</div>', unsafe_allow_html=True)
    trend_days = st.slider("트렌드 기간 (일)", min_value=7, max_value=90, value=30, step=7,
                           key="sidebar_trend_days")

    if st.button("데이터 새로고침", use_container_width=True, key="sidebar_refresh"):
        st.cache_data.clear()
        st.rerun()
    st.caption(f"마지막 로드 · {datetime.now().strftime('%H:%M:%S')}")


# ---------------------------------------------------------------------------
# Delete confirmation dialog
# ---------------------------------------------------------------------------

@st.dialog("⚠️ 상품 삭제 확인")
def _confirm_delete_dialog() -> None:
    pending = st.session_state.get("pending_delete")
    if not pending:
        return

    platform_kr = PLATFORM_KR.get(pending.get("platform", ""), "")
    platform_tag = f"<span class='pill pill-slate'>{platform_kr}</span> " if platform_kr else ""

    st.markdown("<div class='delete-dialog-msg'>해당 상품을 영구 삭제하시겠습니까?</div>",
                unsafe_allow_html=True)
    st.markdown(f"<div class='delete-dialog-name'>🗑️ {platform_tag}{_safe(pending['name'])}</div>",
                unsafe_allow_html=True)
    st.markdown(
        "<div class='delete-dialog-warn'>이 작업은 되돌릴 수 없습니다.<br>"
        "해당 상품의 <b>순위 이력 · 경쟁사 스냅샷 · 트래픽 로그</b>가 함께 삭제됩니다.</div>",
        unsafe_allow_html=True,
    )

    c1, c2 = st.columns(2)
    if c1.button("취소", use_container_width=True, key="dlg_cancel_delete"):
        st.session_state.pop("pending_delete", None)
        st.rerun()
    if c2.button("삭제하기", type="primary", use_container_width=True, key="dlg_confirm_delete"):
        deleted = db.delete_product(pending["id"])
        db.prune_empty_groups()          # 마지막 상품이 빠진 품목은 자동 정리
        st.session_state.pop("pending_delete", None)
        st.cache_data.clear()
        st.toast(f"상품을 삭제했습니다: {pending['name']}" if deleted else "이미 삭제된 항목입니다.",
                 icon="🗑️" if deleted else "⚠️")
        st.rerun()


def _request_delete(product: dict) -> None:
    st.session_state["pending_delete"] = {
        "id": product["id"], "name": product["name"], "platform": product["platform"],
    }
    st.rerun()


# ---------------------------------------------------------------------------
# Page: 대시보드 홈
# ---------------------------------------------------------------------------

def render_home() -> None:
    hour = datetime.now().hour
    greet = "좋은 아침입니다" if 5 <= hour < 12 else ("안녕하세요" if 12 <= hour < 18 else "오늘도 수고하셨습니다")
    today = datetime.now().strftime("%Y년 %m월 %d일")

    st.markdown(f'<div class="greeting">{greet}, 대표님 👋</div>', unsafe_allow_html=True)
    st.markdown(
        f'<div class="greeting-sub">{today} · 네이버·쿠팡 검색 순위 현황을 한눈에 확인하세요.</div>',
        unsafe_allow_html=True,
    )

    naver   = load_all_products("naver")
    coupang = load_all_products("coupang")
    naver_active   = [p for p in naver if p["active"]]
    coupang_active = [p for p in coupang if p["active"]]
    n_stats = _platform_stats(naver_active)
    c_stats = _platform_stats(coupang_active)

    total    = n_stats["total"] + c_stats["total"]
    exposed  = n_stats["exposed"] + c_stats["exposed"]
    improved = n_stats["improved"] + c_stats["improved"]
    worsened = n_stats["worsened"] + c_stats["worsened"]
    blocked  = n_stats["blocked"] + c_stats["blocked"]

    # ── 전사 KPI ──
    with st.container(border=True):
        st.markdown('<div class="section-title">전사 순위 현황</div>', unsafe_allow_html=True)
        render_kpi_grid([
            ("추적 상품", f'{total}<span class="kpi-suffix">개</span>',
             f"네이버 {n_stats['total']} · 쿠팡 {c_stats['total']}"),
            ("노출 중", f'{exposed}<span class="kpi-suffix">/ {total}</span>',
             "검색결과 내 노출 상품"),
            ("순위 상승", f'{improved}<span class="kpi-suffix">개</span>', "전일 대비 상승"),
            ("순위 하락", f'{worsened}<span class="kpi-suffix">개</span>',
             f"차단 {blocked}건" if blocked else "전일 대비 하락"),
        ])

    # ── 플랫폼 현황 2-up ──
    col_n, col_c = st.columns(2)
    for col, platform, stats in ((col_n, "naver", n_stats), (col_c, "coupang", c_stats)):
        with col, st.container(border=True):
            pk = PLATFORM_KR[platform]
            st.markdown(
                f'<div class="section-title">{PLATFORM_EMOJI[platform]} {pk} 요약</div>',
                unsafe_allow_html=True,
            )
            if stats["total"] == 0:
                st.caption(f"등록된 {pk} 상품이 없습니다. [상품 관리]에서 추가하세요.")
            else:
                chips = (
                    f'<span class="pill pill-blue">노출 {stats["exposed"]}/{stats["total"]}</span> '
                    f'<span class="pill pill-green">▲ {stats["improved"]}</span> '
                    f'<span class="pill pill-red">▼ {stats["worsened"]}</span>'
                )
                if stats["blocked"]:
                    chips += f' <span class="pill pill-amber">⛔ 차단 {stats["blocked"]}</span>'
                if stats["errored"]:
                    chips += f' <span class="pill pill-red">⚠️ 오류 {stats["errored"]}</span>'
                st.markdown(chips, unsafe_allow_html=True)
                st.caption(f"메뉴 [{pk} 전략]에서 카드별 순위 트렌드와 AI 분석을 확인하세요.")

    # ── 주의가 필요한 상품 ──
    with st.container(border=True):
        st.markdown('<div class="section-title">⚠️ 주의가 필요한 상품</div>',
                    unsafe_allow_html=True)
        alerts: list[str] = []
        for p in naver_active + coupang_active:
            latest = db.get_latest_rank(p["id"])
            rank, status = _rank_state(dict(latest) if latest else None)
            delta = db.get_rank_delta(p["id"])
            reason = ""
            if status == "blocked":
                reason = '<span class="pill pill-amber">⛔ 차단</span>'
            elif status == "error":
                reason = '<span class="pill pill-red">⚠️ 오류</span>'
            elif rank == 0 and status != "none":
                reason = '<span class="pill pill-slate">미노출</span>'
            elif delta is not None and delta < 0:
                reason = f'<span class="pill pill-red">▼ -{abs(delta)} 하락</span>'
            if reason:
                pk = PLATFORM_KR[p["platform"]]
                alerts.append(
                    f'<div style="display:flex;align-items:center;gap:8px;padding:7px 4px;'
                    f'border-bottom:1px solid #f1f5f9;">'
                    f'<span class="pill pill-slate">{pk}</span>'
                    f'<span style="flex:1;font-size:0.89rem;font-weight:600;color:#0f172a;">'
                    f'{_safe(p["name"])}</span>{reason}</div>'
                )
        if alerts:
            st.markdown("".join(alerts), unsafe_allow_html=True)
        else:
            st.caption("현재 주의가 필요한 상품이 없습니다. 모든 상품이 안정적입니다. ✅")


# ---------------------------------------------------------------------------
# Page: 네이버 / 쿠팡 전략 (카드형 + AI 분석)
# ---------------------------------------------------------------------------

def _render_strategy_card(product: dict) -> None:
    """전략 카드 한 개 — 헤더(순위·등락) + 순위 트렌드 아코디언 + AI 전략 분석."""
    pid       = product["id"]
    platform  = product["platform"]
    latest    = db.get_latest_rank(pid)
    rank, status = _rank_state(dict(latest) if latest else None)
    delta     = db.get_rank_delta(pid)
    group_nm  = product.get("group_name") or UNGROUPED_LABEL

    with st.container(border=True):
        # ── 헤더: 상품명 · 키워드 + 볼드 순위 + 등락 Pill ──
        rank_html, rank_cls = _rank_big_html(rank, status)
        st.markdown(
            f"""
            <div class="strat-head">
                <div>
                    <div class="strat-meta">{PLATFORM_EMOJI[platform]} {PLATFORM_KR[platform]}
                        · 📦 {_safe(group_nm, 40)} · 🔑 {_safe(product["keyword"], 40)}</div>
                    <div class="strat-name">{_safe(product["name"], 70)}</div>
                </div>
                <div class="strat-head-right">
                    <div class="{rank_cls}">{rank_html}</div>
                    {_delta_pill(delta, rank, status)}
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        # ── 순위 트렌드 (누적) — 기본 접힘, 아코디언 클릭 시 펼침 ──
        with st.expander("📈 순위 트렌드 (누적)", expanded=False):
            df             = load_rank_history(pid, trend_days)
            competitors_df = load_competitor_history(pid, trend_days)
            st.plotly_chart(build_trend_chart(df, competitors_df),
                            use_container_width=True, key=f"trend_{pid}")
            if not df.empty:
                hist = df[["rank_date", "rank", "status"]].copy()
                hist.columns = ["날짜", "순위", "상태"]
                hist["날짜"] = hist["날짜"].dt.strftime("%Y-%m-%d")
                _STATUS_KR = {"ok": "정상", "not_found": "미노출",
                              "blocked": "차단", "error": "오류"}
                hist["순위"] = hist.apply(
                    lambda r: "미노출" if r["순위"] == 0 else f"{int(r['순위'])}위", axis=1)
                hist["상태"] = hist["상태"].map(lambda s: _STATUS_KR.get(s, s))
                st.dataframe(_center_styled(hist), use_container_width=True, hide_index=True)

        # ── AI 전략 분석 (Beta) ──
        analysis = ai_advisor.analyze_product(
            name=product["name"], platform=platform, keyword=product["keyword"],
            rank=rank, delta=delta, status=status,
        )
        actions_html = "".join(f"<li>{_safe(a, 120)}</li>" for a in analysis.action_plan)
        st.markdown(
            f"""
            <div class="ai-box ai-{analysis.tone}">
                <div class="ai-head">🤖 AI 전략 분석 <span class="ai-beta">Beta</span></div>
                <div class="ai-label">분석 결과</div>
                <div class="ai-text">{_safe(analysis.summary, 300)}</div>
                <div class="ai-label">권장 액션플랜</div>
                <ul class="ai-actions">{actions_html}</ul>
            </div>
            """,
            unsafe_allow_html=True,
        )


def render_strategy_page(platform: str) -> None:
    pk = PLATFORM_KR[platform]
    st.markdown(f'<div class="page-title">{PLATFORM_EMOJI[platform]} {pk} 전략</div>',
                unsafe_allow_html=True)
    st.markdown(
        f'<p class="page-sub">{pk} 검색 순위를 품목별 카드로 추적합니다. '
        '카드의 [순위 트렌드]를 펼쳐 누적 그래프를, 하단에서 AI 전략 분석을 확인하세요.</p>',
        unsafe_allow_html=True,
    )

    products = load_products(platform)
    if not products:
        st.info(f"등록된 {pk} 상품이 없습니다. 사이드바 [상품 관리]에서 추가해 주세요.")
        return

    # ── KPI 요약 ──
    stats = _platform_stats(products)
    with st.container(border=True):
        st.markdown(f'<div class="section-title">{pk} 순위 요약</div>', unsafe_allow_html=True)
        render_kpi_grid([
            ("추적 상품", f'{stats["total"]}<span class="kpi-suffix">개</span>', "활성 상품 수"),
            ("노출 중", f'{stats["exposed"]}<span class="kpi-suffix">/ {stats["total"]}</span>',
             "검색결과 내 노출"),
            ("순위 상승", f'{stats["improved"]}<span class="kpi-suffix">개</span>', "전일 대비"),
            ("순위 하락", f'{stats["worsened"]}<span class="kpi-suffix">개</span>',
             f"차단 {stats['blocked']} · 오류 {stats['errored']}"),
        ])

    # ── 품목별로 묶어 카드 렌더 (load_products 가 그룹순 정렬됨) ──
    current_group = object()
    for product in products:
        gname = product.get("group_name") or UNGROUPED_LABEL
        if gname != current_group:
            current_group = gname
            count = sum(1 for p in products
                        if (p.get("group_name") or UNGROUPED_LABEL) == gname)
            st.markdown(
                f'<div class="group-head">📦 {_safe(gname, 50)}'
                f'<span class="group-count">{count}개 상품</span></div>',
                unsafe_allow_html=True,
            )
        _render_strategy_card(product)


# ---------------------------------------------------------------------------
# Page: 상품 관리 (네이버/쿠팡 독립 섹션 · 품목 계층형)
# ---------------------------------------------------------------------------

def _render_registration_form(platform: str) -> None:
    """플랫폼별 상품 등록/수정 폼 — 품목 선택/생성 포함."""
    hints       = PLATFORM_FORM_HINTS[platform]
    pk          = PLATFORM_KR[platform]
    all_products = load_all_products(platform)
    groups       = load_groups(platform)

    with st.container(border=True):
        st.markdown(
            f'<div class="section-title">{PLATFORM_EMOJI[platform]} {pk} 상품 등록 / 수정</div>',
            unsafe_allow_html=True,
        )

        mode = st.radio("작업 모드", ["추가", "수정"], horizontal=True,
                        key=f"mode_{platform}", label_visibility="collapsed")

        edit_target: Optional[dict] = None
        if mode == "수정":
            if not all_products:
                st.info(f"등록된 {pk} 상품이 없습니다. 먼저 추가해 주세요.")
            else:
                labels = [f"[{p['id']}] {p['name']}" for p in all_products]
                pick = st.selectbox("수정할 상품", labels, key=f"edit_pick_{platform}")
                edit_target = all_products[labels.index(pick)]

        key_suffix = f"edit_{edit_target['id']}" if edit_target else "add"
        defaults   = edit_target or {}

        st.markdown(
            f"<div style='margin-bottom:10px;'>"
            f"<span class='pill pill-blue'>플랫폼 · {pk}</span></div>",
            unsafe_allow_html=True,
        )

        # ── 품목 선택 / 생성 ──
        group_names = [g["name"] for g in groups]
        if mode == "수정" and edit_target is not None and edit_target.get("group_name"):
            group_mode_default = 0   # 기존 품목
        else:
            group_mode_default = 0 if group_names else 1
        group_mode = st.radio(
            "품목 (상위 분류)", ["기존 품목 선택", "새 품목 추가"],
            index=group_mode_default, horizontal=True, key=f"gmode_{platform}_{key_suffix}",
        )

        chosen_group_id: Optional[int] = None
        new_group_name = ""
        if group_mode == "기존 품목 선택":
            if not group_names:
                st.caption("등록된 품목이 없습니다. '새 품목 추가'를 선택하세요.")
            else:
                cur_group = defaults.get("group_name")
                idx = group_names.index(cur_group) if cur_group in group_names else 0
                picked = st.selectbox("품목 선택", group_names, index=idx,
                                      key=f"gpick_{platform}_{key_suffix}")
                chosen_group_id = groups[group_names.index(picked)]["id"]
        else:
            new_group_name = st.text_input(
                "새 품목명", placeholder=hints["group_placeholder"],
                key=f"gnew_{platform}_{key_suffix}",
            )

        name = st.text_input("상품명", value=str(defaults.get("name") or ""),
                             placeholder=hints["name_placeholder"],
                             key=f"name_{platform}_{key_suffix}")
        keyword = st.text_input("타겟 키워드", value=str(defaults.get("keyword") or ""),
                                placeholder=hints["keyword_placeholder"],
                                key=f"kw_{platform}_{key_suffix}")
        target_url = st.text_input(hints["url_label"],
                                   value=str(defaults.get("target_url") or ""),
                                   placeholder=hints["url_placeholder"], help=hints["url_help"],
                                   key=f"url_{platform}_{key_suffix}")
        target_id = st.text_input(hints["id_label"],
                                  value=str(defaults.get("target_id") or ""),
                                  placeholder=hints["id_placeholder"], help=hints["id_help"],
                                  key=f"tid_{platform}_{key_suffix}")

        if mode == "수정" and edit_target is not None:
            submit_label, submit_key = "수정 저장", f"save_{platform}_{edit_target['id']}"
        else:
            submit_label, submit_key = f"{pk} 상품 추가", f"add_{platform}"

        if st.button(submit_label, type="primary", use_container_width=True, key=submit_key):
            raw_url = target_url.strip()
            raw_id  = target_id.strip()
            effective_id = raw_id or (db.extract_product_id(platform, raw_url) or "")

            # 품목 확정
            resolved_group_id = chosen_group_id
            if group_mode == "새 품목 추가":
                if not new_group_name.strip():
                    st.error("새 품목명을 입력해 주세요.")
                    st.stop()
                resolved_group_id = db.get_or_create_group(new_group_name.strip(), platform)

            if not name.strip() or not keyword.strip():
                st.error("상품명과 키워드는 필수입니다.")
            elif resolved_group_id is None:
                st.error("품목을 선택하거나 새 품목을 추가해 주세요.")
            elif not effective_id and not raw_url:
                st.error("상품 ID 또는 URL 중 하나는 입력해야 합니다.")
            elif edit_target is not None:
                db.update_product(
                    product_id=edit_target["id"], name=name.strip(),
                    keyword=keyword.strip(), target_id=effective_id or None,
                    target_url=raw_url or None, group_id=resolved_group_id,
                )
                st.cache_data.clear()
                st.success(f"수정 완료 (ID: {edit_target['id']})")
                st.rerun()
            else:
                new_id = db.add_product(
                    name=name.strip(), platform=platform, keyword=keyword.strip(),
                    target_id=effective_id or None, target_url=raw_url or None,
                    group_id=resolved_group_id,
                )
                auto_note = (f" · URL 에서 ID 자동 추출: {effective_id}"
                             if not raw_id and effective_id else "")
                st.cache_data.clear()
                st.success(f"{pk} 상품 추가 완료 (ID: {new_id}){auto_note}")
                st.rerun()


def _render_grouped_list(platform: str) -> None:
    """플랫폼별 상품 목록 — '품목' 기준 계층형(Expander) 표시."""
    pk           = PLATFORM_KR[platform]
    all_products = load_all_products(platform)

    with st.container(border=True):
        st.markdown(f'<div class="section-title">{pk} 품목별 상품 목록</div>',
                    unsafe_allow_html=True)

        if not all_products:
            st.caption(f"등록된 {pk} 상품이 없습니다. 좌측에서 추가해 주세요.")
            return

        # group_name 별로 묶기 — 미분류는 맨 뒤
        buckets: dict[str, list[dict]] = {}
        for p in all_products:
            buckets.setdefault(p.get("group_name") or UNGROUPED_LABEL, []).append(p)
        ordered = sorted(buckets.items(),
                         key=lambda kv: (kv[0] == UNGROUPED_LABEL, kv[0]))

        col_ratios = [0.5, 2.3, 1.9, 1.1, 0.9, 0.7]
        for gname, items in ordered:
            with st.expander(f"📦  {gname}   ·   {len(items)}개 상품", expanded=True):
                hdr = st.columns(col_ratios)
                for i, label in enumerate(["ID", "상품명", "키워드", "현재 순위", "상태", ""]):
                    hdr[i].markdown(
                        f"<div class='prod-table-head' style='text-align:center;'>{label}</div>",
                        unsafe_allow_html=True)
                st.markdown("<hr style='margin:2px 0 4px 0;'/>", unsafe_allow_html=True)

                for product in items:
                    latest = db.get_latest_rank(product["id"])
                    rank, status = _rank_state(dict(latest) if latest else None)
                    is_active = bool(product["active"])

                    row = st.columns(col_ratios)
                    row[0].markdown(
                        f"<div class='tr-cell center muted mono'>#{product['id']}</div>",
                        unsafe_allow_html=True)
                    row[1].markdown(
                        f"<div class='tr-cell strong'>{_safe(product['name'], 44)}</div>",
                        unsafe_allow_html=True)
                    row[2].markdown(
                        f"<div class='tr-cell muted'>{_safe(product['keyword'], 32)}</div>",
                        unsafe_allow_html=True)
                    row[3].markdown(
                        f"<div class='tr-cell center'>{_rank_pill(rank, status)}</div>",
                        unsafe_allow_html=True)

                    active_pill = ('<span class="pill pill-green">활성</span>' if is_active
                                   else '<span class="pill pill-slate">비활성</span>')
                    row[4].markdown(f"<div class='tr-cell center'>{active_pill}</div>",
                                    unsafe_allow_html=True)

                    btn_c = row[5].columns(2)
                    if btn_c[0].button("⇄", key=f"toggle_{platform}_{product['id']}",
                                       help="활성/비활성 전환", use_container_width=True):
                        db.update_product(product["id"], active=not is_active)
                        st.cache_data.clear()
                        st.rerun()
                    if btn_c[1].button("🗑", key=f"del_{platform}_{product['id']}",
                                       help=f"'{product['name']}' 삭제", use_container_width=True):
                        _request_delete(product)

        st.caption(f"총 {len(all_products)}개 {pk} 상품 · {len(ordered)}개 품목")


def render_manage_page() -> None:
    st.markdown('<div class="page-title">🗂️ 상품 관리</div>', unsafe_allow_html=True)
    st.markdown(
        '<p class="page-sub">네이버·쿠팡 상품을 <b>품목(상위 분류)</b> 기준으로 계층 관리합니다. '
        '플랫폼별 섹션이 독립적으로 분리되어 있습니다.</p>',
        unsafe_allow_html=True,
    )

    for platform in ("naver", "coupang"):
        pk = PLATFORM_KR[platform]
        st.markdown(
            f'<div class="section-title" style="font-size:1.05rem;margin-top:6px;">'
            f'{PLATFORM_EMOJI[platform]} {pk} 상품 관리</div>',
            unsafe_allow_html=True,
        )
        left, right = st.columns([1, 1.7], gap="large")
        with left:
            _render_registration_form(platform)
        with right:
            _render_grouped_list(platform)
        if platform == "naver":
            st.markdown("<hr/>", unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Main router
# ---------------------------------------------------------------------------

nav = st.session_state.nav
if nav == "home":
    render_home()
elif nav == "naver":
    render_strategy_page("naver")
elif nav == "coupang":
    render_strategy_page("coupang")
elif nav == "manage":
    render_manage_page()
else:
    render_home()

# 삭제 버튼이 눌리면 session_state 에 pending_delete 가 들어가고 다이얼로그가 열린다.
if st.session_state.get("pending_delete"):
    _confirm_delete_dialog()
