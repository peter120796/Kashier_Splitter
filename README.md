# Settlement PDF Splitter — Vercel (Flask preset)

Root `app.py` is the Flask entrypoint. Vercel's Flask preset auto-detects it and
routes all traffic to it — no vercel.json needed.

Splits one ACH settlement PDF into one PDF per MID, pushes the ZIP to MinIO,
and returns a presigned download link (the big ZIP never passes back through the
function, so Vercel's 4.5 MB response cap is avoided). Input PDF must be < 4 MB.

## Deploy
1. Repo must contain ONLY: app.py, splitter.py, storage.py, templates/,
   public/, requirements.txt, .python-version, README.md, .gitignore.
   (Remove any old app server, render.yaml, Procfile, root static/, __pycache__.)
2. Vercel -> New Project -> import repo. Preset = Flask (auto).
3. Environment Variables:
       MINIO_URL          = https://static.kashier.io
       MINIO_ACCESS_KEY   = ...
       MINIO_SECRET_KEY   = ...
       MINIO_BUCKET_NAME  = settlement-pdf-splitter
4. Deploy, then open /health -> expect {"storage": "minio"}.

## Notes
- Hobby caps function runtime at 60s. For bigger/slower splits, move to Pro and
  add a vercel.json with { "functions": { "app.py": { "maxDuration": 300 } } }.
- Without MinIO env vars the app still runs and serves via /download/<token>,
  but that file is ephemeral on Vercel — set MinIO for real use.
