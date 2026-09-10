from __future__ import annotations

import csv
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import database, main, ml_service
from app.config import Settings
from app.main import app


SAMPLE_DATA_DIR = Path(__file__).parent.parent / "sample-data"
SAMPLE_SCHEMAS = {
    "churn_sample.csv": ("churned", {"days_inactive", "tickets", "plan", "churned"}),
    "marketing_response.csv": ("responded", {"visits", "discount_rate", "channel", "membership", "responded"}),
    "returning_customer.csv": ("returned", {"order_count", "average_spend", "category", "loyalty_tier", "returned"}),
}


SAMPLE_CSV = """days_inactive,tickets,plan,churned
1,0,basic,no
2,0,basic,no
3,1,pro,no
4,0,basic,no
5,1,pro,no
6,1,basic,no
18,3,basic,yes
22,4,basic,yes
25,4,pro,yes
28,6,basic,yes
31,5,pro,yes
35,7,basic,yes
"""

ESCAPED_PREVIEW_CSV = """name,label
<script>alert(1)</script>,no
Ada,yes
Bao,no
Chi,yes
"""


@pytest.fixture(autouse=True)
def isolated_storage(tmp_path, monkeypatch):
    storage = tmp_path / "storage"
    test_settings = Settings(
        app_env="test",
        app_secret="test-secret",
        data_dir=storage,
        max_upload_bytes=20 * 1024 * 1024,
        max_rows=100_000,
        trusted_hosts=["localhost", "testserver"],
    )
    storage.mkdir()
    test_settings.upload_dir.mkdir()
    test_settings.model_dir.mkdir()
    for module in (database, main, ml_service):
        monkeypatch.setattr(module, "settings", test_settings)


def get_csrf(html: str) -> str:
    match = re.search(r'name="csrf" value="([^"]+)"', html)
    assert match
    return match.group(1)


def test_upload_train_and_predict_flow():
    with TestClient(app, base_url="http://localhost") as client:
        dashboard = client.get("/")
        assert dashboard.status_code == 200
        assert "Binary Classification Workbench" in dashboard.text
        assert "Upload &amp; train model" in dashboard.text

        upload_page = client.get("/datasets")
        uploaded = client.post(
            "/datasets",
            data={"csrf": get_csrf(upload_page.text)},
            files={"file": ("churn.csv", SAMPLE_CSV.encode(), "text/csv")},
            follow_redirects=False,
        )
        assert uploaded.status_code == 303

        dataset_path = uploaded.headers["location"]
        dataset_page = client.get(dataset_path)
        started = client.post(
            f"{dataset_path}/train",
            data={
                "csrf": get_csrf(dataset_page.text),
                "model_name": "Dự đoán nguy cơ rời dịch vụ",
                "purpose": "Ước lượng khả năng churn từ hành vi và gói dịch vụ.",
                "label_column": "churned",
                "features": ["days_inactive", "tickets", "plan"],
            },
            follow_redirects=False,
        )
        assert started.status_code == 303

        job_page = client.get(started.headers["location"])
        assert "SUCCEEDED" in job_page.text
        assert "Dự đoán nguy cơ rời dịch vụ" in job_page.text
        stored_model = database.fetch_one("SELECT artifact_path, metadata_path FROM model_versions LIMIT 1")
        assert stored_model
        assert not Path(stored_model["artifact_path"]).is_absolute()
        assert not Path(stored_model["metadata_path"]).is_absolute()

        predict_page = client.get("/predict")
        model_id = re.search(r'name="model_id" value="([^"]+)"', predict_page.text)
        assert model_id
        predicted = client.post(
            "/predict",
            data={
                "csrf": get_csrf(predict_page.text),
                "model_id": model_id.group(1),
                "feature_0": "30",
                "feature_1": "5",
                "feature_2": "basic",
            },
        )
        assert predicted.status_code == 200
        assert "Model dự đoán:" in predicted.text
        assert "Dự đoán nguy cơ rời dịch vụ" in predicted.text

        selected_predict = client.get(f"/predict?model_id={model_id.group(1)}")
        assert selected_predict.status_code == 200
        assert f'<option value="{model_id.group(1)}" selected>' in selected_predict.text

        preview = client.get(f"{dataset_path}/preview")
        assert preview.status_code == 200
        assert "Dòng 1-12 trong 12" in preview.text
        assert "days_inactive" in preview.text
        assert client.get(f"{dataset_path}/preview?page=-1").status_code == 404
        assert client.get(f"{dataset_path}/preview?page=1").status_code == 404

        models = client.get("/models")
        assert models.status_code == 200
        assert "Train</dt><dd>9 rows" in models.text
        assert "Test</dt><dd>3 rows" in models.text
        assert f"{dataset_path}/preview" in models.text
        assert "Dự đoán nguy cơ rời dịch vụ" in models.text

        edited = client.post(
            f"/models/{model_id.group(1)}/identity",
            data={
                "csrf": get_csrf(models.text),
                "model_name": "Churn dự báo - bản đã kiểm tra",
                "purpose": "Dùng để minh họa luồng chọn model theo tên ở màn Predict.",
            },
            follow_redirects=False,
        )
        assert edited.status_code == 303
        assert "Churn dự báo - bản đã kiểm tra" in client.get("/models").text


