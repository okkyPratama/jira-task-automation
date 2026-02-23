#!/usr/bin/env python3
"""
scheduler.py
Long-running process for Railway deployment.

Fires jira_automation.py at the correct times for WIB (Asia/Jakarta = UTC+7).
The scheduler triggers each slot 1 minute early so jira_automation.py can use
its built-in wait_for_precise_time() to hit the exact second.

Schedule (UTC → WIB):
  00:59 UTC  →  07:59 WIB  →  8AM  slot (waits until 08:00:00 WIB)
  04:59 UTC  →  11:59 WIB  →  12PM slot (waits until 12:00:00 WIB)
  05:59 UTC  →  12:59 WIB  →  1PM  slot (waits until 13:00:00 WIB)
  09:59 UTC  →  16:59 WIB  →  5PM  slot (waits until 17:00:00 WIB)
"""

import logging
import os
import subprocess
import sys
import datetime

import schedule
import time

from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_weekday() -> bool:
    """Return True if today is Monday–Friday in WIB (UTC+7)."""
    wib = datetime.timezone(datetime.timedelta(hours=7))
    today = datetime.datetime.now(tz=wib).weekday()
    return today < 5  # 0=Mon … 4=Fri


def run_slot(slot: str) -> None:
    """
    Run jira_automation.py for the given slot.
    Skips silently on weekends (the script also checks, but belt-and-suspenders).
    """
    if not _is_weekday():
        logger.info('Weekend — skipping slot %s', slot)
        return

    logger.info('=' * 60)
    logger.info('Triggering slot: %s', slot)
    logger.info('=' * 60)

    cmd = [sys.executable, 'jira_automation.py', '--time-slot', slot]
    result = subprocess.run(cmd, capture_output=True, text=True)

    # Forward stdout/stderr to Railway log stream
    if result.stdout:
        for line in result.stdout.splitlines():
            logger.info('[jira] %s', line)
    if result.stderr:
        for line in result.stderr.splitlines():
            # Filter out the irrelevant zprofile brew warning
            if 'no such file or directory' in line and 'brew' in line:
                continue
            logger.warning('[jira-err] %s', line)

    if result.returncode != 0:
        logger.error('jira_automation.py exited with code %d for slot %s',
                     result.returncode, slot)
    else:
        logger.info('Slot %s completed successfully.', slot)

# ---------------------------------------------------------------------------
# Schedule definition (all times in UTC, fires 1 min before WIB target)
# ---------------------------------------------------------------------------
# The script's wait_for_precise_time() takes over once launched,
# so Railway only needs to wake it up 1 minute before the target.

schedule.every().day.at('00:59').do(run_slot, slot='8AM')   # 07:59 WIB → waits to 08:00
schedule.every().day.at('04:59').do(run_slot, slot='12PM')  # 11:59 WIB → waits to 12:00
schedule.every().day.at('05:59').do(run_slot, slot='1PM')   # 12:59 WIB → waits to 13:00
schedule.every().day.at('09:59').do(run_slot, slot='5PM')   # 16:59 WIB → waits to 17:00

# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------
logger.info('Jira Automation Scheduler started (Railway / UTC clock)')
logger.info('Timezone: WIB = UTC+7')
logger.info('Slots scheduled (UTC → WIB):')
logger.info('  00:59 UTC → 07:59 WIB  [8AM  slot]')
logger.info('  04:59 UTC → 11:59 WIB  [12PM slot]')
logger.info('  05:59 UTC → 12:59 WIB  [1PM  slot]')
logger.info('  09:59 UTC → 16:59 WIB  [5PM  slot]')
logger.info('Weekday check: runs Mon–Fri only (in WIB).')

# Keep the process alive and run pending jobs
while True:
    schedule.run_pending()
    time.sleep(30)
