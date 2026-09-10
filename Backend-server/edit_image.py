import cv2
import numpy as np

# ── เครื่องมือวาดระดับ Sub-pixel ──────────────────────────────────────────
SHIFT = 4  # วาดด้วยความละเอียดย่อย 1/16 พิกเซล
F = 1 << SHIFT


def P(x, y):
    return (int(round(x * F)), int(round(y * F)))


def draw_dashed_line(img_out, p1, p2, color, thickness=2, dash_len=8, space_len=6):
    dist = np.hypot(p2[0] - p1[0], p2[1] - p1[1])
    if dist == 0:
        return
    dx = (p2[0] - p1[0]) / dist
    dy = (p2[1] - p1[1]) / dist

    curr = 0.0
    draw_state = True
    while curr < dist:
        step = dash_len if draw_state else space_len
        next_curr = min(curr + step, dist)
        if draw_state:
            sp = (p1[0] + dx * curr, p1[1] + dy * curr)
            ep = (p1[0] + dx * next_curr, p1[1] + dy * next_curr)
            cv2.line(img_out, P(*sp), P(*ep), color, thickness, cv2.LINE_AA, SHIFT)
        curr = next_curr
        draw_state = not draw_state


def draw_label(img_out, text, pt, color=(255, 255, 255)):
    font = cv2.FONT_HERSHEY_SIMPLEX
    scale = 0.7
    thick = 2
    outline_thick = 5

    (text_w, text_h), _ = cv2.getTextSize(text, font, scale, thick)
    tx = int(round(pt[0] - text_w / 2.0))
    ty = int(round(pt[1] + text_h / 2.0))

    cv2.putText(img_out, text, (tx, ty), font, scale, (0, 0, 0), outline_thick, cv2.LINE_AA)
    cv2.putText(img_out, text, (tx, ty), font, scale, color, thick, cv2.LINE_AA)


