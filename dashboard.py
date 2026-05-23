"""
dashboard.py — 비즈니스 전략 관제 대시보드 (Streamlit).

Run:
    streamlit run dashboard.py

화면 구성 (st.sidebar 글로벌 네비게이션)
----------------------------------------
  대시보드        전사 KPI · 플랫폼 현황 · 주의 상품
  네이버 전략     품목 Selectbox 로 한 품목만 골라 보는 SPA 뷰
                  → 키워드별 카드(순위·트렌드·경쟁사 비교 AI 분석)
  쿠팡 전략       동일 구조
  상품 관리       품목(상위 분류) 기준 계층형 등록/관리

디자인 — 라이트 미니멀 SaaS (Vercel / Linear / Delivas 톤)
----------------------------------------------------------
  bg #ffffff · surface #f8fafc · border #e5e7eb · accent #4f46e5
  타이포 위계 : 상품명 24px/800 · 순위 36px/800(컬러) · 키워드 Pill
  카드 16px radius · 미세 shadow · 차트는 그리드/축장식 제거한 미니멀 라인

CSS 주입은 components.html <script> 로 <head> 에 직접 삽입 → 텍스트 노출 0%.
"""

from __future__ import annotations

import html as _html
from datetime import datetime
from typing import Optional

import os
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import streamlit.components.v1 as components
from dotenv import load_dotenv

load_dotenv(override=False)

import database as db
import ai_advisor

st.set_page_config(
    page_title="전략 관제",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)
db.init_db()

PLATFORM_KR     = {"naver": "네이버", "coupang": "쿠팡"}
UNGROUPED_LABEL = "(미분류)"
NAV_ITEMS = [
    ("home",    "대시보드"),
    ("naver",   "네이버 전략"),
    ("coupang", "쿠팡 전략"),
    ("manage",  "상품 관리"),
]
PERIOD_OPTIONS = {"7일": 7, "30일": 30, "90일": 90}

PLATFORM_FORM_HINTS = {
    "naver": {
        "name_placeholder":    "예) 에어캡 10mm 80장",
        "keyword_placeholder": "예) 친환경 에어캡",
        "group_placeholder":   "예) 에코앤팩 친환경 에어캡",
        "id_label":            "네이버 상품 ID (catalog ID / nvMid)",
        "id_placeholder":      "예) 40155252748",
        "id_help":             "catalog/40155252748, nvMid, productId 중 하나. URL 만 넣어도 자동 추출됩니다.",
        "url_label":           "스마트스토어 / 네이버쇼핑 URL",
        "url_placeholder":     "https://smartstore.naver.com/.../products/12345",
        "url_help":            "스마트스토어 또는 search.shopping.naver.com/catalog/... URL.",
    },
    "coupang": {
        "name_placeholder":    "예) 고체 치약 3p",
        "keyword_placeholder": "예) 고체 치약",
        "group_placeholder":   "예) 덴탈케어 묶음",
        "id_label":            "쿠팡 상품 ID (productId / vendorItemId)",
        "id_placeholder":      "예) 1234567890",
        "id_help":             "/vp/products/<id> 의 productId 또는 vendorItemId. URL 만 넣어도 자동 추출됩니다.",
        "url_label":           "쿠팡 상품 URL",
        "url_placeholder":     "https://www.coupang.com/vp/products/1234567890?...",
        "url_help":            "쿠팡 상품 상세 URL. productId/vendorItemId 가 자동 추출됩니다.",
    },
}

# ---------------------------------------------------------------------------
# CSS
# ---------------------------------------------------------------------------

