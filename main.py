print("Đang import các thư viện...")
from fastapi import FastAPI, File, UploadFile, Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.responses import JSONResponse
from ultralytics import YOLO
import cv2
import numpy as np
import math
import jwt
import logging
from dotenv import load_dotenv
import os

logger = logging.getLogger(__name__)

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")

if not SUPABASE_URL:
    print("Cảnh báo: SUPABASE_URL chưa được cấu hình trong file .env!")

# JWKS client để lấy public key cho ES256 (có cache tự động)
JWKS_URL = f"{SUPABASE_URL}/auth/v1/.well-known/jwks.json"
jwks_client = jwt.PyJWKClient(JWKS_URL) if SUPABASE_URL else None

# Security scheme cho Swagger UI (nút Authorize)
security = HTTPBearer()


async def verify_supabase_token(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> dict:
    """
    Dependency xác thực Supabase JWT token.
    Hỗ trợ cả ES256 (JWKS public key).
    """
    token = credentials.credentials
    try:
        signing_key = jwks_client.get_signing_key_from_jwt(token).key
        payload = jwt.decode(
            token,
            signing_key,
            algorithms=['ES256'],
            audience="authenticated",
        )
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token đã hết hạn. Vui lòng đăng nhập lại.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except jwt.InvalidTokenError as e:
        logger.warning("JWT verification failed: %s", e)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token không hợp lệ.",
            headers={"WWW-Authenticate": "Bearer"},
        )

app = FastAPI(title="Hệ thống Nhận diện Điện trở - Component Vault")

# ==========================================
# 1. KHỞI TẠO VÀ TẢI MÔ HÌNH
# ==========================================
print("⏳ Đang nạp mô hình vào bộ nhớ...")
try:
    model_components = YOLO("best_res.pt")
    model_bands = YOLO("best_res_band_color.pt")
    print("Đã nạp mô hình thành công!")
except Exception as e:
    print(f"Lỗi nạp mô hình: {e}")

# ==========================================
# 2. DICTIONARY & CONFIG
# ==========================================
COLOR_CODE = {
    'black': 0, 'brown': 1, 'red': 2, 'orange': 3, 'yellow': 4,
    'green': 5, 'blue': 6, 'purple': 7,
    'gray': 8, 'grey': 8,
    'white': 9
}

MULTIPLIER = {
    'black': 1, 'brown': 10, 'red': 100, 'orange': 1000, 'yellow': 10000,
    'green': 100000, 'blue': 1000000, 'purple': 10000000,
    'gray': 100000000, 'grey': 100000000,
    'white': 1000000000,
    'side-gold': 0.1, 'side-silver': 0.01,
    'gold': 0.1, 'silver': 0.01
}

E24_BASES = {10, 11, 12, 13, 15, 16, 18, 20, 22, 24, 27,
             30, 33, 36, 39, 43, 47, 51, 56, 62, 68, 75, 82, 91}

CONFUSION_MAP = {
    'side-gold': [('side-silver', 0.30)],
    'brown':     [('black', 0.10), ('orange', 0.03), ('red', 0.02)],
    'side-silver': [('side-gold', 0.08)],
    'black':     [('brown', 0.03)],
    'red':       [('orange', 0.02)]
}

TOLERANCE = {
    'brown': 1, 'red': 2, 'green': 0.5, 'blue': 0.25,
    'purple': 0.1, 'gray': 0.05, 'grey': 0.05,
    'gold': 5, 'silver': 10,
    'side-gold': 5, 'side-silver': 10,
}



def format_ohm_value(value: float) -> str:
    if value >= 1000000:
        return f"{value / 1000000:g}M"
    elif value >= 1000:
        return f"{value / 1000:g}K"
    return f"{value:g}"


def get_e24_base(value: float) -> int:
    if value == 0:
        return 0
    magnitude = math.floor(math.log10(value))
    return round(value / (10 ** (magnitude - 1)))