def process_and_save_image(image_path, pair):
    # 1. โหลดภาพและแปลงเป็น Grayscale
    # ⚠ `cv2.imread` **ไม่ raise** เวลาอ่านไม่ออก — คืน `None` เงียบ ๆ แล้วไป
    #   ระเบิดที่ `cvtColor` บรรทัดถัดไปเป็น `cv2.error` ที่อ่านไม่รู้เรื่อง
    #   เช็คเองตรงนี้เพื่อให้ผู้เรียกได้ข้อความที่บอกสาเหตุจริง (ไฟล์ยังเขียน
    #   ไม่เสร็จ / ถูกล็อก / ไฟล์เสีย) ไม่ใช่ assertion ของ OpenCV
    img = cv2.imread(image_path)
    if img is None:
        raise ValueError(f"อ่านไฟล์รูปไม่ได้ (ไฟล์เสียหรือยังเขียนไม่เสร็จ): {image_path}")

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    # 2. ทำ Threshold แยกชิ้นงานสีเข้มออกจากพื้นหลัง
    _, thresh = cv2.threshold(gray, 70, 255, cv2.THRESH_BINARY_INV)

    # 2.5 ล้างเศษ/รอยขีดข่วนออกจากรู (Morphological Opening)
    CLEAN_KERNEL = 5
    _kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (CLEAN_KERNEL, CLEAN_KERNEL))
    thresh = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, _kernel)

    # 3. หา Contour และ Hierarchy เพื่อระบุรูที่อยู่ด้านในชิ้นงาน (RETR_CCOMP)
    contours, hierarchy = cv2.findContours(thresh, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_NONE)

    detected_holes = []

    if hierarchy is not None:
        for i, cnt in enumerate(contours):
            if hierarchy[0][i][3] != -1:
                area = cv2.contourArea(cnt)
                perimeter = cv2.arcLength(cnt, True)

                if perimeter > 0:
                    circularity = 4 * np.pi * area / (perimeter * perimeter)
                    (x, y), radius = cv2.minEnclosingCircle(cnt)

                    if circularity > 0.65 and 10 < radius < 40:
                        detected_holes.append((x, y, radius))

    output = img.copy()

    # ══════════════════════════════════════════════════════════════════════════
    # LAYER 1: วาดเส้นแนวแกนสีเหลือง (Background Layer)
    # ══════════════════════════════════════════════════════════════════════════
    if detected_holes:
        y_coords = [h[1] for h in detected_holes]
        min_y, max_y = min(y_coords), max(y_coords)
        y_range = max_y - min_y

        top_holes = [h for h in detected_holes if abs(h[1] - min_y) < y_range * 0.25]
        bottom_holes = [h for h in detected_holes if abs(h[1] - max_y) < y_range * 0.25]

        top_holes = sorted(top_holes, key=lambda h: h[0])
        bottom_holes = sorted(bottom_holes, key=lambda h: h[0])

        midpoints = []
        YELLOW = (0, 255, 255)

        for hole_top, hole_bottom in zip(top_holes, bottom_holes):
            x1, y1, r1 = hole_top
            x2, y2, r2 = hole_bottom

            for (x, y, r) in ((x1, y1, r1), (x2, y2, r2)):
                cv2.circle(output, P(x, y), int(round(r * F)), YELLOW, 2, cv2.LINE_AA, SHIFT)

            cv2.line(output, P(x1, y1), P(x2, y2), YELLOW, 2, cv2.LINE_AA, SHIFT)
            midpoints.append(((x1 + x2) / 2.0, (y1 + y2) / 2.0))

        if len(midpoints) >= 2:
            midpoints_sorted = sorted(midpoints, key=lambda m: m[0])

            for (mx1, my1), (mx2, my2) in zip(midpoints_sorted, midpoints_sorted[1:]):
                cv2.line(output, P(mx1, my1), P(mx2, my2), YELLOW, 2, cv2.LINE_AA, SHIFT)

            for (mx, my) in midpoints_sorted:
                cv2.circle(output, P(mx, my), int(round(4 * F)), YELLOW, -1, cv2.LINE_AA, SHIFT)

        if len(top_holes) >= 2 and len(bottom_holes) >= 2:
            t_left, t_right = top_holes[0], top_holes[-1]
            b_left, b_right = bottom_holes[0], bottom_holes[-1]

            bis_top = ((t_left[0] + t_right[0]) / 2.0, (t_left[1] + t_right[1]) / 2.0)
            bis_bottom = ((b_left[0] + b_right[0]) / 2.0, (b_left[1] + b_right[1]) / 2.0)

            cv2.line(output, P(*bis_top), P(*bis_bottom), YELLOW, 2, cv2.LINE_AA, SHIFT)

            for (mx, my) in (bis_top, bis_bottom):
                cv2.circle(output, P(mx, my), int(round(4 * F)), YELLOW, -1, cv2.LINE_AA, SHIFT)

    # ══════════════════════════════════════════════════════════════════════════
    # LAYER 2 & 3: คำนวณและวาดเส้นสีฟ้า / เส้นสีเขียว
    # ══════════════════════════════════════════════════════════════════════════
    NECK_WINDOW = 18
    NECK_GAP = 25
    BLUE = (220, 160, 100)
    GREEN = (0, 255, 0)

    square_cnt = None
    main_body_idx = None

    if hierarchy is not None:
        _h, _w = thresh.shape[:2]
        body_area = 0
        for i, cnt in enumerate(contours):
            if hierarchy[0][i][3] != -1:
                continue
            bx_, by_, bw_, bh_ = cv2.boundingRect(cnt)
            if bw_ > _w * 0.9 and bh_ > _h * 0.9:
                continue
            a = cv2.contourArea(cnt)
            if a > body_area:
                main_body_idx, body_area = i, a

        if main_body_idx is not None:
            best = 0
            for i, cnt in enumerate(contours):
                if hierarchy[0][i][3] != main_body_idx:
                    continue
                a = cv2.contourArea(cnt)
                if a > best:
                    square_cnt, best = cnt, a

    if square_cnt is not None and len(square_cnt) > 4 * NECK_WINDOW:
        pts = square_cnt.reshape(-1, 2).astype(float)
        n = len(pts)

        def _cross2(u, v):
            return u[0] * v[1] - u[1] * v[0]

        turn = np.empty(n)
        for i in range(n):
            v1 = pts[i] - pts[(i - NECK_WINDOW) % n]
            v2 = pts[(i + NECK_WINDOW) % n] - pts[i]
            turn[i] = np.degrees(np.arctan2(_cross2(v1, v2), np.dot(v1, v2)))

        picked = []
        for i in np.argsort(turn):
            if all(min(abs(i - j), n - abs(i - j)) > NECK_GAP for j in picked):
                picked.append(i)
            if len(picked) == 8:
                break
        necks = [tuple(pts[i]) for i in picked]

        if len(necks) == 8:
            sx, sy, sw, sh = cv2.boundingRect(square_cnt)
            scx, scy = sx + sw / 2.0, sy + sh / 2.0
            horiz = lambda p: abs(p[1] - scy) > abs(p[0] - scx)

            edge_top = sorted([p for p in necks if horiz(p) and p[1] < scy], key=lambda p: p[0])
            edge_bottom = sorted([p for p in necks if horiz(p) and p[1] > scy], key=lambda p: p[0])
            edge_left = sorted([p for p in necks if not horiz(p) and p[0] < scx], key=lambda p: p[1])
            edge_right = sorted([p for p in necks if not horiz(p) and p[0] > scx], key=lambda p: p[1])

            for grp in (edge_top, edge_bottom, edge_left, edge_right):
                if len(grp) == 2:
                    cv2.line(output, P(*grp[0]), P(*grp[1]), BLUE, 3, cv2.LINE_AA, SHIFT)

            def add_dimension(edge_pts, ratio=0.5, extra_ratio=0.1, color=BLUE, label=""):
                if len(edge_pts) != 2:
                    return
                a, b = edge_pts[0], edge_pts[1]
                v = (b[0] - a[0], b[1] - a[1])
                length = np.hypot(v[0], v[1])
                if length == 0:
                    return

                offset = length * ratio
                extra = length * extra_ratio

                n1 = (-v[1] / length, v[0] / length)
                n2 = (v[1] / length, -v[0] / length)
                mid = ((a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0)
                out_vec = (mid[0] - scx, mid[1] - scy)
                n = n1 if (out_vec[0] * n1[0] + out_vec[1] * n1[1]) > 0 else n2

                a_dim = (a[0] + n[0] * offset, a[1] + n[1] * offset)
                b_dim = (b[0] + n[0] * offset, b[1] + n[1] * offset)
                a_ext = (a[0] + n[0] * (offset + extra), a[1] + n[1] * (offset + extra))
                b_ext = (b[0] + n[0] * (offset + extra), b[1] + n[1] * (offset + extra))

                cv2.line(output, P(*a), P(*a_ext), color, 2, cv2.LINE_AA, SHIFT)
                cv2.line(output, P(*b), P(*b_ext), color, 2, cv2.LINE_AA, SHIFT)
                draw_dashed_line(output, a_dim, b_dim, color, thickness=2)

                if label:
                    mid_dim = ((a_dim[0] + b_dim[0]) / 2.0, (a_dim[1] + b_dim[1]) / 2.0)
                    draw_label(output, label, mid_dim)

            def add_split_dimension(edge_pts, ratio=0.25, tick_len=12, color=GREEN, labels=("", "")):
                if len(edge_pts) != 2:
                    return
                a, b = edge_pts[0], edge_pts[1]
                v = (b[0] - a[0], b[1] - a[1])
                length = np.hypot(v[0], v[1])
                if length == 0:
                    return

                offset = length * ratio

                n1 = (-v[1] / length, v[0] / length)
                n2 = (v[1] / length, -v[0] / length)
                mid = ((a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0)
                out_vec = (mid[0] - scx, mid[1] - scy)
                n = n1 if (out_vec[0] * n1[0] + out_vec[1] * n1[1]) > 0 else n2

                a_dim = (a[0] + n[0] * offset, a[1] + n[1] * offset)
                b_dim = (b[0] + n[0] * offset, b[1] + n[1] * offset)
                mid_dim = ((a_dim[0] + b_dim[0]) / 2.0, (a_dim[1] + b_dim[1]) / 2.0)

                def draw_tick(pt):
                    p_start = (pt[0] - n[0] * (tick_len / 2.0), pt[1] - n[1] * (tick_len / 2.0))
                    p_end = (pt[0] + n[0] * (tick_len / 2.0), pt[1] + n[1] * (tick_len / 2.0))
                    cv2.line(output, P(*p_start), P(*p_end), color, 2, cv2.LINE_AA, SHIFT)

                draw_tick(a_dim)
                draw_tick(mid_dim)
                draw_tick(b_dim)

                draw_dashed_line(output, a_dim, mid_dim, color, thickness=2)
                draw_dashed_line(output, mid_dim, b_dim, color, thickness=2)

                if labels[0]:
                    seg1_mid = ((a_dim[0] + mid_dim[0]) / 2.0, (a_dim[1] + mid_dim[1]) / 2.0)
                    draw_label(output, labels[0], seg1_mid)
                if labels[1]:
                    seg2_mid = ((mid_dim[0] + b_dim[0]) / 2.0, (mid_dim[1] + b_dim[1]) / 2.0)
                    draw_label(output, labels[1], seg2_mid)

            if len(edge_left) == 2 and len(edge_right) == 2:
                top_wide_pts = [edge_left[0], edge_right[0]]
                add_dimension(top_wide_pts, ratio=0.50, label="[1]")

            if len(edge_top) == 2 and len(edge_bottom) == 2:
                right_wide_pts = [edge_top[1], edge_bottom[1]]
                add_dimension(right_wide_pts, ratio=0.50, label="[2]")

            if len(edge_left) == 2 and len(edge_right) == 2:
                add_split_dimension(top_wide_pts, ratio=0.25, labels=("[3]", "[4]"))

            if len(edge_top) == 2 and len(edge_bottom) == 2:
                add_split_dimension(right_wide_pts, ratio=0.25, labels=("[5]", "[6]"))

    # ══════════════════════════════════════════════════════════════════════════
    # Crop เฉพาะพื้นที่ชิ้นงาน
    # ══════════════════════════════════════════════════════════════════════════
    if main_body_idx is not None:
        bx, by, bw, bh = cv2.boundingRect(contours[main_body_idx])
        padding = 20
        crop_x1 = max(0, bx - padding)
        crop_y1 = max(0, by - padding)
        crop_x2 = min(img.shape[1], bx + bw + padding)
        crop_y2 = min(img.shape[0], by + bh + padding)
        cropped_piece = output[crop_y1:crop_y2, crop_x1:crop_x2]
    else:
        cropped_piece = output.copy()

    # ══════════════════════════════════════════════════════════════════════════
    # รวมภาพชิ้นงาน (ซ้าย) เข้ากับ Canvas ตาราง (ขวา)
    # ══════════════════════════════════════════════════════════════════════════
    TARGET_HEIGHT = 600
    TABLE_WIDTH = 420

    h_c, w_c = cropped_piece.shape[:2]
    scale = TARGET_HEIGHT / float(h_c)
    w_new = int(round(w_c * scale))
    resized_crop = cv2.resize(cropped_piece, (w_new, TARGET_HEIGHT), interpolation=cv2.INTER_LANCZOS4)

    TOTAL_WIDTH = w_new + TABLE_WIDTH
    canvas = np.full((TARGET_HEIGHT, TOTAL_WIDTH, 3), 255, dtype=np.uint8)
    canvas[0:TARGET_HEIGHT, 0:w_new] = resized_crop

    # ══════════════════════════════════════════════════════════════════════════
    # อ่านค่าจาก pair และสร้างตารางข้อมูล
    # ══════════════════════════════════════════════════════════════════════════

    (
        value_x, value_y,
        horizon_left, horizon_right, 
        vertical_bottom, vertical_top,
        offset_opx, offset_opy
    ) = pair

    # ⚠ ต้องเป็น f"{v:.3f}" ไม่ใช่ str(v) — `str()` ให้ความยาวไม่คงที่
    #   (8.157 → "8.157" แต่ 8.1 → "8.1") ตัวเลขในตารางจะกระโดดไม่ตรงหลักกัน
    #   3 ตำแหน่งตรงกับที่ backend ใช้ตัดสิน OK/NG (`_DP = 3` ใน shared.py)
    #   ทุกค่าใน `pair` ผ่าน float() มาแล้วเสมอ ไม่มีทางเป็น None
    #   (ดู `_parse_measurement_line` ใน Data-receiver.py)
    rows_data = [
        ("1. Value X", f"{value_x:.3f}"),
        ("2. Value Y", f"{value_y:.3f}"),
        ("3. Horizon Left", f"{horizon_left:.3f}"),
        ("4. Horizon Right", f"{horizon_right:.3f}"),
        ("5. Vertical Top", f"{vertical_top:.3f}"),
        ("6. Vertical Bottom", f"{vertical_bottom:.3f}"),
        ("7. Offset Opening X", f"{offset_opx:.3f}"),
        ("8. Offset Opening Y", f"{offset_opy:.3f}")
    ]

    # ══════════════════════════════════════════════════════════════════════════
    # วาดตารางแบบ Modern Dashboard
    # ══════════════════════════════════════════════════════════════════════════
    HEADER_HEIGHT = 50
    col1_x1 = w_new
    col1_x2 = w_new + 240
    col2_x2 = w_new + TABLE_WIDTH

    num_rows = len(rows_data)
    row_h = (TARGET_HEIGHT - HEADER_HEIGHT) / float(num_rows)

    font = cv2.FONT_HERSHEY_SIMPLEX
    font_scale_head = 0.6
    font_scale_data = 0.52
    thick = 2
    thick_head = 2
    padding_left = 18

    HEADER_BG_COLOR = (45, 38, 32)
    HEADER_TEXT_COLOR = (255, 255, 255)

    cv2.rectangle(canvas, (col1_x1, 0), (col2_x2, HEADER_HEIGHT), HEADER_BG_COLOR, -1)

    (_, h_h), _ = cv2.getTextSize("Feature", font, font_scale_head, thick_head)
    cv2.putText(canvas, "Feature", (col1_x1 + padding_left, int((HEADER_HEIGHT + h_h) / 2)),
                font, font_scale_head, HEADER_TEXT_COLOR, thick_head, cv2.LINE_AA)

    (m_w, m_h), _ = cv2.getTextSize("Measured", font, font_scale_head, thick_head)
    m_x = int(col1_x2 + ((col2_x2 - col1_x2) - m_w) / 2.0)
    cv2.putText(canvas, "Measured", (m_x, int((HEADER_HEIGHT + m_h) / 2)),
                font, font_scale_head, HEADER_TEXT_COLOR, thick_head, cv2.LINE_AA)

    BG_EVEN = (255, 255, 255)
    BG_ODD = (248, 246, 245)
    BORDER_COLOR = (220, 215, 210)
    TEXT_FEATURE_COLOR = (40, 40, 40)
    TEXT_MEASURED_COLOR = (160, 70, 0)

    for i, (feat, meas) in enumerate(rows_data):
        y_top = int(round(HEADER_HEIGHT + i * row_h))
        y_bottom = int(round(HEADER_HEIGHT + (i + 1) * row_h))

        bg_color = BG_EVEN if i % 2 == 0 else BG_ODD
        cv2.rectangle(canvas, (col1_x1, y_top), (col2_x2, y_bottom), bg_color, -1)
        cv2.line(canvas, (col1_x1, y_bottom), (col2_x2, y_bottom), BORDER_COLOR, 1, cv2.LINE_AA)

        (_, f_h), _ = cv2.getTextSize(feat, font, font_scale_data, thick)
        f_y = int(round(y_top + (row_h + f_h) / 2.0))
        cv2.putText(canvas, feat, (col1_x1 + padding_left, f_y),
                    font, font_scale_data, TEXT_FEATURE_COLOR, thick, cv2.LINE_AA)

        (v_w, v_h), _ = cv2.getTextSize(meas, font, font_scale_data, thick)
        v_x = int(round(col1_x2 + ((col2_x2 - col1_x2) - v_w) / 2.0))
        v_y = int(round(y_top + (row_h + v_h) / 2.0))
        cv2.putText(canvas, meas, (v_x, v_y),
                    font, font_scale_data, TEXT_MEASURED_COLOR, thick, cv2.LINE_AA)

    cv2.line(canvas, (col1_x2, 0), (col1_x2, TARGET_HEIGHT), BORDER_COLOR, 1, cv2.LINE_AA)
    cv2.rectangle(canvas, (col1_x1, 0), (col2_x2, TARGET_HEIGHT), BORDER_COLOR, 1)

    # ══════════════════════════════════════════════════════════════════════════
    # บันทึกภาพทับลงใน Path เดิม
    # ══════════════════════════════════════════════════════════════════════════
    # ⚠ `cv2.imwrite` คืน `False` เวลาเขียนไม่สำเร็จ **ไม่ raise** — เดิมทิ้งค่านี้
    #   แล้ว `return True` ตามหลังทันที ผลคือดิสก์เต็ม/ไฟล์ถูกล็อกก็ผ่านฉลุย
    #   แล้วระบบไปอัปโหลด "รูปดิบตัวเดิม" โดยไม่มีใครรู้ว่าวาดไม่ติด
    if not cv2.imwrite(image_path, canvas):
        raise OSError(f"cv2.imwrite เขียนไฟล์ไม่สำเร็จ (ดิสก์เต็มหรือไฟล์ถูกล็อก): {image_path}")
    return True