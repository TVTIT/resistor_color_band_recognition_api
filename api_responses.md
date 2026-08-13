# Tổng hợp các trường hợp API Response

Tài liệu này tổng hợp toàn bộ các trường hợp phản hồi (Response) của API `/scan-resistor` từ hệ thống nhận diện điện trở, giúp phía Frontend (Flutter/Web) dễ dàng tích hợp và xử lý lỗi.

## Cấu trúc Response chung

Mọi response đều có cấu trúc:

```json
{
  "error_code": 0 | 1 | -1,
  "message": "...",
  "data": { ... } | null
}
```

| Field | Type | Mô tả |
|-------|------|--------|
| `error_code` | `int` | `0` = thành công, `1` = lỗi nghiệp vụ, `-1` = lỗi hệ thống |
| `message` | `string` | Mô tả kết quả |
| `data` | `object \| null` | Dữ liệu kết quả (thành công) hoặc debug info (lỗi nghiệp vụ), `null` nếu không có dữ liệu |

---

## 1. Xác thực Supabase JWT (HTTP 401)

Tất cả các request phải kèm header `Authorization: Bearer <access_token>`.

### 1.1 Token hết hạn

```json
// HTTP 401
{
  "detail": "Token đã hết hạn. Vui lòng đăng nhập lại."
}
```

### 1.2 Token không hợp lệ

```json
// HTTP 401
{
  "detail": "Token không hợp lệ."
}
```

---

## 2. Kiểm tra File đầu vào

### 2.1 Định dạng file không hợp lệ

```json
{
  "error_code": 1,
  "message": "Định dạng file không được hỗ trợ. Chỉ chấp nhận: .png, .jpg, .jpeg, .heic, .webp",
  "data": null
}
```

### 2.2 Kích thước file vượt giới hạn (> 10MB)

```json
{
  "error_code": 1,
  "message": "File quá lớn. Giới hạn tối đa 10MB.",
  "data": null
}
```

### 2.3 File hỏng (không decode được)

```json
{
  "error_code": 1,
  "message": "File không hợp lệ",
  "data": null
}
```

---

## 3. Phát hiện linh kiện

### 3.1 Không phát hiện điện trở nào

```json
{
  "error_code": 1,
  "message": "Không phát hiện điện trở nào trong ảnh.",
  "data": null
}
```

### 3.2 Phát hiện nhiều điện trở

```json
{
  "error_code": 1,
  "message": "Phát hiện 2 điện trở trong ảnh. Vui lòng chỉ chụp 1 điện trở duy nhất.",
  "data": null
}
```

### 3.3 Phát hiện điện trở nhưng không quét được vạch màu

```json
{
  "error_code": 1,
  "message": "Tìm thấy điện trở nhưng không quét được vạch màu nào",
  "data": null
}
```

---

## 4. Kiểm chuẩn vạch màu

### 4.1 Số lượng vạch không hợp lệ (không phải 4 hoặc 5)

```json
{
  "error_code": 1,
  "message": "Lỗi: Nhận diện được 3 vạch. Chỉ hỗ trợ điện trở 4 hoặc 5 vạch.",
  "data": {
    "debug_colors": ["brown", "black", "gold"]
  }
}
```

### 4.2 Vạch nhũ (Gold/Silver) xuất hiện sai quy tắc ở giữa

```json
{
  "error_code": 1,
  "message": "Lỗi: Vạch sai số (Gold/Silver) xuất hiện sai quy tắc ở giữa thân điện trở.",
  "data": {
    "debug_colors": ["brown", "gold", "red", "gold"]
  }
}
```

### 4.3 Không thể tính toán trị số (tổ hợp màu lỗi)

```json
{
  "error_code": 1,
  "message": "Không thể tính toán trị số điện trở từ tổ hợp màu nhận diện được.",
  "data": {
    "debug_colors": ["gold", "red", "brown", "gold"]
  }
}
```

---

## 🎉 5. Thành công

### 5.1 Đúng chuẩn E24

```json
{
  "error_code": 0,
  "message": "Thành công",
  "data": {
    "component_type": "Điện trở",
    "value": "10k",
    "tolerance": "5%",
    "is_e24_standard": true,
    "debug_colors": ["brown", "black", "orange", "gold"],
    "corrected_colors": []
  }
}
```

### 5.2 Đã tự động sửa lỗi theo chuẩn E24

```json
{
  "error_code": 0,
  "message": "Thành công",
  "data": {
    "component_type": "Điện trở",
    "value": "12k",
    "tolerance": "5%",
    "is_e24_standard": false,
    "debug_colors": ["brown", "brown", "orange", "gold"],
    "corrected_colors": ["brown", "red", "orange", "gold"]
  }
}
```

> **Lưu ý về `tolerance`**: Nếu vạch cuối cùng không nằm trong bảng sai số chuẩn (ví dụ do nhận diện sai), `tolerance` sẽ trả về `null`.

---

## ⚡ 6. Lỗi hệ thống

### 6.1 Exception chưa lường trước

```json
{
  "error_code": -1,
  "message": "Đã xảy ra lỗi hệ thống. Vui lòng thử lại sau.",
  "data": null
}
```

> Chi tiết lỗi được ghi log phía server.
