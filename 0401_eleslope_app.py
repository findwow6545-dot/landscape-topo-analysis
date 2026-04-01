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

# --- [1. 한글 폰트 자동 로드 엔진] ---
@st.cache_resource
def load_korean_font():
    font_url = "https://github.com/google/fonts/raw/main/ofl/nanumgothic/NanumGothic-Regular.ttf"
    font_path = "NanumGothic.ttf"
    if not os.path.exists(font_path):
        try:
            res = requests.get(font_url)
            with open(font_path, "wb") as f:
                f.write(res.content)
        except: pass
    
    if os.path.exists(font_path):
        fe = fm.FontEntry(fname=font_path, name='NanumGothic')
        fm.fontManager.ttflist.insert(0, fe)
        plt.rcParams['font.family'] = fe.name
    else:
        plt.rcParams['font.family'] = 'sans-serif'
    
    plt.rcParams['axes.unicode_minus'] = False
    return plt.rcParams['font.family']

load_korean_font()

# --- [2. 전문 테마 CSS] ---
st.set_page_config(page_title="Site Analysis System", layout="wide")

st.markdown("""
    <style>
    .main { background-color: #f8f9fa; }
    .stButton>button { width: 100%; border-radius: 6px; height: 3.5em; background-color: #1e40af; color: white; font-weight: bold; }
    .footer { position: fixed; bottom: 0; left: 0; width: 100%; text-align: center; color: #475569; padding: 10px; background: rgba(255,255,255,0.9); font-size: 13px; z-index: 100; border-top: 1px solid #dee2e6; }
    h1 { color: #0f172a; font-weight: 800; }
    .intro-box { text-align: center; padding: 40px; background: white; border-radius: 15px; border: 1px solid #e2e8f0; margin-bottom: 20px; }
    </style>
    """, unsafe_allow_html=True)

# --- [3. 사이드바 설정] ---
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
    st.info(f"**[System Developer]**\n**박지환 교수**\n국립목포대학교 조경학과")

# --- [4. 메인 화면 헤더] ---
st.title("🗺️ Site Analysis System for Landscape Plan")
st.caption("Developed by Prof. Jihwan Park, Mokpo National University")

# 세션 상태 초기화
if 'final_data' not in st.session_state:
    st.session_state.final_data = None

# --- [5. 데이터 처리 로직 (버튼 클릭 시)] ---
if up_file is not None and submit_btn:
    try:
        raw_data = up_file.getvalue()
        memory_stream = io.BytesIO(raw_data)
        with st.spinner("전문 엔진이 데이터를 정밀 분석 중입니다..."):
            try:
                doc, auditor = recover.read(memory_stream)
            except:
                memory_stream.seek(0)
                doc = ezdxf.read(memory_stream)
            
            msp = doc.modelspace()
            boundary_entities = msp.query('LWPOLYLINE[layer=="0대상지경계"]')
            if not boundary_entities:
                st.error("❌ '0대상지경계' 레이어를 찾을 수 없습니다."); st.stop()
            
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

            # 분석 데이터 세션에 저장
            st.session_state.final_data = {
                'pts': np.array(all_pts), 'res': res_val, 
                'elev_cnt': elev_cnt, 'slope_step': slope_step, 'aspect_cnt': aspect_cnt,
                'mask_alpha': mask_opacity / 100.0, 'b_poly': b_poly, 'b_path': b_path
            }
    except Exception as e:
        st.error(f"⚠️ 시스템 오류: {str(e)}")

# --- [6. 화면 렌더링 분기] ---

# 상황 A: 아직 데이터가 없을 때 (초기 화면)
if st.session_state.final_data is None:
    st.markdown("""
        <div class="intro-box">
            <h2>Welcome to Landscape Analysis Engine</h2>
            <p>DXF 도면을 업로드하면 3D 지형 보간을 통해 정밀한 분석 리포트를 생성합니다.</p>
        </div>
    """, unsafe_allow_html=True)
    # 초기 시각화 이미지 (박지환 교수님께서 요청하신 지형 랜드스케이프 스타일)
    st.image("https://images.unsplash.com/photo-1506744038136-46273834b3fb?auto=format&fit=crop&w=1200&q=80", 
             caption="Topography Visualization & Decision Support System", use_container_width=True)

