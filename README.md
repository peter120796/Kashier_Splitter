# Settlement PDF Splitter — Vercel

Serverless build of the Kashier ACH settlement splitter. Splits one multi-page
settlement PDF into one PDF per MID and returns a ZIP via a presigned MinIO link.

## How it differs from the OKD/Flask-server build
- Runs as a single Vercel Python function (Flask WSGI app at `api/index.py`).
- Only `/tmp` is writable, so uploads/outputs are processed there.
- `/upload` is synchronous: split -> push ZIP to MinIO -> return presigned URL.
  No status-file polling, no hidden iframe. The big ZIP never passes back
  through the function, so Vercel's 4.5 MB response cap is avoided.
- Input PDF goes through the function normally (must be < 4 MB; platform cap).

## Deploy
1. Push this folder to GitHub/GitLab.
2. Vercel dashboard -> New Project -> import the repo. It auto-detects Flask.
3. Add Environment Variables (Settings -> Environment Variables):
       MINIO_URL          = https://static.kashier.io   (must be reachable from Vercel)
       MINIO_ACCESS_KEY   = ...
       MINIO_SECRET_KEY   = ...
       MINIO_BUCKET_NAME  = settlement-pdf-splitter
4. Deploy. Visit the URL, upload a PDF, get the ZIP from the MinIO link.

## Notes
- `vercel.json` sets maxDuration=60 (Hobby ceiling). On Pro, raise to 300 for
  bigger/slower splits.
- Without MinIO env vars the app still runs and serves the ZIP via a local
  `/download/<token>` route (handy for `vercel dev`), but on Vercel that file is
  ephemeral — set MinIO for real use.
- Check `/health` after deploy to confirm storage = "minio".
