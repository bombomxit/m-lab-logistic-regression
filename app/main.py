from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from . import database, ml_service
from .config import settings
from .security import csrf_token, validate_form_security


PREVIEW_PAGE_SIZE = 50


@asynccontextmanager
async def lifespan(_: FastAPI):
    database.init_db()
    yield


app = FastAPI(title="ML Lab", docs_url=None, redoc_url=None, lifespan=lifespan)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.trusted_hosts)
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.app_secret,
    https_only=settings.app_env == "production",
    same_site="lax",
)
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")
templates = Jinja2Templates(directory=Path(__file__).parent / "templates")
sample_data_dir = Path(__file__).parent.parent / "sample-data"
sample_files = {
    "churn_sample.csv",
    "marketing_response.csv",
    "returning_customer.csv",
}


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["Content-Security-Policy"] = "default-src 'self'; style-src 'self'; script-src 'self'; img-src 'self' data:; base-uri 'self'; frame-ancestors 'none'; form-action 'self'"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    return response


def view(request: Request, template_name: str, **context):
    return templates.TemplateResponse(
        request,
        template_name,
        {"csrf_token": csrf_token(request), "app_env": settings.app_env, **context},
    )


def get_dataset(dataset_id: str) -> dict:
    dataset = database.fetch_one("SELECT * FROM datasets WHERE id = ?", (dataset_id,))
    if not dataset:
        raise HTTPException(status_code=404, detail="Không tìm thấy dataset.")
    dataset["columns"] = database.deserialize(dataset.pop("columns_json"))
    dataset["stored_path"] = str(database.resolve_storage_path(dataset["stored_path"]))
    return dataset


def get_model(model_id: str | None = None) -> dict:
    if model_id:
        model = database.fetch_one(
            """
            SELECT m.*, d.original_filename, j.label_column
            FROM model_versions m
            JOIN datasets d ON d.id = m.dataset_id
            JOIN training_jobs j ON j.id = m.job_id
            WHERE m.id = ?
            """,
            (model_id,),
        )
    else:
        model = database.fetch_one(
            """
            SELECT m.*, d.original_filename, j.label_column
            FROM model_versions m
            JOIN datasets d ON d.id = m.dataset_id
            JOIN training_jobs j ON j.id = m.job_id
            WHERE m.is_active = 1
            """
        )
    if not model:
        raise HTTPException(status_code=404, detail="Chưa có model active. Hãy train một model trước.")
    model["metrics"] = database.deserialize(model.pop("metrics_json"))
    model["artifact_path"] = str(database.resolve_storage_path(model["artifact_path"]))
    model["metadata_path"] = str(database.resolve_storage_path(model["metadata_path"]))
    return add_model_display_identity(model)


def validate_model_identity(model_name: str, purpose: str) -> tuple[str, str]:
    normalized_name = " ".join(model_name.split())
    normalized_purpose = purpose.strip()
    if not 3 <= len(normalized_name) <= 80:
        raise ValueError("Tên model cần từ 3 đến 80 ký tự.")
    if not 10 <= len(normalized_purpose) <= 240:
        raise ValueError("Mục đích model cần từ 10 đến 240 ký tự.")
    return normalized_name, normalized_purpose


def add_model_display_identity(model: dict) -> dict:
    saved_name = (model.get("model_name") or "").strip()
    saved_purpose = (model.get("purpose") or "").strip()
    model["display_name"] = saved_name or f"{model['original_filename']} - dự đoán {model['label_column']}"
    model["display_purpose"] = saved_purpose or "Model cũ chưa có mô tả mục đích. Hãy bổ sung để dễ chọn khi Predict."
    model["has_identity"] = bool(saved_name and saved_purpose)
    return model


def list_models() -> list[dict]:
    models = database.fetch_all(
        """
        SELECT m.*, d.original_filename, d.row_count, j.label_column, j.feature_columns_json
        FROM model_versions m
        JOIN datasets d ON d.id = m.dataset_id
        JOIN training_jobs j ON j.id = m.job_id
        ORDER BY m.created_at DESC
        """
    )
    for model in models:
        model["metrics"] = database.deserialize(model.pop("metrics_json"))
        model["feature_count"] = len(database.deserialize(model.pop("feature_columns_json")))
        add_model_display_identity(model)
    return models


@app.get("/health")
def health():
    return JSONResponse({"status": "ok"})


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    datasets = database.fetch_all("SELECT * FROM datasets ORDER BY created_at DESC LIMIT 5")
    active_model = None
    try:
        active_model = get_model()
    except HTTPException:
        pass
    return view(request, "dashboard.html", active_page="dashboard", datasets=datasets, active_model=active_model)


