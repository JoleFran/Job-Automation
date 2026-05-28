#!/usr/bin/env python3
"""
generate_resume.py — Resume document generation script (self-contained, no external scripts)
Joe Frank Job Search Pipeline — Railway deployment
"""

import argparse
import json
import os
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

EM_DASH = "\u2014"


def validate_inputs(template_path, bullets_path):
    if not Path(template_path).exists():
        print(f"ERROR: Template file not found: {template_path}", file=sys.stderr)
        sys.exit(1)
    if not Path(bullets_path).exists():
        print(f"ERROR: Bullets JSON file not found: {bullets_path}", file=sys.stderr)
        sys.exit(1)
    with open(bullets_path) as f:
        try:
            bullets = json.load(f)
        except json.JSONDecodeError as e:
            print(f"ERROR: Invalid JSON in bullets file: {e}", file=sys.stderr)
            sys.exit(1)
    return bullets


def check_em_dashes(bullets):
    violations = []
    for b in bullets:
        if b.get("changed") and b.get("after"):
            if EM_DASH in b["after"]:
                violations.append({
                    "bullet_number": b["bullet_number"],
                    "role": b["role"],
                    "violation": "em dash found in rewritten bullet"
                })
    return violations


def unpack_docx(docx_path, unpack_dir):
    """Unzip the .docx into unpack_dir."""
    with zipfile.ZipFile(docx_path, 'r') as z:
        z.extractall(unpack_dir)


def pack_docx(unpack_dir, output_path, original_docx):
    """
    Repack unpack_dir into a .docx at output_path.
    Preserves the original zip structure and compression.
    """
    output_path = str(output_path)
    # Read original zip to preserve compression types per-member
    original_members = {}
    with zipfile.ZipFile(original_docx, 'r') as orig:
        for info in orig.infolist():
            original_members[info.filename] = info.compress_type

    with zipfile.ZipFile(output_path, 'w') as zout:
        for root, dirs, files in os.walk(unpack_dir):
            for file in files:
                file_path = os.path.join(root, file)
                arcname = os.path.relpath(file_path, unpack_dir)
                compress = original_members.get(arcname, zipfile.ZIP_DEFLATED)
                zout.write(file_path, arcname, compress_type=compress)


def replace_bullets(doc_xml, bullets):
    changelog = []
    content = doc_xml
    changed_bullets = [b for b in bullets if b.get("changed") and b.get("after")]

    for bullet in changed_bullets:
        before_text = bullet["before"].strip()
        after_text = bullet["after"].strip()

        if before_text in content:
            content = content.replace(before_text, after_text, 1)
            changelog.append({
                "role": bullet["role"],
                "bullet_number": bullet["bullet_number"],
                "status": "replaced",
                "before_snippet": before_text[:80] + ("..." if len(before_text) > 80 else ""),
                "after_snippet": after_text[:80] + ("..." if len(after_text) > 80 else "")
            })
        else:
            changelog.append({
                "role": bullet["role"],
                "bullet_number": bullet["bullet_number"],
                "status": "not_found",
                "note": "Original text not found in document. Template may be out of sync.",
                "before_snippet": before_text[:80] + ("..." if len(before_text) > 80 else "")
            })

    return content, changelog


def generate(template_path, bullets_path, output_path, export_pdf=False):
    bullets = validate_inputs(template_path, bullets_path)

    em_violations = check_em_dashes(bullets)
    if em_violations:
        print(json.dumps({
            "status": "error",
            "error": "em_dash_violation",
            "message": "Rewritten bullets contain em dashes.",
            "violations": em_violations
        }, indent=2))
        sys.exit(1)

    with tempfile.TemporaryDirectory() as tmp_dir:
        unpack_dir = os.path.join(tmp_dir, "unpacked")
        os.makedirs(unpack_dir)

        # Unpack
        unpack_docx(template_path, unpack_dir)

        # Read document.xml
        doc_xml_path = os.path.join(unpack_dir, "word", "document.xml")
        with open(doc_xml_path, "r", encoding="utf-8") as f:
            doc_xml = f.read()

        # Replace bullets
        modified_xml, changelog = replace_bullets(doc_xml, bullets)

        # Write modified document.xml
        with open(doc_xml_path, "w", encoding="utf-8") as f:
            f.write(modified_xml)

        # Repack
        pack_docx(unpack_dir, output_path, template_path)

        # Optional PDF export via LibreOffice
        pdf_path = None
        if export_pdf:
            import subprocess
            output_dir = str(Path(output_path).parent)
            result = subprocess.run(
                ["libreoffice", "--headless", "--convert-to", "pdf",
                 "--outdir", output_dir, str(output_path)],
                capture_output=True, text=True
            )
            if result.returncode == 0:
                pdf_path = str(Path(output_path).with_suffix(".pdf"))

        not_found = [c for c in changelog if c["status"] == "not_found"]
        replaced  = [c for c in changelog if c["status"] == "replaced"]

        result = {
            "status": "success",
            "output_docx": str(output_path),
            "output_pdf": pdf_path,
            "bullets_replaced": len(replaced),
            "bullets_not_found": len(not_found),
            "changelog": changelog
        }

        if not_found:
            result["warnings"] = [
                f"Bullet {c['bullet_number']} in '{c['role']}' not found in template."
                for c in not_found
            ]

        print(json.dumps(result, indent=2))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--template", required=True)
    parser.add_argument("--bullets",  required=True)
    parser.add_argument("--output",   required=True)
    parser.add_argument("--pdf", action="store_true")
    args = parser.parse_args()
    generate(args.template, args.bullets, args.output, args.pdf)


if __name__ == "__main__":
    main()
