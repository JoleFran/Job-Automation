#!/usr/bin/env python3
"""
generate_resume.py — Resume document generation script
Joe Frank Job Search Pipeline

Usage:
    python3 generate_resume.py --template <path_to_template.docx> \
                               --bullets <path_to_bullets.json> \
                               --output <path_to_output.docx> \
                               [--pdf]

Arguments:
    --template   Path to the master .docx template file for the selected resume version
    --bullets    Path to JSON file containing the rewriter output bullets array
    --output     Path for the generated .docx output file
    --pdf        Optional flag: also export a .pdf alongside the .docx

Input JSON format (bullets array from Rewriter prompt output):
[
  {
    "role": "Platform Services Product Manager",
    "bullet_number": 1,
    "changed": false,
    "before": "Original bullet text...",
    "after": null
  },
  {
    "role": "Platform Services Product Manager",
    "bullet_number": 2,
    "changed": true,
    "before": "Original bullet text...",
    "after": "Rewritten bullet text..."
  }
]

How it works:
    1. Unpacks the template .docx to a temp directory
    2. Reads document.xml and replaces bullet text for changed bullets
    3. Repacks to a new .docx file
    4. Optionally converts to PDF via LibreOffice
    5. Writes a changelog to stdout as JSON

Rules enforced:
    - Only replaces bullet text that matches the "before" string exactly
    - Never touches the header (floating drawing group)
    - Never modifies unchanged bullets
    - Reports any bullet where the "before" text was not found
    - Rejects output containing em dashes
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPTS_DIR = Path("/mnt/skills/public/docx/scripts/office")
UNPACK_SCRIPT = SCRIPTS_DIR / "unpack.py"
PACK_SCRIPT = SCRIPTS_DIR / "pack.py"
SOFFICE_SCRIPT = SCRIPTS_DIR / "soffice.py"

EM_DASH = "\u2014"


def run(cmd, check=True):
    result = subprocess.run(cmd, capture_output=True, text=True)
    if check and result.returncode != 0:
        print(f"ERROR running {' '.join(str(c) for c in cmd)}", file=sys.stderr)
        print(result.stderr, file=sys.stderr)
        sys.exit(1)
    return result


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


def replace_bullets(doc_xml, bullets):
    """
    Perform surgical text replacement for each changed bullet.
    Matches on the full 'before' text string and replaces with 'after'.
    Returns (modified_xml, changelog).
    """
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
            # Before text not found — may be already modified or mismatch
            changelog.append({
                "role": bullet["role"],
                "bullet_number": bullet["bullet_number"],
                "status": "not_found",
                "note": "Original text not found in document. Template may be out of sync with bullet data.",
                "before_snippet": before_text[:80] + ("..." if len(before_text) > 80 else "")
            })

    return content, changelog


def generate(template_path, bullets_path, output_path, export_pdf=False):
    bullets = validate_inputs(template_path, bullets_path)

    # Em dash check before touching any files
    em_violations = check_em_dashes(bullets)
    if em_violations:
        print(json.dumps({
            "status": "error",
            "error": "em_dash_violation",
            "message": "Rewritten bullets contain em dashes. Correct before generating document.",
            "violations": em_violations
        }, indent=2))
        sys.exit(1)

    with tempfile.TemporaryDirectory() as tmp_dir:
        unpack_dir = os.path.join(tmp_dir, "unpacked")

        # Step 1: Unpack template
        run(["python3", str(UNPACK_SCRIPT), template_path, unpack_dir])

        # Step 2: Read document.xml
        doc_xml_path = os.path.join(unpack_dir, "word", "document.xml")
        with open(doc_xml_path, "r", encoding="utf-8") as f:
            doc_xml = f.read()

        # Step 3: Replace bullet text
        modified_xml, changelog = replace_bullets(doc_xml, bullets)

        # Step 4: Write modified document.xml
        with open(doc_xml_path, "w", encoding="utf-8") as f:
            f.write(modified_xml)

        # Step 5: Repack to output .docx
        run(["python3", str(PACK_SCRIPT), unpack_dir, output_path,
             "--original", template_path])

        # Step 6: Optional PDF export
        pdf_path = None
        if export_pdf:
            output_dir = str(Path(output_path).parent)
            run(["python3", str(SOFFICE_SCRIPT), "--headless",
                 "--convert-to", "pdf", "--outdir", output_dir, output_path])
            pdf_path = str(Path(output_path).with_suffix(".pdf"))

        # Step 7: Report
        not_found = [c for c in changelog if c["status"] == "not_found"]
        replaced = [c for c in changelog if c["status"] == "replaced"]

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
                f"Bullet {c['bullet_number']} in '{c['role']}' not found in template. "
                f"Manual review required."
                for c in not_found
            ]

        print(json.dumps(result, indent=2))


def main():
    parser = argparse.ArgumentParser(
        description="Generate optimized resume .docx from template and rewriter output"
    )
    parser.add_argument("--template", required=True,
                        help="Path to master .docx template file")
    parser.add_argument("--bullets", required=True,
                        help="Path to JSON file with rewriter bullets array")
    parser.add_argument("--output", required=True,
                        help="Output path for generated .docx")
    parser.add_argument("--pdf", action="store_true",
                        help="Also export PDF alongside .docx")
    args = parser.parse_args()

    generate(
        template_path=args.template,
        bullets_path=args.bullets,
        output_path=args.output,
        export_pdf=args.pdf
    )


if __name__ == "__main__":
    main()
