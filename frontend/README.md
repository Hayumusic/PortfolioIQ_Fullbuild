# Portfolio IQ frontend

This folder contains the Next.js and TypeScript frontend for Portfolio IQ. The
Uploads, Dashboard, and Validation sections are aligned to the selected sections
of the original App Analyser MVP. The UI keeps persistent job selection, live
backend health, upload status, validation results, and CSV downloads. It does
not contain sample analysis data or call OpenAI.

## Run locally

Start the backend from the repository root:

```bash
python3 -m uvicorn app.main:app --app-dir backend --reload --host 127.0.0.1 --port 8000
```

In another terminal, start the frontend:

```bash
cd frontend
cp .env.example .env.local
npm install
npm run dev
```

Open `http://localhost:3000`. The default API base URL is
`http://127.0.0.1:8000`. Override it in `.env.local` when needed:

```env
NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000
```

Do not commit `.env.local` or secrets. The browser stores the selected job ID in
local storage under `portfolio-iq-current-job-id`.

## MVP-aligned scope

- Lightweight Dashboard landing page with live `GET /health`, current job,
  required-input readiness, and the MVP module flow
- Persistent job selection and backend-backed job creation
- Uploads for CMDB, mandatory-fields configuration, output-family
  configuration, team validation, CloudWatch, and multiple Confluence PDFs
- Live upload readiness on both Dashboard and Input Uploads from
  `GET /api/jobs/{job_id}/uploads/status`
- Separate select-and-upload controls with backend response and error messages
- Working CMDB Validation page with mandatory-field mapping, explicitly defined
  mandatory CMDB field completeness, paginated application details, validation
  issues, supporting-evidence labels, Team Validation checks, configured output
  families, and the backend completeness CSV download
- Foundation pages for Similarity, Technology, Output Families, and Portfolio
  Insights

The required job inputs are the CMDB, mandatory-fields config, and output-family
config. The CMDB remains the source of truth. Team Validation, CloudWatch, and
Confluence files are optional supporting evidence only. Mandatory CMDB field
completeness is calculated as populated mandatory-field cells divided by total
mandatory-field cells, using the uploaded mandatory-fields configuration. A
backend fallback/default config is labelled as such and is not presented as a
job upload. The analysis pages deliberately contain no fabricated results.

## Manual test flow

1. Start the backend and confirm `http://127.0.0.1:8000/health` is healthy.
2. Start the frontend and open `http://localhost:3000`.
3. Open **Dashboard** and confirm the live backend health, current job,
   required-input readiness, and MVP module flow.
4. Select **New Job**, or paste a known job ID and select **Use**.
5. Open **Uploads** and confirm the current job and upload readiness panel load.
6. Select a real CMDB workbook, choose **Upload selected file**, and confirm the
   success text is the backend response and the latest filename appears.
7. Upload mandatory-fields and output-family configuration files. Confirm all
   three are labelled **Uploaded for this job** and both readiness checks change
   to **Yes**.
8. Optionally upload Team Validation, CloudWatch, and one or more Confluence PDF
   files. Confluence sends all selected PDFs under the multipart `files` field.
9. Confirm **Load and validate inputs** is available only when all required
   inputs have been uploaded for this job.
10. Open **Validation**, then select **Load and validate inputs**.
11. Confirm the MVP section order: field mapping, completeness by application,
    issues, CMDB source/supporting evidence, Team Validation checks, and output
    families. Confirm Application Code is the first identifier and the CMDB CSV
    download is available.
12. Use a job with a backend-global mandatory config but no job config and
    confirm it says **Backend fallback/default config** while validation remains
    not ready.
13. With a job missing any required upload, confirm the page says **Required
    inputs are not loaded yet.** and does not enable validation.

## Checks

```bash
npm run typecheck
npm run build
```

No lint command is currently configured; the strict TypeScript check and
production Next.js build are the available automated frontend checks.
