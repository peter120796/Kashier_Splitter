import csv
import os
import re
import shutil
import tempfile
import zipfile
from collections import defaultdict
from pypdf import PdfReader, PdfWriter

MID_PATTERN = re.compile(r'MID-\d+-\d+')


def extract_mid(text):
    matches = MID_PATTERN.findall(text)
    return matches[0] if matches else None


def create_zip(folder_path, zip_path):
    """
    Build the zip in a TEMP location OUTSIDE folder_path, then move it in.
    This avoids the classic bug where os.walk sees the zip being written
    into the same folder it is walking and tries to add the zip to itself
    (which hangs or corrupts the archive on some systems).
    """
    tmp_fd, tmp_zip = tempfile.mkstemp(suffix=".zip")
    os.close(tmp_fd)
    try:
        with zipfile.ZipFile(tmp_zip, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for root, dirs, files in os.walk(folder_path):
                for file in files:
                    # Never add a stray zip into the archive
                    if file.lower().endswith(".zip"):
                        continue
                    full_path = os.path.join(root, file)
                    arcname = os.path.relpath(full_path, folder_path)
                    zipf.write(full_path, arcname)
        shutil.move(tmp_zip, zip_path)
    finally:
        if os.path.exists(tmp_zip):
            os.remove(tmp_zip)


def clean_filename(name):
    """Make a string safe to use as a filename."""
    name = name.replace("/", "-").replace("\\", "-")
    name = re.sub(r'\s+', '_', name)
    name = re.sub(r'_+', '_', name)
    return name.strip("_")


def split_pdf_file(input_pdf, output_dir):
    os.makedirs(output_dir, exist_ok=True)
    unmatched_dir = os.path.join(output_dir, "_unmatched")
    os.makedirs(unmatched_dir, exist_ok=True)

    reader = PdfReader(input_pdf)
    total_pages = len(reader.pages)

    mid_counts = defaultdict(int)
    audit_rows = []

    for i, page in enumerate(reader.pages, start=1):
        try:
            text = page.extract_text() or ""
        except Exception:
            text = ""

        mid = extract_mid(text)

        writer = PdfWriter()
        writer.add_page(page)

        if mid is None:
            filename = f"page_{i:04d}.pdf"
            out_path = os.path.join(unmatched_dir, filename)
            with open(out_path, "wb") as f:
                writer.write(f)
            audit_rows.append({
                "page": i, "mid": "", "output_file": f"_unmatched/{filename}",
                "result": "no_mid"
            })
            continue

        mid_counts[mid] += 1
        if mid_counts[mid] == 1:
            filename = f"{clean_filename(mid)}.pdf"
        else:
            filename = f"{clean_filename(mid)}_{mid_counts[mid]}.pdf"

        out_path = os.path.join(output_dir, filename)
        with open(out_path, "wb") as f:
            writer.write(f)

        audit_rows.append({
            "page": i, "mid": mid, "output_file": filename, "result": "ok"
        })

    # Write audit CSV
    audit_path = os.path.join(output_dir, "_audit.csv")
    with open(audit_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["page", "mid", "output_file", "result"])
        writer.writeheader()
        writer.writerows(audit_rows)

    # Build the zip (safe temp-then-move method)
    zip_path = os.path.join(output_dir, "output.zip")
    create_zip(output_dir, zip_path)

    return zip_path