def calculate_raw_ohm(colors: list) -> float:
    # Do đã có Pre-processing lọc số lượng vạch (4 hoặc 5) bên dưới,
    # chúng ta có thể tự tin tính toán mà không sợ IndexError
    try:
        if len(colors) == 4:
            return (COLOR_CODE[colors[0]] * 10 + COLOR_CODE[colors[1]]) * MULTIPLIER.get(colors[2], 1)
        else:  # 5 vạch
            return (COLOR_CODE[colors[0]] * 100 + COLOR_CODE[colors[1]] * 10 + COLOR_CODE[colors[2]]) * MULTIPLIER.get(colors[3], 1)
    except KeyError:
        return None


def get_tolerance(colors: list) -> float | None:
    """Trả về sai số (%) dựa trên vạch cuối cùng. None nếu không xác định được."""
    return TOLERANCE.get(colors[-1])

def automatic_white_balance(img):
    result = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(result)
    l_mean = np.mean(l)
    a_mean = np.mean(a)
    b_mean = np.mean(b)
    l = l - ((l_mean - 128) * (l / 255.0) * 1.1)
    a = a - ((a_mean - 128) * (l / 255.0) * 1.1)
    b = b - ((b_mean - 128) * (l / 255.0) * 1.1)
    l = np.clip(l, 0, 255).astype(np.uint8)
    a = np.clip(a, 0, 255).astype(np.uint8)
    b = np.clip(b, 0, 255).astype(np.uint8)
    result = cv2.merge([l, a, b])
    return cv2.cvtColor(result, cv2.COLOR_LAB2BGR)

def validate_and_suggest(predicted_colors: list):
    raw_value = calculate_raw_ohm(predicted_colors)
    base_val = get_e24_base(raw_value)

    if base_val in E24_BASES:
        return True, predicted_colors, format_ohm_value(raw_value)

    candidates = []
    for i, color in enumerate(predicted_colors):
        if color in CONFUSION_MAP:
            for true_color, prob in CONFUSION_MAP[color]:
                hypo_colors = list(predicted_colors)
                hypo_colors[i] = true_color

                hypo_val = calculate_raw_ohm(hypo_colors)
                hypo_base = get_e24_base(hypo_val)

                if hypo_base in E24_BASES:
                    candidates.append({
                        'colors': hypo_colors,
                        'value': hypo_val,
                        'prob': prob
                    })

    if not candidates:
        return False, predicted_colors, format_ohm_value(raw_value)

    best_candidate = max(candidates, key=lambda x: x['prob'])
    best_val = best_candidate['value']

    return False, best_candidate['colors'], format_ohm_value(best_val)

def determine_correct_orientation(filtered_bands: list) -> list:
    """
    Thuật toán thông minh tự động đảo chiều đọc điện trở 
    Dựa trên khoảng cách hình học (Gap) và tính hợp lý của giá trị Ohm (Sanity Check)
    """
    # Lấy mảng màu gốc đọc từ Trái sang Phải
    colors_l_to_r = [b["color"].lower() for b in filtered_bands]
    colors_r_to_l = list(reversed(colors_l_to_r))
    
    #PHÂN TÍCH KHOẢNG CÁCH HÌNH HỌC (GAP ANALYSIS)
    tolerance_colors = ['gold', 'silver', 'side-gold', 'side-silver']
    if len(filtered_bands) >= 4:
        # Khoảng cách giữa vạch 1 và vạch 2
        gap_start = filtered_bands[1]["x_pos"] - filtered_bands[0]["x_pos"]
        # Khoảng cách giữa vạch kế cuối và vạch cuối
        gap_end = filtered_bands[-1]["x_pos"] - filtered_bands[-2]["x_pos"]
        
        # Nếu khoảng cách ở đầu lớn hơn ở đuôi đáng kể (VD: gấp 1.3 lần)
        # Chứng tỏ vạch sai số đang nằm ở bên TRÁI -> Điện trở đang bị cầm ngược!
        if gap_start > gap_end * 1.3 and calculate_raw_ohm(colors_r_to_l):
            return colors_r_to_l
        elif gap_end > gap_start * 1.3 and calculate_raw_ohm(colors_l_to_r):
            return colors_l_to_r

    #KIỂM TRA ĐỘ HỢP LÝ CỦA GIÁ TRỊ (SANITY CHECK)
    val_normal = calculate_raw_ohm(colors_l_to_r)
    val_reversed = calculate_raw_ohm(colors_r_to_l)
    
    MAX_LAB_RESISTANCE = 22000000 # Ngưỡng 22 Mega Ohm thông dụng
    
    # Nếu đọc xuôi ra giá trị không tưởng (>22M) nhưng đảo ngược lại ra giá trị hợp lý
    if val_normal and val_normal > MAX_LAB_RESISTANCE and val_reversed <= MAX_LAB_RESISTANCE:
        return colors_r_to_l
    # Ngược lại nếu đọc ngược ra giá trị quá lớn
    if val_reversed and val_reversed > MAX_LAB_RESISTANCE and val_normal <= MAX_LAB_RESISTANCE:
        return colors_l_to_r
    
    #DỰA VÀO MÀU NHŨ VÀNG/BẠC TRUYỀN THỐNG
    
    if colors_l_to_r[0] in tolerance_colors:
        return colors_r_to_l
        
    return colors_l_to_r


