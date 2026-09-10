# AI context: ML Lab

Đọc file này trước khi sửa code. Chi tiết kiến trúc ở [ARCHITECTURE.md](ARCHITECTURE.md); hướng dẫn chạy ở [README](../README.md).

## Mục tiêu và phạm vi

- Đây là lab học Logistic Regression nhị phân cho CSV dạng bảng.
- Chỉ dùng dữ liệu hư cấu/dữ liệu đã được phép; không biến app thành hệ thống tự động ra quyết định thật.
- Giữ UI tiếng Việt, server-side rendered và không thêm framework frontend/build step nếu không cần.

## Contract không được phá vỡ

- Label phải có đúng hai class; class dương là phần tử thứ hai của `sorted(labels.unique())` (sort lexical), không phụ thuộc thứ tự dòng trong CSV.
- Artifact cần có `model.joblib` và `metadata.json`; Predict phụ thuộc `metadata.features`, `positive_label`, `negative_label` và `threshold`. `model_id` là selector canonical; `model_name`/`display_name` chỉ để trình bày và có thể sửa.
- Metrics JSON phải giữ `accuracy`, `precision`, `recall`, `f1`, `roc_auc`, `classes`, `confusion_matrix`, `train_rows`, `test_rows`; confusion matrix dùng `classes` sorted làm thứ tự hàng/cột.
- Mọi form POST dùng `validate_form_security()` (CSRF + rate limit).
- Không fit scaler/encoder trên test set hoặc toàn CSV trước split.
- Không bỏ migration idempotent trong `database.init_db()`; storage cũ phải vẫn mở được.
- Training chạy qua `BackgroundTasks`, không phải durable queue; restart đánh dấu job đang chạy là failed và không tự retry.
- `inspect_csv()` yêu cầu tối thiểu 4 dòng, nhưng split stratified thực tế cần đủ mẫu cho cả hai class; dataset quá nhỏ có thể fail ở job và phải được báo rõ, không nuốt lỗi.

## Nơi sửa theo nhu cầu

| Nhu cầu | Nơi ưu tiên |
|---|---|
| Thêm validation hoặc route | `app/main.py`, sau đó test route. |
| Thay pipeline/metrics | `app/ml_service.py`, cập nhật metadata và test train/predict. |
| Đổi schema hoặc migration | `app/database.py`, có migration tương thích ngược. |
| Đổi label/feature UI | template tương ứng trong `app/templates/`. |
| Thêm model mẫu | `sample-data/` và `scripts/seed_example_models.py`. |
| Đổi deploy/config | `app/config.py`, `.env.example`, Docker files, README. |

## Kiểm tra bắt buộc sau thay đổi

```bash
uv run --with-requirements requirements.txt pytest -q
python3 -m py_compile app/*.py scripts/*.py
```

Khi sửa UI, mở luồng `Dataset -> Train -> Models -> Predict` trên desktop và mobile. Khi sửa pipeline, chạy seed trên `DATA_DIR` tạm hoặc storage trống rồi kiểm tra ba job đều `succeeded`.

## Quy tắc dữ liệu và Git

- Test tự dùng `tmp_path`; không được làm bẩn `storage/` thật.
- Repo này cố ý version control `storage/` để reproducible demo. Không commit `.env`, WAL/SHM hoặc dữ liệu thật nhạy cảm.
- Chỉ load `model.joblib` do chính pipeline tạo; `joblib`/pickle không an toàn nếu artifact bị thay thế. Path dataset/artifact trong SQLite phải relative-to-storage để clone/Docker portable.
- Trước khi reset storage, dùng backup hoặc đưa thư mục cũ vào Thùng rác; không xóa mơ hồ.
