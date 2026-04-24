# 🚀 Petty Cash - Production Deployment Guide

This document contains the exact commands to safely pull the latest code from GitHub and restart your live VPS server backend for **Petty Cash** (`cashora.nxsys.in`).

> **Crucial Difference from Eskoolia/NxGen:** Petty Cash is a **FastAPI** application running on a supercharged `uvicorn` engine. It relies entirely on a **Cloud PostgreSQL Database** managed by Alembic, meaning you will *never* see `db.sqlite3` Git conflicts again!

---

## ☁️ Safely Refresh the Server
To deploy any API changes you make locally, simply push them to GitHub, and then run this sequence of commands on the VPS:

```bash
cd /var/www/petty-cash
git pull --no-edit
```

```bash
# 1. Enter the virtual environment
source venv/bin/activate

# 2. Install any newly added python modules
pip install -r requirements.txt

# 3. Securely apply any new database tables to your Neon Cloud database
alembic upgrade head

# 4. Restart the background FastAPI Engine!
sudo systemctl restart uvicorn-pettycash
```

---

> [!TIP]
> **View Live Logs**
> If the Petty Cash API ever crashes or your App gets a 500 error, view the live output of the fastAPI engine here:
> `sudo journalctl -u uvicorn-pettycash.service -f`