def test_model_identity_validation():
    with TestClient(app, base_url="http://localhost") as client:
        upload_page = client.get("/datasets")
        uploaded = client.post(
            "/datasets",
            data={"csrf": get_csrf(upload_page.text)},
            files={"file": ("identity.csv", SAMPLE_CSV.encode(), "text/csv")},
            follow_redirects=False,
        )
        dataset_path = uploaded.headers["location"]
        dataset_page = client.get(dataset_path)
        invalid = client.post(
            f"{dataset_path}/train",
            data={
                "csrf": get_csrf(dataset_page.text),
                "model_name": "x",
                "purpose": "quá ngắn",
                "label_column": "churned",
                "features": ["days_inactive", "tickets", "plan"],
            },
        )
        assert invalid.status_code == 200
        assert "Tên model cần từ 3 đến 80 ký tự" in invalid.text


def test_dataset_preview_escapes_uploaded_csv_values():
    with TestClient(app, base_url="http://localhost") as client:
        upload_page = client.get("/datasets")
        uploaded = client.post(
            "/datasets",
            data={"csrf": get_csrf(upload_page.text)},
            files={"file": ("preview.csv", ESCAPED_PREVIEW_CSV.encode(), "text/csv")},
            follow_redirects=False,
        )
        assert uploaded.status_code == 303

        preview = client.get(f"{uploaded.headers['location']}/preview")
        assert preview.status_code == 200
        assert "&lt;script&gt;alert(1)&lt;/script&gt;" in preview.text
        assert "<script>alert(1)</script>" not in preview.text


def test_rejects_non_csv_upload():
    with TestClient(app, base_url="http://localhost") as client:
        page = client.get("/datasets")
        response = client.post(
            "/datasets",
            data={"csrf": get_csrf(page.text)},
            files={"file": ("dangerous.txt", b"not,a,csv", "text/plain")},
        )
        assert response.status_code == 200
        assert "Chỉ nhận file CSV UTF-8" in response.text


def test_docs_and_sample_downloads():
    with TestClient(app, base_url="http://localhost") as client:
        docs = client.get("/docs")
        assert docs.status_code == 200
        assert "Năm bước, một vòng lặp học." in docs.text

        for filename in SAMPLE_SCHEMAS:
            download = client.get(f"/samples/{filename}")
            assert download.status_code == 200
            assert download.headers["content-type"].startswith("text/csv")
            assert filename in download.headers["content-disposition"]

        assert client.get("/samples/not-allowed.csv").status_code == 404


def test_error_page_preserves_http_exception_status():
    with TestClient(app, base_url="http://localhost") as client:
        assert client.get("/samples/not-allowed.csv").status_code == 404
        assert client.get("/datasets/not-a-real-dataset").status_code == 404


def test_sample_csv_schemas_are_binary_and_complete():
    for filename, (label_column, expected_columns) in SAMPLE_SCHEMAS.items():
        with (SAMPLE_DATA_DIR / filename).open(encoding="utf-8", newline="") as file:
            rows = list(csv.DictReader(file))

        assert set(rows[0]) == expected_columns
        assert len(rows) >= 12
        assert all(all(value.strip() for value in row.values()) for row in rows)
        assert len({row[label_column] for row in rows}) == 2