# 상황 B: 분석 데이터가 있을 때 (초기 이미지는 사라지고 결과 출력)
else:
    fd = st.session_state.final_data
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
    
    xlim_tmp, ylim_tmp = (xmin - padding, xmax + padding), (ymin - padding, ymax + padding)
    outer_sq = [(xlim_tmp[0], ylim_tmp[0]), (xlim_tmp[1], ylim_tmp[0]), (xlim_tmp[1], ylim_tmp[1]), (xlim_tmp[0], ylim_tmp[1]), (xlim_tmp[0], ylim_tmp[0])]
    combined_path = Path(outer_sq + b_poly, [Path.MOVETO] + [Path.LINETO]*4 + [Path.MOVETO] + [Path.LINETO]*(len(b_poly)-1))

    # 결과 대시보드 탭 구성
    tab1, tab2, tab3, tab4 = st.tabs(["⛰️ 표고 분석", "📐 경사 분석", "🧭 향 분석", "📝 종합 리포트"])

    # --- [공통 범례 함수 정의] ---
    def draw_categorical_legend(ax, cmap, norm, unit, data_array, cell_area, is_aspect=False):
        boundaries = norm.boundaries
        valid_data = data_array[~np.isnan(data_array)]
        total_area = len(valid_data) * cell_area
        for i in range(len(boundaries) - 1):
            lower, upper = boundaries[i], boundaries[i+1]
            count = np.sum((valid_data >= lower) & (valid_data < upper))
            area = count * cell_area
            percentage = (area / total_area * 100) if total_area > 0 else 0
            rect = plt.Rectangle((0, i), 1, 1, facecolor=cmap(i), edgecolor='black', linewidth=0.5)
            ax.add_patch(rect)
            label = f"{int(lower)}~{int(upper)}{unit} : {area:,.1f}m2 ({percentage:.1f}%)"
            if is_aspect:
                asp_lbls = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
                label = f"{asp_lbls[i]} : {area:,.1f}m2 ({percentage:.1f}%)"
            ax.text(1.2, i + 0.5, label, va='center', fontsize=10, fontweight='bold')
        ax.set_xlim(0, 15); ax.set_ylim(0, len(boundaries)-1); ax.axis('off')

    with tab1:
        st.subheader("01. 표고 분석 (Elevation)")
        Z_final = np.where(mask, Z, np.nan)
        z_min, z_max = np.nanmin(Z_final), np.nanmax(Z_final)
        z_levels = np.linspace(z_min, z_max, fd['elev_cnt'] + 1)
        fig1, ax1 = plt.subplots(1, 2, figsize=(16, 6), gridspec_kw={'width_ratios': [1.3, 2.7]})
        draw_categorical_legend(ax1[0], plt.get_cmap('terrain', fd['elev_cnt']), BoundaryNorm(z_levels, ncolors=256), "m", Z_final, cell_area)
        ax1[1].imshow(Z, extent=(min(xi), max(xi), min(yi), max(yi)), origin='lower', cmap='terrain', norm=BoundaryNorm(z_levels, ncolors=256), aspect='equal')
        ax1[1].add_patch(PathPatch(combined_path, facecolor='white', alpha=m_alpha, edgecolor='none', zorder=5))
        ax1[1].plot(bx_raw, by_raw, color='red', linewidth=2, zorder=10)
        st.pyplot(fig1)

    with tab2:
        st.subheader("02. 경사 분석 (Slope)")
        dx, dy = np.gradient(Z, (xi[1]-xi[0]), (yi[1]-yi[0]))
        slope = np.degrees(np.arctan(np.sqrt(dx**2 + dy**2)))
        slope_final = np.where(mask, slope, np.nan)
        s_max = np.nanmax(slope_final)
        s_levels = np.arange(0, s_max + fd['slope_step'], fd['slope_step'])
        fig2, ax2 = plt.subplots(1, 2, figsize=(16, 6), gridspec_kw={'width_ratios': [1.3, 2.7]})
        draw_categorical_legend(ax2[0], plt.get_cmap('YlOrRd', len(s_levels)-1), BoundaryNorm(s_levels, ncolors=256), "도", slope_final, cell_area)
        ax2[1].imshow(slope, extent=(min(xi), max(xi), min(yi), max(yi)), origin='lower', cmap='YlOrRd', norm=BoundaryNorm(s_levels, ncolors=256), aspect='equal')
        ax2[1].add_patch(PathPatch(combined_path, facecolor='white', alpha=m_alpha, edgecolor='none', zorder=5))
        ax2[1].plot(bx_raw, by_raw, color='red', linewidth=2, zorder=10)
        st.pyplot(fig2)

    with tab3:
        st.subheader("03. 향 분석 (Aspect)")
        aspect = np.degrees(np.arctan2(-dx, dy)); aspect = np.mod(aspect, 360)
        aspect_final = np.where(mask, aspect, np.nan)
        a_cnt = fd['aspect_cnt']
        a_levels = np.linspace(0, 360, a_cnt + 1)
        a_cmap = ListedColormap(['#e6194b', '#f58231', '#ffe119', '#bfef45', '#3cb44b', '#42d4f4', '#4363d8', '#911eb4']) if a_cnt == 8 else plt.get_cmap('hsv', a_cnt)
        fig3, ax3 = plt.subplots(1, 2, figsize=(16, 6), gridspec_kw={'width_ratios': [1.3, 2.7]})
        draw_categorical_legend(ax3[0], a_cmap, BoundaryNorm(a_levels, ncolors=a_cnt), "", aspect_final, cell_area, is_aspect=True)
        ax3[1].imshow(aspect, extent=(min(xi), max(xi), min(yi), max(yi)), origin='lower', cmap=a_cmap, norm=BoundaryNorm(a_levels, ncolors=a_cnt), aspect='equal')
        ax3[1].add_patch(PathPatch(combined_path, facecolor='white', alpha=m_alpha, edgecolor='none', zorder=5))
        ax3[1].plot(bx_raw, by_raw, color='red', linewidth=2, zorder=10)
        st.pyplot(fig3)

    with tab4:
        st.subheader("04. 종합 리포트")
        total_site_area = np.sum(~np.isnan(Z_final)) * cell_area
        st.metric("대상지 면적", f"{total_site_area:,.1f} m2")
        st.info(f"분석 엔진: 국립목포대학교 박지환 교수")

# --- [7. 공식 푸터] ---
st.markdown(f'<div class="footer">© 2026 Landscape Analysis Pro | Created by <b>박지환 교수 (국립목포대학교 조경학과)</b></div>', unsafe_allow_html=True)
