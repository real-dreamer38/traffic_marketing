"""
dashboard.py — Streamlit marketing automation dashboard.

Run:
    streamlit run dashboard.py

Sections
--------
  탭 1 [순위 현황]
    • 상품별 현재 순위 요약 카드 (전일 대비 등락)
    • 상품 선택 → 꺾은선 트렌드 + 경쟁사 Top 5 오버레이

  탭 2 [트래픽 주입]
    • 발주 정보 입력 (상품, 키워드, URL/ID, 수량, 시작일)
    • create_traffic_order() 호출 → DB 저장 + 발주서 텍스트 출력 + Slack 푸시 옵션
    • 최근 트래픽 로그 테이블

  탭 3 [상품 관리]
    • 좌측 등록/수정 폼 + 우측 전체 상품 운영 현황 표
"""

from __future__ import annotations

import os
from datetime import date, datetime, timedelta
from typing import Optional

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from dotenv import load_dotenv

# .env 파일 로드 — st.set_page_config 전에 환경변수를 확정해야 함
load_dotenv(override=False)

import database as db
from api_client import create_traffic_order

# ---------------------------------------------------------------------------
# Page config (must be first Streamlit call)
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="마케팅 대시보드",
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
# Custom CSS — modern SaaS dark theme
# ---------------------------------------------------------------------------
# 색상 토큰
#   bg-0   #0b0d12   페이지 배경
#   bg-1   #14171f   카드 / 패널
#   bg-2   #1c2030   호버 / 입력
#   border #262b3a
#   text   #e6e8ef
#   muted  #8b90a6
#   accent #6366f1   primary
#   succ   #22c55e   green
#   warn   #f59e0b
#   danger #ef4444
# ---------------------------------------------------------------------------

