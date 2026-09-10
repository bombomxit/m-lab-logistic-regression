from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any
from uuid import uuid4

import joblib
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, confusion_matrix, f1_score, precision_score, recall_score, roc_auc_score
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from . import database
from .config import settings


def inspect_csv(path: Path) -> tuple[int, list[dict[str, Any]]]:
    preview = pd.read_csv(path, nrows=1_000, encoding="utf-8-sig")
    with path.open("rb") as source:
        row_count = max(0, sum(1 for _ in source) - 1)
    if row_count < 4:
        raise ValueError("CSV cần ít nhất 4 dòng dữ liệu ngoài header.")
    if row_count > settings.max_rows:
        raise ValueError(f"CSV vượt giới hạn {settings.max_rows:,} dòng.")
    if len(preview.columns) < 2:
        raise ValueError("CSV cần tối thiểu một feature và một cột label.")
    if preview.columns.duplicated().any():
        raise ValueError("Tên cột trong CSV không được trùng nhau.")

    columns = []
    for name in preview.columns:
        sample = preview[name].dropna().head(5).astype(str).tolist()
        kind = "number" if pd.api.types.is_numeric_dtype(preview[name]) else "category"
        columns.append({"name": str(name), "kind": kind, "sample": sample})
    return row_count, columns


def preview_csv(path: Path, page: int, page_size: int) -> tuple[list[str], list[list[str]]]:
    if page < 0 or page_size < 1:
        raise ValueError("Trang preview không hợp lệ.")
    start_row = page * page_size
    with path.open(encoding="utf-8-sig", newline="") as source:
        reader = csv.reader(source)
        headers = next(reader, None)
        if not headers:
            raise ValueError("CSV không có header.")
        rows = []
        for row_index, row in enumerate(reader):
            if row_index < start_row:
                continue
            if len(rows) == page_size:
                break
            normalized_row = row[:len(headers)] + [""] * max(0, len(headers) - len(row))
            rows.append([str(value)[:240] for value in normalized_row])
    return headers, rows