#API ENDPOINT GIAO TIẾP VỚI FLUTTER
@app.post("/scan-resistor")
async def scan_component(
    file: UploadFile = File(...),
    user_payload: dict = Depends(verify_supabase_token),
):
    # Validate file type
    ALLOWED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".heic", ".webp"}
    file_ext = os.path.splitext(file.filename or "")[1].lower()
    if file_ext not in ALLOWED_EXTENSIONS:
        return JSONResponse(content={
            "error_code": 1,
            "message": f"Định dạng file không được hỗ trợ. Chỉ chấp nhận: {', '.join(ALLOWED_EXTENSIONS)}",
            "data": None
        })

    try:
        # Validate file size (max 10MB)
        MAX_FILE_SIZE = 10 * 1024 * 1024
        image_bytes = await file.read()
        if len(image_bytes) > MAX_FILE_SIZE:
            return JSONResponse(content={
                "error_code": 1,
                "message": "File quá lớn. Giới hạn tối đa 10MB.",
                "data": None
            })

        nparr = np.frombuffer(image_bytes, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

        if img is None:
            return JSONResponse(content={"error_code": 1, "message": "File không hợp lệ", "data": None})

        h_img, w_img = img.shape[:2]
        results_comp = model_components.predict(img, conf=0.3, verbose=False)
        
        # Model chỉ có 1 class (điện trở), predict 1 ảnh → results_comp[0]
        total_resistors = len(results_comp[0].boxes)
        
        if total_resistors == 0:
            return JSONResponse(content={
                "error_code": 1,
                "message": "Không phát hiện điện trở nào trong ảnh.",
                "data": None
            })
        elif total_resistors > 1:
            return JSONResponse(content={
                "error_code": 1,
                "message": f"Phát hiện {total_resistors} điện trở trong ảnh. Vui lòng chỉ chụp 1 điện trở duy nhất.",
                "data": None
            })

        for result in results_comp:
            for box in result.boxes:
                cls_id = int(box.cls[0].item())
                class_name = model_components.names[cls_id].lower()

                if "resistor" in class_name:
                    x1, y1, x2, y2 = map(int, box.xyxy[0])
                    pad = 0
                    crop_y1, crop_y2 = max(0, y1 - pad), min(h_img, y2 + pad)
                    crop_x1, crop_x2 = max(0, x1 - pad), min(w_img, x2 + pad)
                    cropped_resistor = img[crop_y1:crop_y2, crop_x1:crop_x2]
                    cropped_resistor = automatic_white_balance(cropped_resistor)

                    results_bands = model_bands.predict(cropped_resistor, conf=0.35, iou=0.45, verbose=False,
                                                        agnostic_nms=True, imgsz=640)

                    raw_bands = []
                    for r_band in results_bands:
                        for b_box in r_band.boxes:
                            b_cls_id = int(b_box.cls[0].item())
                            raw_bands.append({
                                "color": model_bands.names[b_cls_id],
                                "x_pos": int(b_box.xyxy[0][0].item()),
                                "conf": float(b_box.conf[0].item())
                            })

                    if not raw_bands:
                        continue

                    # Sắp xếp tọa độ X và lọc khoảng cách (NMS)
                    raw_bands = sorted(raw_bands, key=lambda x: x["x_pos"])
                    
                    resistor_width = crop_x2 - crop_x1 
                    # Khoảng cách tối thiểu = 5% chiều dài điện trở
                    min_gap = resistor_width * 0.05
                    filtered_bands = []
                    for band in raw_bands:
                        if not filtered_bands:
                            filtered_bands.append(band)
                        else:
                            last_band = filtered_bands[-1]
                            if abs(band["x_pos"] - last_band["x_pos"]) < min_gap:
                                if band["conf"] > last_band["conf"]:
                                    filtered_bands[-1] = band
                            else:
                                filtered_bands.append(band)

                    color_list = [b["color"].replace(
                        'band_', '').lower() for b in filtered_bands]

                    # ==========================================
                    # 🛡️ TIỀN XỬ LÝ (FAIL-FAST RULES)
                    # ==========================================

                    # Rule 1: Trả về Failed nếu số lượng vạch không phải 4 hoặc 5
                    if len(color_list) not in [4, 5]:
                        return JSONResponse(content={
                            "error_code": 1,
                            "message": f"Lỗi: Nhận diện được {len(color_list)} vạch. Chỉ hỗ trợ điện trở 4 hoặc 5 vạch.",
                            "data": {"debug_colors": color_list}
                        })

                    #Rule 2: Trả về Failed nếu Vàng Kim / Bạc lọt vào giữa mảng
                    #Cắt mảng để lấy các phần tử ở giữa (bỏ đầu và đuôi)
                    
                    tolerance_colors = ['gold', 'silver',
                                        'side-gold', 'side-silver']

                    color_list = determine_correct_orientation(filtered_bands)
                        
                    middle_colors = color_list[1:-2]
                    if any(c in tolerance_colors for c in middle_colors):
                        return JSONResponse(content={
                            "error_code": 1,
                            "message": "Lỗi: Vạch sai số (Gold/Silver) xuất hiện sai quy tắc ở giữa thân điện trở.",
                            "data": {"debug_colors": color_list}
                        })

                    #Kiểm tra tính hợp lệ của tổ hợp màu trước khi tính toán E24
                    if calculate_raw_ohm(color_list) is None:
                        return JSONResponse(content={
                            "error_code": 1,
                            "message": "Không thể tính toán trị số điện trở từ tổ hợp màu nhận diện được.",
                            "data": {"debug_colors": color_list}
                        })

                    #Hậu xử lý E24
                    is_std, final_colors, formatted_val = validate_and_suggest(
                        color_list)

                    tolerance = get_tolerance(color_list)

                    return JSONResponse(content={
                        "error_code": 0,
                        "message": "Thành công",
                        "data": {
                            "component_type": "Điện trở",
                            "value": formatted_val,
                            "tolerance": f"{tolerance}%" if tolerance is not None else None,
                            "is_e24_standard": is_std,
                            "debug_colors": color_list,
                            "corrected_colors": final_colors if not is_std else []
                        }
                    })

        return JSONResponse(content={
            "error_code": 1,
            "message": "Tìm thấy điện trở nhưng không quét được vạch màu nào",
            "data": None
        })

    except Exception as e:
        logger.exception("Lỗi hệ thống khi xử lý ảnh")
        return JSONResponse(content={
            "error_code": -1,
            "message": "Đã xảy ra lỗi hệ thống. Vui lòng thử lại sau.",
            "data": None
        })
