# ML Lab - Logistic Regression Workbench

Web app nhỏ, server-rendered để học trọn luồng Binary Classification: CSV -> chọn feature/label -> train Logistic Regression -> đọc metrics -> predict một record. Nội dung và dữ liệu mẫu dùng tiếng Việt, phù hợp để làm bài tập hoặc demo môn Machine Learning.

> Chỉ dùng để học và thử nghiệm. Không dùng kết quả model để tự động từ chối giao dịch, đưa chẩn đoán, hay thay thế quyết định ảnh hưởng con người.

## Bắt đầu nhanh

Yêu cầu: Python 3.11+ và `uv` (hoặc `pip`).

```bash
cd ml-lab
uv run --with-requirements requirements.txt uvicorn app.main:app --reload
```

Mở [http://127.0.0.1:8000](http://127.0.0.1:8000). Nếu đã có một storage trống, nạp bộ demo đã được version control:

```bash
python3 scripts/seed_example_models.py
```

Script chỉ chạy khi `storage/` chưa có dataset. Nó tạo ba CSV đã import, ba job/model thành công và đặt model churn active.

## Ba model mẫu

| Model | Label | Features | Dùng để học gì? |
|---|---|---|---|
| Dự đoán nguy cơ rời dịch vụ | `churned` | `days_inactive`, `tickets`, `plan` | Ví dụ ngắn nhất về feature số + categorical. |
| Dự đoán phản hồi chiến dịch | `responded` | `visits`, `discount_rate`, `channel`, `membership` | Thử so sánh hành vi, giảm giá và kênh tiếp thị. |
| Dự đoán khách quay lại | `returned` | `order_count`, `average_spend`, `category`, `loyalty_tier` | Thử đọc feature thương mại điện tử và các metric. |

Tất cả CSV ở `sample-data/` là hư cấu và nhỏ. Score đẹp chỉ chứng minh pipeline chạy đúng, không phản ánh chất lượng hay khả năng tổng quát hóa ngoài đời.

## Luồng học trong app

1. Vào **Dataset**, upload CSV hoặc tải một CSV mẫu.
2. Trên màn train, nhập **tên** và **mục đích** model.
3. Chọn một label nhị phân và các feature model được phép dùng.
4. Train. App chia stratified 80/20, fit preprocessing trên train và đo metrics trên test.
5. Vào **Models** để xem mục đích, dataset nguồn, metric, đổi active model hoặc sửa mô tả.
6. Vào **Predict**, chọn model bằng tên rồi nhập một record mới. Kết quả gồm probability, label dự đoán và prediction log.

Mã `v...` chỉ là version kỹ thuật; chọn model bằng tên/mục đích, không dựa vào mã.

## Dữ liệu CSV được hỗ trợ

- UTF-8/BOM UTF-8, extension `.csv`, tối đa 20 MB và 100.000 rows theo mặc định.
- Ít nhất hai cột; label có đúng hai giá trị và mỗi class có ít nhất hai dòng.
- Feature có thể là số hoặc categorical text. Giá trị rỗng trong feature được pipeline imputing; label không được trống.

## Pipeline ML

```text
CSV -> train/test split (80/20, stratified)
    -> numeric: median imputation + StandardScaler
    -> categorical: mode imputation + OneHotEncoder
    -> LogisticRegression
    -> Accuracy / Precision / Recall / F1 / ROC-AUC / Confusion Matrix
```

Threshold mặc định là `0.5`. Probability là xác suất model ước lượng từ pattern đã học, không phải sự chắc chắn hoặc bằng chứng nhân quả.

## Tài liệu dự án

- [Kiến trúc, route map, schema và artifact contract](docs/ARCHITECTURE.md)
- [Bối cảnh dành cho AI khi đọc/sửa code](docs/AI_CONTEXT.md)
- [Learning guide trong app](/docs) khi server đang chạy
- [Ba bản design lịch sử](docs/superpowers/specs/) ghi lại quyết định về docs, chọn model và model identity.

## Kiểm thử

```bash
uv run --with-requirements requirements.txt pytest -q
python3 -m py_compile app/*.py scripts/*.py
```

Test dùng storage tạm độc lập; không làm bẩn `storage/` đang chạy app.

## Chạy Docker

```bash
cp .env.example .env
# Đặt APP_SECRET khác, dài tối thiểu 32 ký tự khi production.
docker compose up -d --build
curl http://127.0.0.1:8000/health
```

Docker chỉ bind `127.0.0.1:8000` mặc định. Khi public qua reverse proxy, dùng HTTPS + authentication và thêm domain thực vào `TRUSTED_HOSTS`.

## Storage, backup và Git

```text
storage/
├── ml_lab.sqlite3
├── uploads/<dataset-id>.csv
└── models/<model-id>/{model.joblib,metadata.json}
```

Repo cá nhân này cố ý commit SQLite, CSV import và model artifact để demo tái lập được. Không commit `.env`, dữ liệu thật nhạy cảm, hoặc SQLite WAL/SHM tạm thời.

Backup trước khi thay đổi dữ liệu:

```bash
chmod +x scripts/backup.sh
./scripts/backup.sh ./storage ./backups
```

Restore khi app đã dừng:

```bash
tar -xzf backups/ml-lab-YYYYMMDD-HHMMSS.tar.gz
```

## Security checklist

- `APP_ENV=production` và `APP_SECRET` mới dài ít nhất 32 ký tự trước deploy.
- Không mở port app trực tiếp ra Internet; dùng reverse proxy HTTPS có authentication.
- Giữ CSRF validation trên mọi form POST.
- Không upload password, token, cookie, PII nhạy cảm hoặc production log thô.
