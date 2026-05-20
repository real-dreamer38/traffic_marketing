"""
dashboard.py — Streamlit marketing automation dashboard (MVP 1차).

Run:
    streamlit run dashboard.py

Design system
-------------
라이트 미니멀 + 카드형 UI (Linear / Vercel 톤).
  bg       #ffffff
  surface  #f8fafc   card background
  border   #e5e7eb   1px
  text     #0f172a   heading
  muted    #64748b   subtle text
  accent   #4f46e5   primary
  pills    green / red / slate / blue (pastel)
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

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="순위 모니터링",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

db.init_db()

PLATFORM_KR = {"naver": "네이버", "coupang": "쿠팡"}

# ---------------------------------------------------------------------------
# Global CSS — single <style> block (no leaked text, @import inside)
# ---------------------------------------------------------------------------

CSS = """<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');

html, body, [class*="css"], [class*="st-"] {
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, system-ui, sans-serif !important;
}
.stApp { background: #ffffff !important; color: #0f172a; }

/* hide Streamlit chrome */
#MainMenu, footer, header[data-testid="stHeader"] { visibility: hidden; height: 0; }

/* hide leaked Material icon text on st.metric delta arrows */
[data-testid="stMetricDeltaIcon-Up"],
[data-testid="stMetricDeltaIcon-Down"] { display: none !important; }

.block-container {
    padding-top: 2rem !important;
    padding-bottom: 3rem !important;
    max-width: 1280px;
}

/* ── Page header ───────────────────────────────────────────── */
.page-title {
    font-size: 1.85rem;
    font-weight: 800;
    letter-spacing: -0.03em;
    color: #0f172a;
    margin: 0 0 0.35rem 0;
    line-height: 1.2;
}
.page-sub {
    color: #64748b;
    font-size: 0.95rem;
    font-weight: 400;
    margin: 0 0 1.8rem 0;
}

/* ── Section title ─────────────────────────────────────────── */
.section-title {
    font-size: 0.95rem;
    font-weight: 700;
    color: #0f172a;
    margin: 0 0 1rem 0;
    letter-spacing: -0.01em;
}

/* ── Sidebar ───────────────────────────────────────────────── */
[data-testid="stSidebar"] {
    background: #f8fafc !important;
    border-right: 1px solid #e5e7eb;
}
[data-testid="stSidebar"] h1 {
    font-size: 1.1rem !important;
    font-weight: 700 !important;
    color: #0f172a !important;
}
[data-testid="stSidebar"] hr {
    border-color: #e5e7eb;
    opacity: 1;
    margin: 1rem 0;
}

/* ── Tabs ──────────────────────────────────────────────────── */
.stTabs [data-baseweb="tab-list"] {
    gap: 4px;
    background: transparent;
    padding: 0;
    border-bottom: 1px solid #e5e7eb;
}
.stTabs [data-baseweb="tab"] {
    height: 40px;
    padding: 0 16px;
    background: transparent;
    border-radius: 0;
    color: #64748b;
    font-weight: 600;
    font-size: 0.95rem;
    border-bottom: 2px solid transparent;
    margin-bottom: -1px;
}
.stTabs [data-baseweb="tab"]:hover { color: #0f172a; }
.stTabs [aria-selected="true"] {
    background: transparent !important;
    color: #0f172a !important;
    border-bottom: 2px solid #4f46e5 !important;
    font-weight: 700 !important;
}
.stTabs [data-baseweb="tab-highlight"],
.stTabs [data-baseweb="tab-border"] { background: transparent !important; }

/* ── Card wrapper — st.container(border=True) ─────────────── */
[data-testid="stVerticalBlockBorderWrapper"] {
    background: #ffffff;
    border: 1px solid #e5e7eb !important;
    border-radius: 14px !important;
    padding: 22px 24px !important;
    box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04),
                0 4px 12px rgba(15, 23, 42, 0.03);
    margin-bottom: 16px;
}

/* ── KPI grid (custom HTML, no st.metric arrows) ──────────── */
.kpi-grid {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 14px;
}
.kpi-card {
    background: #f8fafc;
    border: 1px solid #e5e7eb;
    border-radius: 12px;
    padding: 18px 20px;
    transition: border-color 0.15s ease, transform 0.15s ease;
}
.kpi-card:hover {
    border-color: #cbd5e1;
    transform: translateY(-1px);
}
.kpi-label {
    font-size: 0.82rem;
    color: #64748b;
    font-weight: 500;
    margin-bottom: 8px;
    letter-spacing: -0.005em;
}
.kpi-value {
    font-size: 2rem;
    font-weight: 800;
    color: #0f172a;
    letter-spacing: -0.03em;
    line-height: 1.1;
}
.kpi-value .kpi-suffix {
    font-size: 1rem;
    font-weight: 600;
    color: #64748b;
    margin-left: 4px;
}
@media (max-width: 900px) {
    .kpi-grid { grid-template-columns: repeat(2, 1fr); }
}

/* ── Product cards grid ───────────────────────────────────── */
.prod-grid {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 14px;
}
.prod-card {
    background: #f8fafc;
    border: 1px solid #e5e7eb;
    border-radius: 12px;
    padding: 16px 18px;
    transition: border-color 0.15s ease;
}
.prod-card:hover { border-color: #cbd5e1; }
.prod-meta {
    font-size: 0.74rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    color: #64748b;
    margin-bottom: 6px;
}
.prod-name {
    font-size: 0.95rem;
    font-weight: 600;
    color: #0f172a;
    margin-bottom: 10px;
    line-height: 1.35;
    /* truncate over 2 lines */
    display: -webkit-box;
    -webkit-line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
    min-height: 2.5em;
}
.prod-rank {
    font-size: 1.65rem;
    font-weight: 800;
    color: #0f172a;
    letter-spacing: -0.025em;
    line-height: 1;
    margin-bottom: 10px;
}
.prod-rank.dimmed { color: #94a3b8; font-weight: 700; }
@media (max-width: 900px) {
    .prod-grid { grid-template-columns: repeat(2, 1fr); }
}

/* ── Pastel pill tags ─────────────────────────────────────── */
.pill {
    display: inline-flex;
    align-items: center;
    gap: 3px;
    padding: 3px 10px;
    border-radius: 999px;
    font-size: 0.78rem;
    font-weight: 600;
    letter-spacing: -0.005em;
    line-height: 1.3;
}
.pill-green { background: #dcfce7; color: #166534; }
.pill-red   { background: #fee2e2; color: #991b1b; }
.pill-slate { background: #f1f5f9; color: #475569; }
.pill-blue  { background: #dbeafe; color: #1e40af; }

/* ── Buttons ───────────────────────────────────────────────── */
.stButton > button {
    border-radius: 8px;
    border: 1px solid #e5e7eb;
    background: #ffffff;
    color: #0f172a;
    padding: 8px 16px;
    font-weight: 600;
    font-size: 0.9rem;
    box-shadow: none;
    transition: background 0.12s ease, border-color 0.12s ease;
}
.stButton > button:hover {
    background: #f8fafc;
    border-color: #cbd5e1;
    transform: none;
    box-shadow: none;
}
.stButton > button[kind="primary"] {
    background: #0f172a;
    border: 1px solid #0f172a;
    color: #ffffff;
    font-weight: 700;
}
.stButton > button[kind="primary"]:hover {
    background: #1e293b;
    border-color: #1e293b;
}

/* ── Inputs ────────────────────────────────────────────────── */
.stTextInput input, .stTextArea textarea,
.stNumberInput input, .stDateInput input,
[data-baseweb="select"] > div {
    background: #ffffff !important;
    border: 1px solid #e5e7eb !important;
    border-radius: 8px !important;
    color: #0f172a !important;
    font-size: 0.9rem;
}
.stTextInput input:focus, .stTextArea textarea:focus,
.stNumberInput input:focus, .stDateInput input:focus {
    border-color: #4f46e5 !important;
    box-shadow: 0 0 0 3px rgba(79, 70, 229, 0.14) !important;
    outline: none !important;
}
.stTextInput label, .stSelectbox label, .stNumberInput label,
.stDateInput label, .stTextArea label, .stRadio label {
    color: #334155 !important;
    font-size: 0.85rem !important;
    font-weight: 600 !important;
}

/* slider */
.stSlider [data-baseweb="slider"] > div > div > div { background: #4f46e5; }

/* radio pill */
.stRadio [role="radiogroup"] label {
    background: #ffffff;
    border: 1px solid #e5e7eb;
    border-radius: 8px;
    padding: 6px 12px;
    margin-right: 6px;
    font-size: 0.88rem;
    font-weight: 500;
}
.stRadio [role="radiogroup"] label:hover {
    border-color: #cbd5e1;
    background: #f8fafc;
}

/* Dataframe — center alignment enforced via pandas Styler too */
[data-testid="stDataFrame"] {
    border: 1px solid #e5e7eb;
    border-radius: 10px;
    overflow: hidden;
    box-shadow: none;
}
[data-testid="stDataFrame"] [data-testid="stDataFrameResizable"] {
    background: #ffffff;
}

/* Alerts */
[data-testid="stAlert"] {
    border-radius: 10px;
    border: 1px solid #e5e7eb;
    background: #f8fafc;
}

/* Expander */
.streamlit-expanderHeader,
[data-testid="stExpander"] details > summary {
    background: #ffffff !important;
    border: 1px solid #e5e7eb !important;
    border-radius: 8px !important;
    font-weight: 600 !important;
    color: #334155 !important;
}

hr { border-color: #e5e7eb !important; opacity: 1; margin: 1.5rem 0; }

/* Status pill in sidebar */
.status-pill {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    background: #ffffff;
    border: 1px solid #e5e7eb;
    border-radius: 999px;
    padding: 4px 10px;
    font-size: 0.78rem;
    color: #334155;
    font-weight: 600;
}
.status-pill .dot { width: 6px; height: 6px; border-radius: 50%; background: #22c55e; }
.status-pill.warn .dot { background: #f59e0b; }

/* fix any rogue label rendering */
.stCaption, [data-testid="stCaptionContainer"] {
    color: #64748b !important;
    font-weight: 400;
}
</style>"""

st.markdown(CSS, unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Page header
# ---------------------------------------------------------------------------

st.markdown('<div class="page-title">순위 모니터링</div>', unsafe_allow_html=True)
st.markdown(
    '<p class="page-sub">네이버 · 쿠팡 검색 순위 일일 추적. 매일 아침 텔레그램으로 자동 리포트가 전송됩니다.</p>',
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

with st.sidebar:
    st.title("설정")
    st.divider()

    st.markdown('<div class="section-title">알림 채널</div>', unsafe_allow_html=True)
    tg_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    tg_chat  = os.getenv("TELEGRAM_CHAT_ID", "")
    if tg_token and tg_chat:
        st.markdown(
            '<span class="status-pill"><span class="dot"></span>Telegram 연결됨</span>',
            unsafe_allow_html=True,
        )
        st.caption(f"chat_id: {tg_chat}")
    else:
        st.markdown(
            '<span class="status-pill warn"><span class="dot"></span>Telegram 미설정</span>',
            unsafe_allow_html=True,
        )
        st.caption(".env 의 TELEGRAM_BOT_TOKEN / CHAT_ID 확인")

    st.divider()
    st.markdown('<div class="section-title">조회 옵션</div>', unsafe_allow_html=True)
    trend_days = st.slider(
        "트렌드 기간 (일)",
        min_value=7, max_value=90, value=30, step=7,
        key="sidebar_trend_days_slider",
    )

    st.divider()
    if st.button("데이터 새로고침", use_container_width=True, key="sidebar_refresh_btn"):
        st.cache_data.clear()
        st.rerun()

    st.caption(f"마지막 로드 · {datetime.now().strftime('%H:%M:%S')}")


# ---------------------------------------------------------------------------
# Cached data helpers
# ---------------------------------------------------------------------------

@st.cache_data(ttl=60)
def load_products() -> list[dict]:
    rows = db.list_products(active_only=True)
    return [dict(r) for r in rows]


@st.cache_data(ttl=60)
def load_rank_history(product_id: int, days: int) -> pd.DataFrame:
    rows = db.get_rank_history(product_id, days=days)
    if not rows:
        return pd.DataFrame(columns=["rank_date", "rank"])
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
# Pill / status helpers
# ---------------------------------------------------------------------------

def _delta_pill(delta: Optional[int], today_rank: int) -> str:
    """Return an HTML pill span for the rank delta."""
    if today_rank == 0:
        return '<span class="pill pill-slate">미노출</span>'
    if delta is None:
        return '<span class="pill pill-blue">신규</span>'
    if delta > 0:
        return f'<span class="pill pill-green">▲ {delta}</span>'
    if delta < 0:
        return f'<span class="pill pill-red">▼ {abs(delta)}</span>'
    return '<span class="pill pill-slate">변동없음</span>'


def _center_styled(df: pd.DataFrame):
    """가운데 정렬된 pandas Styler 를 반환 — 본문 + 헤더 모두 가운데."""
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
# Plotly chart
# ---------------------------------------------------------------------------

COMPETITOR_COLORS = ["#fb7185", "#fbbf24", "#a3e635", "#34d399", "#22d3ee"]


def build_trend_chart(
    product_name: str,
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
                    x=sub["rank_date"],
                    y=sub["rank"],
                    mode="lines+markers",
                    name=f"경쟁사 {int(rank_pos)}위",
                    line=dict(color=color, width=1.3, dash="dot"),
                    marker=dict(size=4, color=color),
                    customdata=sub["name"].fillna("").to_numpy().reshape(-1, 1),
                    hovertemplate=(
                        "<b>%{x|%Y-%m-%d}</b><br>"
                        "경쟁사 %{y}위<br>"
                        "%{customdata[0]}"
                        "<extra></extra>"
                    ),
                    opacity=0.7,
                )
            )

    if has_my_data:
        fig.add_trace(
            go.Scatter(
                x=df["rank_date"],
                y=df["rank_display"],
                mode="lines+markers",
                name="내 상품",
                line=dict(color="#4f46e5", width=2.8),
                marker=dict(size=8, color="#4f46e5", line=dict(color="#ffffff", width=1.5)),
                hovertemplate="<b>%{x|%Y-%m-%d}</b><br>내 순위: %{y}위<extra></extra>",
                connectgaps=False,
            )
        )

    if not has_my_data and (competitors_df is None or competitors_df.empty):
        fig.add_annotation(
            text="데이터 없음",
            xref="paper", yref="paper",
            x=0.5, y=0.5, showarrow=False,
            font=dict(size=14, color="#94a3b8"),
        )

    valid_my = df["rank_display"].dropna() if has_my_data else pd.Series(dtype=float)
    valid_comp = (
        competitors_df["rank"] if (competitors_df is not None and not competitors_df.empty)
        else pd.Series(dtype=float)
    )
    pool = pd.concat([valid_my, valid_comp], ignore_index=True)
    y_max = int(pool.max()) + 5 if not pool.empty else 50

    fig.update_layout(
        height=400,
        margin=dict(l=10, r=10, t=20, b=10),
        paper_bgcolor="#ffffff",
        plot_bgcolor="#ffffff",
        font=dict(color="#334155", family="Inter, sans-serif", size=12),
        yaxis=dict(
            title=dict(text="순위", font=dict(size=12, color="#64748b")),
            autorange="reversed",
            range=[y_max, 0],
            gridcolor="#f1f5f9",
            linecolor="#e5e7eb",
            zeroline=False,
            ticksuffix="위",
        ),
        xaxis=dict(
            title="",
            gridcolor="#f1f5f9",
            linecolor="#e5e7eb",
            zeroline=False,
        ),
        showlegend=True,
        legend=dict(
            orientation="h",
            yanchor="bottom", y=1.02,
            xanchor="right",  x=1,
            bgcolor="rgba(255,255,255,0)",
            font=dict(size=11, color="#64748b"),
        ),
    )
    return fig


# ---------------------------------------------------------------------------
# KPI + product grids — single HTML render
# ---------------------------------------------------------------------------

def render_kpi_grid(total: int, exposed: int, improved: int, worsened: int) -> None:
    html = f"""
    <div class="kpi-grid">
        <div class="kpi-card">
            <div class="kpi-label">등록 상품</div>
            <div class="kpi-value">{total}<span class="kpi-suffix">개</span></div>
        </div>
        <div class="kpi-card">
            <div class="kpi-label">노출 중</div>
            <div class="kpi-value">{exposed}<span class="kpi-suffix">/ {total}</span></div>
        </div>
        <div class="kpi-card">
            <div class="kpi-label">순위 상승</div>
            <div class="kpi-value">{improved}<span class="kpi-suffix">개</span></div>
        </div>
        <div class="kpi-card">
            <div class="kpi-label">순위 하락</div>
            <div class="kpi-value">{worsened}<span class="kpi-suffix">개</span></div>
        </div>
    </div>
    """
    st.markdown(html, unsafe_allow_html=True)


def render_product_grid(products: list[dict]) -> None:
    """4-column responsive grid of product cards — each with rank + pastel pill."""
    cards: list[str] = []
    for product in products:
        latest   = db.get_latest_rank(product["id"])
        delta    = db.get_rank_delta(product["id"])
        rank_now = latest["rank"] if latest else 0
        platform = PLATFORM_KR.get(product["platform"], product["platform"])
        name_esc = _html.escape(product["name"])

        rank_class = "prod-rank dimmed" if rank_now == 0 else "prod-rank"
        rank_str   = "미노출" if rank_now == 0 else f"{rank_now}<span style='font-size:0.95rem;font-weight:600;color:#64748b;margin-left:2px;'>위</span>"
        pill_html  = _delta_pill(delta, rank_now)

        cards.append(
            f"""
            <div class="prod-card">
                <div class="prod-meta">{platform}</div>
                <div class="prod-name">{name_esc}</div>
                <div class="{rank_class}">{rank_str}</div>
                {pill_html}
            </div>
            """
        )

    st.markdown(f'<div class="prod-grid">{"".join(cards)}</div>', unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Tab 1 — 순위 현황
# ---------------------------------------------------------------------------

def render_rank_tab(products: list[dict]) -> None:
    if not products:
        st.info("등록된 상품이 없습니다. [상품 관리] 탭에서 추가해 주세요.")
        return

    total = len(products)
    exposed = improved = worsened = 0
    for p in products:
        latest = db.get_latest_rank(p["id"])
        delta  = db.get_rank_delta(p["id"])
        rank   = latest["rank"] if latest else 0
        if rank > 0:
            exposed += 1
        if delta is not None and delta > 0:
            improved += 1
        elif delta is not None and delta < 0:
            worsened += 1

    # ── Card 1: KPI ──
    with st.container(border=True):
        st.markdown('<div class="section-title">전체 요약</div>', unsafe_allow_html=True)
        render_kpi_grid(total, exposed, improved, worsened)

    # ── Card 2: 상품별 현재 순위 ──
    with st.container(border=True):
        st.markdown('<div class="section-title">상품별 현재 순위</div>', unsafe_allow_html=True)
        render_product_grid(products)

    # ── Card 3: 트렌드 차트 ──
    with st.container(border=True):
        st.markdown('<div class="section-title">순위 트렌드</div>', unsafe_allow_html=True)

        product_names = [
            f"{p['name']} · {PLATFORM_KR.get(p['platform'], p['platform'])}"
            for p in products
        ]
        selected_label = st.selectbox(
            "상품 선택",
            options=product_names,
            label_visibility="collapsed",
            key="rank_product_select",
        )
        selected_idx  = product_names.index(selected_label)
        selected_prod = products[selected_idx]

        df             = load_rank_history(selected_prod["id"], trend_days)
        competitors_df = load_competitor_history(selected_prod["id"], trend_days)
        fig            = build_trend_chart(selected_prod["name"], df, competitors_df)
        st.plotly_chart(fig, use_container_width=True)

    # ── Card 4: 원본 데이터 ──
    with st.container(border=True):
        st.markdown('<div class="section-title">원본 데이터</div>', unsafe_allow_html=True)

        col_a, col_b = st.columns(2)

        with col_a:
            st.caption("내 상품 순위 이력")
            if df.empty:
                st.caption("데이터 없음")
            else:
                display_df = df[["rank_date", "rank"]].copy()
                display_df.columns = ["날짜", "순위"]
                display_df["날짜"] = display_df["날짜"].dt.strftime("%Y-%m-%d")
                display_df["순위"] = display_df["순위"].apply(
                    lambda x: "미노출" if x == 0 else f"{x}위"
                )
                st.dataframe(
                    _center_styled(display_df),
                    use_container_width=True,
                    hide_index=True,
                )

        with col_b:
            st.caption("경쟁사 Top 5 (최신일자)")
            if competitors_df.empty:
                st.caption("경쟁사 데이터 없음 — 다음 스크래핑 후 채워집니다.")
            else:
                latest_date = competitors_df["rank_date"].max()
                snap = competitors_df[competitors_df["rank_date"] == latest_date][
                    ["rank", "name"]
                ].copy()
                snap.columns = ["순위", "상품명"]
                snap["순위"] = snap["순위"].apply(lambda x: f"{int(x)}위")
                st.dataframe(
                    _center_styled(snap),
                    use_container_width=True,
                    hide_index=True,
                )


# ---------------------------------------------------------------------------
# Tab 2 — 상품 관리
# ---------------------------------------------------------------------------

@st.cache_data(ttl=30)
def load_management_overview() -> pd.DataFrame:
    rows = db.list_products(active_only=False)
    records: list[dict] = []
    for r in rows:
        p = dict(r)
        latest = db.get_latest_rank(p["id"])
        rank_str = "미노출" if (not latest or latest["rank"] == 0) else f"{latest['rank']}위"
        created = (p["created_at"] or "")[:10]
        records.append({
            "ID":         p["id"],
            "상품명":      p["name"],
            "키워드":      p["keyword"],
            "플랫폼":      PLATFORM_KR.get(p["platform"], p["platform"]),
            "현재 순위":   rank_str,
            "등록일":      created,
            "상태":        "활성" if p["active"] else "중지",
        })
    return pd.DataFrame(records)


def render_manage_tab() -> None:
    all_products_full = [dict(p) for p in db.list_products(active_only=False)]

    left, right = st.columns([1, 1.7], gap="large")

    # ── 좌측 카드: 등록 / 수정 폼 ─────────────────────────────
    with left:
        with st.container(border=True):
            st.markdown('<div class="section-title">상품 등록 / 수정</div>',
                        unsafe_allow_html=True)

            mode = st.radio(
                "작업 모드",
                ["추가", "수정"],
                horizontal=True,
                key="manage_mode_radio",
                label_visibility="collapsed",
            )

            edit_target: Optional[dict] = None
            if mode == "수정":
                if not all_products_full:
                    st.info("등록된 상품이 없습니다. 먼저 추가해 주세요.")
                else:
                    edit_labels = [f"[{p['id']}] {p['name']}" for p in all_products_full]
                    pick = st.selectbox(
                        "수정할 상품",
                        edit_labels,
                        key="manage_edit_target_select",
                    )
                    edit_target = all_products_full[edit_labels.index(pick)]

            key_suffix = f"edit_{edit_target['id']}" if edit_target else "add"
            defaults   = edit_target or {}

            name = st.text_input(
                "상품명",
                value=str(defaults.get("name") or ""),
                placeholder="친환경 에어캡",
                key=f"manage_name_input_{key_suffix}",
            )

            platform_opts = ["naver", "coupang"]
            platform_idx  = (
                platform_opts.index(defaults["platform"])
                if defaults.get("platform") in platform_opts else 0
            )
            platform = st.selectbox(
                "플랫폼",
                platform_opts,
                index=platform_idx,
                format_func=lambda x: PLATFORM_KR[x],
                key=f"manage_platform_select_{key_suffix}",
            )

            keyword = st.text_input(
                "타겟 키워드",
                value=str(defaults.get("keyword") or ""),
                placeholder="친환경 에어캡",
                key=f"manage_keyword_input_{key_suffix}",
            )

            target_id = st.text_input(
                "상품 ID",
                value=str(defaults.get("target_id") or ""),
                placeholder="40155252748",
                key=f"manage_target_id_input_{key_suffix}",
            )

            target_url = st.text_input(
                "상품 URL",
                value=str(defaults.get("target_url") or ""),
                placeholder="https://smartstore.naver.com/...",
                key=f"manage_target_url_input_{key_suffix}",
            )

            if mode == "수정" and edit_target is not None:
                submit_label = "수정 저장"
                submit_key   = f"manage_save_btn_{edit_target['id']}"
            else:
                submit_label = "상품 추가"
                submit_key   = "manage_add_btn"

            if st.button(submit_label, type="primary",
                         use_container_width=True, key=submit_key):
                if not name.strip() or not keyword.strip():
                    st.error("상품명과 키워드는 필수입니다.")
                elif edit_target is not None:
                    db.update_product(
                        product_id=edit_target["id"],
                        name=name.strip(),
                        keyword=keyword.strip(),
                        target_id=target_id.strip() or None,
                        target_url=target_url.strip() or None,
                    )
                    if platform != edit_target.get("platform"):
                        with db.get_conn() as conn:
                            conn.execute(
                                "UPDATE products SET platform = ? WHERE id = ?",
                                (platform, edit_target["id"]),
                            )
                    st.success(f"수정 완료 (ID: {edit_target['id']})")
                    st.cache_data.clear()
                    st.rerun()
                else:
                    new_id = db.add_product(
                        name=name.strip(),
                        platform=platform,
                        keyword=keyword.strip(),
                        target_id=target_id.strip() or None,
                        target_url=target_url.strip() or None,
                    )
                    st.success(f"상품 추가 완료 (ID: {new_id})")
                    st.cache_data.clear()
                    st.rerun()

    # ── 우측 카드: 상품 목록 + 빠른 작업 ───────────────────
    with right:
        with st.container(border=True):
            st.markdown('<div class="section-title">등록 상품 목록</div>',
                        unsafe_allow_html=True)

            overview_df = load_management_overview()
            if overview_df.empty:
                st.caption("등록된 상품이 없습니다. 좌측에서 추가해 주세요.")
                return

            column_order = ["ID", "상품명", "키워드", "플랫폼",
                            "현재 순위", "등록일", "상태"]
            st.dataframe(
                _center_styled(overview_df[column_order]),
                use_container_width=True,
                hide_index=True,
            )

            st.caption(f"총 {len(overview_df)}개 상품")

            st.markdown('<div class="section-title" style="margin-top:1.2rem;">빠른 작업</div>',
                        unsafe_allow_html=True)
            action_labels = [f"[{p['id']}] {p['name']}" for p in all_products_full]
            action_pick = st.selectbox(
                "대상 상품",
                action_labels,
                key="manage_action_target_select",
                label_visibility="collapsed",
            )
            action_target = all_products_full[action_labels.index(action_pick)]
            is_active = bool(action_target["active"])
            toggle_label = "비활성화" if is_active else "활성화"
            if st.button(toggle_label, key="manage_toggle_btn", use_container_width=True):
                db.update_product(action_target["id"], active=not is_active)
                st.cache_data.clear()
                st.rerun()


# ---------------------------------------------------------------------------
# Main — 2 tabs (MVP 1차)
# ---------------------------------------------------------------------------

products = load_products()

tab_rank, tab_manage = st.tabs(["순위 현황", "상품 관리"])

with tab_rank:
    render_rank_tab(products)

with tab_manage:
    render_manage_tab()
