import streamlit as st
import ezdxf
from ezdxf import recover
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.colors import BoundaryNorm, ListedColormap
from scipy.interpolate import griddata
from matplotlib.path import Path
from matplotlib.patches import PathPatch
import io

# --- [1. 환경 설정 및 테마 적용] ---
st.set_page_config(page_title="Topography Analysis Pro", layout="wide", initial_sidebar_state="expanded")

# 전문적인 인터페이스를 위한 CSS 설정
st.markdown("""
    <style>
    .main { background-color: #f8f9fa; }
    .stButton>button { width: 100%; border-radius: 5px; height: 3em; background-color: #1e3a8a; color: white; font-weight: bold; }
    .stTabs [data-baseweb="tab-list"] { gap: 24px; }
    .stTabs [data-baseweb="tab"] { height: 50px; white-space: pre-wrap; font-weight: bold; font-size: 16px; }
    .footer { position: fixed; bottom: 0; left: 0; width: 100%; text-align: center; color: #6c757d; padding: 10px; background: rgba(255,255,255,0.9); font-size: 14px; z-index: 100; border-top: 1px solid #dee2e6; }
    h1 { color: #1e3a8a; }
    h3 { border-left: 5px solid #1e3a8a; padding-left: 10px; color: #334155; margin-top: 20px; }
    </style>
    """, unsafe_allow_html=True)

# 한글 폰트 설정
try:
    plt.rcParams['font.family'] = 'Malgun Gothic'
except:
    plt.rcParams['font.family'] = 'sans-serif'
plt.rcParams['axes.unicode_minus'] = False

# --- [2. 공통 함수: 범례 및 면적 계산] ---
def draw_categorical_legend_with_area(ax, cmap, norm, unit, data_array, cell_area, is_aspect=False):
    boundaries = norm.boundaries
    valid_data = data_array[~np.isnan(data_array)]
    total_area = len(valid_data) * cell_area
    
    def get_aspect_label(idx, total_steps):
        if total_steps == 8:
            return ["북(N)", "북동(NE)", "동(E)", "남동(SE)", "남(S)", "남서(SW)", "서(W)", "북서(NW)"][idx]
        elif total_steps == 4:
            return ["북(N)", "동(E)", "남(S)", "서(W)"][idx]
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
            label = f"{direction_name} : {area:,.1f}㎡ ({percentage:.1f}%)"
        else:
            label = f"{int(lower)}~{int(upper)}{unit} : {area:,.1f}㎡ ({percentage:.1f}%)"
        ax.text(1.2, i + 0.5, label, va='center', fontsize=10, fontweight='bold')
        
    ax.set_xlim(0, 15)
    ax.set_ylim(0, max(len(boundaries) - 1, 1))
    ax.axis('off')
    ax.set_title(f"📊 통계 (총 면적: {total_area:,.1f}㎡)", fontsize=12, pad=15, fontweight='bold')

# --- [3. 사이드바 구성] ---
with st.sidebar:
    st.header("🛠️ 표고분석/경사분석/향분석")
    
    with st.form("analysis_form"):
        up_file = st.file_uploader("DXF 도면 파일 업로드(수치지형도)", type=["dxf"])
        st.markdown("---")
        res_val = st.slider("분석 해상도 (Grid)", 50, 400, 250)
        elev_cnt = st.number_input("표고 범례 구간 수", 3, 20, 10)
        slope_step = st.number_input("경사 범례 간격 (도)", 1, 15, 5)
        aspect_cnt = st.selectbox("향 분석 방위 설정", [4, 8, 16], index=1)
        mask_opacity = st.slider("경계 외부 마스킹 (%)", 0, 100, 50)
        
        submit_btn = st.form_submit_button("🚀 종합 분석 실행")

    st.markdown("---")
    st.info(f"""
    **[시스템 제작자]** **박지환 교수** (국립목포대학교 조경학과)  
    전문 지형 분석 알고리즘 탑재 v2.0
    """)

# --- [4. 메인 화면 구성] ---
st.title("🗺️ Landscape Topography Analysis Pro")
st.caption("고정밀 수치지형 데이터를 활용한 조경 설계 의사결정 지원 시스템")

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
                st.error(f"❌ 도면 오류: '{BOUNDARY_LAYER}' 레이어가 존재하지 않습니다."); st.stop()
            
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

