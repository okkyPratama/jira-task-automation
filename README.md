# Jira Support Task Automation

Automatically transitions Jira SUPPORT tasks at specific times throughout
the workday to achieve exactly **8 hours** of tracked working time.

## Business Logic

| Time | From Status | Transition | To Status | Effect |
|------|-------------|------------|-----------|--------|
| 08:00:00 | SUPPORT OPEN | INPROGRESS SUPPORT | SUPPORT INPROGRESS | Start counting |
| 12:00:00 | SUPPORT INPROGRESS | Hold Support | SUPPORT HOLD | Pause (lunch) |
| 13:00:00 | SUPPORT HOLD | HOLD ke INPROGRESS SUPPORT | SUPPORT INPROGRESS | Resume counting |
| 17:00:00 | SUPPORT INPROGRESS | Support Done | SUPPORT DONE | Stop counting |

**Total:** 4 h (08:00–12:00) + 4 h (13:00–17:00) = **8 hours**

---

## Prerequisites

- Python 3.8+
- pip
- A Jira Cloud account with API token access

---

## Installation

```bash
cd jira_automation
pip install -r requirements.txt
```

---

## Environment Setup

### Option 1 — Shell script (Linux/Mac)

```bash
chmod +x setup_env.sh
./setup_env.sh
source ~/.bashrc
```

### Option 2 — Batch script (Windows)

```cmd
setup_env.bat
```
Restart your terminal after running.

### Option 3 — `.env` file

Copy `.env.example` to `.env` and fill in your values:

```bash
cp .env.example .env
```

```
JIRA_DOMAIN=https://mufpm.atlassian.net
JIRA_EMAIL=your.email@company.com
JIRA_API_TOKEN=your_api_token_here
```

The script loads `.env` automatically via `python-dotenv`.

### Generating a Jira API Token

1. Go to <https://id.atlassian.com/manage-profile/security/api-tokens>
2. Click **Create API token**
3. Give it a label (e.g. "jira-automation") and copy the token

---

## Usage

### Verify credentials

```bash
python jira_automation.py --verify
```

### Show automation schedule

```bash
python jira_automation.py --schedule
```

### Show duration calculation

```bash
python jira_automation.py --calc-duration
```

### Test mode (search only, no transitions)

```bash
python jira_automation.py --test --time-slot 8AM
python jira_automation.py --test --time-slot 12PM
python jira_automation.py --test --time-slot 1PM
python jira_automation.py --test --time-slot 5PM
```

### Run immediately (skip waiting for exact time)

```bash
python jira_automation.py --no-wait --time-slot 8AM
```

### Auto-detect time slot and run

```bash
python jira_automation.py
```

### All CLI options

```
--time-slot {8AM,12PM,1PM,5PM,auto}
                  Time slot to run (default: auto)
--test            Search only; do not execute transitions
--no-wait         Skip waiting for exact target time
--calc-duration   Show duration calculation and exit
--schedule        Show schedule table and exit
--verify          Verify Jira credentials and exit
```

---

## Railway Deployment

The project ships with a `scheduler.py` that keeps the process alive and fires
each time slot at the right moment. Railway runs it as a **Worker** service.

### Files added for Railway

| File | Purpose |
|------|---------|
| `scheduler.py` | Long-running worker — fires each slot 1 min early (UTC) |
| `railway.toml` | Tells Railway to run `python scheduler.py` |
| `Procfile` | Fallback start command (`worker: python scheduler.py`) |

### UTC → WIB time mapping

| UTC trigger | WIB (UTC+7) | Slot |
|-------------|-------------|------|
| 00:59 | 07:59 | 8AM — waits to 08:00:00 exact |
| 04:59 | 11:59 | 12PM — waits to 12:00:00 exact |
| 05:59 | 12:59 | 1PM — waits to 13:00:00 exact |
| 09:59 | 16:59 | 5PM — waits to 17:00:00 exact |

### Deploy steps

1. **Push** all files to GitHub (make sure `.env` is in `.gitignore` — it is)
2. Go to [railway.app](https://railway.app) → **New Project** → **Deploy from GitHub repo**
3. Select your repository
4. In the service settings → **Variables**, add:
   ```
   JIRA_DOMAIN=https://mufpm.atlassian.net
   JIRA_EMAIL=okky.pratama@muf.co.id
   JIRA_API_TOKEN=your_api_token_here
   ```
5. Railway will detect `railway.toml` and run `python scheduler.py` automatically
6. Check the **Logs** tab — you should see:
   ```
   Jira Automation Scheduler started (Railway / UTC clock)
   Slots scheduled (UTC → WIB): ...
   ```

> **Note:** Railway's container clock runs in UTC. The scheduler accounts for
> this — all times in `scheduler.py` are in UTC. The `jira_automation.py`
> script itself uses the system clock for `wait_for_precise_time()`, which will
> also be UTC on Railway — but since it only waits for the **time component**
> (not the date), and the scheduler already fires at the correct UTC time,
> everything aligns correctly.

---

## Windows Task Scheduler Setup

Create four scheduled tasks so the script launches **1 minute early** and
waits internally for the precise transition time.

| Task Name | Trigger | Days | Command |
|-----------|---------|------|---------|
| Jira_Support_8AM | 07:59 AM | Mon–Fri | `python jira_automation.py --time-slot 8AM` |
| Jira_Support_12PM | 11:59 AM | Mon–Fri | `python jira_automation.py --time-slot 12PM` |
| Jira_Support_1PM | 12:59 PM | Mon–Fri | `python jira_automation.py --time-slot 1PM` |
| Jira_Support_5PM | 04:59 PM | Mon–Fri | `python jira_automation.py --time-slot 5PM` |

### Steps

1. Open **Task Scheduler** (`taskschd.msc`)
2. Click **Create Basic Task…**
3. Name: `Jira_Support_8AM` → Next
4. Trigger: **Daily** → Next
5. Start time: `07:59:00 AM`, recur every `1` day → Next
6. Action: **Start a program** → Next
7. Program/script: `python`
   Arguments: `C:\path\to\jira_automation\jira_automation.py --time-slot 8AM`
   Start in: `C:\path\to\jira_automation`
8. Finish → open task properties → **Conditions** tab →
   uncheck "Start the task only if the computer is on AC power"
9. **Triggers** tab → Edit → check **Monday through Friday** only
10. Repeat for `12PM` (11:59), `1PM` (12:59), `5PM` (16:59)

---

## Log File

All activity is written to `jira_automation.log` in the working directory.
Log format:

```
2026-02-23 08:00:00.123 - INFO - === Running automation for 8AM (Start work) ===
2026-02-23 08:00:00.456 - INFO - Found 1 issue(s): ['PRJ20250101-1206']
2026-02-23 08:00:00.789 - INFO - SUCCESS: PRJ20250101-1206 transitioned via "INPROGRESS SUPPORT"
```

---

## Troubleshooting

### `JIRA_API_TOKEN environment variable is not set`
Run `setup_env.sh` / `setup_env.bat` or create a `.env` file.

### `No issues found`
- Verify `--time-slot` matches the current status of your task in Jira.
- Check that today's date falls within `cf[10093]` (plan start date).
- Run `--test` mode to inspect the JQL without executing transitions.

### `Transition "X" not found`
- Transition names are matched case-insensitively against what Jira returns.
- Confirm the workflow transition names in your Jira project settings.

### Authentication errors (401/403)
- Regenerate your API token and update the environment variable.
- Ensure `JIRA_EMAIL` matches the account that owns the token.

### Script runs on weekends
- The script exits automatically on Saturday and Sunday.
- If you need to test on a weekend, use `--test --no-wait`.
