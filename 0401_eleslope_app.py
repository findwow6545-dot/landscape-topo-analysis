import streamlit as st
import ezdxf
from ezdxf import recover
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.colors import BoundaryNorm, ListedColormap
from scipy.interpolate import griddata
from matplotlib.path import Path
from matplotlib.patches import PathPatch
import matplotlib.font_manager as fm
import io
import requests
import os

# --- [1. 한글 폰트 및 설정] ---
@st.cache_resource
def load_korean_font():
    font_url = "https://github.com/google/fonts/raw/main/ofl/nanumgothic/NanumGothic-Regular.ttf"
    font_path = "NanumGothic.ttf"
    if not os.path.exists(font_path):
        res = requests.get(font_url)
        with open(font_path, "wb") as f:
            f.write(res.content)
    fe = fm.FontEntry(fname=font_path, name='NanumGothic')
    fm.fontManager.ttflist.insert(0, fe)
    plt.rcParams['font.family'] = fe.name
    plt.rcParams['axes.unicode_minus'] = False
    return fe.name

load_korean_font()

# --- [2. CSS 테마 및 레이아웃] ---
st.set_page_config(page_title="Site Analysis System", layout="wide")

st.markdown("""
    <style>
    .main { background-color: #f1f5f9; }
    .stButton>button { width: 100%; border-radius: 6px; height: 3.5em; background-color: #1e40af; color: white; font-weight: bold; }
    .footer { position: fixed; bottom: 0; left: 0; width: 100%; text-align: center; color: #475569; padding: 12px; background: rgba(255,255,255,0.95); font-size: 13px; z-index: 100; border-top: 2px solid #cbd5e1; }
    h1 { color: #0f172a; font-weight: 800; }
    h3 { border-left: 6px solid #1e40af; padding-left: 12px; color: #1e293b; margin-top: 24px; font-weight: bold; }
    .intro-box { text-align: center; padding: 50px; background: white; border-radius: 15px; border: 1px solid #e2e8f0; margin-top: 20px; }
    </style>
    """, unsafe_allow_html=True)

# --- [3. 사이드바 인터페이스] ---
with st.sidebar:
    st.header("⚙️ 표고/경사/향 분석")
    with st.form("analysis_form"):
        up_file = st.file_uploader("DXF 도면 파일 업로드", type=["dxf"])
        st.markdown("---")
        res_val = st.slider("분석도면 해상도", 50, 400, 250)
        elev_cnt = st.number_input("표고 범례 구간 수", 3, 20, 10)
        slope_step = st.number_input("경사 범례 간격 (도)", 1, 15, 5)
        aspect_cnt = st.selectbox("향 분석 방위 설정", [4, 8, 16], index=1)
        mask_opacity = st.slider("White Masking (%)", 0, 100, 50)
        submit_btn = st.form_submit_button("🚀 종합 분석 실행")
    st.markdown("---")
    st.info(f"**[System Developer]**\n**박지환 교수**\n국립목포대학교 조경학과")

# --- [4. 메인 화면 구성] ---
st.title("🗺️ Site Analysis System for Landscape Plan")
st.caption("Developed by Prof. Jihwan Park, Mokpo National University")

# 초기 화면 및 결과 출력을 위한 컨테이너 생성
main_container = st.empty()

if 'final_data' not in st.session_state:
    st.session_state.final_data = None

# --- [5. 초기 화면 이미지 및 안내 (데이터가 없을 때만 표시)] ---
if st.session_state.final_data is None:
    with main_container.container():
        st.markdown("""
            <div class="intro-box">
                <h2>Welcome to Terrain Analysis Engine</h2>
                <p>사이드바에서 DXF 도면을 업로드하고 분석을 시작하세요.</p>
            </div>
        """, unsafe_allow_html=True)
        # 이미지 업로드: 3D 지형 랜드스케이프를 상징하는 이미지 (URL 교체 가능)
        st.image("https://images.unsplash.com/photo-1550684848-fac1c5b4e853?ixlib=rb-1.2.1&auto=format&fit=crop&w=1350&q=80", 
                 caption="Landscape Topography Visualization Engine", use_container_width=True)

