"""Cloud Sync Service (Refactored)

Run locally:
  pip install -r cloud_service/requirements.txt
  uvicorn cloud_service.app:app --host 0.0.0.0 --port 8000
"""
import os
import traceback
import html
from typing import Dict, Any
from fastapi import FastAPI, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from .modules.config import DATA_DIR
from .modules.routes import (
    public, contact, register, teacher_auth, admin_dashboard,
    pairing, sync, license, classes, students, teachers,
    messages, settings, logs, import_export, payment,
    admin_super
)

app = FastAPI(title="SchoolPoints Sync")

# Mount assets if needed (though public.py handles specific assets, we might want a general static mount if used)
# app.mount("/static", StaticFiles(directory="static"), name="static")

@app.middleware("http")
async def catch_exceptions_middleware(request: Request, call_next):
    try:
        return await call_next(request)
    except Exception as exc:
        traceback.print_exc()
        # If it's a browser request, show the traceback HTML
        accept = request.headers.get("accept", "")
        if "text/html" in accept:
            tb_str = traceback.format_exc()
            html_content = f"""
            <html>
            <head>
                <title>500 Internal Server Error</title>
                <style>
                    body {{ font-family: monospace; padding: 20px; background: #f8f9fa; color: #333; }}
                    h1 {{ color: #e74c3c; }}
                    pre {{ background: #fff; padding: 15px; border: 1px solid #ddd; border-radius: 5px; overflow: auto; }}
                </style>
            </head>
            <body>
                <h1>500 Internal Server Error</h1>
                <p>An unexpected error occurred.</p>
                <pre>{html.escape(tb_str)}</pre>
            </body>
            </html>
            """
            return HTMLResponse(content=html_content, status_code=500)
        
        # For API/JSON requests
        return Response(content="Internal Server Error", status_code=500)

# Include Routers
app.include_router(public.router)
app.include_router(contact.router)
app.include_router(register.router)
app.include_router(teacher_auth.router)
app.include_router(admin_dashboard.router)
app.include_router(pairing.router)
app.include_router(sync.router)
app.include_router(license.router)
app.include_router(classes.router)
app.include_router(students.router)
app.include_router(teachers.router)
app.include_router(messages.router)
app.include_router(settings.router)
app.include_router(logs.router)
app.include_router(import_export.router)
app.include_router(payment.router)
app.include_router(admin_super.router)

@app.get("/", include_in_schema=False)
def root() -> Response:
    return RedirectResponse(url="/web", status_code=302)

@app.get("/admin", include_in_schema=False)
def root_admin() -> Response:
    return RedirectResponse(url="/web/admin", status_code=302)

APP_BUILD_TAG = "2026-02-05-modular-refactor"

@app.get("/health", include_in_schema=False)
def health() -> Dict[str, Any]:
    return {
        "ok": True,
        "build": APP_BUILD_TAG,
    }

# Web build info for client check
@app.get("/web/build")
def web_build() -> Dict[str, Any]:
    routes_list = []
    for r in getattr(app, "routes", []) or []:
        path = getattr(r, "path", None)
        if path:
            routes_list.append(path)
    return {
        "build": APP_BUILD_TAG,
        "routes": len(routes_list)
    }
