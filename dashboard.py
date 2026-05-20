"""
dashboard.py — Streamlit marketing automation dashboard (MVP 1차).

Run:
    streamlit run dashboard.py

Sections
--------
  탭 1 [순위 현황]
    • 상품별 현재 순위 요약 카드 (전일 대비 등락)
    • 상품 선택 → 꺾은선 트렌드 + 경쟁사 Top 5 오버레이

  탭 2 [상품 관리]
    • 좌측: 등록/수정 폼   • 우측: 상품 목록 표 + 빠른 작업

Note
----
MVP 1차에서는 [트래픽 주입] 탭이 비활성화되어 있다.
관련 로직은 api_client.py 에 보존되어 있고, 향후 재개 시 아래
HIDE_TRAFFIC_TAB 플래그를 False 로 바꾸면 다시 노출된다.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from dotenv import load_dotenv

load_dotenv(override=False)

import database as db

# ---------------------------------------------------------------------------
# Feature flag — MVP 1차 [트래픽 주입] 탭 비활성화
# ---------------------------------------------------------------------------
HIDE_TRAFFIC_TAB = True

# ---------------------------------------------------------------------------
# Page config (must be first Streamlit call)
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="순위 모니터링 대시보드",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------------
# Init
# ---------------------------------------------------------------------------

db.init_db()

PLATFORM_KR   = {"naver": "네이버", "coupang": "쿠팡"}
PLATFORM_ICON = {"naver": "🟢", "coupang": "🟡"}

# ---------------------------------------------------------------------------
# Modern SaaS Custom CSS
# ---------------------------------------------------------------------------

st.markdown(
    """
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
    <style>
    /* ── Global typography & background ─────────────────────────── */
    html, body, [class*="css"], [class*="st-"] {
        font-family: 'Inter', -apple-system, system-ui, sans-serif !important;
    }
    .stApp {
        background:
            radial-gradient(1200px 600px at 10% -10%, rgba(99,102,241,0.08), transparent 60%),
            radial-gradient(800px 500px at 100% 0%, rgba(168,85,247,0.06), transparent 55%),
            #0b0d12 !important;
        color: #e6e8ef;
    }
    #MainMenu, footer, header[data-testid="stHeader"] { visibility: hidden; height: 0; }

    /* ── Hero header ─────────────────────────────────────────────── */
    .hero {
        margin: 0.2rem 0 1.6rem 0;
        padding: 22px 26px;
        border-radius: 18px;
        background: linear-gradient(135deg, rgba(99,102,241,0.15) 0%, rgba(168,85,247,0.10) 50%, rgba(34,197,94,0.08) 100%);
        border: 1px solid #262b3a;
        box-shadow: 0 10px 30px rgba(0,0,0,0.35), inset 0 1px 0 rgba(255,255,255,0.04);
    }
    .hero h1 {
        margin: 0;
        font-size: 1.6rem;
        font-weight: 800;
        letter-spacing: -0.02em;
        color: #ffffff;
    }
    .hero p {
        margin: 6px 0 0 0;
        color: #b6bbd0;
        font-size: 0.92rem;
    }

    /* ── Section title primitive ────────────────────────────────── */
    .section-title {
        font-size: 0.95rem;
        font-weight: 600;
        letter-spacing: 0.02em;
        text-transform: uppercase;
        color: #8b90a6;
        margin: 0.25rem 0 0.85rem 0;
        display: flex;
        align-items: center;
        gap: 0.5rem;
    }
    .section-title::before {
        content: "";
        display: inline-block;
        width: 3px; height: 14px;
        background: linear-gradient(180deg, #6366f1 0%, #818cf8 100%);
        border-radius: 2px;
    }

    /* ── Sidebar ────────────────────────────────────────────────── */
    [data-testid="stSidebar"] {
        background: #0e1117 !important;
        border-right: 1px solid #262b3a;
    }
    [data-testid="stSidebar"] h1 { font-size: 1.15rem !important; font-weight: 700; }
    [data-testid="stSidebar"] hr { border-color: #262b3a; opacity: 0.6; }

    /* ── Tabs ───────────────────────────────────────────────────── */
    .stTabs [data-baseweb="tab-list"] {
        gap: 8px;
        background: #14171f;
        padding: 8px;
        border-radius: 14px;
        border: 1px solid #262b3a;
        box-shadow: 0 4px 16px rgba(0,0,0,0.25);
    }
    .stTabs [data-baseweb="tab"] {
        height: 42px;
        padding: 0 22px;
        background: transparent;
        border-radius: 10px;
        color: #8b90a6;
        font-weight: 500;
        transition: all 0.15s ease;
    }
    .stTabs [data-baseweb="tab"]:hover {
        background: #1c2030;
        color: #e6e8ef;
    }
    .stTabs [aria-selected="true"] {
        background: linear-gradient(135deg, #6366f1 0%, #4f46e5 100%) !important;
        color: #ffffff !important;
        box-shadow: 0 4px 14px rgba(99, 102, 241, 0.35);
    }
    .stTabs [data-baseweb="tab-highlight"], .stTabs [data-baseweb="tab-border"] {
        background: transparent !important;
    }

    /* ── Metric cards — 큼지막한 KPI 카드 ────────────────────────── */
    [data-testid="metric-container"] {
        background: linear-gradient(180deg, #161a25 0%, #14171f 100%);
        border: 1px solid #262b3a;
        border-radius: 16px;
        padding: 22px 24px;
        box-shadow:
            0 10px 30px rgba(0,0,0,0.30),
            inset 0 1px 0 rgba(255,255,255,0.04);
        transition: border-color 0.2s ease, transform 0.15s ease, box-shadow 0.2s ease;
    }
    [data-testid="metric-container"]:hover {
        border-color: #4f46e5;
        transform: translateY(-2px);
        box-shadow:
            0 14px 36px rgba(0,0,0,0.40),
            0 0 0 1px rgba(99,102,241,0.25);
    }
    [data-testid="stMetricLabel"] > div {
        color: #8b90a6 !important;
        font-size: 0.82rem !important;
        font-weight: 500;
        text-transform: uppercase;
        letter-spacing: 0.05em;
    }
    [data-testid="stMetricValue"] {
        font-size: 2.4rem !important;
        font-weight: 800;
        color: #ffffff !important;
        letter-spacing: -0.025em;
        line-height: 1.1;
    }
    [data-testid="stMetricDelta"] {
        font-size: 0.95rem !important;
        font-weight: 600;
    }

    /* ── Buttons ────────────────────────────────────────────────── */
    .stButton > button {
        border-radius: 12px;
        border: 1px solid #262b3a;
        background: #1c2030;
        color: #e6e8ef;
        padding: 10px 20px;
        font-weight: 500;
        transition: all 0.15s ease;
    }
    .stButton > button:hover {
        background: #232839;
        border-color: #3b4055;
        transform: translateY(-1px);
        box-shadow: 0 4px 12px rgba(0,0,0,0.3);
    }
    .stButton > button[kind="primary"] {
        background: linear-gradient(135deg, #6366f1 0%, #4f46e5 100%);
        border: 1px solid #4f46e5;
        color: #ffffff;
        font-weight: 600;
        box-shadow: 0 4px 14px rgba(99, 102, 241, 0.3);
    }
    .stButton > button[kind="primary"]:hover {
        background: linear-gradient(135deg, #7c7ff5 0%, #6366f1 100%);
        box-shadow: 0 6px 22px rgba(99, 102, 241, 0.5);
    }

    /* ── Inputs / selects ───────────────────────────────────────── */
    .stTextInput input, .stTextArea textarea,
    .stNumberInput input, .stDateInput input,
    [data-baseweb="select"] > div {
        background: #14171f !important;
        border: 1px solid #262b3a !important;
        border-radius: 10px !important;
        color: #e6e8ef !important;
        transition: border-color 0.15s ease, box-shadow 0.15s ease;
    }
    .stTextInput input:focus, .stTextArea textarea:focus,
    .stNumberInput input:focus, .stDateInput input:focus {
        border-color: #6366f1 !important;
        box-shadow: 0 0 0 3px rgba(99, 102, 241, 0.18) !important;
        outline: none !important;
    }

    /* ── Slider ─────────────────────────────────────────────────── */
    .stSlider [data-baseweb="slider"] > div > div > div { background: #6366f1; }

    /* ── Radio (pill style) ─────────────────────────────────────── */
    .stRadio [role="radiogroup"] label {
        background: #14171f;
        border: 1px solid #262b3a;
        border-radius: 10px;
        padding: 7px 14px;
        margin-right: 6px;
        transition: all 0.15s ease;
    }
    .stRadio [role="radiogroup"] label:hover { border-color: #3b4055; }

    /* ── Dataframe ──────────────────────────────────────────────── */
    [data-testid="stDataFrame"] {
        border: 1px solid #262b3a;
        border-radius: 12px;
        overflow: hidden;
        box-shadow: 0 4px 16px rgba(0,0,0,0.25);
    }

    /* ── Alerts ─────────────────────────────────────────────────── */
    [data-testid="stAlert"] {
        border-radius: 12px;
        border: 1px solid #262b3a;
    }

    /* ── Card wrapper used by form panels ───────────────────────── */
    .card {
        background: linear-gradient(180deg, #161a25 0%, #14171f 100%);
        border: 1px solid #262b3a;
        border-radius: 14px;
        padding: 22px 22px;
        box-shadow: 0 8px 24px rgba(0,0,0,0.30), inset 0 1px 0 rgba(255,255,255,0.03);
    }

    /* ── Expander ───────────────────────────────────────────────── */
    .streamlit-expanderHeader {
        background: #14171f !important;
        border: 1px solid #262b3a !important;
        border-radius: 10px !important;
        font-weight: 500;
    }

    /* ── Dividers ──────────────────────────────────────────────── */
    hr { border-color: #262b3a !important; opacity: 0.6; }

    /* ── Stat pill ──────────────────────────────────────────────── */
    .stat-pill {
        display: inline-flex;
        align-items: center;
        gap: 6px;
        background: #1c2030;
        border: 1px solid #262b3a;
        border-radius: 999px;
        padding: 4px 12px;
        font-size: 0.82rem;
        color: #b6bbd0;
    }
    .stat-pill .dot { width: 6px; height: 6px; border-radius: 50%; background: #22c55e; }
    .stat-pill.warn .dot   { background: #f59e0b; }
    .stat-pill.danger .dot { background: #ef4444; }

    /* ── Code blocks ────────────────────────────────────────────── */
    pre, code, .stCodeBlock {
        font-family: 'JetBrains Mono', 'Consolas', monospace !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------------------
# Hero header
# ---------------------------------------------------------------------------

st.markdown(
    """
    <div class="hero">
        <h1>📊 순위 모니터링 대시보드</h1>
        <p>네이버 · 쿠팡 검색 순위 일일 추적 — 매일 아침 텔레그램으로 자동 리포트 전송</p>
    </div>
    """,
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

with st.sidebar:
    st.title("⚙️ 설정")
    st.caption("조회 옵션 & 알림 상태")
    st.divider()

    # Telegram 상태 표시 (편집 불가 — .env 로 관리)
    st.subheader("🔔 알림 채널")
    import os
    tg_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    tg_chat  = os.getenv("TELEGRAM_CHAT_ID", "")
    if tg_token and tg_chat:
        st.markdown(
            '<span class="stat-pill"><span class="dot"></span>Telegram 연결됨</span>',
            unsafe_allow_html=True,
        )
        st.caption(f"챗 ID: `{tg_chat}`")
    else:
        st.markdown(
            '<span class="stat-pill warn"><span class="dot"></span>Telegram 미설정</span>',
            unsafe_allow_html=True,
        )
        st.caption("`.env` 에 TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID 를 추가하세요.")

    st.divider()
    trend_days = st.slider(
        "트렌드 조회 기간 (일)",
        min_value=7, max_value=90, value=30, step=7,
        key="sidebar_trend_days_slider",
    )

    st.divider()
    if st.button("🔄 데이터 새로고침", use_container_width=True, key="sidebar_refresh_btn"):
        st.cache_data.clear()
        st.rerun()

    st.caption(f"마지막 로드: {datetime.now().strftime('%H:%M:%S')}")


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
# Helper: rank delta string & color
# ---------------------------------------------------------------------------

def _delta_label(delta: Optional[int], today_rank: int) -> str:
    if today_rank == 0:
        return "미노출"
    if delta is None:
        return "신규"
    if delta > 0:
        return f"▲ {delta}"
    if delta < 0:
        return f"▼ {abs(delta)}"
    return "변동없음"


def _delta_color(delta: Optional[int], today_rank: int) -> str:
    if today_rank == 0 or delta is None:
        return "off"
    if delta > 0:
        return "normal"
    if delta < 0:
        return "inverse"
    return "off"


# ---------------------------------------------------------------------------
# Plotly rank trend chart
# ---------------------------------------------------------------------------

COMPETITOR_COLORS = ["#f38ba8", "#fab387", "#f9e2af", "#a6e3a1", "#94e2d5"]


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
                    line=dict(color=color, width=1.4, dash="dot"),
                    marker=dict(size=5, color=color),
                    customdata=sub["name"].fillna("").to_numpy().reshape(-1, 1),
                    hovertemplate=(
                        "<b>%{x|%Y-%m-%d}</b><br>"
                        "경쟁사 %{y}위<br>"
                        "상품명: %{customdata[0]}"
                        "<extra></extra>"
                    ),
                    opacity=0.85,
                )
            )

    if has_my_data:
        fig.add_trace(
            go.Scatter(
                x=df["rank_date"],
                y=df["rank_display"],
                mode="lines+markers",
                name=f"내 상품 ({product_name})",
                line=dict(color="#89b4fa", width=3),
                marker=dict(size=9, color="#cba6f7", line=dict(color="#89b4fa", width=1.5)),
                hovertemplate="<b>%{x|%Y-%m-%d}</b><br>내 순위: %{y}위<extra></extra>",
                connectgaps=False,
            )
        )

    if not has_my_data and (competitors_df is None or competitors_df.empty):
        fig.add_annotation(
            text="데이터 없음",
            xref="paper", yref="paper",
            x=0.5, y=0.5, showarrow=False,
            font=dict(size=16, color="#6c7086"),
        )

    valid_my   = df["rank_display"].dropna() if has_my_data else pd.Series(dtype=float)
    valid_comp = (
        competitors_df["rank"] if (competitors_df is not None and not competitors_df.empty)
        else pd.Series(dtype=float)
    )
    pool = pd.concat([valid_my, valid_comp], ignore_index=True)
    y_max = int(pool.max()) + 5 if not pool.empty else 50

    fig.update_layout(
        height=420,
        margin=dict(l=10, r=10, t=40, b=10),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color="#cdd6f4"),
        yaxis=dict(
            title="순위",
            autorange="reversed",
            range=[y_max, 0],
            gridcolor="#262b3a",
            ticksuffix="위",
        ),
        xaxis=dict(title="", gridcolor="#262b3a"),
        showlegend=True,
        legend=dict(
            orientation="h",
            yanchor="bottom", y=1.02,
            xanchor="right",  x=1,
            bgcolor="rgba(0,0,0,0)",
            font=dict(size=11),
        ),
        title=dict(
            text=f"{product_name} 순위 트렌드 vs 경쟁사 Top 5",
            font=dict(size=15),
            x=0.01,
        ),
    )
    return fig


# ---------------------------------------------------------------------------
# Tab 1 — 순위 현황
# ---------------------------------------------------------------------------

def render_rank_tab(products: list[dict]) -> None:
    if not products:
        st.info("등록된 상품이 없습니다. [상품 관리] 탭에서 추가해 주세요.")
        return

    # ── KPI 요약 행 ──
    st.markdown('<p class="section-title">전체 요약</p>', unsafe_allow_html=True)

    total = len(products)
    exposed = 0
    improved = 0
    worsened = 0
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

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("등록 상품",   f"{total}개")
    c2.metric("노출 중",     f"{exposed}/{total}")
    c3.metric("🔺 순위 상승", f"{improved}개")
    c4.metric("🔻 순위 하락", f"{worsened}개")

    st.markdown("<br>", unsafe_allow_html=True)

    # ── 상품별 카드 ──
    st.markdown('<p class="section-title">상품별 현재 순위</p>', unsafe_allow_html=True)

    cols_per_row = 4
    for i in range(0, len(products), cols_per_row):
        cols = st.columns(min(cols_per_row, len(products) - i))
        for col, product in zip(cols, products[i : i + cols_per_row]):
            latest   = db.get_latest_rank(product["id"])
            delta    = db.get_rank_delta(product["id"])
            rank_now = latest["rank"] if latest else 0
            icon     = PLATFORM_ICON.get(product["platform"], "")
            platform = PLATFORM_KR.get(product["platform"], product["platform"])

            label    = _delta_label(delta, rank_now)
            d_color  = _delta_color(delta, rank_now)
            rank_str = "미노출" if rank_now == 0 else f"{rank_now}위"

            col.metric(
                label=f"{icon} {product['name']} ({platform})",
                value=rank_str,
                delta=label,
                delta_color=d_color,
                help=f"키워드: {product['keyword']}",
            )

    st.divider()

    # ── 트렌드 차트 ──
    st.markdown('<p class="section-title">순위 트렌드</p>', unsafe_allow_html=True)

    product_names = [
        f"{PLATFORM_ICON.get(p['platform'],'')} {p['name']} ({PLATFORM_KR.get(p['platform'], p['platform'])})"
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

    with st.expander("📋 원본 데이터 보기"):
        col_a, col_b = st.columns(2)

        with col_a:
            st.caption("내 상품 순위 이력")
            if df.empty:
                st.caption("데이터 없음")
            else:
                display_df = df[["rank_date", "rank"]].copy()
                display_df.columns = ["날짜", "순위"]
                display_df["순위"] = display_df["순위"].apply(
                    lambda x: "미노출" if x == 0 else f"{x}위"
                )
                st.dataframe(display_df, use_container_width=True, hide_index=True)

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
                st.dataframe(snap, use_container_width=True, hide_index=True)


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
        if not latest or latest["rank"] == 0:
            rank_str = "미노출"
        else:
            rank_str = f"{latest['rank']}위"
        created = (p["created_at"] or "")[:10]
        records.append({
            "ID":         p["id"],
            "상품명":      p["name"],
            "타겟 키워드": p["keyword"],
            "플랫폼":      PLATFORM_KR.get(p["platform"], p["platform"]),
            "현재 순위":   rank_str,
            "등록일":      created,
            "활성":        "✅" if p["active"] else "⏸️",
        })
    return pd.DataFrame(records)


def render_manage_tab() -> None:
    left, right = st.columns([1, 1.8], gap="large")

    all_products_full = [dict(p) for p in db.list_products(active_only=False)]

    # ── 좌측: 입력 폼 ─────────────────────────────────────────
    with left:
        st.markdown('<p class="section-title">상품 등록 / 수정</p>', unsafe_allow_html=True)

        mode = st.radio(
            "작업 모드",
            ["➕ 추가", "✏️ 수정"],
            horizontal=True,
            key="manage_mode_radio",
        )

        edit_target: Optional[dict] = None
        if mode == "✏️ 수정":
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
            "상품명 *",
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
            "플랫폼 *",
            platform_opts,
            index=platform_idx,
            format_func=lambda x: PLATFORM_KR[x],
            key=f"manage_platform_select_{key_suffix}",
        )

        keyword = st.text_input(
            "타겟 키워드 *",
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

        if mode == "✏️ 수정" and edit_target is not None:
            submit_label = "💾 수정 저장"
            submit_key   = f"manage_save_btn_{edit_target['id']}"
        else:
            submit_label = "➕ 상품 추가"
            submit_key   = "manage_add_btn"

        if st.button(submit_label, type="primary", use_container_width=True, key=submit_key):
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
                st.success(f"✅ 수정 완료 (ID: {edit_target['id']})")
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
                st.success(f"✅ 상품 추가 완료 (ID: {new_id})")
                st.cache_data.clear()
                st.rerun()

    # ── 우측: 상품 목록 + 빠른 작업 ─────────────────────────
    with right:
        st.markdown('<p class="section-title">등록 상품 목록</p>', unsafe_allow_html=True)

        overview_df = load_management_overview()
        if overview_df.empty:
            st.caption("등록된 상품이 없습니다. 좌측에서 추가해 주세요.")
            return

        column_order = ["ID", "상품명", "타겟 키워드", "플랫폼", "현재 순위", "등록일", "활성"]
        st.dataframe(
            overview_df[column_order],
            use_container_width=True,
            hide_index=True,
            column_config={
                "ID":   st.column_config.NumberColumn(width="small"),
                "활성": st.column_config.TextColumn(width="small"),
            },
        )

        st.caption(f"총 {len(overview_df)}개 상품")

        st.markdown("##### 빠른 작업")
        action_labels = [f"[{p['id']}] {p['name']}" for p in all_products_full]
        action_pick = st.selectbox(
            "대상 상품",
            action_labels,
            key="manage_action_target_select",
        )
        action_target = all_products_full[action_labels.index(action_pick)]
        is_active = bool(action_target["active"])
        toggle_label = "⏸️ 비활성화" if is_active else "▶️ 활성화"
        if st.button(toggle_label, key="manage_toggle_btn", use_container_width=True):
            db.update_product(action_target["id"], active=not is_active)
            st.cache_data.clear()
            st.rerun()


# ---------------------------------------------------------------------------
# Main layout — MVP 1차: 2 tabs only
# ---------------------------------------------------------------------------

products = load_products()

tab_rank, tab_manage = st.tabs(["📈 순위 현황 차트", "📦 상품 관리"])

with tab_rank:
    render_rank_tab(products)

with tab_manage:
    render_manage_tab()


# ---------------------------------------------------------------------------
# (Hidden) Traffic injection tab — MVP 1차 비활성
# ---------------------------------------------------------------------------
# 향후 재개 시 아래 블록의 주석을 풀고, st.tabs 호출에 "🚀 트래픽 주입" 을 다시 추가.
# 관련 비즈니스 로직과 단위테스트는 api_client.py / test_integration.py 에 그대로 보존.
#
# def render_traffic_tab(products: list[dict]) -> None:
#     ...  # 트래픽 발주 폼 + 발주서 결과 + 최근 발주 로그