# --- [5. 결과 대시보드] ---
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
    combined_path = Path([(xmin-padding, ymin-padding), (xmax+padding, ymin-padding), (xmax+padding, ymax+padding), (xmin-padding, ymax+padding), (xmin-padding, ymin-padding)] + b_poly, 
                         [Path.MOVETO] + [Path.LINETO]*4 + [Path.MOVETO] + [Path.LINETO]*(len(b_poly)-1))

    # 전문 Tab UI
    tab1, tab2, tab3, tab4 = st.tabs(["⛰️ 표고 분석", "📐 경사 분석", "🧭 향 분석", "📝 종합 리포트"])

    with tab1:
        st.subheader("01. 표고 분석 (Elevation Analysis)")
        Z_final = np.where(mask, Z, np.nan)
        z_min, z_max = np.nanmin(Z_final), np.nanmax(Z_final)
        z_levels = np.linspace(z_min, z_max, fd['elev_cnt'] + 1)
        fig1, ax1 = plt.subplots(1, 2, figsize=(16, 6), gridspec_kw={'width_ratios': [1, 2]})
        draw_categorical_legend_with_area(ax1[0], plt.get_cmap('terrain', fd['elev_cnt']), BoundaryNorm(z_levels, ncolors=fd['elev_cnt']), "m", Z_final, cell_area)
        ax1[1].imshow(Z, extent=(min(xi), max(xi), min(yi), max(yi)), origin='lower', cmap='terrain', norm=BoundaryNorm(z_levels, ncolors=fd['elev_cnt']), aspect='equal')
        ax1[1].add_patch(PathPatch(combined_path, facecolor='white', alpha=m_alpha, edgecolor='none', zorder=5))
        ax1[1].plot(bx_raw, by_raw, color='#ef4444', linewidth=2.5, zorder=10)
        st.pyplot(fig1)

    with tab2:
        st.subheader("02. 경사 분석 (Slope Analysis)")
        dx, dy = np.gradient(Z, (xi[1]-xi[0]), (yi[1]-yi[0]))
        slope = np.degrees(np.arctan(np.sqrt(dx**2 + dy**2)))
        slope_final = np.where(mask, slope, np.nan)
        s_max = np.nanmax(slope_final)
        s_levels = np.arange(0, s_max + fd['slope_step'], fd['slope_step'])
        s_cnt = len(s_levels) - 1
        fig2, ax2 = plt.subplots(1, 2, figsize=(16, 6), gridspec_kw={'width_ratios': [1, 2]})
        draw_categorical_legend_with_area(ax2[0], plt.get_cmap('YlOrRd', s_cnt), BoundaryNorm(s_levels, ncolors=s_cnt), "°", slope_final, cell_area)
        ax2[1].imshow(slope, extent=(min(xi), max(xi), min(yi), max(yi)), origin='lower', cmap='YlOrRd', norm=BoundaryNorm(s_levels, ncolors=s_cnt), aspect='equal')
        ax2[1].add_patch(PathPatch(combined_path, facecolor='white', alpha=m_alpha, edgecolor='none', zorder=5))
        ax2[1].plot(bx_raw, by_raw, color='#ef4444', linewidth=2.5, zorder=10)
        st.pyplot(fig2)

    with tab3:
        st.subheader("03. 향 분석 (Aspect Analysis)")
        aspect = np.degrees(np.arctan2(-dx, dy)); aspect = np.mod(aspect, 360)
        aspect_final = np.where(mask, aspect, np.nan)
        a_cnt = fd['aspect_cnt']
        aspect_levels = np.linspace(0, 360, a_cnt + 1)
        if a_cnt == 4: a_cmap = ListedColormap(['#e6194b', '#3cb44b', '#ffe119', '#4363d8'])
        elif a_cnt == 8: a_cmap = ListedColormap(['#e6194b', '#f58231', '#ffe119', '#bfef45', '#3cb44b', '#42d4f4', '#4363d8', '#911eb4'])
        else: a_cmap = plt.get_cmap('hsv', a_cnt)
        fig3, ax3 = plt.subplots(1, 2, figsize=(16, 6), gridspec_kw={'width_ratios': [1, 2]})
        draw_categorical_legend_with_area(ax3[0], a_cmap, BoundaryNorm(aspect_levels, ncolors=a_cnt), "", aspect_final, cell_area, is_aspect=True)
        ax3[1].imshow(aspect, extent=(min(xi), max(xi), min(yi), max(yi)), origin='lower', cmap=a_cmap, norm=BoundaryNorm(aspect_levels, ncolors=a_cnt), aspect='equal')
        ax3[1].add_patch(PathPatch(combined_path, facecolor='white', alpha=m_alpha, edgecolor='none', zorder=5))
        ax3[1].plot(bx_raw, by_raw, color='#ef4444', linewidth=2.5, zorder=10)
        st.pyplot(fig3)

    with tab4:
        st.subheader("04. 종합 분석 리포트")
        total_site_area = np.sum(~np.isnan(Z_final)) * cell_area
        col1, col2, col3 = st.columns(3)
        col1.metric("대상지 총 면적", f"{total_site_area:,.1f} ㎡")
        col2.metric("평균 경사도", f"{np.nanmean(slope_final):.1f} °")
        col3.metric("최고 표고", f"{z_max:.1f} m")
        st.success(f"**전문 분석 엔진 가동 결과:** 본 데이터는 국립목포대학교 박지환 교수의 알고리즘에 의해 정밀 산출되었습니다.")
        st.download_button("📂 텍스트 결과 저장", f"총면적: {total_site_area:,.1f}㎡\n평균경사: {np.nanmean(slope_final):.1f}도", file_name="report.txt")

else:
    st.info("👈 사이드바의 설정창에서 DXF 도면을 업로드하고 [종합 분석 실행]을 클릭하십시오.")

# --- [6. 공식 푸터 표기] ---
st.markdown(f"""
    <div class="footer">
        © 2026 Landscape Topography Analysis Engine | Developed by <b>박지환 교수 (국립목포대학교 조경학과)</b>
    </div>
    """, unsafe_allow_html=True)
