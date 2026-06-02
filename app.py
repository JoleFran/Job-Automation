#!/usr/bin/env python3
"""
app.py — Flask HTTP wrapper for generate_resume.py
Joe Frank Job Search Pipeline — Railway deployment

Endpoints:
    POST /generate   — generate a resume document from bullets + template name
    GET  /health     — health check (Railway uses this)
    GET  /templates  — list available template files

Environment variables:
    TEMPLATES_DIR    — path to directory containing .docx templates (default: /app/templates)
    OUTPUTS_DIR      — path to write generated files (default: /app/outputs)
    AUTH_TOKEN       — shared secret for request auth (set this in Railway env vars)

n8n calls this via HTTP Request node with:
    POST /generate
    Headers: { Authorization: Bearer <AUTH_TOKEN>, Content-Type: application/json }
    Body: {
        "template": "MeridianLink",         // must match a .docx filename in TEMPLATES_DIR
        "bullets": [...],                    // bullets array from Rewriter output
        "job_id": "recXXXXXXXXXXXXXX",     // Airtable record ID — used to name the output file
        "pdf": true                          // optional, default true
    }

Response:
    {
        "status": "success",
        "docx_url": "/outputs/recXXX_MeridianLink.docx",
        "pdf_url":  "/outputs/recXXX_MeridianLink.pdf",
        "bullets_replaced": 3,
        "bullets_not_found": 0,
        "changelog": [...],
        "warnings": [...]
    }
"""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory, abort

app = Flask(__name__)

TEMPLATES_DIR = Path(os.environ.get("TEMPLATES_DIR", "/app/templates"))
OUTPUTS_DIR   = Path(os.environ.get("OUTPUTS_DIR",   "/app/outputs"))
AUTH_TOKEN    = os.environ.get("AUTH_TOKEN", "")

# Path to the core script — lives alongside this file in the repo
SCRIPT_PATH = Path(__file__).parent / "generate_resume.py"


# ── Auth ──────────────────────────────────────────────────────────────────────

def check_auth():
    """Return 401 if AUTH_TOKEN is set and the request doesn't match."""
    if not AUTH_TOKEN:
        return  # No token configured — open (only do this on Railway private network)
    header = request.headers.get("Authorization", "")
    if header != f"Bearer {AUTH_TOKEN}":
        abort(401, description="Invalid or missing Authorization header")


# ── Routes ────────────────────────────────────────────────────────────────────

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "templates_dir": str(TEMPLATES_DIR),
                    "outputs_dir": str(OUTPUTS_DIR)})


@app.route("/templates", methods=["GET"])
def list_templates():
    check_auth()
    if not TEMPLATES_DIR.exists():
        return jsonify({"templates": [], "error": f"{TEMPLATES_DIR} does not exist"})
    files = [f.stem for f in sorted(TEMPLATES_DIR.glob("*.docx"))]
    return jsonify({"templates": files})


@app.route("/generate", methods=["POST"])
def generate():
    check_auth()

    body = request.get_json(force=True, silent=True)
    if isinstance(body, str):
        try:
            # Strip leading = that n8n sometimes prepends to expressions
            cleaned = body.lstrip('=').strip()
            body = json.loads(cleaned)
        except json.JSONDecodeError:
            body = None
    if not body:
        return jsonify({"status": "error", "message": "Request body must be JSON"}), 400

    # ── Validate required fields ──────────────────────────────────────────────
    template_name = body.get("template")
    bullets       = body.get("bullets")
    job_id        = body.get("resume_filename", body.get("job_id", "job"))
    export_pdf    = body.get("pdf", True)

    if not template_name:
        return jsonify({"status": "error", "message": "Missing required field: template"}), 400
    if not bullets:
        return jsonify({"status": "error", "message": "Missing required field: bullets"}), 400
    if not isinstance(bullets, list):
        return jsonify({"status": "error", "message": "bullets must be a JSON array"}), 400

    # ── Resolve template path ─────────────────────────────────────────────────
    # Accept "MeridianLink" or "MeridianLink.docx"
    template_stem = Path(template_name).stem
    template_path = TEMPLATES_DIR / f"{template_stem}.docx"
    if not template_path.exists():
        available = [f.stem for f in TEMPLATES_DIR.glob("*.docx")] if TEMPLATES_DIR.exists() else []
        return jsonify({
            "status": "error",
            "message": f"Template '{template_stem}.docx' not found in {TEMPLATES_DIR}",
            "available_templates": available
        }), 404

    # ── Sanitize job_id for use in filenames ──────────────────────────────────
    safe_id = "".join(c for c in str(job_id) if c.isalnum() or c in "-_")[:40]
    output_stem = f"{safe_id}_{template_stem}"

    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    output_docx = OUTPUTS_DIR / f"{output_stem}.docx"

    # ── Write bullets to a temp file and call the script ─────────────────────
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json",
                                     delete=False, encoding="utf-8") as tmp:
        json.dump(bullets, tmp)
        bullets_path = tmp.name

    try:
        cmd = [
            sys.executable, str(SCRIPT_PATH),
            "--template", str(template_path),
            "--bullets",  bullets_path,
            "--output",   str(output_docx),
        ]
        if export_pdf:
            cmd.append("--pdf")

        result = subprocess.run(cmd, capture_output=True, text=True)

        # Script always writes JSON to stdout
        stdout_text = result.stdout.strip()
        if not stdout_text:
            return jsonify({
                "status": "error",
                "message": "Script produced no output",
                "stderr": result.stderr[:2000]
            }), 500

        try:
            script_output = json.loads(stdout_text)
        except json.JSONDecodeError:
            return jsonify({
                "status": "error",
                "message": "Script output was not valid JSON",
                "raw_stdout": stdout_text[:2000],
                "stderr": result.stderr[:2000]
            }), 500

        if result.returncode != 0:
            # Script exited non-zero — return its error JSON as-is
            return jsonify(script_output), 422

        # ── Build response with URL paths ──────────────────────────────────
        response = {
            "status": script_output.get("status", "success"),
            "docx_path": str(output_docx),
            "docx_url": f"/outputs/{output_docx.name}",
            "pdf_path": script_output.get("output_pdf"),
            "pdf_url": f"/outputs/{output_stem}.pdf" if export_pdf and script_output.get("output_pdf") else None,
            "bullets_replaced": script_output.get("bullets_replaced", 0),
            "bullets_not_found": script_output.get("bullets_not_found", 0),
            "changelog": script_output.get("changelog", []),
        }
        if script_output.get("warnings"):
            response["warnings"] = script_output["warnings"]

        return jsonify(response), 200

    finally:
        os.unlink(bullets_path)


@app.route("/outputs/<path:filename>", methods=["GET"])
def download_output(filename):
    """Download a generated file by name. n8n can use this URL to retrieve the file."""
    check_auth()
    return send_from_directory(str(OUTPUTS_DIR), filename)


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    app.run(host="0.0.0.0", port=port, debug=False)