CSS = """
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');

html, body, [class*="css"], [class*="st-"] {
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, system-ui, sans-serif !important;
}
.stApp { background: #ffffff !important; color: #0f172a; }

/* CSS 주입용 components.html iframe(height=0) 흔적 제거 */
iframe[srcdoc] { display: none !important; height: 0 !important; }
[data-testid="stElementContainer"]:has(iframe[srcdoc]) {
    display: none !important; height: 0 !important; margin: 0 !important;
}

/* Streamlit Material 아이콘은 Inter 강제에서 제외 (ligature 텍스트 노출 방지) */
span[data-testid="stIconMaterial"], [data-testid="stExpanderToggleIcon"],
[data-testid="stIconMaterial"], [class*="material-symbols"], [class*="material-icons"] {
    font-family: 'Material Symbols Rounded','Material Symbols Outlined','Material Icons' !important;
}

#MainMenu, footer, header[data-testid="stHeader"] { visibility: hidden; height: 0; }
[data-testid="stMetricDeltaIcon-Up"], [data-testid="stMetricDeltaIcon-Down"] { display: none !important; }

.block-container { padding-top: 2.4rem !important; padding-bottom: 3rem !important; max-width: 1180px; }

/* ── Page header ─────────────────────────────────────────── */
.page-title { font-size: 1.6rem; font-weight: 800; letter-spacing: -0.03em;
              color: #0f172a; margin: 0 0 0.25rem 0; line-height: 1.2; }
.page-sub   { color: #64748b; font-size: 0.92rem; margin: 0 0 1.5rem 0; }
.greeting   { font-size: 1.5rem; font-weight: 800; letter-spacing: -0.03em;
              color: #0f172a; margin: 0 0 0.2rem 0; }
.greeting-sub { color: #64748b; font-size: 0.9rem; margin: 0 0 1.5rem 0; }
.section-title { font-size: 0.95rem; font-weight: 700; color: #0f172a; margin: 0 0 1rem 0; }

/* ── Sidebar ─────────────────────────────────────────────── */
[data-testid="stSidebar"] { background: #f8fafc !important; border-right: 1px solid #e5e7eb; }
[data-testid="stSidebar"] .block-container { padding-top: 1.6rem !important; }
.sb-brand { font-size: 1.12rem; font-weight: 800; color: #0f172a; letter-spacing: -0.02em; }
.sb-brand-sub { font-size: 0.66rem; font-weight: 700; color: #a5b4fc;
                letter-spacing: 0.16em; margin: 2px 0 18px 0; }
.sb-label { font-size: 0.66rem; font-weight: 700; color: #94a3b8;
            letter-spacing: 0.12em; margin: 8px 0 8px 2px; }
[data-testid="stSidebar"] hr { border-color: #e5e7eb; opacity: 1; margin: 1.1rem 0; }
[data-testid="stSidebar"] .stButton > button {
    width: 100%; text-align: left; justify-content: flex-start;
    border-radius: 9px; padding: 10px 14px; font-size: 0.92rem; font-weight: 600;
    border: 1px solid transparent; background: transparent; color: #475569;
    box-shadow: none; transition: background .12s ease;
}
[data-testid="stSidebar"] .stButton > button:hover { background: #eef2ff; color: #4f46e5; }
[data-testid="stSidebar"] .stButton > button[kind="primary"] {
    background: #4f46e5; border-color: #4f46e5; color: #ffffff; font-weight: 700;
}
[data-testid="stSidebar"] .stButton > button[kind="primary"]:hover { background: #4338ca; }

/* ── Card wrapper ────────────────────────────────────────── */
[data-testid="stVerticalBlockBorderWrapper"] {
    background: #ffffff; border: 1px solid #e5e7eb !important; border-radius: 16px !important;
    padding: 22px 24px !important;
    box-shadow: 0 1px 2px rgba(15,23,42,.04), 0 6px 18px rgba(15,23,42,.04);
    margin-bottom: 16px;
}

/* ── KPI grid ────────────────────────────────────────────── */
.kpi-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 13px; }
.kpi-card { background: #f8fafc; border: 1px solid #e5e7eb; border-radius: 13px; padding: 17px 19px; }
.kpi-label { font-size: 0.78rem; color: #64748b; font-weight: 500; margin-bottom: 7px; }
.kpi-value { font-size: 1.9rem; font-weight: 800; color: #0f172a; letter-spacing: -0.03em; line-height: 1.05; }
.kpi-value .kpi-suffix { font-size: 0.92rem; font-weight: 600; color: #64748b; margin-left: 3px; }
.kpi-foot { font-size: 0.76rem; color: #94a3b8; font-weight: 500; margin-top: 7px; }
@media (max-width: 900px) { .kpi-grid { grid-template-columns: repeat(2, 1fr); } }

/* ── Pills ───────────────────────────────────────────────── */
.pill { display: inline-flex; align-items: center; gap: 3px; padding: 3px 10px;
        border-radius: 999px; font-size: 0.76rem; font-weight: 600; line-height: 1.35; }
.pill-green { background: #dcfce7; color: #15803d; }
.pill-red   { background: #fee2e2; color: #b91c1c; }
.pill-slate { background: #f1f5f9; color: #475569; }
.pill-blue  { background: #e0e7ff; color: #4338ca; }
.pill-amber { background: #fef3c7; color: #b45309; }

/* 키워드 Pill — 카드 상단, 파스텔 인디고 배경 */
.kw-pill { display: inline-flex; align-items: center; background: #eef2ff; color: #4f46e5;
           font-size: 0.78rem; font-weight: 700; padding: 4px 12px; border-radius: 999px;
           letter-spacing: -0.01em; }

/* ── 전략 카드 타이포 위계 ───────────────────────────────── */
.strat-flex { display: flex; align-items: flex-start; justify-content: space-between;
              gap: 16px; margin-top: 10px; }
.prod-name-lg { font-size: 1.5rem; font-weight: 800; color: #111827;
                letter-spacing: -0.035em; line-height: 1.25; }
.rank-block { text-align: right; white-space: nowrap; }
.rank-xl { font-size: 2.25rem; font-weight: 800; letter-spacing: -0.04em; line-height: 1; }
.rank-xl .rank-unit { font-size: 1rem; font-weight: 700; color: #94a3b8; margin-left: 2px; }
.rank-top  { color: #16a34a; }
.rank-mid  { color: #4f46e5; }
.rank-low  { color: #d97706; }
.rank-none { color: #94a3b8; font-size: 1.5rem; }
.rank-cap  { font-size: 0.7rem; font-weight: 700; color: #94a3b8; letter-spacing: 0.08em;
             text-transform: uppercase; margin-bottom: 3px; }

/* ── AI 전략 분석 ────────────────────────────────────────── */
.ai-box { background: #fbfbfd; border: 1px solid #e9e9f2; border-radius: 13px;
          padding: 16px 18px; margin-top: 14px; }
.ai-box.ai-good { background: #f0fdf4; border-color: #bbf7d0; }
.ai-box.ai-warn { background: #fffbeb; border-color: #fde68a; }
.ai-box.ai-bad  { background: #fef2f2; border-color: #fecaca; }
.ai-head { font-size: 0.86rem; font-weight: 800; color: #0f172a;
           display: flex; align-items: center; gap: 7px; margin-bottom: 11px; }
.ai-beta { font-size: 0.62rem; font-weight: 800; color: #4f46e5; background: #e0e7ff;
           border-radius: 5px; padding: 2px 6px; letter-spacing: 0.04em; }
.ai-label { font-size: 0.72rem; font-weight: 800; color: #4f46e5; letter-spacing: 0.05em;
            text-transform: uppercase; margin: 12px 0 5px 0; }
.ai-text { font-size: 0.92rem; color: #1e293b; line-height: 1.65; font-weight: 500; }
.ai-actions { margin: 4px 0 0 0; padding-left: 0; list-style: none; }
.ai-actions li { font-size: 0.88rem; color: #334155; line-height: 1.55; margin-bottom: 7px;
                 padding-left: 22px; position: relative; }
.ai-actions li:before { content: ""; position: absolute; left: 6px; top: 8px;
    width: 6px; height: 6px; border-radius: 50%; background: #4f46e5; }

/* 경쟁 지표 비교 카드 */
.cmp-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 11px; margin-top: 4px; }
.cmp-metric { background: #ffffff; border: 1px solid #e9e9f2; border-radius: 11px; padding: 13px 15px; }
.cmp-metric-label { font-size: 0.74rem; font-weight: 700; color: #64748b; margin-bottom: 8px; }
.cmp-row { display: flex; align-items: baseline; justify-content: space-between; }
.cmp-mine { font-size: 1.32rem; font-weight: 800; color: #0f172a; letter-spacing: -0.02em; }
.cmp-vs { font-size: 0.78rem; color: #94a3b8; font-weight: 500; }
.cmp-comp { font-size: 0.92rem; font-weight: 700; color: #475569; }
.cmp-gap { margin-top: 7px; }
@media (max-width: 760px) { .cmp-grid { grid-template-columns: 1fr; } }

/* 경쟁사 Top5 비교 테이블 */
.cmp-table { width: 100%; border-collapse: collapse; margin-top: 4px; font-size: 0.85rem; }
.cmp-table th { background: #f8fafc; color: #64748b; font-weight: 700; font-size: 0.74rem;
    text-transform: uppercase; letter-spacing: 0.04em; padding: 8px 10px; text-align: center;
    border-bottom: 1px solid #e5e7eb; }
.cmp-table td { padding: 9px 10px; text-align: center; color: #1e293b;
    border-bottom: 1px solid #f1f5f9; font-variant-numeric: tabular-nums; }
.cmp-table td.nm { text-align: left; font-weight: 500; }
.cmp-table tr.cmp-me td { background: #eef2ff; font-weight: 700; color: #4338ca; }
.cmp-table tr:last-child td { border-bottom: none; }

/* ── Group header (계층형 관리) ──────────────────────────── */
.group-head { display: flex; align-items: center; gap: 8px; font-size: 0.95rem;
              font-weight: 700; color: #0f172a; }
.group-count { font-size: 0.72rem; font-weight: 600; color: #64748b;
               background: #f1f5f9; border-radius: 999px; padding: 2px 9px; }
.prod-table-head { font-size: 0.7rem; font-weight: 700; color: #94a3b8;
                   text-transform: uppercase; letter-spacing: 0.05em; padding: 2px 4px; }
.tr-cell { padding: 5px 4px; font-size: 0.87rem; color: #0f172a;
           display: flex; align-items: center; min-height: 38px; }
.tr-cell.center { justify-content: center; text-align: center; }
.tr-cell.muted { color: #64748b; font-size: 0.83rem; }
.tr-cell.strong { font-weight: 600; }
.tr-cell.mono { font-variant-numeric: tabular-nums; }
[data-testid="stHorizontalBlock"] .stButton > button {
    padding: 6px 8px; font-size: 0.82rem; min-height: 34px; line-height: 1; }

/* ── Buttons / inputs ────────────────────────────────────── */
.stButton > button { border-radius: 9px; border: 1px solid #e5e7eb; background: #ffffff;
    color: #0f172a; padding: 8px 16px; font-weight: 600; font-size: 0.89rem; box-shadow: none; }
.stButton > button:hover { background: #f8fafc; border-color: #cbd5e1; }
.stButton > button[kind="primary"] { background: #4f46e5; border-color: #4f46e5;
    color: #fff; font-weight: 700; }
.stButton > button[kind="primary"]:hover { background: #4338ca; border-color: #4338ca; }
.stTextInput input, .stTextArea textarea, .stNumberInput input, .stDateInput input,
[data-baseweb="select"] > div {
    background: #fff !important; border: 1px solid #e5e7eb !important;
    border-radius: 9px !important; color: #0f172a !important; font-size: 0.9rem; }
.stTextInput input:focus, [data-baseweb="select"] > div:focus-within {
    border-color: #4f46e5 !important; box-shadow: 0 0 0 3px rgba(79,70,229,.13) !important; }
.stTextInput label, .stSelectbox label, .stTextInput label, .stRadio label,
.stTextArea label, .stNumberInput label, .stDateInput label {
    color: #334155 !important; font-size: 0.8rem !important; font-weight: 700 !important; }

/* 기간 선택 radio → pill 토글 */
.stRadio [role="radiogroup"] { gap: 6px; }
.stRadio [role="radiogroup"] label { background: #f1f5f9; border: 1px solid transparent;
    border-radius: 8px; padding: 5px 14px; font-size: 0.84rem; font-weight: 600; margin: 0; }
.stRadio [role="radiogroup"] label:hover { background: #eef2ff; }
.stRadio [role="radiogroup"] label[data-checked="true"],
.stRadio [role="radiogroup"] label:has(input:checked) {
    background: #4f46e5; color: #fff; }

[data-testid="stExpander"] details { border: 1px solid #e5e7eb !important;
    border-radius: 11px !important; background: #ffffff !important; }
[data-testid="stExpander"] details > summary { font-weight: 600 !important;
    color: #334155 !important; font-size: 0.86rem !important; padding: 9px 13px !important; }
[data-testid="stAlert"] { border-radius: 11px; border: 1px solid #e5e7eb; background: #f8fafc; }
[data-testid="stDataFrame"] { border: 1px solid #e5e7eb; border-radius: 10px; overflow: hidden; }
hr { border-color: #e5e7eb !important; opacity: 1; margin: 1.3rem 0; }
.stCaption, [data-testid="stCaptionContainer"] { color: #94a3b8 !important; }

/* 사이드바 시스템 상태 */
.sys-pill { display: inline-flex; align-items: center; gap: 7px; background: #ffffff;
    border: 1px solid #e5e7eb; border-radius: 999px; padding: 5px 12px;
    font-size: 0.78rem; color: #334155; font-weight: 600; }
.sys-pill .dot { width: 7px; height: 7px; border-radius: 50%; background: #22c55e; }
.sys-pill.off .dot { background: #f59e0b; }

/* 빈 상태 / alert row */
.alert-row { display: flex; align-items: center; gap: 9px; padding: 9px 4px;
             border-bottom: 1px solid #f1f5f9; }
.alert-name { flex: 1; font-size: 0.89rem; font-weight: 600; color: #0f172a; }

.delete-dialog-name { background: #fef2f2; border: 1px solid #fecaca; border-radius: 9px;
    padding: 10px 14px; margin: 12px 0; font-size: 0.95rem; color: #b91c1c; font-weight: 600; }
"""