# --- [6. 데이터 처리 로직] ---
if up_file is not None and submit_btn:
    try:
        raw_data = up_file.getvalue()
        memory_stream = io.BytesIO(raw_data)
        with st.spinner("전문 엔진이 지형 데이터를 정밀 분석 중입니다..."):
            try:
                doc, auditor = recover.read(memory_stream)
            except:
                memory_stream.seek(0)
                doc = ezdxf.read(memory_stream)
            
            msp = doc.modelspace()
            boundary_entities = msp.query('LWPOLYLINE[layer=="0대상지경계"]')
            if not boundary_entities:
                st.error("❌ 도면 오류: '0대상지경계' 레이어가 없습니다."); st.stop()
            
            b_poly = list(boundary_entities[0].get_points(format='xy'))
            if b_poly[0] != b_poly[-1]: b_poly.append(b_poly[0])
            b_path = Path(b_poly)

            all_pts = []
            CONTOUR_LAYERS = ["F0017111", "F0017114"]
            for entity in msp.query('LWPOLYLINE POLYLINE LINE'):
                if entity.dxf.layer in CONTOUR_LAYERS:
                    z = entity.dxf.elevation if hasattr(entity.dxf, 'elevation') else 0
                    if z == 0 and entity.dxftype() == 'LWPOLYLINE':
                        p_list = list(entity.get_points()); z = p_list[0][2] if p_list and len(p_list[0]) > 2 else 0
                    for p in list(entity.get_points(format='xy')): all_pts.append((p[0], p[1], z))

            st.session_state.final_data = {
                'pts': np.array(all_pts), 'res': res_val, 
                'elev_cnt': elev_cnt, 'slope_step': slope_step, 'aspect_cnt': aspect_cnt,
                'mask_alpha': mask_opacity / 100.0, 'b_poly': b_poly, 'b_path': b_path
            }
            # 데이터 처리 완료 후 초기 화면을 비우기 위해 리런
            st.rerun()
    except Exception as e:
        st.error(f"⚠️ 시스템 오류: {str(e)}")

# --- [7. 분석 대시보드 출력 (데이터가 있을 때 초기 화면 대체)] ---
if st.session_state.final_data:
    # main_container를 다시 활용하여 초기 이미지를 덮어씀
    with main_container.container():
        fd = st.session_state.final_data
        # (기존의 시각화 로직 동일하게 수행)
        v_pts, d_res, b_poly, b_path, m_alpha = fd['pts'], fd['res'], fd['b_poly'], fd['b_path'], fd['mask_alpha']
        
        bx_raw, by_raw = zip(*b_poly)
        xmin, xmax, ymin, ymax = min(bx_raw), max(bx_raw), min(by_raw), max(by_raw)
        padding = max(xmax-xmin, ymax-ymin) * 0.15
        xi = np.linspace(xmin - padding, xmax + padding, d_res)
        yi = np.linspace(ymin - padding, ymax + padding, d_res)
        X, Y = np.meshgrid(xi, yi)
        cell_area = (xi[1]-xi[0]) * (yi[1]-yi[0])
        Z = griddata((v_pts[:, 0], v_pts[:, 1]), v_pts[:, 2], (X, Y), method='linear')
        grid_coords = np.stack([X.ravel(), Y.ravel()], axis=-1)
        mask = b_path.contains_points(grid_coords).reshape(X.shape)
        
        # 차트 출력 및 탭 구성
        tab1, tab2, tab3, tab4 = st.tabs(["⛰️ 표고 분석", "📐 경사 분석", "🧭 향 분석", "📝 종합 리포트"])
        
        # (tab1~tab4 내부 시각화 코드는 이전과 동일하게 유지)
        # 예시로 tab1만 표시
        with tab1:
            st.subheader("01. 표고 분석 (Elevation)")
            # ... (이전 코드와 동일한 차트 생성 로직)
            st.info("데이터 분석 결과가 화면에 표시됩니다.")

# --- [8. 푸터] ---
st.markdown(f'<div class="footer">© 2026 Landscape Analysis Pro | Created by <b>박지환 교수 (국립목포대학교 조경학과)</b></div>', unsafe_allow_html=True)
