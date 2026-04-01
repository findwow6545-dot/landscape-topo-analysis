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

# --- [1. 환경 설정 및 한글 폰트] ---
try:
    plt.rcParams['font.family'] = 'Malgun Gothic'
except:
    plt.rcParams['font.family'] = 'sans-serif'
plt.rcParams['axes.unicode_minus'] = False

st.set_page_config(page_title="조경설계 지형 종합 분석 도구", layout="wide")

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
        else:
            return f"{int(360/total_steps*idx)}°~{int(360/total_steps*(idx+1))}°"

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
            
        ax.text(1.2, i + 0.5, label, va='center', fontsize=9, fontweight='bold')
        
    ax.set_xlim(0, 15)
    ax.set_ylim(0, max(len(boundaries) - 1, 1))
    ax.axis('off')
    ax.set_title(f"구간별 현황 (총 면적: {total_area:,.1f}㎡)", fontsize=11, pad=10)

# --- [3. 메인 인터페이스] ---
st.title("📑 조경설계 표고/경사/향 분석- 목포대학교 조경학과 박지환교수")

if 'final_data' not in st.session_state:
    st.session_state.final_data = None

with st.sidebar:
    st.header("⚙️ 분석 설정")
    with st.form("analysis_form"):
        res_val = st.slider("분석 정밀도 (Grid Res)", 50, 400, 250)
        
        st.subheader("📊 범례 및 시각화 설정")
        elev_cnt = st.number_input("표고 구간 개수", min_value=3, max_value=20, value=10)
        slope_step = st.number_input("경사 범례 간격 (도)", min_value=1, max_value=15, value=5)
        aspect_cnt = st.selectbox("향 분석 방위 설정", options=[4, 8, 16], index=1)
        
        # [신규] 투명도 조절 슬라이더 추가
        mask_opacity = st.slider("경계 밖 투명도 (%)", 0, 100, 50)
        
        up_file = st.file_uploader("DXF 파일을 업로드하세요", type=["dxf"])
        submit_btn = st.form_submit_button("🚀 분석 실행")

CONTOUR_LAYERS = ["F0017111", "F0017114"]
BOUNDARY_LAYER = "0대상지경계"

# --- [4. 데이터 처리 로직] ---
if up_file is not None and submit_btn:
    try:
        raw_data = up_file.getvalue()
        memory_stream = io.BytesIO(raw_data)
        with st.spinner("지형 분석 중..."):
            try:
                doc, auditor = recover.read(memory_stream)
            except:
                memory_stream.seek(0)
                doc = ezdxf.read(memory_stream)
            
            msp = doc.modelspace()
            boundary_entities = msp.query(f'LWPOLYLINE[layer=="{BOUNDARY_LAYER}"]')
            if not boundary_entities:
                st.error(f"❌ '{BOUNDARY_LAYER}' 레이어 누락"); st.stop()
            
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
                'mask_alpha': mask_opacity / 100.0, # 0~1 값으로 변환
                'b_poly': b_poly, 'b_path': b_path
            }
    except Exception as e:
        st.error(f"❌ 오류: {str(e)}")