@app.get("/docs", response_class=HTMLResponse)
def docs_page(request: Request):
    return view(request, "docs.html", active_page="docs")


@app.get("/samples/{filename}")
def download_sample(filename: str):
    if filename not in sample_files:
        raise HTTPException(status_code=404, detail="Không tìm thấy CSV mẫu.")
    return FileResponse(sample_data_dir / filename, media_type="text/csv", filename=filename)


@app.get("/datasets", response_class=HTMLResponse)
def datasets_page(request: Request):
    datasets = database.fetch_all("SELECT * FROM datasets ORDER BY created_at DESC")
    return view(request, "datasets.html", active_page="datasets", datasets=datasets)


@app.post("/datasets", response_class=HTMLResponse)
async def upload_dataset(request: Request, csrf: str = Form(...), file: UploadFile = File(...)):
    await validate_form_security(request, csrf)
    filename = (file.filename or "").strip()
    content_type = (file.content_type or "").lower()
    allowed_types = {"text/csv", "application/csv", "application/vnd.ms-excel", "text/plain"}
    if Path(filename).suffix.lower() != ".csv" or content_type not in allowed_types:
        return view(request, "datasets.html", active_page="datasets", datasets=database.fetch_all("SELECT * FROM datasets ORDER BY created_at DESC"), error="Chỉ nhận file CSV UTF-8.")

    dataset_id = uuid4().hex
    destination = settings.upload_dir / f"{dataset_id}.csv"
    bytes_written = 0
    try:
        with destination.open("wb") as target:
            while chunk := await file.read(1024 * 1024):
                bytes_written += len(chunk)
                if bytes_written > settings.max_upload_bytes:
                    raise ValueError(f"File vượt giới hạn {settings.max_upload_bytes // 1024 // 1024} MB.")
                target.write(chunk)
        row_count, columns = ml_service.inspect_csv(destination)
        database.create_dataset(dataset_id, Path(filename).name, destination, row_count, columns)
    except Exception as error:
        destination.unlink(missing_ok=True)
        return view(request, "datasets.html", active_page="datasets", datasets=database.fetch_all("SELECT * FROM datasets ORDER BY created_at DESC"), error=f"Không thể import CSV: {str(error)[:220]}")
    finally:
        await file.close()
    return RedirectResponse(f"/datasets/{dataset_id}", status_code=303)


@app.get("/datasets/{dataset_id}", response_class=HTMLResponse)
def dataset_detail(request: Request, dataset_id: str):
    dataset = get_dataset(dataset_id)
    jobs = database.fetch_all("SELECT * FROM training_jobs WHERE dataset_id = ? ORDER BY created_at DESC", (dataset_id,))
    return view(request, "dataset_detail.html", active_page="datasets", dataset=dataset, jobs=jobs)


@app.get("/datasets/{dataset_id}/preview", response_class=HTMLResponse)
def dataset_preview(request: Request, dataset_id: str, page: int = 0):
    dataset = get_dataset(dataset_id)
    last_page = (dataset["row_count"] - 1) // PREVIEW_PAGE_SIZE
    if page < 0 or page > last_page:
        raise HTTPException(status_code=404, detail="Không tìm thấy trang preview dữ liệu.")
    try:
        headers, rows = ml_service.preview_csv(Path(dataset["stored_path"]), page, PREVIEW_PAGE_SIZE)
    except (OSError, UnicodeDecodeError, ValueError):
        raise HTTPException(status_code=404, detail="Không thể đọc CSV nguồn của dataset.") from None
    return view(
        request,
        "dataset_preview.html",
        active_page="datasets",
        dataset=dataset,
        headers=headers,
        rows=rows,
        page=page,
        page_size=PREVIEW_PAGE_SIZE,
        last_page=last_page,
    )


