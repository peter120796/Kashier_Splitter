"""
Settlement PDF Splitter — Vercel serverless entrypoint.

Key differences from the OKD/Flask-server version:
  * The ONLY writable directory on Vercel is /tmp. All uploads/outputs go there.
  * No status/*.json polling and no hidden iframe. /upload is SYNCHRONOUS:
    receive PDF -> split in /tmp -> upload output.zip to MinIO -> return a
    presigned download URL as JSON. The big ZIP never passes back through the
    function, so the 4.5 MB response cap is irrelevant.
  * Frontend downloads the ZIP straight from MinIO via the presigned URL.

Entrypoint: Vercel loads the `app` WSGI variable from this file.
"""
import os
import sys
import uuid
import logging
import traceback
from datetime import datetime

from flask import Flask, render_template, request, jsonify, send_file

# splitter.py and storage.py live next to this file (inside api/)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from splitter import split_pdf_file
import storage

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app = Flask(
    __name__,
    template_folder=os.path.join(BASE_DIR, "templates"),
    static_folder=None,            # static assets are served from /public via Vercel CDN
)
app.secret_key = "kashier-secret-key"

# Fail cleanly instead of OOM/413 deep in the stack. Vercel's hard platform cap
# is 4.5 MB on the request body anyway; we guard slightly under it.
app.config["MAX_CONTENT_LENGTH"] = 4 * 1024 * 1024  # 4 MB

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    stream=sys.stdout,
    force=True,
)
logger = logging.getLogger("kashier_splitter")


def log(msg, *args):
    logger.info(msg, *args)
    sys.stdout.flush()


# Only /tmp is writable on Vercel.
TMP_ROOT = "/tmp/kashier"
UPLOAD_FOLDER = os.path.join(TMP_ROOT, "uploads")
OUTPUT_FOLDER = os.path.join(TMP_ROOT, "outputs")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(OUTPUT_FOLDER, exist_ok=True)


@app.errorhandler(413)
def too_large(e):
    log("!!! 413 REQUEST ENTITY TOO LARGE — Content-Length=%s", request.content_length)
    return jsonify({
        "ok": False,
        "error": "PDF is larger than the 4 MB upload limit on this platform. "
                 "Split it into smaller files, or deploy on a host without the cap."
    }), 413


@app.route("/", methods=["GET"])
def home():
    return render_template("index.html",
                           storage_enabled=storage.is_enabled())


@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "ok": True,
        "storage": "minio" if storage.is_enabled() else "local-fallback",
        "writable_tmp": os.access(TMP_ROOT, os.W_OK),
    })


@app.route("/upload", methods=["POST"])
def upload_pdf():
    """Synchronous: split -> push ZIP to MinIO -> return presigned URL."""
    log("=== /upload reached ===")

    if "pdf_file" not in request.files:
        return jsonify({"ok": False, "error": "No file uploaded"}), 400

    file = request.files["pdf_file"]
    if not file.filename:
        return jsonify({"ok": False, "error": "Please select a PDF file"}), 400
    if not file.filename.lower().endswith(".pdf"):
        return jsonify({"ok": False, "error": "Only PDF files are allowed"}), 400

    unique_id = str(uuid.uuid4())
    upload_path = os.path.join(UPLOAD_FOLDER, f"{unique_id}.pdf")
    output_path = os.path.join(OUTPUT_FOLDER, unique_id)
    os.makedirs(output_path, exist_ok=True)

    try:
        file.save(upload_path)
        saved_bytes = os.path.getsize(upload_path)
        log("Saved upload: %s (%.2f MB)", file.filename, saved_bytes / 1024 / 1024)

        log("Splitting...")
        zip_path = split_pdf_file(upload_path, output_path)
        if not zip_path or not os.path.exists(zip_path):
            return jsonify({"ok": False, "error": "Split finished but ZIP was not created."}), 500

        zip_size = os.path.getsize(zip_path)
        # count produced PDFs (exclude the audit csv and the zip itself)
        produced = sum(
            1 for root, _, files in os.walk(output_path)
            for f in files if f.lower().endswith(".pdf")
        )
        log("Split OK: %d PDFs, zip=%.2f MB", produced, zip_size / 1024 / 1024)

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        base = os.path.splitext(os.path.basename(file.filename))[0]
        saved_name = f"{ts}_{base}.zip"

        # Push the big ZIP to MinIO and hand back a presigned URL.
        if storage.is_enabled():
            obj = storage.upload_file(zip_path, saved_name, content_type="application/zip")
            if not obj:
                return jsonify({"ok": False, "error": "Upload to storage failed."}), 502
            url = storage.presigned_url(obj)
            if not url:
                return jsonify({"ok": False, "error": "Could not create download link."}), 502
            log("MinIO URL ready: %s", url)
            return jsonify({
                "ok": True, "count": produced, "filename": saved_name,
                "download_url": url, "via": "minio",
            })

        # Local fallback (for `vercel dev` / local testing without MinIO):
        # stash the zip path and serve it via /download so the flow still works.
        local_token = unique_id
        with open(os.path.join(TMP_ROOT, f"{local_token}.zippath"), "w") as f:
            f.write(zip_path)
        return jsonify({
            "ok": True, "count": produced, "filename": saved_name,
            "download_url": f"/download/{local_token}", "via": "local",
        })

    except Exception as e:
        log("UPLOAD FAILED: %s\n%s", e, traceback.format_exc())
        return jsonify({"ok": False, "error": f"Processing failed: {e}"}), 500


@app.route("/download/<token>", methods=["GET"])
def download_local(token):
    """Local-fallback download only. On Vercel with MinIO this is never used."""
    safe = os.path.basename(token)
    ptr = os.path.join(TMP_ROOT, f"{safe}.zippath")
    if not os.path.exists(ptr):
        return jsonify({"error": "not found or expired"}), 404
    with open(ptr) as f:
        zip_path = f.read().strip()
    if not os.path.exists(zip_path):
        return jsonify({"error": "expired"}), 404
    return send_file(zip_path, as_attachment=True,
                     download_name="Kashier_Settlement_Output.zip",
                     mimetype="application/zip")


# Local dev convenience (not used by Vercel).
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=True)