def _inject_css(css_body: str) -> None:
    """components.html <script> 로 부모 문서 <head> 에 <style> 직접 삽입.
    CSS 가 <script> 안 문자열로만 존재 → 텍스트 노출 0%, 항상 전역 적용."""
    safe = (css_body.replace("\\", "\\\\").replace("`", "\\`").replace("${", "\\${"))
    components.html(
        "<script>(function(){"
        "  var d = window.parent.document;"
        "  var prev = d.getElementById('dashboard-custom-css');"
        "  if (prev) prev.remove();"
        "  var s = d.createElement('style');"
        "  s.id = 'dashboard-custom-css';"
        f"  s.textContent = `{safe}`;"
        "  d.head.appendChild(s);"
        "})();</script>",
        height=0,
    )


_inject_css(CSS)


# ---------------------------------------------------------------------------
# Safety helper
# ---------------------------------------------------------------------------

def _safe(text: object, max_len: int = 90) -> str:
    """외부/스크래핑 문자열을 escape + 절단 — HTML/코드 노출 방어선."""
    if text is None:
        return ""
    s = str(text).replace("\n", " ").replace("\r", " ").strip()
    if len(s) > max_len:
        s = s[:max_len].rstrip() + "…"
    return _html.escape(s)


def _won(n) -> str:
    return f"{int(n):,}원" if n not in (None, "") else "—"


