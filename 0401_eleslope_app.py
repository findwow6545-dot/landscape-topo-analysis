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

# --- [1. 환경 설정 및 전문 테마 CSS] ---
st.set_page_config(page_title="Topography Analysis Pro", layout="wide", initial_sidebar_state="expanded")

# [폰트 해결] 특수기호 네모 현상 방지를 위한 시스템 폰트 강제 설정
plt.rcParams['axes.unicode_minus'] = False
plt.rcParams['font.family'] = 'sans-serif'
plt.rcParams['font.sans-serif'] = ['Arial', 'DejaVu Sans', 'Liberation Sans', 'sans-serif']

st.markdown("""
    <style>
    .main { background-color: #f8f9fa; }
    .stButton>button { width: 100%; border-radius: 5px; height: 3em; background-color: #1e3a8a; color: white; font-weight: bold; }
    .stTabs [data-baseweb="tab-list"] { gap: 24px; }
    .stTabs [data-baseweb="tab"] { height: 50px; font-weight: bold; font-size: 16px; }
    .footer { position: fixed; bottom: 0; left: 0; width: 100%; text-align: center; color: #6c757d; padding: 10px; background: rgba(255,255,255,0.9); font-size: 14px; z-index: 100; border-top: 1px solid #dee2e6; }
    h1 { color: #1e3a8a; }
    h3 { border-left: 5px solid #1e3a8a; padding-left: 10px; color: #334155; margin-top: 20px; }
    </style>
    """, unsafe_allow_html=True)

# --- [2. 공통 함수: 범례 및 면적 계산] ---
def draw_categorical_legend_with_area(ax, cmap, norm, unit, data_array, cell_area, is_aspect=False):
    boundaries = norm.boundaries
    valid_data = data_array[~np.isnan(data_array)]
    total_area = len(valid_data) * cell_area
    
    # ㎡ 기호 대신 m2 사용 (깨짐 방지)
    def get_aspect_label(idx, total_steps):
        labels_8 = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
        labels_4 = ["N", "E", "S", "W"]
        if total_steps == 8: return labels_8[idx]
        elif total_steps == 4: return labels_4[idx]
        else: return f"Dir {idx+1}"

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
            # deg 기호 대신 deg 텍스트 사용
            u_txt = "m" if unit == "m" else "deg"
            label = f"{int(lower)}~{int(upper)}{u_txt} : {area:,.1f} m2 ({percentage:.1f}%)"
        
        ax.text(1.2, i + 0.5, label, va='center', fontsize=10, fontweight='bold', family='sans-serif')
        
    ax.set_xlim(0, 15)
    ax.set_ylim(0, max(len(boundaries) - 1, 1))
    ax.axis('off')
    ax.set_title(f"Statistics (Total Area: {total_area:,.1f} m2)", fontsize=12, pad=15, fontweight='bold')

# --- [3. 사이드바 설정] ---
with st.sidebar:
    st.header("🛠️ Analysis Engine")
    with st.form("analysis_form"):
        up_file = st.file_uploader("DXF Drawing Upload", type=["dxf"])
        st.markdown("---")
        res_val = st.slider("Grid Resolution", 50, 400, 250)
        elev_cnt = st.number_input("Elevation Steps", 3, 20, 10)
        slope_step = st.number_input("Slope Step (deg)", 1, 15, 5)
        aspect_cnt = st.selectbox("Aspect Directions", [4, 8, 16], index=1)
        mask_opacity = st.slider("Masking Opacity (%)", 0, 100, 50)
        submit_btn = st.form_submit_button("🚀 Run Analysis")

    st.markdown("---")
    st.info(f"**[System Developer]**\n**Prof. Jihwan Park**\nMokpo National Univ.\nDept. of Landscape Architecture")

# --- [4. 메인 화면 구성] ---
st.title("🗺️ Landscape Topography Analysis Pro")
st.caption("Developed by Prof. Jihwan Park, Mokpo National University")

if 'final_data' not in st.session_state:
    st.session_state.final_data = None

CONTOUR_LAYERS = ["F0017111", "F0017114"]
BOUNDARY_LAYER = "0대상지경계"

if up_file is not None and submit_btn:
    try:
        raw_data = up_file.getvalue()
        memory_stream = io.BytesIO(raw_data)
        with st.spinner("Analyzing terrain data..."):
            try:
                doc, auditor = recover.read(memory_stream)
            except:
                memory_stream.seek(0)
                doc = ezdxf.read(memory_stream)
            
            msp = doc.modelspace()
            boundary_entities = msp.query(f'LWPOLYLINE[layer=="{BOUNDARY_LAYER}"]')
            if not boundary_entities:
                st.error(f"Error: Layer '{BOUNDARY_LAYER}' not found."); st.stop()
            
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
        st.error(f"System Error: {str(e)}")

# --- [5. 결과 대시보드 출력] ---
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

    tab1, tab2, tab3, tab4 = st.tabs(["⛰️ Elevation", "📐 Slope", "🧭 Aspect", "📝 Summary"])

    with tab1:
        st.subheader("01. Elevation Analysis (m)")
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
        st.subheader("02. Slope Analysis (deg)")
        dx, dy = np.gradient(Z, (xi[1]-xi[0]), (yi[1]-yi[0]))
        slope = np.degrees(np.arctan(np.sqrt(dx**2 + dy**2)))
        slope_final = np.where(mask, slope, np.nan)
        s_max = np.nanmax(slope_final)
        s_levels = np.arange(0, s_max + fd['slope_step'], fd['slope_step'])
        s_cnt = len(s_levels) - 1
        fig2, ax2 = plt.subplots(1, 2, figsize=(16, 6), gridspec_kw={'width_ratios': [1.3, 2.7]})
        draw_categorical_legend_with_area(ax2[0], plt.get_cmap('YlOrRd', s_cnt), BoundaryNorm(s_levels, ncolors=256), "deg", slope_final, cell_area)
        ax2[1].imshow(slope, extent=(min(xi), max(xi), min(yi), max(yi)), origin='lower', cmap='YlOrRd', norm=BoundaryNorm(s_levels, ncolors=256), aspect='equal')
        ax2[1].add_patch(PathPatch(combined_path, facecolor='white', alpha=m_alpha, edgecolor='none', zorder=5))
        ax2[1].plot(bx_raw, by_raw, color='red', linewidth=2, zorder=10)
        st.pyplot(fig2)

    with tab3:
        st.subheader("03. Aspect Analysis")
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
        st.subheader("04. Analysis Report")
        total_site_area = np.sum(~np.isnan(Z_final)) * cell_area
        col1, col2, col3 = st.columns(3)
        col1.metric("Site Area", f"{total_site_area:,.1f} m2")
        col2.metric("Avg Slope", f"{np.nanmean(slope_final):.1f} deg")
        col3.metric("Peak Elev", f"{z_max:.1f} m")
        st.info(f"**Analysis Report generated by Prof. Jihwan Park's Algorithm**")
        st.download_button("📂 Download CSV Report", f"Area: {total_site_area:,.1f}m2\nAvg Slope: {np.nanmean(slope_final):.1f}deg", file_name="topo_report.txt")

    st.markdown(f'<div class="footer">© 2026 Topography Analysis Engine | Created by <b>Prof. Jihwan Park (Mokpo National Univ.)</b></div>', unsafe_allow_html=True)
else:
    st.info("👈 Please upload a DXF file and click [Run Analysis] to begin.")
