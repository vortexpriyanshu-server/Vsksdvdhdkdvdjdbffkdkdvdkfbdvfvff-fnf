# PRIYANSHU API CLOUD — VORTEX

Lightweight FastAPI API marketplace starter with a premium red/white/black UI and admin-only control panel.

## Run
`pip install -r requirements.txt`
`export ADMIN_PASSWORD='your-password'`
`uvicorn main:app --reload`

Open `/` and `/admin`.

## Notes
- Configure secrets through environment variables.
- Firebase entries are management records for legitimate integrations; do not store private service-account credentials in the browser or repository.
- This starter intentionally does not include bulk-SMS/bomber functionality.