def _cnt(n) -> str:
    return f"{int(n):,}" if n not in (None, "") else "—"


# ---------------------------------------------------------------------------
# Cached data loaders
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
def load_latest_competitors(product_id: int) -> list[dict]:
    return [dict(r) for r in db.get_latest_competitors(product_id)]


# ---------------------------------------------------------------------------
# Status / pill helpers
# ---------------------------------------------------------------------------

def _rank_state(latest: Optional[dict]) -> tuple[int, str]:
    if not latest:
        return 0, "none"
    return int(latest.get("rank") or 0), str(latest.get("status") or "ok")


def _rank_pill(rank: int, status: str) -> str:
    if status == "blocked":
        return '<span class="pill pill-amber">차단</span>'
    if status == "error":
        return '<span class="pill pill-red">오류</span>'
    if rank > 0:
        return f'<span class="pill pill-blue">{rank}위</span>'
    if status == "none":
        return '<span class="pill pill-slate">데이터 없음</span>'
    return '<span class="pill pill-slate">미노출</span>'


def _delta_pill(delta: Optional[int], rank: int, status: str) -> str:
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


def _rank_big(rank: int, status: str) -> str:
    """순위 36px 표기 HTML — 순위대별 컬러 포인트."""
    if status == "blocked":
        return '<div class="rank-xl rank-none">차단</div>'
    if status == "error":
        return '<div class="rank-xl rank-none">오류</div>'
    if rank <= 0:
        label = "—" if status == "none" else "미노출"
        return f'<div class="rank-xl rank-none">{label}</div>'
    cls = "rank-top" if rank <= 5 else ("rank-mid" if rank <= 20 else "rank-low")
    return f'<div class="rank-xl {cls}">{rank}<span class="rank-unit">위</span></div>'


# ---------------------------------------------------------------------------
# Minimal trend chart
# ---------------------------------------------------------------------------

def build_trend_chart(df: pd.DataFrame) -> go.Figure:
    """미니멀 순위 트렌드 — 그리드/축장식 제거, 부드러운 모던 라인."""
    fig = go.Figure()
    has = not df.empty and not df["rank_display"].isna().all()

    if has:
        fig.add_trace(go.Scatter(
            x=df["rank_date"], y=df["rank_display"],
            mode="lines+markers",
            line=dict(color="#4f46e5", width=2.6, shape="spline"),
            marker=dict(size=6, color="#4f46e5", line=dict(color="#fff", width=1.5)),
            hovertemplate="%{x|%m월 %d일} · <b>%{y}위</b><extra></extra>",
            connectgaps=False,
        ))
        valid = df["rank_display"].dropna()
        y_max = int(valid.max()) + 3
        y_min = max(0, int(valid.min()) - 3)
    else:
        fig.add_annotation(text="순위 데이터 없음 — 스크래핑 후 채워집니다",
                           xref="paper", yref="paper", x=0.5, y=0.5,
                           showarrow=False, font=dict(size=12, color="#cbd5e1"))
        y_max, y_min = 30, 0

    fig.update_layout(
        height=190, margin=dict(l=6, r=6, t=10, b=6),
        paper_bgcolor="#ffffff", plot_bgcolor="#ffffff",
        font=dict(family="Inter, sans-serif"),
        showlegend=False,
        xaxis=dict(showgrid=False, showline=False, zeroline=False,
                   tickfont=dict(size=10, color="#cbd5e1"), tickformat="%m/%d",
                   nticks=6),
        yaxis=dict(autorange="reversed", range=[y_max, y_min],
                   showgrid=False, showline=False, zeroline=False,
                   tickfont=dict(size=10, color="#cbd5e1"), ticksuffix="위",
                   nticks=4),
    )
    return fig


# ---------------------------------------------------------------------------
# KPI grid
# ---------------------------------------------------------------------------

def render_kpi_grid(cells: list[tuple[str, str, str]]) -> None:
    html = "".join(
        f'<div class="kpi-card"><div class="kpi-label">{lbl}</div>'
        f'<div class="kpi-value">{val}</div><div class="kpi-foot">{foot}</div></div>'
        for lbl, val, foot in cells
    )
    st.markdown(f'<div class="kpi-grid">{html}</div>', unsafe_allow_html=True)


