import cv2
import numpy as np

try:
  from PIL import Image, ImageDraw, ImageFont

  PIL_OK = True
except ImportError:  # ยังใช้งานได้ แต่ตัวหนังสือจะหยาบกว่า
  PIL_OK = False

# =====================================================================
# CONFIGURATION SECTION (ปรับแต่งค่าทั้งหมดได้ที่นี่)
# =====================================================================

# 1. ค่าการวัดที่กรอกเอง (Manual Input Values) -- แค่เติมข้อความ ไม่ได้คำนวณจริง
MANUAL_VALUES = {
    "1": "5.017 mm",  # ลูกศรแนวนอน ใต้กรอบ
    "2": "5.017 mm",  # ลูกศรแนวตั้ง ด้านขวากรอบ
    "3": "0.006 mm",  # ลูกศรเล็ก >|< ตรงกลาง
}

# 2. ภาพ / การครอป
IMAGE_CONFIG = {
    "detect_height": 900,  # ความสูงที่ใช้ตรวจจับชิ้นงาน (เร็วขึ้น)
    "work_height": 1000,  # ความสูงภาพผลลัพธ์ -- ยิ่งสูง ตัวเลขยิ่งคม
    "crop_to_part": True,  # True = ซูมเข้าที่ชิ้นงาน
    "auto_deskew": True,  # True = หมุนภาพให้ชิ้นงานตรงก่อน (รองรับภาพที่วางเอียง)
    "crop_pad_ratio": 0.10,  # ระยะเผื่อรอบชิ้นงานตอนครอป
    "window_name": "Measurement Result",
    "save_path": "result.png",  # PNG คมกว่า JPG (ไม่มี artifact รอบตัวอักษร)
    "window_max_height": 900,  # ย่อเฉพาะตอนแสดงผล ไฟล์ที่เซฟยังคมเต็มความละเอียด
}

# ค่าตำแหน่ง/ความหนาทั้งหมดด้านล่าง อ้างอิงที่ความสูง 620 px
# แล้วโปรแกรมจะสเกลให้อัตโนมัติตาม work_height (ไม่ต้องจูนใหม่)
REFERENCE_HEIGHT = 620

# 3. การตรวจจับ (อิงสัดส่วนภาพ ใช้ได้ทุกความละเอียด)
DETECT_CONFIG = {
    "min_area_ratio": 0.02,
    "max_area_ratio": 0.60,
    "aspect_min": 0.75,
    "aspect_max": 1.35,
    "center_tolerance": 0.25,
    "rectangularity_min": 0.80,  # พื้นที่ contour / พื้นที่กรอบเอียง (ยิ่งใกล้ 1 ยิ่งเป็นสี่เหลี่ยม)
    "feature_min_area_ratio": 0.002,
    "feature_max_area_ratio": 0.30,
    "side_circle_band": 0.18,
}

# 4. สี (BGR)
COLOR = {
    "green": (90, 235, 90),
    "amber": (60, 190, 245),
    "yellow": (35, 205, 250),
    "blue": (190, 45, 45),
    "text": (255, 255, 255),  # สีตัวหนังสือ
    "text_outline": (0, 0, 0),  # สีขอบตัวหนังสือ
    "text_bg": (0, 0, 0),  # สีกล่องพื้นหลังตัวหนังสือ
}

