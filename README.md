# Resistor Color Band Recognition API

API backend nhận diện trị số điện trở qua vạch màu bằng thị giác máy tính. Gửi ảnh chụp điện trở → nhận về trị số Ohm, sai số, và danh sách vạch màu.

Server nhận ảnh từ ứng dụng di động, chạy 2 mô hình [YOLOv8](https://docs.ultralytics.com/) để phát hiện thân điện trở và nhận diện các vạch màu, rồi áp dụng một chuỗi bước hậu xử lý (cân bằng trắng, lọc trùng lặp, xác định chiều đọc, kiểm chuẩn E24) để trả về kết quả chính xác qua JSON.

## Kỹ thuật đáng chú ý

- **Cân bằng trắng tự động bằng [không gian màu LAB](https://docs.opencv.org/4.x/de/d25/imgproc_color_conversions.html)** — Chuyển ảnh sang LAB để tách riêng kênh sáng (L) và kênh màu (a, b), rồi điều chỉnh a, b về giá trị trung tính 128. Loại bỏ ảnh hưởng ánh sáng vàng/xanh mà không làm mất chi tiết ảnh.

- **1D Non-Maximum Suppression theo tọa độ X** — Thay vì dùng IoU-NMS 2 chiều, hệ thống sắp xếp vạch theo trục X và loại bỏ vạch trùng dựa trên khoảng cách tối thiểu (5% chiều rộng điện trở), giữ vạch có confidence cao hơn. Đơn giản và phù hợp hơn cho bài toán 1 chiều.

- **Tự động xác định chiều đọc qua 3 tầng** — Phân tích gap hình học giữa các vạch → kiểm tra giá trị Ohm có hợp lý không (< 22 MΩ) → fallback bằng quy tắc Gold/Silver không đứng đầu.

- **Sửa lỗi nhận diện dựa trên [chuẩn E24](https://en.wikipedia.org/wiki/E_series_of_preferred_numbers)** — Nếu trị số không khớp E24, hệ thống tra bảng `CONFUSION_MAP` (các cặp màu YOLO hay nhầm) để thử thay thế và đề xuất tổ hợp màu hợp lệ có xác suất cao nhất.

- **Xác thực JWT bằng [JWKS](https://datatracker.ietf.org/doc/html/rfc7517) + ES256** — Lấy public key từ endpoint `.well-known/jwks.json` của Supabase để verify token, không cần lưu secret key trên server. PyJWKClient tự cache key.

- **[FastAPI Dependency Injection](https://fastapi.tiangolo.com/tutorial/dependencies/)** — Xác thực token được triển khai qua `Depends()`, tách biệt hoàn toàn logic auth khỏi logic xử lý ảnh.

## Cấu trúc repo

```
resistor-color-band-api/
├── .vscode/              # Cấu hình debug cho VSCode
├── .env.example          # Template biến môi trường
├── .gitignore
├── main.py               # Toàn bộ logic API: auth, xử lý ảnh, hậu xử lý
├── best_res.pt           # Mô hình YOLO — phát hiện thân điện trở
├── best_res_color.pt # Mô hình YOLO — nhận diện vạch màu
└── requirement.txt       # Thư viện Python phụ thuộc
```

## Luồng hoạt động của API
![Biểu đồ luồng hoạt động của API](/docs/api_diagram.svg)

## Cách đặt tên class cho mô hình YOLO

Repo đã có 2 model YOLO đã được train sẵn nhằm phục vụ test API. Nếu bạn muốn tự train 1 mô hình bằng dataset của mình, hãy đặt tên class theo cách bên dưới:

### Model 1 — Phát hiện thân điện trở (`best_res.pt`)

Mô hình này chỉ có **1 class**:

| Class | Mô tả |
|-------|--------|
| `Resistor` | Thân điện trở |

Code kiểm tra bằng `"resistor" in class_name.lower()`, nên tên class không phân biệt hoa/thường.

### Model 2 — Nhận diện vạch màu (`best_res_color.pt`)

Mô hình này có **14 class**, tất cả đều có prefix ``:

| Màu         | Class       | Vai trò                               |
|-------------|-------------|---------------------------------------|
| Đen         | black       | Trị số 0 / Hệ số ×1                   |
| Nâu         | brown       | Trị số 1 / Hệ số ×10 / Sai số ±1%     |
| Đỏ          | red         | Trị số 2 / Hệ số ×100 / Sai số ±2%    |
| Cam         | orange      | Trị số 3 / Hệ số ×1K                  |
| Vàng        | yellow      | Trị số 4 / Hệ số ×10K                 |
| Xanh lá cây | green       | Trị số 5 / Hệ số ×100K / Sai số ±0.5% |
| Xanh dương  | blue        | Trị số 6 / Hệ số ×1M / Sai số ±0.25%  |
| Tím         | purple      | Trị số 7 / Hệ số ×10M / Sai số ±0.1%  |
| Xám         | gray        | Trị số 8 / Sai số ±0.05%              |
| Trắng       | white       | Trị số 9                              |
| Vàng nhũ    | side-gold   | Hệ số ×0.1 / Sai số ±5%               |
| Bạc         | side-silver | Hệ số ×0.01 / Sai số ±10%             |

Code xử lý prefix bằng `.replace('', '').lower()` trước khi tra bảng `COLOR_CODE`, `MULTIPLIER`, và `TOLERANCE`.

> `side-gold` và `side-silver` là các class riêng để phân biệt trường hợp vạch nhũ nằm ở cạnh bên thân điện trở (góc chụp xiên), thường bị nhầm lẫn với nhau nên có xác suất confusion cao nhất trong `CONFUSION_MAP` (30%).

## Cài đặt và chạy

### Yêu cầu

- Python 3.10+
- Supabase project đã cấu hình Auth

### Các bước

1. Clone repo và tạo môi trường ảo:

```bash
git clone https://github.com/TVTIT/resistor_color_band_recognition_api
cd resistor_color_band_recognition_api
python -m venv .venv
```

2. Chuyển sang môi trường ảo

Linux / MacOS
```bash
source .venv/bin/activate
```

Windows
```batch
.venv\Scripts\activate.bat
```

2. Cài thư viện cho Python:

```bash
pip install -r requirement.txt
```

3. Chỉnh sửa file `.env.example` theo project Supabase của bạn rồi copy 1 file mới đặt tên là `.env` để cấu hình biến môi trường:

```bash
cp .env.example .env
```

4. Chạy server:

```bash
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

## Sử dụng API

**Endpoint:** `POST /scan-resistor`

**Headers:** `Authorization: Bearer <supabase_access_token>`

**Body:** `multipart/form-data` với field `file` (ảnh `.png`, `.jpg`, `.jpeg`, `.heic`, `.webp`, tối đa 10MB)

**Response thành công:**

```json
{
  "error_code": 0,
  "message": "Thành công",
  "data": {
    "component_type": "Điện trở",
    "value": "10K Ohm",
    "tolerance": "5%",
    "is_e24_standard": true,
    "debug_colors": ["brown", "black", "orange", "gold"],
    "corrected_colors": []
  }
}
```

Xem chi tiết tất cả các trường hợp response tại [api_responses.md](api_responses.md).


## Về API này
Đây là API phục vụ cho tính năng đọc điện trở vạch của dự án [App Component Vault](https://github.com/TVTIT/electronic_component_storage_app). Khoảng 90% code là do AI viết, vì vậy code trông khá là rối.

API chắc hẳn còn nhiều thiếu sót. Vì đây là repo mã nguồn mở nên nếu bạn muốn đóng góp hãy [tạo 1 Pull request](https://github.com/TVTIT/resistor_color_band_recognition_api/pulls) hoặc [tạo 1 Issue](https://github.com/TVTIT/resistor_color_band_recognition_api/issues/new).

## Giấy phép (License) ![GitHub License](https://img.shields.io/github/license/TVTIT/electronic_component_storage_app)
Dự án được phân phối dưới giấy phép MIT