def _platform_stats(products: list[dict]) -> dict:
    total = len(products)
    exposed = improved = worsened = blocked = errored = 0
    rank_sum = rank_n = 0
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
            rank_sum += rank
            rank_n += 1
        if delta is not None and delta > 0:
            improved += 1
        elif delta is not None and delta < 0:
            worsened += 1
    avg_rank = round(rank_sum / rank_n) if rank_n else 0
    return {"total": total, "exposed": exposed, "improved": improved,
            "worsened": worsened, "blocked": blocked, "errored": errored,
            "avg_rank": avg_rank}


# ---------------------------------------------------------------------------
# Sidebar — 글로벌 네비 + 시스템 상태만 (심플)
# ---------------------------------------------------------------------------

if "nav" not in st.session_state:
    st.session_state.nav = "home"

with st.sidebar:
    st.markdown('<div class="sb-brand">전략 관제</div>', unsafe_allow_html=True)
    st.markdown('<div class="sb-brand-sub">RANK INTELLIGENCE</div>', unsafe_allow_html=True)

    for key, label in NAV_ITEMS:
        if st.button(label, key=f"nav_{key}", use_container_width=True,
                     type="primary" if st.session_state.nav == key else "secondary"):
            st.session_state.nav = key
            st.rerun()

    st.divider()
    st.markdown('<div class="sb-label">SYSTEM</div>', unsafe_allow_html=True)
    tg_ok = bool(os.getenv("TELEGRAM_BOT_TOKEN")) and bool(os.getenv("TELEGRAM_CHAT_ID"))
    if tg_ok:
        st.markdown('<span class="sys-pill"><span class="dot"></span>텔레그램 연동됨</span>',
                    unsafe_allow_html=True)
    else:
        st.markdown('<span class="sys-pill off"><span class="dot"></span>텔레그램 미설정</span>',
                    unsafe_allow_html=True)
    if st.button("데이터 새로고침", key="sb_refresh", use_container_width=True):
        st.cache_data.clear()
        st.rerun()
    st.caption(f"업데이트 {datetime.now().strftime('%H:%M')}")


# ---------------------------------------------------------------------------
# Delete dialog
# ---------------------------------------------------------------------------

@st.dialog("상품 삭제 확인")
def _confirm_delete_dialog() -> None:
    pending = st.session_state.get("pending_delete")
    if not pending:
        return
    st.markdown("해당 상품을 영구 삭제하시겠습니까?")
    st.markdown(f"<div class='delete-dialog-name'>{_safe(pending['name'])}</div>",
                unsafe_allow_html=True)
    st.caption("순위 이력 · 경쟁사 스냅샷 · 트래픽 로그가 함께 삭제됩니다. 되돌릴 수 없습니다.")
    c1, c2 = st.columns(2)
    if c1.button("취소", use_container_width=True, key="dlg_cancel"):
        st.session_state.pop("pending_delete", None)
        st.rerun()
    if c2.button("삭제하기", type="primary", use_container_width=True, key="dlg_confirm"):
        deleted = db.delete_product(pending["id"])
        db.prune_empty_groups()
        st.session_state.pop("pending_delete", None)
        st.cache_data.clear()
        st.toast("삭제했습니다." if deleted else "이미 삭제된 항목입니다.")
        st.rerun()


# ---------------------------------------------------------------------------
# Page: 대시보드 홈
# ---------------------------------------------------------------------------

def render_home() -> None:
    hour = datetime.now().hour
    greet = ("좋은 아침입니다" if 5 <= hour < 12 else
             "안녕하세요" if 12 <= hour < 18 else "오늘도 수고하셨습니다")
    st.markdown(f'<div class="greeting">{greet}, 대표님</div>', unsafe_allow_html=True)
    st.markdown(
        f'<div class="greeting-sub">{datetime.now().strftime("%Y년 %m월 %d일")} · '
        '네이버·쿠팡 검색 순위 현황 요약</div>', unsafe_allow_html=True)

    naver   = [p for p in load_all_products("naver") if p["active"]]
    coupang = [p for p in load_all_products("coupang") if p["active"]]
    ns, cs = _platform_stats(naver), _platform_stats(coupang)
    total   = ns["total"] + cs["total"]
    exposed = ns["exposed"] + cs["exposed"]
    improved = ns["improved"] + cs["improved"]
    worsened = ns["worsened"] + cs["worsened"]
    blocked  = ns["blocked"] + cs["blocked"]

    with st.container(border=True):
        st.markdown('<div class="section-title">전사 순위 현황</div>', unsafe_allow_html=True)
        render_kpi_grid([
            ("추적 상품", f'{total}<span class="kpi-suffix">개</span>',
             f"네이버 {ns['total']} · 쿠팡 {cs['total']}"),
            ("노출 중", f'{exposed}<span class="kpi-suffix">/ {total}</span>', "검색결과 노출"),
            ("순위 상승", f'{improved}<span class="kpi-suffix">개</span>', "전일 대비"),
            ("순위 하락", f'{worsened}<span class="kpi-suffix">개</span>',
             f"차단 {blocked}건" if blocked else "전일 대비"),
        ])

    cn, cc = st.columns(2)
    for col, plat, s in ((cn, "naver", ns), (cc, "coupang", cs)):
        with col, st.container(border=True):
            pk = PLATFORM_KR[plat]
            st.markdown(f'<div class="section-title">{pk} 요약</div>', unsafe_allow_html=True)
            if s["total"] == 0:
                st.caption(f"등록된 {pk} 상품이 없습니다. [상품 관리]에서 추가하세요.")
            else:
                chips = (f'<span class="pill pill-blue">노출 {s["exposed"]}/{s["total"]}</span> '
                         f'<span class="pill pill-green">▲ {s["improved"]}</span> '
                         f'<span class="pill pill-red">▼ {s["worsened"]}</span>')
                if s["blocked"]:
                    chips += f' <span class="pill pill-amber">차단 {s["blocked"]}</span>'
                st.markdown(chips, unsafe_allow_html=True)
                avg = f'{s["avg_rank"]}위' if s["avg_rank"] else "—"
                st.caption(f"노출 상품 평균 순위 {avg} · 메뉴 [{pk} 전략]에서 상세 확인")

    with st.container(border=True):
        st.markdown('<div class="section-title">주의가 필요한 상품</div>', unsafe_allow_html=True)
        alerts: list[str] = []
        for p in naver + coupang:
            latest = db.get_latest_rank(p["id"])
            rank, status = _rank_state(dict(latest) if latest else None)
            delta = db.get_rank_delta(p["id"])
            reason = ""
            if status == "blocked":
                reason = '<span class="pill pill-amber">차단</span>'
            elif status == "error":
                reason = '<span class="pill pill-red">오류</span>'
            elif rank == 0 and status != "none":
                reason = '<span class="pill pill-slate">미노출</span>'
            elif delta is not None and delta < 0:
                reason = f'<span class="pill pill-red">▼ -{abs(delta)} 하락</span>'
            if reason:
                alerts.append(
                    f'<div class="alert-row"><span class="pill pill-slate">'
                    f'{PLATFORM_KR[p["platform"]]}</span>'
                    f'<span class="alert-name">{_safe(p["name"], 50)}</span>{reason}</div>')
        if alerts:
            st.markdown("".join(alerts), unsafe_allow_html=True)
        else:
            st.caption("현재 주의가 필요한 상품이 없습니다. 모든 지표가 안정적입니다.")


