# Kiến trúc ML Lab

ML Lab là FastAPI web app phục vụ học Binary Classification bằng Logistic Regression. Nó xử lý CSV dạng bảng, không phải nền tảng MLOps hay hệ thống ra quyết định thực tế.

## Luồng dữ liệu

```text
CSV upload hoặc sample-data/
  -> storage/uploads/<dataset-id>.csv
  -> datasets (SQLite metadata)
  -> training_jobs (label + features + tên/mục đích)
  -> scikit-learn Pipeline
  -> storage/models/<model-id>/{model.joblib, metadata.json}
  -> model_versions (SQLite metadata + metrics)
  -> Predict form + prediction_logs
```

Mỗi lần train thành công tạo một `model_versions` mới và đặt nó thành active. Người dùng có thể đổi active model ở `/models`; seed script đặt model churn active vì đây là ví dụ ngắn nhất. `model_id` là selector canonical và không đổi; `model_name`/`display_name` chỉ là nhãn hiển thị, có thể sửa và không bắt buộc unique.

## Module chính

| Nơi | Trách nhiệm |
|---|---|
| `app/main.py` | FastAPI routes, validation input, HTTP response và render Jinja templates. |
| `app/database.py` | SQLite schema, migration idempotent, query helper và lưu job/model/prediction. |
| `app/ml_service.py` | Đọc CSV, train pipeline scikit-learn, ghi artifact/metadata, predict một record. |
| `app/security.py` | Session CSRF token và rate limit in-memory theo IP/route. |
| `app/templates/` | Giao diện server-rendered. |
| `app/static/` | CSS/JS/Favicon không có build step. |
| `sample-data/` | Ba CSV hư cấu, được commit để học và seed demo. |
| `scripts/seed_example_models.py` | Tạo ba dataset và model mẫu trên storage trống. |

## Pipeline train

1. App kiểm tra CSV UTF-8, kích thước và schema cơ bản.
2. Người dùng chọn đúng một `label` nhị phân và các `features`, đồng thời ghi tên/mục đích model.
3. `train_test_split(..., test_size=0.2, random_state=42, stratify=labels)` tách train/test.
4. Feature số: median imputation + `StandardScaler`; feature categorical: most-frequent imputation + `OneHotEncoder(handle_unknown="ignore")`.
5. `LogisticRegression(max_iter=2000, random_state=42)` train trong một `Pipeline`.
6. App ghi Accuracy, Precision, Recall, F1, ROC-AUC, confusion matrix, schema feature và threshold `0.5`.

Pipeline chỉ fit preprocessing trên train split, tránh data leakage. `metadata.json` là contract giữa training và Predict; không đổi format tùy tiện nếu còn model cũ.

## SQLite schema

| Bảng | Nội dung |
|---|---|
| `datasets` | `id`, `original_filename`, `stored_path`, `row_count`, `columns_json`, `created_at`. |
| `training_jobs` | `id`, `dataset_id` (FK), `label_column`, `feature_columns_json`, `model_name`, `purpose`, trạng thái queued/running/succeeded/failed, lỗi/thời gian. |
| `model_versions` | `id`, `dataset_id`/`job_id` (FK), `version`, artifact/metadata path, metrics, active flag, `model_name`, `purpose`, `created_at`. Identity columns nullable để đọc model cũ. |
| `prediction_logs` | Input đã chuẩn hóa, probability, label, threshold và thời gian predict. |

`database.init_db()` chạy migration thêm cột bằng `PRAGMA table_info`, nên version cũ được nâng cấp mà không reset schema.

### Artifact và metrics contract

`metadata.json` cần có `model_id`, `version`, `label_column`, `positive_label`, `negative_label`, `threshold` và `features`. Mỗi feature có `name`, `kind` (`number` hoặc `category`), `example`; feature category có thêm `choices`.

`metrics_json` có `accuracy`, `precision`, `recall`, `f1`, `roc_auc`, `classes`, `confusion_matrix`, `train_rows`, `test_rows`. `classes` là hai label đã sort lexical; confusion matrix dùng cùng thứ tự, hàng là label thật và cột là label dự đoán. Positive class là `classes[1]` trong probability/threshold.

## Route map và lifecycle

| Route | Mục đích |
|---|---|
| `GET /` | Dashboard, dataset gần đây và active model. |
| `GET/POST /datasets` | Liệt kê/import CSV. |
| `GET /datasets/{id}` | Chọn tên, mục đích, label và features để train. |
| `GET /datasets/{id}/preview?page=N` | Preview tối đa 50 dòng/trang. |
| `POST /datasets/{id}/train` | Tạo training job; chỉ một job active tại một thời điểm. Trả redirect 303 tới job. |
| `GET /samples/{filename}` | Tải một trong ba CSV mẫu allowlist. |
| `GET /jobs/{id}` | Trạng thái/metrics của training job. |
| `GET /models` | Liệt kê model và identity. |
| `POST /models/{id}/activate` | Đặt model active, redirect 303 về registry. |
| `POST /models/{id}/identity` | Sửa tên/mục đích, redirect 303; `model_id` vẫn giữ nguyên. |
| `GET /predict?model_id=<id>` | Chọn model cụ thể; bỏ query dùng active model. |
| `POST /predict` | Gửi `model_id` + `feature_N`, predict và ghi log. |
| `GET /docs` | Learning guide hiển thị trong app. |
| `GET /health` | Health check JSON. |

`POST /datasets/{id}/train` tạo job `queued`; FastAPI `BackgroundTasks` chuyển `running` -> `succeeded` hoặc `failed`, ghi lỗi tối đa 300 ký tự. Khi server restart, job đang `running` được đánh dấu failed; đây không phải durable queue và không có retry tự động.

Các route không tìm thấy dataset/model, CSV mẫu không nằm trong allowlist hoặc preview ngoài phạm vi trả error page HTTP tương ứng (thường 404). POST thiếu/sai CSRF trả 403.

## Dữ liệu được version control

`storage/` được commit theo chủ đích cho repo cá nhân này, gồm SQLite, ba CSV đã import và ba artifact `joblib`. Các path trong SQLite là relative-to-storage để snapshot chạy được sau khi clone sang thư mục khác hoặc trong Docker. Không commit file `*.sqlite3-wal` hoặc `*.sqlite3-shm` vì chúng là trạng thái tạm của SQLite WAL.

Các metric từ CSV nhỏ hư cấu chỉ kiểm tra pipeline; dữ liệu gần đơn điệu theo label nên F1/ROC-AUC cao là shortcut synthetic, không suy rộng thành chất lượng model thực tế. Với dự án thật nên dùng dataset lớn hơn, cross-validation và kiểm tra category chưa từng thấy.
