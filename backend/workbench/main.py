from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles

from .engine import process
from .export import export_workbook
from .ingest import InputError, MAX_BYTES, parse_file
from .models import ProcessConfig
from .storage import Store


def create_app(db_path: Optional[str] = None) -> FastAPI:
    app = FastAPI(title="Data Automation Workbench", version="1.0.0")
    store = Store(db_path)

    @app.middleware("http")
    async def local_access(request: Request, call_next):
        if request.url.hostname not in ("localhost", "127.0.0.1", "testserver"):
            return Response("Local access only.", status_code=403)
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            origin = request.headers.get("origin")
            allowed = {
                f"{request.url.scheme}://{request.url.netloc}",
                "http://localhost:5173",
                "http://127.0.0.1:5173",
            }
            if origin and origin not in allowed:
                return Response("Cross-origin access blocked.", status_code=403)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    def get(kind: str, identity: str) -> Dict[str, Any]:
        value = store.get(kind, identity)
        if value is None:
            raise HTTPException(404, f"{kind.title()} not found.")
        return value

    @app.get("/api/health")
    def health() -> Dict[str, str]:
        return {"status": "ok"}

    @app.post("/api/datasets", status_code=201)
    async def upload(file: UploadFile = File(...), delimiter: str = Form(",")) -> Dict[str, Any]:
        try:
            content = await file.read(MAX_BYTES + 1)
            dataset = store.save(
                "dataset", parse_file(file.filename or "upload", content, delimiter)
            )
            return {
                **{key: value for key, value in dataset.items() if key != "rows"},
                "row_count": len(dataset["rows"]),
            }
        except InputError as exc:
            raise HTTPException(422, str(exc)) from exc
        finally:
            await file.close()

    @app.get("/api/datasets/{dataset_id}")
    def dataset(
        dataset_id: str, offset: int = Query(0, ge=0), limit: int = Query(25, ge=1, le=100)
    ) -> Dict[str, Any]:
        data = get("dataset", dataset_id)
        return {
            **{key: value for key, value in data.items() if key != "rows"},
            "row_count": len(data["rows"]),
            "rows": data["rows"][offset : offset + limit],
        }

    @app.post("/api/datasets/{dataset_id}/runs", status_code=201)
    def run(dataset_id: str, config: ProcessConfig) -> Dict[str, Any]:
        data = get("dataset", dataset_id)
        try:
            result = process(data, config)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        result = store.save(
            "run",
            {
                **result,
                "dataset_id": dataset_id,
                "filename": data["filename"],
                "source_columns": data["columns"],
                "source_notes": data["notes"],
                "config": config.model_dump(),
            },
        )
        return {key: value for key, value in result.items() if key not in ("records", "audit")}

    @app.get("/api/runs")
    def history() -> List[Dict[str, Any]]:
        return store.history()

    @app.get("/api/runs/{run_id}")
    def review(
        run_id: str,
        status: str = Query("all", pattern="^(all|accepted|changed|rejected)$"),
        offset: int = Query(0, ge=0),
        limit: int = Query(25, ge=1, le=100),
        q: str = Query("", max_length=200),
    ) -> Dict[str, Any]:
        data = get("run", run_id)
        records = [
            row
            for row in data["records"]
            if status == "all"
            or row["status"] == status
            or (status == "changed" and row["status"] == "accepted" and row["changed"])
        ]
        query = q.strip().casefold()
        if query:
            records = [
                row
                for row in records
                if any(
                    query in str(value).casefold()
                    for value in [
                        *row["original"].values(),
                        *row["cleaned"].values(),
                        *row["reasons"],
                    ]
                    if value is not None
                )
            ]
        return {
            **{key: value for key, value in data.items() if key not in ("records", "audit")},
            "records": records[offset : offset + limit],
            "filtered_count": len(records),
        }

    @app.get("/api/runs/{run_id}/export")
    def export(run_id: str) -> Response:
        return Response(
            export_workbook(get("run", run_id)),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f'attachment; filename="cleaned-{run_id[:8]}.xlsx"'},
        )

    @app.get("/api/sample")
    def sample() -> Response:
        path = Path(__file__).resolve().parents[2] / "samples" / "messy_customers.csv"
        return Response(
            path.read_bytes(),
            media_type="text/csv",
            headers={"Content-Disposition": 'attachment; filename="messy_customers.csv"'},
        )

    @app.get("/api/sample/config", response_model=ProcessConfig)
    def sample_config() -> ProcessConfig:
        path = Path(__file__).resolve().parents[2] / "samples" / "customer_rules.json"
        return ProcessConfig.model_validate_json(path.read_text(encoding="utf-8"))

    frontend = Path(__file__).resolve().parents[2] / "frontend" / "dist"
    if frontend.exists():
        app.mount("/", StaticFiles(directory=frontend, html=True), name="frontend")
    return app