# ---------------------------------------------------------------------------
# Page: 전략 (품목 SPA + 카드)
# ---------------------------------------------------------------------------

def _gap_pill(value: Optional[int], unit: str, higher_is_bad: bool = True) -> str:
    """가격/리뷰 격차 Pill — higher_is_bad: 양수가 나쁜 지표(가격)인지."""
    if value is None:
        return '<span class="pill pill-slate">비교 불가</span>'
    if value == 0:
        return '<span class="pill pill-slate">동일</span>'
    bad = (value > 0) if higher_is_bad else (value < 0)
    cls = "pill-red" if bad else "pill-green"
    sign = "+" if value > 0 else "-"
    return f'<span class="pill {cls}">{sign}{abs(value):,}{unit}</span>'


def _render_competitor_block(analysis, product: dict,
                              competitors: list[dict]) -> None:
    """경쟁 지표 비교 + 경쟁사 Top5 테이블 HTML 렌더."""
    m = analysis.metrics or {}

    # ── 경쟁 지표 비교 카드 (가격 / 리뷰) ──
    blocks = []
    if m.get("comp_avg_price") and m.get("my_price"):
        blocks.append(
            f'<div class="cmp-metric"><div class="cmp-metric-label">가격 경쟁력</div>'
            f'<div class="cmp-row"><span class="cmp-mine">{_won(m["my_price"])}</span>'
            f'<span class="cmp-vs">vs 경쟁사 평균 '
            f'<b class="cmp-comp">{_won(m["comp_avg_price"])}</b></span></div>'
            f'<div class="cmp-gap">{_gap_pill(m.get("price_gap"), "원", True)}</div></div>')
    if m.get("comp_avg_reviews") is not None and m.get("my_reviews") is not None:
        blocks.append(
            f'<div class="cmp-metric"><div class="cmp-metric-label">리뷰 신뢰도</div>'
            f'<div class="cmp-row"><span class="cmp-mine">{_cnt(m["my_reviews"])}개</span>'
            f'<span class="cmp-vs">vs 경쟁사 평균 '
            f'<b class="cmp-comp">{_cnt(m["comp_avg_reviews"])}개</b></span></div>'
            f'<div class="cmp-gap">{_gap_pill(m.get("review_gap"), "개", False)}</div></div>')
    if blocks:
        st.markdown('<div class="ai-label">경쟁 지표 비교</div>', unsafe_allow_html=True)
        st.markdown(f'<div class="cmp-grid">{"".join(blocks)}</div>', unsafe_allow_html=True)

    # ── 경쟁사 Top5 테이블 ──
    valid = [c for c in competitors if c.get("price") or c.get("review_count")]
    if valid:
        rows = ""
        my_p = m.get("my_price")
        my_r = m.get("my_reviews")
        rows += (f'<tr class="cmp-me"><td>당사</td>'
                 f'<td class="nm">{_safe(product["name"], 28)}</td>'
                 f'<td>{_won(my_p)}</td><td>{_cnt(my_r)}</td></tr>')
        for c in valid[:5]:
            rows += (f'<tr><td>{c.get("rank","")}위</td>'
                     f'<td class="nm">{_safe(c.get("name"), 28)}</td>'
                     f'<td>{_won(c.get("price"))}</td>'
                     f'<td>{_cnt(c.get("review_count"))}</td></tr>')
        st.markdown('<div class="ai-label">경쟁사 Top5 비교</div>', unsafe_allow_html=True)
        st.markdown(
            f'<table class="cmp-table"><thead><tr><th>순위</th><th>상품</th>'
            f'<th>가격</th><th>리뷰</th></tr></thead><tbody>{rows}</tbody></table>',
            unsafe_allow_html=True)