st.markdown(
    """
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
    <style>
    /* ── Global typography & background ───────────────────────────── */
    html, body, [class*="css"], [class*="st-"] {
        font-family: 'Inter', -apple-system, system-ui, sans-serif !important;
    }
    .stApp {
        background: radial-gradient(ellipse at top, #131722 0%, #0b0d12 60%) !important;
        color: #e6e8ef;
    }
    /* hide Streamlit branding */
    #MainMenu, footer, header[data-testid="stHeader"] { visibility: hidden; height: 0; }

    /* ── Section title primitive ───────────────────────────────────── */
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

    /* ── Sidebar ──────────────────────────────────────────────────── */
    [data-testid="stSidebar"] {
        background: #0e1117 !important;
        border-right: 1px solid #262b3a;
    }
    [data-testid="stSidebar"] h1 { font-size: 1.15rem !important; font-weight: 700; }
    [data-testid="stSidebar"] hr { border-color: #262b3a; opacity: 0.6; }

    /* ── Tabs (탭바) ──────────────────────────────────────────────── */
    .stTabs [data-baseweb="tab-list"] {
        gap: 6px;
        background: #14171f;
        padding: 6px;
        border-radius: 12px;
        border: 1px solid #262b3a;
    }
    .stTabs [data-baseweb="tab"] {
        height: 38px;
        padding: 0 18px;
        background: transparent;
        border-radius: 8px;
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

    /* ── Metric cards ─────────────────────────────────────────────── */
    [data-testid="metric-container"] {
        background: linear-gradient(180deg, #161a25 0%, #14171f 100%);
        border: 1px solid #262b3a;
        border-radius: 14px;
        padding: 18px 20px;
        box-shadow: 0 4px 16px rgba(0,0,0,0.25), inset 0 1px 0 rgba(255,255,255,0.03);
        transition: border-color 0.2s ease, transform 0.15s ease;
    }
    [data-testid="metric-container"]:hover {
        border-color: #3b4055;
        transform: translateY(-1px);
    }
    [data-testid="stMetricLabel"] > div {
        color: #8b90a6 !important;
        font-size: 0.78rem !important;
        font-weight: 500;
        text-transform: uppercase;
        letter-spacing: 0.04em;
    }
    [data-testid="stMetricValue"] {
        font-size: 2rem !important;
        font-weight: 700;
        color: #e6e8ef !important;
        letter-spacing: -0.02em;
    }
    [data-testid="stMetricDelta"] {
        font-size: 0.85rem !important;
        font-weight: 500;
    }

    /* ── Buttons ──────────────────────────────────────────────────── */
    .stButton > button {
        border-radius: 10px;
        border: 1px solid #262b3a;
        background: #1c2030;
        color: #e6e8ef;
        padding: 9px 18px;
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
        box-shadow: 0 6px 20px rgba(99, 102, 241, 0.45);
    }

    /* ── Inputs / selects ────────────────────────────────────────── */
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

    /* ── Slider ───────────────────────────────────────────────────── */
    .stSlider [data-baseweb="slider"] > div > div > div {
        background: #6366f1;
    }

    /* ── Radio (pill style) ──────────────────────────────────────── */
    .stRadio [role="radiogroup"] label {
        background: #14171f;
        border: 1px solid #262b3a;
        border-radius: 10px;
        padding: 7px 14px;
        margin-right: 6px;
        transition: all 0.15s ease;
    }
    .stRadio [role="radiogroup"] label:hover {
        border-color: #3b4055;
    }

    /* ── Dataframe ────────────────────────────────────────────────── */
    [data-testid="stDataFrame"] {
        border: 1px solid #262b3a;
        border-radius: 12px;
        overflow: hidden;
        box-shadow: 0 2px 8px rgba(0,0,0,0.15);
    }

    /* ── Alerts ───────────────────────────────────────────────────── */
    [data-testid="stAlert"] {
        border-radius: 10px;
        border: 1px solid #262b3a;
    }

    /* ── Code blocks (발주서) ────────────────────────────────────── */
    pre, code, .stCodeBlock {
        font-family: 'JetBrains Mono', 'Consolas', monospace !important;
    }
    .stCodeBlock {
        border: 1px solid #262b3a;
        border-radius: 12px;
        box-shadow: 0 4px 16px rgba(0,0,0,0.25);
    }

    /* ── Expander ─────────────────────────────────────────────────── */
    .streamlit-expanderHeader {
        background: #14171f !important;
        border: 1px solid #262b3a !important;
        border-radius: 10px !important;
        font-weight: 500;
    }

    /* ── Dividers ─────────────────────────────────────────────────── */
    hr { border-color: #262b3a !important; opacity: 0.6; }

    /* ── Custom helper: "stat pill" used inside traffic tab summary  */
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
    .stat-pill .dot {
        width: 6px; height: 6px; border-radius: 50%;
        background: #22c55e;
    }
    .stat-pill.warn .dot   { background: #f59e0b; }
    .stat-pill.danger .dot { background: #ef4444; }
    </style>
    """,
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

with st.sidebar:
    st.title("📊 마케팅 대시보드")
    st.caption("네이버 · 쿠팡 순위 추적 & 트래픽 발주")
    st.divider()

    st.subheader("🔔 알림 연동")
    slack_webhook_url = st.text_input(
        "Slack Webhook URL",
        value=os.getenv("SLACK_WEBHOOK_URL", ""),
        type="password",
        placeholder="https://hooks.slack.com/services/...",
        help="입력 시 발주서 생성과 동시에 슬랙 채널로 전송됩니다.",
        key="sidebar_slack_webhook_input",
    )
    if slack_webhook_url:
        st.markdown(
            '<span class="stat-pill"><span class="dot"></span>Slack 연결됨</span>',
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            '<span class="stat-pill warn"><span class="dot"></span>Slack 미설정</span>',
            unsafe_allow_html=True,
        )

    st.divider()
    trend_days = st.slider(
        "트렌드 조회 기간 (일)",
        min_value=7,
        max_value=90,
        value=30,
        step=7,
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


@st.cache_data(ttl=30)
def load_traffic_logs(product_id: int, limit: int = 20) -> pd.DataFrame:
    rows = db.get_traffic_logs(product_id, limit=limit)
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame([dict(r) for r in rows])
    df["requested_at"] = pd.to_datetime(df["requested_at"])
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


@st.cache_data(ttl=30)
def load_total_traffic_qty(product_id: int) -> int:
    return db.get_total_traffic_qty(product_id)


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
        return "normal"   # green  (rank improved = number went down)
    if delta < 0:
        return "inverse"  # red
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
    """
    내 상품의 순위 트렌드 + Top 5 경쟁사 점선 오버레이.

    경쟁사 라인은 검색결과 1~5위 '자리(position)' 단위로 그려진다.
    매일 그 자리에 있던 상품이 달라도 같은 색 라인으로 묶여서, 호버에 그날 상품명이 표시된다.
    """
    fig = go.Figure()

    has_my_data = not df.empty and not df["rank_display"].isna().all()

    # 1) 경쟁사 라인을 먼저 깔고, 내 상품 라인을 위에 덮어 가독성 확보
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

    # Y축 범위 — 내 상품과 경쟁사 모두 고려
    valid_my   = df["rank_display"].dropna() if has_my_data else pd.Series(dtype=float)
    valid_comp = (
        competitors_df["rank"] if (competitors_df is not None and not competitors_df.empty)
        else pd.Series(dtype=float)
    )
    pool = pd.concat([valid_my, valid_comp], ignore_index=True)
    y_max = int(pool.max()) + 5 if not pool.empty else 50

    fig.update_layout(
        height=380,
        margin=dict(l=10, r=10, t=30, b=10),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color="#cdd6f4"),
        yaxis=dict(
            title="순위",
            autorange="reversed",     # 1위가 위쪽
            range=[y_max, 0],
            gridcolor="#313149",
            ticksuffix="위",
        ),
        xaxis=dict(
            title="",
            gridcolor="#313149",
        ),
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
            font=dict(size=14),
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

    # ── 요약 카드 (한 행에 최대 4개) ──
    st.markdown('<p class="section-title">현재 순위 요약</p>', unsafe_allow_html=True)

    cols_per_row = 4
    for i in range(0, len(products), cols_per_row):
        cols = st.columns(min(cols_per_row, len(products) - i))
        for col, product in zip(cols, products[i : i + cols_per_row]):
            latest   = db.get_latest_rank(product["id"])
            delta    = db.get_rank_delta(product["id"])
            rank_now = latest["rank"] if latest else 0
            icon     = PLATFORM_ICON.get(product["platform"], "")
            platform = PLATFORM_KR.get(product["platform"], product["platform"])

            label   = _delta_label(delta, rank_now)
            d_color = _delta_color(delta, rank_now)
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

    # Raw data expander
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
# Tab 2 — 트래픽 주입
# ---------------------------------------------------------------------------

def render_traffic_tab(products: list[dict]) -> None:
    if not products:
        st.info("등록된 상품이 없습니다. [상품 관리] 탭에서 추가해 주세요.")
        return

    st.markdown('<p class="section-title">발주 정보 입력</p>', unsafe_allow_html=True)

    left, right = st.columns([1, 1.15], gap="large")

    with left:
        product_labels = [
            f"{PLATFORM_ICON.get(p['platform'],'')} {p['name']} ({PLATFORM_KR.get(p['platform'], p['platform'])})"
            for p in products
        ]
        sel_label   = st.selectbox(
            "상품 선택",
            product_labels,
            key="traffic_product_select",
        )
        sel_idx     = product_labels.index(sel_label)
        sel_product = products[sel_idx]

        st.caption(f"🔑 타겟 키워드: `{sel_product['keyword']}`")

        target_url = st.text_input(
            "상품 URL",
            value=sel_product.get("target_url") or "",
            placeholder="https://smartstore.naver.com/...",
            help="시행사에 전달할 상품 페이지 URL",
            key=f"traffic_target_url_input_{sel_product['id']}",
        )

        target_id = st.text_input(
            "상품 ID (참고용)",
            value=sel_product.get("target_id") or "",
            placeholder="예: 40155252748",
            help="URL 이 비어 있을 때 시행사가 식별할 수 있도록 함께 표기",
            key=f"traffic_target_id_input_{sel_product['id']}",
        )

        col_qty, col_date = st.columns([1, 1])
        with col_qty:
            qty = st.number_input(
                "목표 수량",
                min_value=1,
                max_value=100_000,
                value=200,
                step=100,
                help="발주할 방문자 수",
                key="traffic_quantity_input",
            )
        with col_date:
            start_date = st.date_input(
                "시작 일자",
                value=date.today(),
                min_value=date.today() - timedelta(days=1),
                help="시행사가 트래픽을 시작할 날짜",
                key="traffic_start_date_input",
            )

        slack_label = "🟢 Slack 푸시 활성" if slack_webhook_url else "⚪ Slack 미설정 (사이드바에서 입력)"
        st.caption(slack_label)

        submit = st.button(
            "🚀 발주서 생성 & 기록",
            type="primary",
            use_container_width=True,
            key="traffic_submit_btn",
        )

    with right:
        st.markdown('<p class="section-title">발주서 결과</p>', unsafe_allow_html=True)

        if submit:
            with st.spinner("발주서 생성 중..."):
                result = create_traffic_order(
                    product_id   = sel_product["id"],
                    product_name = sel_product["name"],
                    platform     = sel_product["platform"],
                    keyword      = sel_product["keyword"],
                    target_url   = target_url.strip(),
                    target_id    = target_id.strip(),
                    quantity     = int(qty),
                    start_date   = start_date,
                    slack_webhook= slack_webhook_url or None,
                )
                st.cache_data.clear()  # 로그/누적트래픽 캐시 갱신

            if result.success:
                st.success(
                    "✅ 발주서가 생성되었습니다. 아래 내용을 시행사에게 전달하세요."
                )
                st.code(result.order_text, language="text")

                # Slack 푸시 상태 배지
                if slack_webhook_url:
                    if result.slack_pushed:
                        st.markdown(
                            '<span class="stat-pill"><span class="dot"></span>'
                            'Slack 채널 전송 완료</span>',
                            unsafe_allow_html=True,
                        )
                    else:
                        st.markdown(
                            f'<span class="stat-pill danger"><span class="dot"></span>'
                            f'Slack 전송 실패: {result.slack_error or "unknown"}</span>',
                            unsafe_allow_html=True,
                        )
                if result.requested_at:
                    st.caption(f"DB 기록 완료 · {result.requested_at.strftime('%Y-%m-%d %H:%M:%S')}")
            else:
                st.error(f"❌ 발주서 생성 실패: {result.error}")
        else:
            st.caption(
                "좌측에서 상품과 수량·시작일을 설정한 뒤 [발주서 생성 & 기록] 버튼을 누르세요. "
                "생성된 발주서는 코드블록에서 한 번에 복사할 수 있습니다."
            )

    st.divider()

    # ── 최근 트래픽 로그 ──
    st.markdown('<p class="section-title">최근 발주 로그</p>', unsafe_allow_html=True)

    log_product_labels = ["전체"] + product_labels
    log_filter = st.selectbox(
        "로그 필터 (상품)",
        log_product_labels,
        label_visibility="collapsed",
        key="traffic_log_filter_select",
    )

    all_logs: list[dict] = []
    target_products = products if log_filter == "전체" else [products[product_labels.index(log_filter)]]

    for p in target_products:
        logs_df = load_traffic_logs(p["id"], limit=30)
        if not logs_df.empty:
            logs_df.insert(0, "상품명", p["name"])
            all_logs.append(logs_df)

    if all_logs:
        combined = pd.concat(all_logs).sort_values("requested_at", ascending=False)
        combined["requested_at"] = combined["requested_at"].dt.strftime("%Y-%m-%d %H:%M")
        combined = combined.rename(columns={
            "requested_at": "요청일시",
            "traffic_qty":  "수량",
            "api_status":   "상태",
            "error_message":"오류",
        })
        display_cols = ["상품명", "요청일시", "수량", "상태", "오류"]
        st.dataframe(
            combined[display_cols].head(50),
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.caption("발주 로그가 없습니다.")


# ---------------------------------------------------------------------------
# Tab 3 — 상품 관리
# ---------------------------------------------------------------------------

@st.cache_data(ttl=30)
def load_management_overview() -> pd.DataFrame:
    """관리 탭 우측 표용 — 모든 상품의 운영 지표를 한 번에 묶어서 반환."""
    rows = db.list_products(active_only=False)
    records: list[dict] = []
    for r in rows:
        p = dict(r)
        latest = db.get_latest_rank(p["id"])
        if not latest or latest["rank"] == 0:
            rank_str = "미노출"
        else:
            rank_str = f"{latest['rank']}위"
        total = db.get_total_traffic_qty(p["id"])
        created = (p["created_at"] or "")[:10]
        records.append({
            "상품 ID":      p["id"],
            "상품명":       p["name"],
            "타겟 키워드":  p["keyword"],
            "플랫폼":       PLATFORM_KR.get(p["platform"], p["platform"]),
            "누적 트래픽":  int(total),
            "시작일자":     created,
            "현재 순위":    rank_str,
            "활성":         "✅" if p["active"] else "⏸️",
        })
    return pd.DataFrame(records)


def render_manage_tab(products: list[dict]) -> None:
    left, right = st.columns([1, 2], gap="large")

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

        # 위젯 key를 모드+선택대상으로 묶어, 대상이 바뀌면 기본값이 자동 갱신되도록 한다
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
                # 플랫폼은 update_product 가 받지 않음 — 변경 필요 시 별도 처리
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

    # ── 우측: 상품 목록 표 + 행 액션 ─────────────────────────
    with right:
        st.markdown('<p class="section-title">등록 상품 목록</p>', unsafe_allow_html=True)

        overview_df = load_management_overview()
        if overview_df.empty:
            st.caption("등록된 상품이 없습니다.")
            return

        column_order = [
            "상품 ID", "상품명", "타겟 키워드", "플랫폼",
            "누적 트래픽", "시작일자", "현재 순위", "활성",
        ]
        st.dataframe(
            overview_df[column_order],
            use_container_width=True,
            hide_index=True,
            column_config={
                "상품 ID":     st.column_config.NumberColumn(width="small"),
                "누적 트래픽": st.column_config.NumberColumn(format="%,d"),
                "활성":        st.column_config.TextColumn(width="small"),
            },
        )

        st.caption(f"총 {len(overview_df)}개 상품")

        # 행 액션 — 활성/비활성 토글
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
# Main layout
# ---------------------------------------------------------------------------

products = load_products()

tab_rank, tab_traffic, tab_manage = st.tabs(["📈 순위 현황", "🚀 트래픽 주입", "📦 상품 관리"])

with tab_rank:
    render_rank_tab(products)

with tab_traffic:
    render_traffic_tab(products)

with tab_manage:
    render_manage_tab(products)
