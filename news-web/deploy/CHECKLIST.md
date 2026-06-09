# First Deployment Checklist

1. [ ] Install Python 3.11+ and Node.js 20+
2. [ ] Clone repo to /opt/news-web (or user home)
3. [ ] Create venv: `python -m venv /opt/news-web/venv`
4. [ ] Copy config.json.example → config.json, fill in db_path and openai_* values
5. [ ] Ensure SQLite DB at configured db_path exists (or will be created by pipeline)
6. [ ] Run `chmod +x run_prod.sh && ./run_prod.sh` (or install service file)
7. [ ] Verify: `curl http://localhost:8080/api/health`
8. [ ] Open browser → Dashboard should show stats
9. [ ] Test manual pipeline: curl -X POST http://localhost:8080/api/pipeline/run
10. [ ] Check backup dir for daily SQLite backups