def _render_strategy_card(product: dict, days: int) -> None:
    pid    = product["id"]
    latest = db.get_latest_rank(pid)
    latest_d = dict(latest) if latest else None
    rank, status = _rank_state(latest_d)
    delta = db.get_rank_delta(pid)
    competitors = load_latest_competitors(pid)

    analysis = ai_advisor.analyze_product(
        name=product["name"], platform=product["platform"], keyword=product["keyword"],
        rank=rank, delta=delta, status=status,
        my_price=(latest_d or {}).get("price"),
        my_review_count=(latest_d or {}).get("review_count"),
        competitors=competitors,
    )

    with st.container(border=True):
        # ── 타이포 위계: 키워드 Pill · 상품명 24px · 순위 36px ──
        st.markdown(
            f'<div><span class="kw-pill">키워드 · {_safe(product["keyword"], 40)}</span></div>'
            f'<div class="strat-flex">'
            f'  <div class="prod-name-lg">{_safe(product["name"], 60)}</div>'
            f'  <div class="rank-block">'
            f'    <div class="rank-cap">현재 순위</div>'
            f'    {_rank_big(rank, status)}'
            f'    <div style="margin-top:6px;">{_delta_pill(delta, rank, status)}</div>'
            f'  </div>'
            f'</div>',
            unsafe_allow_html=True)

        # ── 미니멀 순위 트렌드 ──
        df = load_rank_history(pid, days)
        st.markdown('<div class="ai-label" style="color:#64748b;">'
                    f'순위 트렌드 · 최근 {days}일</div>', unsafe_allow_html=True)
        st.plotly_chart(build_trend_chart(df), use_container_width=True,
                        key=f"trend_{pid}_{days}", config={"displayModeBar": False})

        # ── AI 전략 분석 ──
        actions = "".join(f"<li>{_safe(a, 160)}</li>" for a in analysis.action_plan)
        st.markdown(
            f'<div class="ai-box ai-{analysis.tone}">'
            f'  <div class="ai-head">AI 전략 분석 <span class="ai-beta">BETA</span></div>'
            f'  <div class="ai-label">분석 결과</div>'
            f'  <div class="ai-text">{_safe(analysis.summary, 400)}</div>'
            f'</div>',
            unsafe_allow_html=True)
        with st.container(border=True):
            _render_competitor_block(analysis, product, competitors)
            st.markdown('<div class="ai-label">권장 액션플랜</div>', unsafe_allow_html=True)
            st.markdown(f'<ul class="ai-actions">{actions}</ul>', unsafe_allow_html=True)


def render_strategy_page(platform: str) -> None:
    pk = PLATFORM_KR[platform]
    st.markdown(f'<div class="page-title">{pk} 전략</div>', unsafe_allow_html=True)
    st.markdown(
        f'<p class="page-sub">품목을 선택하면 해당 품목의 키워드별 순위·트렌드·'
        'AI 경쟁 분석만 집중해서 보여줍니다.</p>', unsafe_allow_html=True)

    products = load_products(platform)
    if not products:
        st.info(f"등록된 {pk} 상품이 없습니다. 사이드바 [상품 관리]에서 추가해 주세요.")
        return

    # 품목 목록 (그룹명, 미분류 포함)
    group_names = sorted({(p.get("group_name") or UNGROUPED_LABEL) for p in products},
                         key=lambda g: (g == UNGROUPED_LABEL, g))

    # ── 상단 컨트롤: 품목 Selectbox + 기간 (사이드바에서 이동) ──
    c1, c2 = st.columns([2, 1.4])
    with c1:
        selected = st.selectbox("품목 선택", group_names, key=f"strat_group_{platform}")
    with c2:
        period = st.radio("조회 기간", list(PERIOD_OPTIONS.keys()),
                          index=1, horizontal=True, key=f"strat_period_{platform}")
    days = PERIOD_OPTIONS[period]

    items = [p for p in products
             if (p.get("group_name") or UNGROUPED_LABEL) == selected]

    # ── 선택 품목 KPI ──
    stats = _platform_stats(items)
    with st.container(border=True):
        st.markdown(f'<div class="section-title">품목 · {_safe(selected, 40)}</div>',
                    unsafe_allow_html=True)
        render_kpi_grid([
            ("키워드", f'{stats["total"]}<span class="kpi-suffix">개</span>', "추적 중"),
            ("노출 중", f'{stats["exposed"]}<span class="kpi-suffix">/ {stats["total"]}</span>',
             "검색결과 노출"),
            ("평균 순위", (f'{stats["avg_rank"]}<span class="kpi-suffix">위</span>'
                        if stats["avg_rank"] else "—"), "노출 상품 기준"),
            ("순위 하락", f'{stats["worsened"]}<span class="kpi-suffix">개</span>',
             f"차단 {stats['blocked']} · 오류 {stats['errored']}"),
        ])

    # ── 키워드별 카드 ──
    for product in items:
        _render_strategy_card(product, days)


# ---------------------------------------------------------------------------
# Page: 상품 관리 (품목 계층형)
# ---------------------------------------------------------------------------