@app.post("/datasets/{dataset_id}/train")
async def start_training(request: Request, dataset_id: str, csrf: str = Form(...), model_name: str = Form(...), purpose: str = Form(...), label_column: str = Form(...), features: list[str] = Form(default=[]), background_tasks: BackgroundTasks = None):
    await validate_form_security(request, csrf)
    dataset = get_dataset(dataset_id)
    valid_columns = {column["name"] for column in dataset["columns"]}
    form_values = {"model_name": model_name, "purpose": purpose}
    try:
        model_name, purpose = validate_model_identity(model_name, purpose)
    except ValueError as error:
        jobs = database.fetch_all("SELECT * FROM training_jobs WHERE dataset_id = ? ORDER BY created_at DESC", (dataset_id,))
        return view(request, "dataset_detail.html", active_page="datasets", dataset=dataset, jobs=jobs, error=str(error), form_values=form_values)
    if label_column not in valid_columns or not features or label_column in features or not set(features).issubset(valid_columns):
        jobs = database.fetch_all("SELECT * FROM training_jobs WHERE dataset_id = ? ORDER BY created_at DESC", (dataset_id,))
        return view(request, "dataset_detail.html", active_page="datasets", dataset=dataset, jobs=jobs, error="Chọn một label và ít nhất một feature khác label.", form_values=form_values)
    try:
        job_id = uuid4().hex
        database.create_job(job_id, dataset_id, label_column, features, model_name, purpose)
    except ValueError as error:
        jobs = database.fetch_all("SELECT * FROM training_jobs WHERE dataset_id = ? ORDER BY created_at DESC", (dataset_id,))
        return view(request, "dataset_detail.html", active_page="datasets", dataset=dataset, jobs=jobs, error=str(error), form_values=form_values)
    if background_tasks is None:
        raise HTTPException(status_code=500, detail="Không khởi tạo được background task.")
    background_tasks.add_task(ml_service.run_training_job, job_id)
    return RedirectResponse(f"/jobs/{job_id}", status_code=303)


@app.get("/jobs/{job_id}", response_class=HTMLResponse)
def job_detail(request: Request, job_id: str):
    job = database.fetch_one("SELECT * FROM training_jobs WHERE id = ?", (job_id,))
    if not job:
        raise HTTPException(status_code=404, detail="Không tìm thấy training job.")
    model = database.fetch_one("SELECT * FROM model_versions WHERE job_id = ?", (job_id,))
    if model:
        model["metrics"] = database.deserialize(model.pop("metrics_json"))
        model["display_name"] = (model.get("model_name") or "").strip() or model["version"]
    return view(request, "job_detail.html", active_page="datasets", job=job, model=model)


@app.get("/models", response_class=HTMLResponse)
def models_page(request: Request):
    return view(request, "models.html", active_page="models", models=list_models())


@app.post("/models/{model_id}/activate")
async def activate_model(request: Request, model_id: str, csrf: str = Form(...)):
    await validate_form_security(request, csrf)
    if not database.activate_model(model_id):
        raise HTTPException(status_code=404, detail="Không tìm thấy model.")
    return RedirectResponse("/models", status_code=303)


@app.post("/models/{model_id}/identity")
async def update_model_identity(request: Request, model_id: str, csrf: str = Form(...), model_name: str = Form(...), purpose: str = Form(...)):
    await validate_form_security(request, csrf)
    try:
        model_name, purpose = validate_model_identity(model_name, purpose)
    except ValueError as error:
        models = list_models()
        for model in models:
            if model["id"] == model_id:
                model["model_name"] = model_name
                model["purpose"] = purpose
                break
        return view(request, "models.html", active_page="models", models=models, error=str(error))
    if not database.update_model_identity(model_id, model_name, purpose):
        raise HTTPException(status_code=404, detail="Không tìm thấy model.")
    return RedirectResponse("/models", status_code=303)


@app.get("/predict", response_class=HTMLResponse)
def predict_page(request: Request, model_id: str | None = None):
    model = get_model(model_id)
    metadata = ml_service.load_metadata(model)
    return view(request, "predict.html", active_page="predict", model=model, models=list_models(), metadata=metadata, result=None, error=None)


@app.post("/predict", response_class=HTMLResponse)
async def predict_request(request: Request, csrf: str = Form(...), model_id: str = Form(...)):
    await validate_form_security(request, csrf)
    model = get_model(model_id)
    metadata = ml_service.load_metadata(model)
    form = await request.form()
    raw_inputs = {feature["name"]: form.get(f"feature_{index}") for index, feature in enumerate(metadata["features"])}
    try:
        result = ml_service.predict(model, raw_inputs)
        database.log_prediction(uuid4().hex, model["id"], result["inputs"], result["probability"], result["label"], metadata["threshold"])
        return view(request, "predict.html", active_page="predict", model=model, models=list_models(), metadata=metadata, result=result, error=None)
    except ValueError as error:
        return view(request, "predict.html", active_page="predict", model=model, models=list_models(), metadata=metadata, result=None, error=str(error))


@app.exception_handler(HTTPException)
async def handled_error(request: Request, error: HTTPException):
    response = view(request, "error.html", active_page="", status_code=error.status_code, message=error.detail)
    response.status_code = error.status_code
    return response