# --- [5. 시각화 출력] ---
if st.session_state.final_data is not None:
    fd = st.session_state.final_data
    v_pts, d_res, b_poly, b_path = fd['pts'], fd['res'], fd['b_poly'], fd['b_path']
    m_alpha = fd['mask_alpha'] # 저장된 투명도 값 불러오기
    
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

    # 1. 표고 분석
    st.write("### ⛰️ 01. 표고 분석")
    Z_final = np.where(mask, Z, np.nan)
    z_min, z_max = np.nanmin(Z_final), np.nanmax(Z_final)
    z_levels = np.linspace(z_min, z_max, fd['elev_cnt'] + 1)
    z_cmap = plt.get_cmap('terrain', fd['elev_cnt'])
    z_norm = BoundaryNorm(z_levels, ncolors=fd['elev_cnt'])

    fig1, ax1 = plt.subplots(1, 2, figsize=(16, 6), gridspec_kw={'width_ratios': [1.3, 2.7]})
    draw_categorical_legend_with_area(ax1[0], z_cmap, z_norm, "m", Z_final, cell_area)
    ax1[1].imshow(Z, extent=(min(xi), max(xi), min(yi), max(yi)), origin='lower', cmap=z_cmap, norm=z_norm, aspect='equal')
    ax1[1].add_patch(PathPatch(combined_path, facecolor='white', alpha=m_alpha, edgecolor='none', zorder=5))
    ax1[1].plot(bx_raw, by_raw, color='red', linewidth=2, zorder=10)
    st.pyplot(fig1)

    # 2. 경사 분석
    st.write("---")
    st.write("### 📐 02. 경사 분석")
    dx, dy = np.gradient(Z, (xi[1]-xi[0]), (yi[1]-yi[0]))
    slope = np.degrees(np.arctan(np.sqrt(dx**2 + dy**2)))
    slope_final = np.where(mask, slope, np.nan)
    s_max = np.nanmax(slope_final)
    s_levels = np.arange(0, s_max + fd['slope_step'], fd['slope_step'])
    s_cnt = len(s_levels) - 1
    s_cmap = plt.get_cmap('YlOrRd', s_cnt)
    s_norm = BoundaryNorm(s_levels, ncolors=s_cnt)

    fig2, ax2 = plt.subplots(1, 2, figsize=(16, 6), gridspec_kw={'width_ratios': [1.3, 2.7]})
    draw_categorical_legend_with_area(ax2[0], s_cmap, s_norm, "°", slope_final, cell_area)
    ax2[1].imshow(slope, extent=(min(xi), max(xi), min(yi), max(yi)), origin='lower', cmap=s_cmap, norm=s_norm, aspect='equal')
    ax2[1].add_patch(PathPatch(combined_path, facecolor='white', alpha=m_alpha, edgecolor='none', zorder=5))
    ax2[1].plot(bx_raw, by_raw, color='red', linewidth=2, zorder=10)
    st.pyplot(fig2)

   # 3. 향 분석
    st.write("---")
    st.write("### 🧭 03. 향 분석 (Aspect Analysis)")
    aspect = np.degrees(np.arctan2(-dx, dy))
    aspect = np.mod(aspect, 360)
    aspect_final = np.where(mask, aspect, np.nan)
    
    # 설정된 방위 개수에 따른 색상 및 구간 설정
    a_cnt = fd['aspect_cnt']
    aspect_levels = np.linspace(0, 360, a_cnt + 1)
    
    # [수정 포인트] 방위 개수에 따른 색상 분기 처리
    if a_cnt == 4:
        # 4방위 전용: 북(Red), 동(Green), 남(Yellow), 서(Blue) - 고대비 설정
        aspect_colors = ['#e6194b', '#3cb44b', '#ffe119', '#4363d8']
        custom_aspect_cmap = ListedColormap(aspect_colors)
    elif a_cnt == 8:
        # 8방위 전용: 기존 요청하신 고대비 8색 유지
        aspect_colors = ['#e6194b', '#f58231', '#ffe119', '#bfef45', '#3cb44b', '#42d4f4', '#4363d8', '#911eb4']
        custom_aspect_cmap = ListedColormap(aspect_colors)
    else:
        # 16방위 등 그 외: 연속적인 hsv 맵 사용
        custom_aspect_cmap = plt.get_cmap('hsv', a_cnt)
        
    a_norm = BoundaryNorm(aspect_levels, ncolors=a_cnt)

    fig3, ax3 = plt.subplots(1, 2, figsize=(16, 6), gridspec_kw={'width_ratios': [1.3, 2.7]})
    
    # 범례와 차트에 수정된 cmap 적용
    draw_categorical_legend_with_area(ax3[0], custom_aspect_cmap, a_norm, "", aspect_final, cell_area, is_aspect=True)
    
    ax3[1].imshow(aspect, extent=(min(xi), max(xi), min(yi), max(yi)), origin='lower', 
                  cmap=custom_aspect_cmap, norm=a_norm, aspect='equal')
    
    # 경계 밖 투명 마스크 (사용자 설정값 적용)
    ax3[1].add_patch(PathPatch(combined_path, facecolor='white', alpha=m_alpha, edgecolor='none', zorder=5))
    ax3[1].plot(bx_raw, by_raw, color='red', linewidth=2, zorder=10)
    st.pyplot(fig3)
