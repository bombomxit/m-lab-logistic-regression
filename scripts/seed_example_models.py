"""Nạp ba dataset hư cấu và train lại các model minh họa cho ML Lab.

Chỉ chạy script này trên storage trống. Script cố ý dừng nếu đã có dataset
để không ghi đè dữ liệu do người dùng upload.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import database, ml_service
from app.config import settings


EXAMPLE_MODELS = (
    {
        "filename": "churn_sample.csv",
        "model_name": "Dự đoán nguy cơ rời dịch vụ",
        "purpose": "Ước lượng khả năng churn từ số ngày không hoạt động, số ticket hỗ trợ và gói dịch vụ.",
        "label": "churned",
        "features": ["days_inactive", "tickets", "plan"],
    },
    {
        "filename": "marketing_response.csv",
        "model_name": "Dự đoán phản hồi chiến dịch",
        "purpose": "Ước lượng khả năng phản hồi marketing từ lượt truy cập, mức giảm giá, kênh và hạng thành viên.",
        "label": "responded",
        "features": ["visits", "discount_rate", "channel", "membership"],
    },
    {
        "filename": "returning_customer.csv",
        "model_name": "Dự đoán khách quay lại",
        "purpose": "Ước lượng khả năng khách mua lại từ lịch sử đơn hàng, chi tiêu, danh mục và hạng khách hàng thân thiết.",
        "label": "returned",
        "features": ["order_count", "average_spend", "category", "loyalty_tier"],
    },
)


def main() -> None:
    database.init_db()
    if database.fetch_one("SELECT id FROM datasets LIMIT 1"):
        raise SystemExit("Storage không trống. Hãy backup hoặc dùng storage mới trước khi seed.")

    active_model_id: str | None = None
    for example in EXAMPLE_MODELS:
        source = ROOT / "sample-data" / example["filename"]
        dataset_id = uuid4().hex
        destination = settings.upload_dir / f"{dataset_id}.csv"
        shutil.copy2(source, destination)
        row_count, columns = ml_service.inspect_csv(destination)
        database.create_dataset(dataset_id, example["filename"], destination, row_count, columns)

        job_id = uuid4().hex
        database.create_job(
            job_id,
            dataset_id,
            example["label"],
            example["features"],
            example["model_name"],
            example["purpose"],
        )
        ml_service.run_training_job(job_id)
        job = database.fetch_one("SELECT status, error_message FROM training_jobs WHERE id = ?", (job_id,))
        if not job or job["status"] != "succeeded":
            raise RuntimeError(job["error_message"] if job else "Không tìm thấy training job.")

        model = database.fetch_one("SELECT id, metrics_json FROM model_versions WHERE job_id = ?", (job_id,))
        if not model:
            raise RuntimeError("Training thành công nhưng không tìm thấy model artifact.")
        if example["filename"] == "churn_sample.csv":
            active_model_id = model["id"]
        metrics = database.deserialize(model["metrics_json"])
        print(f"✓ {example['model_name']}: F1={metrics['f1']:.2f}, Accuracy={metrics['accuracy']:.2f}")

    if active_model_id:
        database.activate_model(active_model_id)
    print("Đã seed 3 model. Model churn đang active mặc định.")


if __name__ == "__main__":
    main()