def _render_registration_form(platform: str) -> None:
    hints = PLATFORM_FORM_HINTS[platform]
    pk = PLATFORM_KR[platform]
    all_products = load_all_products(platform)
    groups = load_groups(platform)

    with st.container(border=True):
        st.markdown(f'<div class="section-title">{pk} 상품 등록 / 수정</div>',
                    unsafe_allow_html=True)
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
        defaults = edit_target or {}

        group_names = [g["name"] for g in groups]
        group_mode = st.radio("품목 (상위 분류)", ["기존 품목 선택", "새 품목 추가"],
                              index=0 if group_names else 1, horizontal=True,
                              key=f"gmode_{platform}_{key_suffix}")
        chosen_group_id: Optional[int] = None
        new_group_name = ""
        if group_mode == "기존 품목 선택":
            if not group_names:
                st.caption("등록된 품목이 없습니다. '새 품목 추가'를 선택하세요.")
            else:
                cur = defaults.get("group_name")
                idx = group_names.index(cur) if cur in group_names else 0
                picked = st.selectbox("품목 선택", group_names, index=idx,
                                      key=f"gpick_{platform}_{key_suffix}")
                chosen_group_id = groups[group_names.index(picked)]["id"]
        else:
            new_group_name = st.text_input("새 품목명", placeholder=hints["group_placeholder"],
                                           key=f"gnew_{platform}_{key_suffix}")

        name = st.text_input("상품명", value=str(defaults.get("name") or ""),
                             placeholder=hints["name_placeholder"],
                             key=f"name_{platform}_{key_suffix}")
        keyword = st.text_input("타겟 키워드", value=str(defaults.get("keyword") or ""),
                                placeholder=hints["keyword_placeholder"],
                                key=f"kw_{platform}_{key_suffix}")
        target_url = st.text_input(hints["url_label"], value=str(defaults.get("target_url") or ""),
                                   placeholder=hints["url_placeholder"], help=hints["url_help"],
                                   key=f"url_{platform}_{key_suffix}")
        target_id = st.text_input(hints["id_label"], value=str(defaults.get("target_id") or ""),
                                  placeholder=hints["id_placeholder"], help=hints["id_help"],
                                  key=f"tid_{platform}_{key_suffix}")

        if mode == "수정" and edit_target is not None:
            label, btn_key = "수정 저장", f"save_{platform}_{edit_target['id']}"
        else:
            label, btn_key = f"{pk} 상품 추가", f"add_{platform}"

        if st.button(label, type="primary", use_container_width=True, key=btn_key):
            raw_url, raw_id = target_url.strip(), target_id.strip()
            effective_id = raw_id or (db.extract_product_id(platform, raw_url) or "")
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
                db.update_product(product_id=edit_target["id"], name=name.strip(),
                                  keyword=keyword.strip(), target_id=effective_id or None,
                                  target_url=raw_url or None, group_id=resolved_group_id)
                st.cache_data.clear()
                st.success(f"수정 완료 (ID: {edit_target['id']})")
                st.rerun()
            else:
                new_id = db.add_product(name=name.strip(), platform=platform,
                                        keyword=keyword.strip(), target_id=effective_id or None,
                                        target_url=raw_url or None, group_id=resolved_group_id)
                st.cache_data.clear()
                st.success(f"{pk} 상품 추가 완료 (ID: {new_id})")
                st.rerun()


def _render_grouped_list(platform: str) -> None:
    pk = PLATFORM_KR[platform]
    all_products = load_all_products(platform)
    with st.container(border=True):
        st.markdown(f'<div class="section-title">{pk} 품목별 상품 목록</div>',
                    unsafe_allow_html=True)
        if not all_products:
            st.caption(f"등록된 {pk} 상품이 없습니다. 좌측에서 추가해 주세요.")
            return

        buckets: dict[str, list[dict]] = {}
        for p in all_products:
            buckets.setdefault(p.get("group_name") or UNGROUPED_LABEL, []).append(p)
        ordered = sorted(buckets.items(), key=lambda kv: (kv[0] == UNGROUPED_LABEL, kv[0]))

        ratios = [0.5, 2.3, 1.9, 1.1, 0.9, 0.7]
        for gname, items in ordered:
            with st.expander(f"{gname}  ·  {len(items)}개 상품", expanded=True):
                hdr = st.columns(ratios)
                for i, lbl in enumerate(["ID", "상품명", "키워드", "현재 순위", "상태", ""]):
                    hdr[i].markdown(
                        f"<div class='prod-table-head' style='text-align:center;'>{lbl}</div>",
                        unsafe_allow_html=True)
                st.markdown("<hr style='margin:2px 0 4px 0;'/>", unsafe_allow_html=True)
                for product in items:
                    latest = db.get_latest_rank(product["id"])
                    rank, status = _rank_state(dict(latest) if latest else None)
                    is_active = bool(product["active"])
                    row = st.columns(ratios)
                    row[0].markdown(f"<div class='tr-cell center muted mono'>#{product['id']}</div>",
                                    unsafe_allow_html=True)
                    row[1].markdown(f"<div class='tr-cell strong'>{_safe(product['name'], 44)}</div>",
                                    unsafe_allow_html=True)
                    row[2].markdown(f"<div class='tr-cell muted'>{_safe(product['keyword'], 30)}</div>",
                                    unsafe_allow_html=True)
                    row[3].markdown(f"<div class='tr-cell center'>{_rank_pill(rank, status)}</div>",
                                    unsafe_allow_html=True)
                    active_pill = ('<span class="pill pill-green">활성</span>' if is_active
                                   else '<span class="pill pill-slate">비활성</span>')
                    row[4].markdown(f"<div class='tr-cell center'>{active_pill}</div>",
                                    unsafe_allow_html=True)
                    bc = row[5].columns(2)
                    if bc[0].button("⇄", key=f"tg_{platform}_{product['id']}",
                                    help="활성/비활성 전환", use_container_width=True):
                        db.update_product(product["id"], active=not is_active)
                        st.cache_data.clear()
                        st.rerun()
                    if bc[1].button("🗑", key=f"del_{platform}_{product['id']}",
                                    help="삭제", use_container_width=True):
                        st.session_state["pending_delete"] = {
                            "id": product["id"], "name": product["name"],
                            "platform": product["platform"]}
                        st.rerun()
        st.caption(f"총 {len(all_products)}개 {pk} 상품 · {len(ordered)}개 품목")


def render_manage_page() -> None:
    st.markdown('<div class="page-title">상품 관리</div>', unsafe_allow_html=True)
    st.markdown('<p class="page-sub">네이버·쿠팡 상품을 품목(상위 분류) 기준으로 '
                '계층 관리합니다. 플랫폼별 섹션이 독립 분리돼 있습니다.</p>',
                unsafe_allow_html=True)
    for platform in ("naver", "coupang"):
        st.markdown(f'<div class="section-title" style="font-size:1.05rem;margin-top:4px;">'
                    f'{PLATFORM_KR[platform]} 상품 관리</div>', unsafe_allow_html=True)
        left, right = st.columns([1, 1.7], gap="large")
        with left:
            _render_registration_form(platform)
        with right:
            _render_grouped_list(platform)
        if platform == "naver":
            st.markdown("<hr/>", unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

nav = st.session_state.nav
if nav == "naver":
    render_strategy_page("naver")
elif nav == "coupang":
    render_strategy_page("coupang")
elif nav == "manage":
    render_manage_page()
else:
    render_home()

if st.session_state.get("pending_delete"):
    _confirm_delete_dialog()