# 5. ตัวหนังสือ  <-- ปรับตรงนี้ถ้าอยากให้ตัวเลขชัดขึ้น
TEXT_CONFIG = {
    "font_size": 13,  # ขนาดฟอนต์ (ใหญ่ขึ้น = ชัดขึ้น)
    "stroke_width": 2,  # ความหนาขอบดำรอบตัวอักษร
    "bg_alpha": 0.55,  # ความทึบกล่องพื้นหลัง 0 = ไม่ใส่กล่อง, 1 = ทึบสนิท
    "bg_padding": 5,
    "bg_radius": 6,
    # ฟอนต์ที่จะลองใช้ตามลำดับ (ตัวหนาอ่านง่ายกว่า)
    "font_candidates": [
        "C:/Windows/Fonts/segoeuib.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
        "C:/Windows/Fonts/tahomabd.ttf",
        "C:/Windows/Fonts/consolab.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    ],
}

# 6. รูปแบบเส้น
STYLE_CONFIG = {
    "dash_len": 9,
    "gap_len": 6,
    "dash_thickness": 2,
    "center_v_thickness": 2,
    "center_h_thickness": 2,
    "circle_thickness": 4,
    "tick_thickness": 5,
    "tick_len_ratio": 0.34,  # อัตราส่วน -- ไม่ถูกสเกล
    "arrow_thickness": 2,
    "arrow_head_px": 10,
    # ใช้เฉพาะกรณีไม่มี Pillow
    "hershey_font_scale": 0.42,
    "hershey_thickness": 1,
}

# 7. ตำแหน่ง
POS_CONFIG = {
    "box_padding": 8,
    "tick_inset": 0,  # + = ขยับแถบขีดเข้าใน, - = ออกนอก
    "ext_overshoot": 14,
    "dim1_offset_y": 62,  # ลูกศร [1] ห่างจากขอบล่างกรอบ
    "dim1_text_offset_y": 22,
    "dim2_offset_x": 88,  # ลูกศร [2] ห่างจากขอบขวากรอบ
    "dim2_text_offset_x": -10,
    "dim3_half_gap": 5,
    "dim3_len": 20,
    "dim3_offset_y": 0,
    "dim3_text_offset_x": 30,
    "dim3_text_offset_y": -26,
}

# --- ตัวแปรที่ถูกคำนวณตอนรัน (อย่าแก้) ---
S = dict(STYLE_CONFIG)
P = dict(POS_CONFIG)
T = dict(TEXT_CONFIG)
_FONT_CACHE = {}


def build_runtime_config(work_height):
  """สเกลค่าพิกเซลทั้งหมดตามความสูงภาพจริง"""
  global S, P, T
  k = work_height / float(REFERENCE_HEIGHT)

  def px(v, minimum=1):
    return max(minimum, int(round(v * k)))

  S = dict(STYLE_CONFIG)
  for key in (
      "dash_len", "gap_len", "dash_thickness", "center_v_thickness",
      "center_h_thickness", "circle_thickness", "tick_thickness",
      "arrow_thickness", "arrow_head_px", "hershey_thickness",
  ):
    S[key] = px(STYLE_CONFIG[key])
  S["hershey_font_scale"] = STYLE_CONFIG["hershey_font_scale"] * k

  P = {
      key: (int(round(v * k)) if isinstance(v, (int, float)) else v)
      for key, v in POS_CONFIG.items()
  }

  T = dict(TEXT_CONFIG)
  T["font_size"] = px(TEXT_CONFIG["font_size"], 8)
  T["stroke_width"] = px(TEXT_CONFIG["stroke_width"], 1)
  T["bg_padding"] = px(TEXT_CONFIG["bg_padding"], 1)
  T["bg_radius"] = px(TEXT_CONFIG["bg_radius"], 1)


# =====================================================================
# TEXT RENDERING (Pillow = คมชัด / Hershey = สำรอง)
# =====================================================================


def get_font(size):
  if size in _FONT_CACHE:
    return _FONT_CACHE[size]
  font = None
  for path in T["font_candidates"]:
    try:
      font = ImageFont.truetype(path, size)
      break
    except Exception:
      continue
  if font is None:
    font = ImageFont.load_default()
  _FONT_CACHE[size] = font
  return font


def render_text_tile(text):
  """สร้าง tile RGBA ของข้อความ (มีขอบ + กล่องพื้นหลังโปร่งแสง)"""
  font = get_font(T["font_size"])
  stroke = T["stroke_width"]
  pad = T["bg_padding"]

  probe = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
  left, top, right, bottom = probe.textbbox(
      (0, 0), text, font=font, stroke_width=stroke
  )
  w = (right - left) + 2 * pad
  h = (bottom - top) + 2 * pad

  tile = Image.new("RGBA", (w, h), (0, 0, 0, 0))
  draw = ImageDraw.Draw(tile)
  if T["bg_alpha"] > 0:
    b, g, r = COLOR["text_bg"]
    draw.rounded_rectangle(
        [0, 0, w - 1, h - 1],
        radius=T["bg_radius"],
        fill=(r, g, b, int(255 * T["bg_alpha"])),
    )
  tb, tg, tr = COLOR["text"]
  ob, og, orr = COLOR["text_outline"]
  draw.text(
      (pad - left, pad - top),
      text,
      font=font,
      fill=(tr, tg, tb, 255),
      stroke_width=stroke,
      stroke_fill=(orr, og, ob, 255),
  )
  return tile


def paste_rgba(img_bgr, tile, x, y):
  """วาง tile RGBA ลงบนภาพ BGR แบบ alpha blend (ตัดขอบให้พอดีภาพ)"""
  rgba = np.array(tile)
  th, tw = rgba.shape[:2]
  ih, iw = img_bgr.shape[:2]

  sx, sy = max(0, -x), max(0, -y)
  x, y = max(0, x), max(0, y)
  ex, ey = min(iw, x + tw - sx), min(ih, y + th - sy)
  if ex <= x or ey <= y:
    return
  patch = rgba[sy : sy + (ey - y), sx : sx + (ex - x)]

  rgb = patch[..., :3][..., ::-1].astype(np.float32)  # RGB -> BGR
  alpha = patch[..., 3:4].astype(np.float32) / 255.0
  roi = img_bgr[y:ey, x:ex].astype(np.float32)
  img_bgr[y:ey, x:ex] = np.clip(roi * (1 - alpha) + rgb * alpha, 0, 255).astype(
      np.uint8
  )


def put_label(img, text, org, anchor="left", rotate=False):
  """anchor: left = มุมซ้ายบน | center = กึ่งกลาง | right = ชิดขวา+กลางแนวตั้ง"""
  if PIL_OK:
    tile = render_text_tile(text)
    if rotate:
      tile = tile.rotate(90, expand=True)
    w, h = tile.size
  else:
    tile, mask, w, h = render_text_tile_cv(text, rotate)

  x, y = int(round(org[0])), int(round(org[1]))
  if anchor == "center":
    x -= w // 2
    y -= h // 2
  elif anchor == "right":
    x -= w
    y -= h // 2

  if PIL_OK:
    paste_rgba(img, tile, x, y)
  else:
    x = max(0, min(x, img.shape[1] - w))
    y = max(0, min(y, img.shape[0] - h))
    roi = img[y : y + h, x : x + w]
    np.copyto(roi, tile, where=mask[..., None] > 0)


def render_text_tile_cv(text, rotate):
  """ทางสำรองเมื่อไม่มี Pillow"""
  font = cv2.FONT_HERSHEY_SIMPLEX
  scale = S["hershey_font_scale"]
  thick = S["hershey_thickness"]
  out_thick = thick + 2
  (tw, th), base = cv2.getTextSize(text, font, scale, thick)
  pad = out_thick + 2

  tile = np.zeros((th + base + 2 * pad, tw + 2 * pad, 3), np.uint8)
  mask = np.zeros(tile.shape[:2], np.uint8)
  origin = (pad, th + pad)
  for canvas, col, t in (
      (tile, COLOR["text_outline"], out_thick),
      (mask, 255, out_thick),
      (tile, COLOR["text"], thick),
      (mask, 255, thick),
  ):
    cv2.putText(canvas, text, origin, font, scale, col, t, cv2.LINE_AA)

  if rotate:
    tile = cv2.rotate(tile, cv2.ROTATE_90_COUNTERCLOCKWISE)
    mask = cv2.rotate(mask, cv2.ROTATE_90_COUNTERCLOCKWISE)
  h, w = tile.shape[:2]
  return tile, mask, w, h


# =====================================================================
# DRAWING HELPERS
# =====================================================================


def draw_dashed_line(img, p1, p2, color, thickness, dash=None, gap=None):
  dash = S["dash_len"] if dash is None else dash
  gap = S["gap_len"] if gap is None else gap
  p1 = np.array(p1, dtype=float)
  p2 = np.array(p2, dtype=float)
  length = float(np.linalg.norm(p2 - p1))
  if length < 1:
    return
  direction = (p2 - p1) / length
  pos = 0.0
  while pos < length:
    a = p1 + direction * pos
    b = p1 + direction * min(pos + dash, length)
    cv2.line(
        img,
        tuple(np.round(a).astype(int)),
        tuple(np.round(b).astype(int)),
        color,
        thickness,
        cv2.LINE_AA,
    )
    pos += dash + gap


def draw_dashed_rect(img, x1, y1, x2, y2, color, thickness):
  draw_dashed_line(img, (x1, y1), (x2, y1), color, thickness)
  draw_dashed_line(img, (x2, y1), (x2, y2), color, thickness)
  draw_dashed_line(img, (x2, y2), (x1, y2), color, thickness)
  draw_dashed_line(img, (x1, y2), (x1, y1), color, thickness)


def draw_double_arrow(img, p1, p2, color, thickness=None, head_px=None):
  """ลูกศรสองหัว ขนาดหัวคงที่ ไม่ขึ้นกับความยาวเส้น"""
  thickness = S["arrow_thickness"] if thickness is None else thickness
  head_px = S["arrow_head_px"] if head_px is None else head_px
  p1 = tuple(int(round(v)) for v in p1)
  p2 = tuple(int(round(v)) for v in p2)
  length = float(np.hypot(p2[0] - p1[0], p2[1] - p1[1]))
  if length < 2:
    return
  tip = min(0.5, head_px / length)
  cv2.arrowedLine(img, p1, p2, color, thickness, cv2.LINE_AA, tipLength=tip)
  cv2.arrowedLine(img, p2, p1, color, thickness, cv2.LINE_AA, tipLength=tip)


# =====================================================================
# DETECTION
# =====================================================================


def resize_keep_ratio(img, target_h):
  h, w = img.shape[:2]
  if not target_h or h == target_h:
    return img, 1.0
  scale = target_h / float(h)
  new_w = max(1, int(round(w * scale)))
  interp = cv2.INTER_AREA if scale < 1 else cv2.INTER_CUBIC
  return cv2.resize(img, (new_w, target_h), interpolation=interp), scale


def find_part_rect(gray):
  """หาชิ้นงาน (พื้นดำ) กลางภาพ -> คืน minAreaRect ((cx,cy),(w,h),angle)

  ใช้กรอบเอียง (rotated rect) แทน bounding box ธรรมดา
  จึงรองรับกรณีวางชิ้นงานเอียงได้
  """
  img_h, img_w = gray.shape[:2]
  _, thresh = cv2.threshold(
      gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU
  )
  thresh = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
  contours, _ = cv2.findContours(
      thresh, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE
  )

  img_area = float(img_w * img_h)
  cx0, cy0 = img_w / 2.0, img_h / 2.0
  max_dist = DETECT_CONFIG["center_tolerance"] * max(img_w, img_h)

  best, best_dist = None, float("inf")
  for cnt in contours:
    area = cv2.contourArea(cnt)
    ratio = area / img_area
    if not (
        DETECT_CONFIG["min_area_ratio"] <= ratio <= DETECT_CONFIG["max_area_ratio"]
    ):
      continue

    rect = cv2.minAreaRect(cnt)
    (rcx, rcy), (rw, rh), _ = rect
    if rw < 1 or rh < 1:
      continue
    aspect = rw / float(rh)
    if not (DETECT_CONFIG["aspect_min"] <= aspect <= DETECT_CONFIG["aspect_max"]):
      continue
    if area / (rw * rh) < DETECT_CONFIG["rectangularity_min"]:
      continue

    dist = float(np.hypot(rcx - cx0, rcy - cy0))
    if dist < max_dist and dist < best_dist:
      best, best_dist = rect, dist
  return best


def deskew_angle(rect):
  """มุมที่ต้องหมุนเพื่อให้ชิ้นงานตั้งตรง (ช่วง -45..45 องศา)"""
  angle = rect[2] % 90.0
  if angle > 45.0:
    angle -= 90.0
  return angle


def rotate_about(img, center, angle):
  """หมุนภาพรอบจุดที่กำหนด (จุดนั้นอยู่กับที่)"""
  m = cv2.getRotationMatrix2D(center, angle, 1.0)
  return cv2.warpAffine(
      img,
      m,
      (img.shape[1], img.shape[0]),
      flags=cv2.INTER_CUBIC,
      borderMode=cv2.BORDER_REPLICATE,
  )


def find_features(gray, square):
  """หาชิ้นงานกลาง + วงกลมซ้าย/ขวา ภายในสี่เหลี่ยมชิ้นงาน"""
  sx, sy, sw, sh = square
  pad = int(0.08 * max(sw, sh))
  x0 = max(0, sx - pad)
  y0 = max(0, sy - pad)
  x1 = min(gray.shape[1], sx + sw + pad)
  y1 = min(gray.shape[0], sy + sh + pad)
  roi = gray[y0:y1, x0:x1]

  _, bright = cv2.threshold(roi, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
  bright = cv2.morphologyEx(bright, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
  contours, _ = cv2.findContours(bright, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)

  roi_h, roi_w = roi.shape[:2]
  cx_sq, cy_sq = sx + sw / 2.0, sy + sh / 2.0
  sq_area = float(sw * sh)
  min_area = DETECT_CONFIG["feature_min_area_ratio"] * sq_area
  max_area = DETECT_CONFIG["feature_max_area_ratio"] * sq_area
  band = DETECT_CONFIG["side_circle_band"] * sh

  center_box, center_cnt, center_dist = None, None, float("inf")
  left_circle, right_circle = None, None
  left_best, right_best = float("inf"), float("-inf")

  for cnt in contours:
    area = cv2.contourArea(cnt)
    if not (min_area <= area <= max_area):
      continue

    bx, by, bw, bh = cv2.boundingRect(cnt)
    # ตัดพื้นหลังสว่างรอบนอกทิ้ง
    if bw >= 0.85 * roi_w and bh >= 0.85 * roi_h:
      continue

    bx += x0
    by += y0
    ccx, ccy = bx + bw / 2.0, by + bh / 2.0

    d = float(np.hypot(ccx - cx_sq, ccy - cy_sq))
    if d < center_dist and d < 0.25 * max(sw, sh):
      center_dist, center_box, center_cnt = d, (bx, by, bw, bh), cnt

    roundness = bw / float(bh) if bh else 0
    if abs(ccy - cy_sq) < band and 0.45 <= roundness <= 2.2:
      radius = max(bw, bh) / 2.0
      if ccx < cx_sq - 0.25 * sw and ccx < left_best:
        left_best, left_circle = ccx, (ccx, ccy, radius)
      if ccx > cx_sq + 0.25 * sw and ccx > right_best:
        right_best, right_circle = ccx, (ccx, ccy, radius)

  inner_box = inner_flat_edges(center_cnt, roi.shape, (x0, y0))
  return center_box, inner_box, left_circle, right_circle


def inner_flat_edges(cnt, roi_shape, origin):
  """หาขอบ 'ด้านเรียบ' ของรูตรงกลาง (จุดที่เส้นกลางตัดขอบชิ้นงาน)

  ชิ้นงานเป็นรูปกากบาท bounding box จะกินถึงปลายแฉก
  จึงวัดจากแถว/คอลัมน์กึ่งกลางแทน เพื่อให้ได้ด้านเว้าตรงกลางแต่ละด้าน
  """
  if cnt is None:
    return None
  mask = np.zeros(roi_shape[:2], np.uint8)
  cv2.drawContours(mask, [cnt], -1, 255, -1)

  m = cv2.moments(mask, binaryImage=True)
  if m["m00"] == 0:
    return None
  cx = int(round(m["m10"] / m["m00"]))
  cy = int(round(m["m01"] / m["m00"]))

  v_run = contiguous_run(mask[:, cx] > 0, cy)
  h_run = contiguous_run(mask[cy, :] > 0, cx)
  if v_run is None or h_run is None:
    return None

  ox, oy = origin
  return (h_run[0] + ox, v_run[0] + oy, h_run[1] + ox, v_run[1] + oy)


def contiguous_run(flags, idx):
  """ช่วง True ที่ต่อเนื่องกันและครอบ index ที่กำหนด"""
  n = len(flags)
  if idx < 0 or idx >= n or not flags[idx]:
    return None
  start = idx
  while start > 0 and flags[start - 1]:
    start -= 1
  end = idx
  while end < n - 1 and flags[end + 1]:
    end += 1
  return start, end


# =====================================================================
# WINDOW
# =====================================================================


def show_window(win, img):
  """แสดงหน้าต่าง -- ปิดได้ด้วย Ctrl+C / ESC / q / กดปุ่ม X"""
  max_h = IMAGE_CONFIG.get("window_max_height")
  view = img
  if max_h and img.shape[0] > max_h:
    view, _ = resize_keep_ratio(img, max_h)

  cv2.namedWindow(win, cv2.WINDOW_AUTOSIZE)
  cv2.imshow(win, view)
  print("กด Ctrl+C ที่ terminal หรือ ESC / q ที่หน้าต่าง เพื่อปิด")
  try:
    while True:
      # timeout สั้น ๆ แทน waitKey(0) เพื่อให้ Python รับสัญญาณ Ctrl+C ได้
      key = cv2.waitKey(30) & 0xFF
      if key in (27, ord("q")):
        break
      if cv2.getWindowProperty(win, cv2.WND_PROP_VISIBLE) < 1:
        break
  except KeyboardInterrupt:
    print("\nปิดโปรแกรม (Ctrl+C)")
  finally:
    try:
      cv2.destroyAllWindows()
      cv2.waitKey(1)
    except Exception:
      pass


# =====================================================================
# MAIN
# =====================================================================


def process_and_measure(image_path):
  original = cv2.imread(image_path)
  if original is None:
    print(f"Error: ไม่พบไฟล์ {image_path}")
    return
  if not PIL_OK:
    print("Tip: ติดตั้ง Pillow เพื่อให้ตัวหนังสือคมขึ้นมาก -> pip install pillow")

  build_runtime_config(IMAGE_CONFIG["work_height"])

  # --- ตรวจจับชิ้นงานบนภาพย่อ ---
  det_img, det_scale = resize_keep_ratio(original, IMAGE_CONFIG["detect_height"])
  det_gray = cv2.cvtColor(det_img, cv2.COLOR_BGR2GRAY)
  rect_det = find_part_rect(det_gray)
  if rect_det is None:
    print("Error: ไม่พบสี่เหลี่ยมชิ้นงาน -- ลองปรับ min/max_area_ratio")
    return

  # แปลงกลับเป็นพิกัดภาพต้นฉบับ
  (rcx, rcy), (rw, rh), _ = rect_det
  rcx, rcy = rcx / det_scale, rcy / det_scale
  rw, rh = rw / det_scale, rh / det_scale

  # --- หมุนภาพให้ชิ้นงานตั้งตรง (ถ้าเปิด auto_deskew) ---
  if IMAGE_CONFIG["auto_deskew"]:
    angle = deskew_angle(rect_det)
    if abs(angle) > 0.1:
      original = rotate_about(original, (rcx, rcy), angle)
      print(f"หมุนภาพให้ชิ้นงานตั้งตรง: {angle:+.2f} องศา")

  # กรอบชิ้นงานแบบตั้งฉาก หลังหมุนแล้ว
  sq_orig = [
      int(round(rcx - rw / 2)),
      int(round(rcy - rh / 2)),
      int(round(rw)),
      int(round(rh)),
  ]

  # --- ครอป แล้วย่อ/ขยายเป็นภาพผลลัพธ์ ---
  if IMAGE_CONFIG["crop_to_part"]:
    pad = int(IMAGE_CONFIG["crop_pad_ratio"] * max(sq_orig[2], sq_orig[3]))
    cx0 = max(0, sq_orig[0] - pad)
    cy0 = max(0, sq_orig[1] - pad)
    cx1 = min(original.shape[1], sq_orig[0] + sq_orig[2] + pad)
    cy1 = min(original.shape[0], sq_orig[1] + sq_orig[3] + pad)
    cropped = original[cy0:cy1, cx0:cx1]
  else:
    cx0, cy0 = 0, 0
    cropped = original

  img, scale = resize_keep_ratio(cropped, IMAGE_CONFIG["work_height"])
  img_h, img_w = img.shape[:2]

  square = (
      int(round((sq_orig[0] - cx0) * scale)),
      int(round((sq_orig[1] - cy0) * scale)),
      int(round(sq_orig[2] * scale)),
      int(round(sq_orig[3] * scale)),
  )

  gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
  out = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
  center_box, inner_box, left_circle, right_circle = find_features(gray, square)

  sx, sy, sw, sh = square
  cx_sq, cy_sq = sx + sw // 2, sy + sh // 2

  # ---------- 1) เส้นทึบแนวตั้งกลางภาพ ----------
  cv2.line(
      out, (cx_sq, 0), (cx_sq, img_h), COLOR["yellow"],
      S["center_v_thickness"], cv2.LINE_AA,
  )

  # ---------- 2) เส้นประแนวนอนกลางภาพ ----------
  hx1 = int(left_circle[0]) if left_circle else sx
  hx2 = int(right_circle[0]) if right_circle else sx + sw
  draw_dashed_line(
      out, (hx1, cy_sq), (hx2, cy_sq), COLOR["amber"], S["center_h_thickness"]
  )

  # ---------- 3) วงกลมซ้าย/ขวา ----------
  for circ in (left_circle, right_circle):
    if circ:
      cv2.circle(
          out, (int(circ[0]), int(circ[1])), int(circ[2]),
          COLOR["green"], S["circle_thickness"], cv2.LINE_AA,
      )

  if center_box is None:
    print("Warning: ไม่พบชิ้นงานกลาง -- ใช้กรอบประมาณแทน")
    bw = bh = int(0.30 * min(sw, sh))
    center_box = (cx_sq - bw // 2, cy_sq - bh // 2, bw, bh)
    inner_box = None

  # ---------- 4) กรอบประรอบชิ้นงานกลาง + แถบขีด ----------
  p = P["box_padding"]
  bx, by, bw, bh = center_box
  bx1, by1 = bx - p, by - p
  bx2, by2 = bx + bw + p, by + bh + p
  bcx, bcy = (bx1 + bx2) // 2, (by1 + by2) // 2

  draw_dashed_rect(out, bx1, by1, bx2, by2, COLOR["green"], S["dash_thickness"])

  # แถบขีดเขียว 4 เส้น -- แตะขอบ "ด้านเรียบ" ของรูตรงกลาง
  ti = P["tick_inset"]
  if inner_box is not None:
    fx1, fy1, fx2, fy2 = inner_box
  else:
    fx1, fy1, fx2, fy2 = bx, by, bx + bw, by + bh
  fx1, fy1, fx2, fy2 = fx1 + ti, fy1 + ti, fx2 - ti, fy2 - ti
  fcx, fcy = (fx1 + fx2) // 2, (fy1 + fy2) // 2
  tick_w = int(S["tick_len_ratio"] * (fx2 - fx1))
  tick_h = int(S["tick_len_ratio"] * (fy2 - fy1))
  tt = S["tick_thickness"]
  cv2.line(out, (fcx - tick_w, fy1), (fcx + tick_w, fy1), COLOR["green"], tt)
  cv2.line(out, (fcx - tick_w, fy2), (fcx + tick_w, fy2), COLOR["green"], tt)
  cv2.line(out, (fx1, fcy - tick_h), (fx1, fcy + tick_h), COLOR["green"], tt)
  cv2.line(out, (fx2, fcy - tick_h), (fx2, fcy + tick_h), COLOR["green"], tt)

  over = P["ext_overshoot"]

  # ---------- 5) ลูกศร [1] แนวนอน (ใต้กรอบ) ----------
  d1_y = by2 + P["dim1_offset_y"]
  draw_dashed_line(
      out, (bx1, by2), (bx1, d1_y + over), COLOR["green"], S["dash_thickness"]
  )
  draw_dashed_line(
      out, (bx2, by2), (bx2, d1_y + over), COLOR["green"], S["dash_thickness"]
  )
  draw_double_arrow(out, (bx1, d1_y), (bx2, d1_y), COLOR["blue"])
  put_label(
      out,
      f"[1] {MANUAL_VALUES.get('1', '')}",
      (bcx, d1_y + P["dim1_text_offset_y"]),
      anchor="center",
  )

  # ---------- 6) ลูกศร [2] แนวตั้ง (ขวากรอบ) ----------
  d2_x = bx2 + P["dim2_offset_x"]
  draw_dashed_line(
      out, (bx2, by1), (d2_x + over, by1), COLOR["green"], S["dash_thickness"]
  )
  draw_dashed_line(
      out, (bx2, by2), (d2_x + over, by2), COLOR["green"], S["dash_thickness"]
  )
  draw_double_arrow(out, (d2_x, by1), (d2_x, by2), COLOR["blue"])
  put_label(
      out,
      f"[2] {MANUAL_VALUES.get('2', '')}",
      (d2_x + P["dim2_text_offset_x"], bcy),
      anchor="right",
      rotate=True,
  )

  # ---------- 7) ลูกศร [3] เล็ก ๆ ตรงกลาง ----------
  d3_y = bcy + P["dim3_offset_y"]
  g, ln = P["dim3_half_gap"], P["dim3_len"]
  for sign in (-1, 1):
    cv2.arrowedLine(
        out,
        (cx_sq + sign * (g + ln), d3_y),
        (cx_sq + sign * g, d3_y),
        COLOR["blue"],
        S["arrow_thickness"],
        cv2.LINE_AA,
        tipLength=0.45,
    )
  put_label(
      out,
      f"[3] {MANUAL_VALUES.get('3', '')}",
      (cx_sq + P["dim3_text_offset_x"], d3_y + P["dim3_text_offset_y"]),
      anchor="left",
  )

  # ---------- แสดงผล / บันทึก ----------
  if IMAGE_CONFIG["save_path"]:
    cv2.imwrite(IMAGE_CONFIG["save_path"], out)
    print(f"บันทึกผลลัพธ์: {IMAGE_CONFIG['save_path']}  ({img_w}x{img_h})")

  show_window(IMAGE_CONFIG["window_name"], out)

if __name__ == "__main__":
  process_and_measure("test.png")