def run_training_job(job_id: str) -> None:
    try:
        job = database.fetch_one("SELECT * FROM training_jobs WHERE id = ?", (job_id,))
        if not job:
            return
        database.update_job(job_id, "running")
        dataset = database.fetch_one("SELECT * FROM datasets WHERE id = ?", (job["dataset_id"],))
        if not dataset:
            raise ValueError("Không tìm thấy dataset của job.")

        label_column = job["label_column"]
        features: list[str] = database.deserialize(job["feature_columns_json"])
        dataframe = pd.read_csv(database.resolve_storage_path(dataset["stored_path"]), encoding="utf-8-sig")
        if len(dataframe) > settings.max_rows:
            raise ValueError("Dataset vượt giới hạn row đã cấu hình.")
        if label_column not in dataframe.columns:
            raise ValueError("Cột label không tồn tại trong dataset.")
        if not features or label_column in features or any(name not in dataframe.columns for name in features):
            raise ValueError("Feature được chọn không hợp lệ.")
        if dataframe[label_column].isna().any():
            raise ValueError("Cột label không được có giá trị trống.")

        labels = dataframe[label_column].astype(str)
        classes = sorted(labels.unique().tolist())
        if len(classes) != 2:
            raise ValueError("Logistic Regression trong app này yêu cầu label có đúng 2 giá trị.")
        if labels.value_counts().min() < 2:
            raise ValueError("Mỗi class cần ít nhất 2 dòng dữ liệu.")

        feature_frame = dataframe[features].copy()
        train_x, test_x, train_y, test_y = train_test_split(
            feature_frame,
            labels,
            test_size=0.2,
            random_state=42,
            stratify=labels,
        )
        numeric_features = [name for name in features if pd.api.types.is_numeric_dtype(feature_frame[name])]
        categorical_features = [name for name in features if name not in numeric_features]
        transformers = []
        if numeric_features:
            transformers.append(
                ("numeric", Pipeline([("impute", SimpleImputer(strategy="median")), ("scale", StandardScaler())]), numeric_features)
            )
        if categorical_features:
            transformers.append(
                ("categorical", Pipeline([("impute", SimpleImputer(strategy="most_frequent")), ("onehot", OneHotEncoder(handle_unknown="ignore"))]), categorical_features)
            )
        if not transformers:
            raise ValueError("Không có feature hợp lệ để train.")

        model = Pipeline(
            [
                ("preprocess", ColumnTransformer(transformers=transformers)),
                ("classifier", LogisticRegression(max_iter=2_000, random_state=42)),
            ]
        )
        model.fit(train_x, train_y)
        predictions = model.predict(test_x)
        probability_index = list(model.classes_).index(classes[1])
        probabilities = model.predict_proba(test_x)[:, probability_index]
        matrix = confusion_matrix(test_y, predictions, labels=classes).tolist()
        metrics = {
            "accuracy": round(float(accuracy_score(test_y, predictions)), 4),
            "precision": round(float(precision_score(test_y, predictions, pos_label=classes[1], zero_division=0)), 4),
            "recall": round(float(recall_score(test_y, predictions, pos_label=classes[1], zero_division=0)), 4),
            "f1": round(float(f1_score(test_y, predictions, pos_label=classes[1], zero_division=0)), 4),
            "roc_auc": round(float(roc_auc_score((test_y == classes[1]).astype(int), probabilities)), 4),
            "confusion_matrix": matrix,
            "classes": classes,
            "test_rows": len(test_x),
            "train_rows": len(train_x),
        }
        feature_schema = []
        for name in features:
            series = feature_frame[name]
            if name in numeric_features:
                feature_schema.append({"name": name, "kind": "number", "example": float(series.dropna().median()) if not series.dropna().empty else 0})
            else:
                choices = sorted(series.dropna().astype(str).unique().tolist())[:100]
                feature_schema.append({"name": name, "kind": "category", "choices": choices, "example": choices[0] if choices else ""})

        model_id = uuid4().hex
        version = f"v{model_id[:8]}"
        staging_dir = settings.model_dir / f".{model_id}.tmp"
        final_dir = settings.model_dir / model_id
        staging_dir.mkdir(parents=True, exist_ok=False)
        artifact_path = staging_dir / "model.joblib"
        metadata_path = staging_dir / "metadata.json"
        joblib.dump(model, artifact_path)
        metadata = {
            "model_id": model_id,
            "version": version,
            "label_column": label_column,
            "positive_label": classes[1],
            "negative_label": classes[0],
            "threshold": 0.5,
            "features": feature_schema,
            "metrics": metrics,
        }
        metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
        staging_dir.replace(final_dir)
        database.create_model(
            {
                "id": model_id,
                "dataset_id": dataset["id"],
                "job_id": job_id,
                "version": version,
                "artifact_path": str(final_dir / "model.joblib"),
                "metadata_path": str(final_dir / "metadata.json"),
                "metrics": metrics,
                "model_name": job["model_name"],
                "purpose": job["purpose"],
            }
        )
        database.update_job(job_id, "succeeded")
    except Exception as error:
        database.update_job(job_id, "failed", f"Không thể train: {str(error)[:300]}")


def load_metadata(model: dict[str, Any]) -> dict[str, Any]:
    return json.loads(database.resolve_storage_path(model["metadata_path"]).read_text(encoding="utf-8"))


def predict(model: dict[str, Any], inputs: dict[str, Any]) -> dict[str, Any]:
    metadata = load_metadata(model)
    model_object = joblib.load(database.resolve_storage_path(model["artifact_path"]))
    feature_values: dict[str, list[Any]] = {}
    normalized_inputs: dict[str, Any] = {}
    for feature in metadata["features"]:
        name = feature["name"]
        raw = inputs.get(name)
        if raw is None or str(raw).strip() == "":
            raise ValueError(f"{name} là bắt buộc.")
        if feature["kind"] == "number":
            try:
                value: Any = float(str(raw))
            except ValueError as error:
                raise ValueError(f"{name} phải là số.") from error
        else:
            value = str(raw)
            if value not in feature["choices"]:
                raise ValueError(f"{name} không thuộc các giá trị đã có khi train.")
        feature_values[name] = [value]
        normalized_inputs[name] = value
    frame = pd.DataFrame(feature_values)
    index = list(model_object.classes_).index(metadata["positive_label"])
    probability = float(model_object.predict_proba(frame)[0][index])
    label = metadata["positive_label"] if probability >= metadata["threshold"] else metadata["negative_label"]
    return {"probability": probability, "label": label, "metadata": metadata, "inputs": normalized_inputs}
