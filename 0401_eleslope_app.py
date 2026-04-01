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
        res = requests.get(font_url)
        with open(font_path, "wb") as f:
            f.write(res.content)
    
    fe = fm.FontEntry(fname=font_path, name='NanumGothic')
    fm.fontManager.ttflist.insert(0, fe)
    plt.rcParams['font.family'] = fe.name
    plt.rcParams['axes.unicode_minus'] = False
    return fe.name

font_name = load_korean_font()

# --- [2. 전문 테마 및 레이아웃 CSS] ---
st.set_page_config(page_title="Site Analysis System", layout="wide")

st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Nanum+Gothic:wght@400;700&display=swap');
    html, body, [class*="css"] { font-family: 'Nanum Gothic', sans-serif; }
    .main { background-color: #f1f5f9; }
    .stButton>button { width: 100%; border-radius: 6px; height: 3.5em; background-color: #1e40af; color: white; font-weight: bold; border: none; }
    .stButton>button:hover { background-color: #1e3a8a; border: 1px solid #ffffff; }
    .footer { position: fixed; bottom: 0; left: 0; width: 100%; text-align: center; color: #475569; padding: 12px; background: rgba(255,255,255,0.95); font-size: 13px; z-index: 100; border-top: 2px solid #cbd5e1; }
    h1 { color: #0f172a; font-weight: 800; letter-spacing: -0.5px; }
    h3 { border-left: 6px solid #1e40af; padding-left: 12px; color: #1e293b; margin-top: 24px; font-weight: bold; }
    .stMetric { background: white; padding: 15px; border-radius: 10px; border: 1px solid #e2e8f0; }
    </style>
    """, unsafe_allow_html=True)

# --- [3. 분석 핵심 함수] ---
def draw_categorical_legend_with_area(ax, cmap, norm, unit, data_array, cell_area, is_aspect=False):
    boundaries = norm.boundaries
    valid_data = data_array[~np.isnan(data_array)]
    total_area = len(valid_data) * cell_area
    
    def get_aspect_label(idx, total_steps):
        labels_8 = ["북(N)", "북동(NE)", "동(E)", "남동(SE)", "남(S)", "남서(SW)", "서(W)", "북서(NW)"]
        labels_4 = ["북(N)", "동(E)", "남(S)", "서(W)"]
        if total_steps == 8: return labels_8[idx]
        elif total_steps == 4: return labels_4[idx]
        else: return f"방위 {idx+1}"

    for i in range(len(boundaries) - 1):
        lower, upper = boundaries[i], boundaries[i+1]
        count = np.sum((valid_data >= lower) & (valid_data < upper))
        area = count * cell_area
        percentage = (area / total_area * 100) if total_area > 0 else 0
        color = cmap(i)
        rect = plt.Rectangle((0, i), 1, 1, facecolor=color, edgecolor='black', linewidth=0.5)
        ax.add_patch(rect)
        
        if is_aspect:
            direction_name = get_aspect_label(i, len(boundaries)-1)
            label = f"{direction_name} : {area:,.1f} m2 ({percentage:.1f}%)"
        else:
            u_txt = "m" if unit == "m" else "도"
            label = f"{int(lower)}~{int(upper)}{u_txt} : {area:,.1f} m2 ({percentage:.1f}%)"
        
        ax.text(1.2, i + 0.5, label, va='center', fontsize=10, fontweight='bold')
        
    ax.set_xlim(0, 15)
    ax.set_ylim(0, max(len(boundaries) - 1, 1))
    ax.axis('off')
    ax.set_title(f"현황 통계 (Total Area: {total_area:,.1f} m2)", fontsize=12, pad=15, fontweight='bold')

# --- [4. 사이드바 인터페이스 (용어 변경)] ---
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

# --- [5. 메인 화면 구성] ---
st.title("🗺️ Site Analysis System for Landscape Plan")
st.caption("Developed by Prof. Jihwan Park, Mokpo National University")

if 'final_data' not in st.session_state:
    st.session_state.final_data = None

CONTOUR_LAYERS = ["F0017111", "F0017114"]
BOUNDARY_LAYER = "0대상지경계"

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
            boundary_entities = msp.query(f'LWPOLYLINE[layer=="{BOUNDARY_LAYER}"]')
            if not boundary_entities:
                st.error(f"❌ 도면 오류: '{BOUNDARY_LAYER}' 레이어가 없습니다."); st.stop()
            
            b_poly = list(boundary_entities[0].get_points(format='xy'))
            if b_poly[0] != b_poly[-1]: b_poly.append(b_poly[0])
            b_path = Path(b_poly)

            all_pts = []
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
    except Exception as e:
        st.error(f"⚠️ 시스템 오류: {str(e)}")

# --- [6. 분석 대시보드] ---
if st.session_state.final_data:
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

    tab1, tab2, tab3, tab4 = st.tabs(["⛰️ 표고 분석", "📐 경사 분석", "🧭 향 분석", "📝 종합 리포트"])

    with tab1:
        st.subheader("01. 표고 분석 (Elevation)")
        Z_final = np.where(mask, Z, np.nan)
        z_min, z_max = np.nanmin(Z_final), np.nanmax(Z_final)
        z_levels = np.linspace(z_min, z_max, fd['elev_cnt'] + 1)
        fig1, ax1 = plt.subplots(1, 2, figsize=(16, 6), gridspec_kw={'width_ratios': [1.3, 2.7]})
        draw_categorical_legend_with_area(ax1[0], plt.get_cmap('terrain', fd['elev_cnt']), BoundaryNorm(z_levels, ncolors=256), "m", Z_final, cell_area)
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
        s_cnt = len(s_levels) - 1
        fig2, ax2 = plt.subplots(1, 2, figsize=(16, 6), gridspec_kw={'width_ratios': [1.3, 2.7]})
        draw_categorical_legend_with_area(ax2[0], plt.get_cmap('YlOrRd', s_cnt), BoundaryNorm(s_levels, ncolors=256), "도", slope_final, cell_area)
        ax2[1].imshow(slope, extent=(min(xi), max(xi), min(yi), max(yi)), origin='lower', cmap='YlOrRd', norm=BoundaryNorm(s_levels, ncolors=256), aspect='equal')
        ax2[1].add_patch(PathPatch(combined_path, facecolor='white', alpha=m_alpha, edgecolor='none', zorder=5))
        ax2[1].plot(bx_raw, by_raw, color='red', linewidth=2, zorder=10)
        st.pyplot(fig2)

    with tab3:
        st.subheader("03. 향 분석 (Aspect)")
        aspect = np.degrees(np.arctan2(-dx, dy)); aspect = np.mod(aspect, 360)
        aspect_final = np.where(mask, aspect, np.nan)
        a_cnt = fd['aspect_cnt']
        aspect_levels = np.linspace(0, 360, a_cnt + 1)
        if a_cnt == 4: a_cmap = ListedColormap(['#e6194b', '#3cb44b', '#ffe119', '#4363d8'])
        elif a_cnt == 8: a_cmap = ListedColormap(['#e6194b', '#f58231', '#ffe119', '#bfef45', '#3cb44b', '#42d4f4', '#4363d8', '#911eb4'])
        else: a_cmap = plt.get_cmap('hsv', a_cnt)
        fig3, ax3 = plt.subplots(1, 2, figsize=(16, 6), gridspec_kw={'width_ratios': [1.3, 2.7]})
        draw_categorical_legend_with_area(ax3[0], a_cmap, BoundaryNorm(aspect_levels, ncolors=a_cnt), "", aspect_final, cell_area, is_aspect=True)
        ax3[1].imshow(aspect, extent=(min(xi), max(xi), min(yi), max(yi)), origin='lower', cmap=a_cmap, norm=BoundaryNorm(aspect_levels, ncolors=a_cnt), aspect='equal')
        ax3[1].add_patch(PathPatch(combined_path, facecolor='white', alpha=m_alpha, edgecolor='none', zorder=5))
        ax3[1].plot(bx_raw, by_raw, color='red', linewidth=2, zorder=10)
        st.pyplot(fig3)

    with tab4:
        st.subheader("04. 종합 분석 리포트")
        total_site_area = np.sum(~np.isnan(Z_final)) * cell_area
        col1, col2, col3 = st.columns(3)
        col1.metric("대상지 면적", f"{total_site_area:,.1f} m2")
        col2.metric("평균 경사", f"{np.nanmean(slope_final):.1f} 도")
        col3.metric("최고 표고", f"{z_max:.1f} m")
        st.info(f"**시스템 정보:** 국립목포대학교 박지환 교수 지형 분석 엔진 가동 중")
        st.download_button("📂 결과 데이터 저장", f"면적: {total_site_area:,.1f}m2\n평균경사: {np.nanmean(slope_final):.1f}도", file_name="topo_report.txt")

    st.markdown(f'<div class="footer">© 2026 Landscape Analysis Pro | Created by <b>박지환 교수 (국립목포대학교 조경학과)</b></div>', unsafe_allow_html=True)
else:
    st.info("👈 사이드바에서 DXF 도면을 업로드하고 설정을 마친 뒤 [종합 분석 실행]을 클릭하세요.")
