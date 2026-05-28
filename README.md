# resume-service — Railway Deployment Guide

Flask HTTP wrapper around `generate_resume.py`. Receives bullet arrays from n8n, returns `.docx` + `.pdf` paths.

---

## Files in this repo

```
resume-service/
├── app.py               ← Flask wrapper (the new file)
├── generate_resume.py   ← Core generation script (copy from project outputs)
├── Dockerfile
├── requirements.txt
├── railway.toml
└── templates/           ← Upload your .docx templates here (or via Railway volume)
    └── MeridianLink.docx
```

---

## Step 1 — Create the GitHub repo

```bash
# From your local machine
mkdir resume-service && cd resume-service
# Copy app.py, generate_resume.py, Dockerfile, requirements.txt, railway.toml here
# Copy Joe_Frank_-_2026_Resume_-_MeridianLink.docx → templates/MeridianLink.docx

git init
git add .
git commit -m "initial resume service"
gh repo create resume-service --private --source=. --push
# (or: git remote add origin https://github.com/YOUR_USER/resume-service && git push)
```

---

## Step 2 — Deploy to Railway

1. Go to https://railway.com/project/efd5cacf-d3a2-4f6d-9a56-4121cf90fae3
2. Click **+ New** → **GitHub Repo** → select `resume-service`
3. Railway detects the Dockerfile automatically
4. Under **Settings → Networking**, click **Generate Domain** — you'll get a URL like `resume-service-production-XXXX.up.railway.app`

---

## Step 3 — Set environment variables (Railway → Variables tab)

| Variable | Value |
|---|---|
| `AUTH_TOKEN` | Generate a random string: `openssl rand -hex 24` — save this, you'll put it in n8n too |
| `TEMPLATES_DIR` | `/app/templates` (default, can leave unset) |
| `OUTPUTS_DIR` | `/app/outputs` (default, can leave unset) |

**Note on templates persistence:** Railway's filesystem is ephemeral — outputs will be lost on redeploy. For now this is fine because:
- n8n reads the `docx_url` path immediately after generation and stores it in Airtable
- The `docx_path` and `pdf_path` fields in Airtable record the full path
- Long-term: add a Railway Volume (Settings → Volumes) mounted at `/app/outputs` for persistence

---

## Step 4 — Upload the MeridianLink template

The template file is binary, so it lives in the repo (or a Railway Volume). Easiest path:

```bash
# In your local resume-service folder, before pushing to GitHub:
cp /path/to/Joe_Frank_-_2026_Resume_-_MeridianLink.docx templates/MeridianLink.docx
git add templates/MeridianLink.docx
git commit -m "add MeridianLink template"
git push
```

Railway will redeploy automatically. Verify with:
```
GET https://resume-service-production-XXXX.up.railway.app/templates
Headers: Authorization: Bearer <AUTH_TOKEN>
```
Should return: `{"templates": ["MeridianLink"]}`

---

## Step 5 — Test the endpoint directly

```bash
curl -X POST https://resume-service-production-XXXX.up.railway.app/generate \
  -H "Authorization: Bearer YOUR_AUTH_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "template": "MeridianLink",
    "job_id": "recTEST001",
    "pdf": true,
    "bullets": [
      {
        "role": "Platform Services Product Manager",
        "bullet_number": 1,
        "changed": false,
        "before": "Lead product vision...",
        "after": null
      },
      {
        "role": "Platform Services Product Manager",
        "bullet_number": 2,
        "changed": true,
        "before": "Own platform services and REST APIs processing 200M+ calls/month",
        "after": "Scaled REST API platform to 200M+ calls/month across 40+ integration points"
      }
    ]
  }'
```

Expected response:
```json
{
  "status": "success",
  "docx_url": "/outputs/recTEST001_MeridianLink.docx",
  "pdf_url":  "/outputs/recTEST001_MeridianLink.pdf",
  "bullets_replaced": 1,
  "bullets_not_found": 0,
  "changelog": [...]
}
```

---

## Step 6 — Wire into n8n

### Add this node after "Parse Rewriter Output" in the manual intake workflow:

**Node type:** HTTP Request  
**Name:** Generate Resume Document  
**Method:** POST  
**URL:** `https://resume-service-production-XXXX.up.railway.app/generate`

**Headers:**
```
Authorization: Bearer {{ $env.RESUME_SERVICE_TOKEN }}
Content-Type: application/json
```

Add `RESUME_SERVICE_TOKEN` to Railway Primary env vars (same value as `AUTH_TOKEN` in resume service).

**Body (JSON):**
```json
{
  "template": "={{ $json.resume_version || 'MeridianLink' }}",
  "job_id": "={{ $json.airtable_record_id }}",
  "pdf": true,
  "bullets": "={{ $json.bullets }}"
}
```

**Response mapping** — pass these into the Prepare Airtable Record node:
- `docx_path` → `{{ $json.docx_url }}`
- `pdf_path`  → `{{ $json.pdf_url }}`

### Connection in the workflow:
```
Parse Rewriter Output
  → Generate Resume Document    ← NEW NODE
  → Merge1 (Input 1)
```

---

## Reconnecting the Rewriter (do this same session)

Once the service is deployed, the Rewriter in n8n can be fully reconnected:

```
Recommendation Route (rewrite branch)
  → Airtable: Get Template Bullets   ← fetch resume_templates table by resume_version
  → Anthropic Rewrite
  → Parse Rewriter Output
  → Generate Resume Document          ← calls this service
  → Merge1
      Input 1: Generate Resume Document output
      Input 2: Recommendation Route (rewrite branch)
  → Prepare Airtable Record
  → Create a record (Airtable)
```

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| `/health` returns 502 | Build failed — check Railway deploy logs for Python/apt errors |
| `/templates` returns empty array | Template file not in `templates/` in the repo — re-push |
| `bullets_not_found > 0` | "before" text in bullets doesn't exactly match template XML text — check whitespace |
| PDF export times out | LibreOffice cold start is slow (~15s). Raise Gunicorn `--timeout` to `180` in Dockerfile CMD |
| 401 on every request | AUTH_TOKEN mismatch — re-check Railway env var vs n8n header |
