# Security Notes

This project should not require committed credentials or local runtime output.

Do not commit:

- API keys
- browser/session credentials
- `.env` files
- local virtual environments
- generated crawl reports
- logs or database files
- local downloaded datasets

If a secret is accidentally published, rotate it and remove it from git history before making the repository public.
