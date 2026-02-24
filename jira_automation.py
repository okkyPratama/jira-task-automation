#!/usr/bin/env python3
"""
Jira Support Task Automation
Automatically transitions Jira SUPPORT tasks at specific times to achieve
exactly 8 hours of tracked working time.
"""

import argparse
import datetime
import logging
import os
import sys
import time

import requests
from dotenv import load_dotenv
from requests.auth import HTTPBasicAuth

# Load .env file if present
load_dotenv()

# ---------------------------------------------------------------------------
# Logging configuration
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s.%(msecs)03d - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    handlers=[
        logging.FileHandler('jira_automation.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Global configuration
# ---------------------------------------------------------------------------
JIRA_DOMAIN = os.environ.get('JIRA_DOMAIN', 'https://mufpm.atlassian.net')
JIRA_EMAIL = os.environ.get('JIRA_EMAIL', '')
JIRA_API_TOKEN = os.environ.get('JIRA_API_TOKEN', '')

# Cached account ID (populated by initialize_account_id)
JIRA_ACCOUNT_ID: str = ''

# WIB = Asia/Jakarta = UTC+7  (no DST)
_WIB = datetime.timezone(datetime.timedelta(hours=7))


def now_wib() -> datetime.datetime:
    """Return the current time as a naive datetime in WIB (UTC+7).

    Using a naive datetime keeps the rest of the code simple — we strip the
    timezone info so comparisons with other naive datetimes work unchanged.
    On Railway the system clock is UTC, so this is the critical conversion.
    On a local WIB machine datetime.now() already returns WIB time, and
    astimezone(_WIB).replace(tzinfo=None) still gives the correct WIB value.
    """
    return datetime.datetime.now(tz=_WIB).replace(tzinfo=None)

# Schedule definition
SCHEDULE = {
    '8AM': {
        'target_time': datetime.time(8, 0, 0, 0),   # fallback only; actual time = cf[10093]
        'from_status': 'SUPPORT OPEN',
        'transition_name': 'INPROGRESS SUPPORT',
        'description': 'Start work (time from cf[10093])',
    },
    '12PM': {
        'target_time': datetime.time(12, 0, 0, 0),
        'from_status': 'SUPPORT INPROGRESS',
        'transition_name': 'Hold Support',
        'description': 'Lunch break (pause)',
    },
    '1PM': {
        'target_time': datetime.time(13, 0, 0, 0),
        'from_status': 'SUPPORT HOLD',
        'transition_name': 'HOLD ke INPROGRESS SUPPORT',
        'description': 'Resume work',
    },
    '5PM': {
        'target_time': datetime.time(17, 0, 0, 0),  # fallback only; actual time = cf[10094]
        'from_status': 'SUPPORT INPROGRESS',
        'transition_name': 'Support Done',
        'description': 'End work (time from cf[10094])',
    },
}

# ---------------------------------------------------------------------------
# Authentication & User Functions
# ---------------------------------------------------------------------------

def get_auth() -> HTTPBasicAuth:
    """
    Returns HTTPBasicAuth object using JIRA_EMAIL and JIRA_API_TOKEN.
    Raises ValueError if JIRA_API_TOKEN is not set.
    """
    token = os.environ.get('JIRA_API_TOKEN', JIRA_API_TOKEN)
    if not token:
        raise ValueError(
            'JIRA_API_TOKEN environment variable is not set. '
            'Run setup_env.sh (Linux/Mac) or setup_env.bat (Windows).'
        )
    email = os.environ.get('JIRA_EMAIL', JIRA_EMAIL)
    return HTTPBasicAuth(email, token)


def get_current_user() -> dict:
    """
    GET /rest/api/3/myself
    Returns user info dict containing accountId, displayName, emailAddress.
    Returns None on error.
    """
    url = f'{JIRA_DOMAIN}/rest/api/3/myself'
    logger.debug('REQUEST  GET %s', url)
    try:
        t0 = time.perf_counter()
        response = requests.get(
            url,
            auth=get_auth(),
            headers={'Accept': 'application/json'},
            timeout=30,
        )
        elapsed = (time.perf_counter() - t0) * 1000
        logger.debug('RESPONSE %d  %.0fms  GET %s', response.status_code, elapsed, url)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.HTTPError as exc:
        logger.error('HTTP error fetching current user: %s', exc)
        try:
            logger.error('Response body: %s', exc.response.text)
        except Exception:
            pass
        return None
    except Exception as exc:
        logger.error('Error fetching current user: %s', exc)
        return None


def initialize_account_id() -> str:
    """
    Calls get_current_user() and extracts accountId.
    Caches the result in global variable JIRA_ACCOUNT_ID.
    Raises ValueError if unable to fetch.
    """
    global JIRA_ACCOUNT_ID
    if JIRA_ACCOUNT_ID:
        return JIRA_ACCOUNT_ID

    user = get_current_user()
    if not user or 'accountId' not in user:
        raise ValueError('Unable to fetch Jira account ID. Check credentials.')

    JIRA_ACCOUNT_ID = user['accountId']
    logger.info('Authenticated as: %s (%s)', user.get('displayName'), user.get('emailAddress'))
    logger.info('Account ID: %s', JIRA_ACCOUNT_ID)
    return JIRA_ACCOUNT_ID

# ---------------------------------------------------------------------------
# Jira API Functions
# ---------------------------------------------------------------------------

def search_issues(jql: str) -> list:
    """
    POST /rest/api/3/search/jql
    Returns list of issues or empty list on error.
    Also fetches cf[10093] (plan start) and cf[10094] (plan end) for each issue.
    """
    url = f'{JIRA_DOMAIN}/rest/api/3/search/jql'
    payload = {
        'jql': jql,
        'maxResults': 10,
        'fields': ['key', 'summary', 'status', 'customfield_10093', 'customfield_10094'],
    }
    logger.info('REQUEST  POST %s', url)
    logger.info('         JQL: %s', jql)
    try:
        t0 = time.perf_counter()
        response = requests.post(
            url,
            auth=get_auth(),
            headers={
                'Accept': 'application/json',
                'Content-Type': 'application/json',
            },
            json=payload,
            timeout=30,
        )
        elapsed = (time.perf_counter() - t0) * 1000
        data = response.json()
        issues = data.get('issues', [])
        is_last = data.get('isLast', True)
        logger.info('RESPONSE %d  %.0fms  issues=%d  isLast=%s  POST %s',
                    response.status_code, elapsed, len(issues), is_last, url)
        response.raise_for_status()
        return issues
    except requests.exceptions.HTTPError as exc:
        logger.error('HTTP error searching issues: %s', exc)
        try:
            logger.error('Response body: %s', exc.response.text)
        except Exception:
            pass
        return []
    except Exception as exc:
        logger.error('Error searching issues: %s', exc)
        return []


def get_transitions(issue_key: str) -> list:
    """
    GET /rest/api/3/issue/{issue_key}/transitions
    Returns list of available transitions or empty list on error.
    """
    url = f'{JIRA_DOMAIN}/rest/api/3/issue/{issue_key}/transitions'
    logger.info('REQUEST  GET %s', url)
    try:
        t0 = time.perf_counter()
        response = requests.get(
            url,
            auth=get_auth(),
            headers={'Accept': 'application/json'},
            timeout=30,
        )
        elapsed = (time.perf_counter() - t0) * 1000
        data = response.json()
        transitions = data.get('transitions', [])
        names = [t['name'] for t in transitions]
        logger.info('RESPONSE %d  %.0fms  transitions=%s  GET %s',
                    response.status_code, elapsed, names, url)
        response.raise_for_status()
        return transitions
    except requests.exceptions.HTTPError as exc:
        logger.error('HTTP error fetching transitions for %s: %s', issue_key, exc)
        try:
            logger.error('Response body: %s', exc.response.text)
        except Exception:
            pass
        return []
    except Exception as exc:
        logger.error('Error fetching transitions for %s: %s', issue_key, exc)
        return []


def transition_issue(issue_key: str, transition_id: str) -> tuple:
    """
    POST /rest/api/3/issue/{issue_key}/transitions
    Returns (success: bool, timestamp_before: str, timestamp_after: str)
    Timestamps have microsecond precision: "%Y-%m-%d %H:%M:%S.%f"
    """
    url = f'{JIRA_DOMAIN}/rest/api/3/issue/{issue_key}/transitions'
    payload = {'transition': {'id': transition_id}}
    logger.info('REQUEST  POST %s', url)
    logger.info('         Body: %s', payload)
    timestamp_before = get_precise_timestamp()
    try:
        t0 = time.perf_counter()
        response = requests.post(
            url,
            auth=get_auth(),
            headers={
                'Accept': 'application/json',
                'Content-Type': 'application/json',
            },
            json=payload,
            timeout=30,
        )
        elapsed = (time.perf_counter() - t0) * 1000
        timestamp_after = get_precise_timestamp()
        # Log response — 204 has no body, anything else log it
        body = response.text.strip() if response.text.strip() else '(empty — 204 No Content)'
        logger.info('RESPONSE %d  %.0fms  POST %s', response.status_code, elapsed, url)
        logger.info('         Body: %s', body)
        response.raise_for_status()
        return (True, timestamp_before, timestamp_after)
    except requests.exceptions.HTTPError as exc:
        timestamp_after = get_precise_timestamp()
        logger.error('HTTP error transitioning %s: %s', issue_key, exc)
        try:
            logger.error('Response body: %s', exc.response.text)
        except Exception:
            pass
        return (False, timestamp_before, timestamp_after)
    except Exception as exc:
        timestamp_after = get_precise_timestamp()
        logger.error('Error transitioning %s: %s', issue_key, exc)
        return (False, timestamp_before, timestamp_after)


def find_transition_id(transitions: list, transition_name: str) -> str:
    """
    Find transition ID by name (case-insensitive comparison).
    Returns transition ID string or None if not found.
    """
    target = transition_name.lower()
    for t in transitions:
        if t.get('name', '').lower() == target:
            return t['id']
    return None

# ---------------------------------------------------------------------------
# Timing Functions (Microsecond Precision)
# ---------------------------------------------------------------------------

def get_precise_timestamp() -> str:
    """
    Returns current timestamp with microsecond precision.
    Format: "%Y-%m-%d %H:%M:%S.%f"
    Example: "2026-02-23 08:00:00.000123"
    """
    return now_wib().strftime('%Y-%m-%d %H:%M:%S.%f')


def get_microseconds_since_midnight() -> int:
    """
    Returns microseconds elapsed since midnight.
    Used for precision tracking.
    """
    now = now_wib()
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    delta = now - midnight
    return int(delta.total_seconds() * 1_000_000)


def wait_for_precise_time(target_time: datetime.time) -> None:
    """
    Waits until the exact target time with microsecond precision.

    Strategy:
    - If remaining > 60 seconds: sleep(30)
    - If remaining > 1 second:   sleep(0.5)
    - If remaining > 10ms:       sleep(0.001)
    - If remaining > 100μs:      sleep(0.0001)
    - Otherwise:                 busy-wait (pass)

    Logs when target time is reached.
    """
    logger.info('Waiting for target time: %s WIB  (now: %s WIB)',
                target_time.strftime('%H:%M:%S'), now_wib().strftime('%H:%M:%S'))

    last_heartbeat = [now_wib()]  # list so it's mutable inside the loop

    while True:
        now = now_wib()
        target_dt = now.replace(
            hour=target_time.hour,
            minute=target_time.minute,
            second=target_time.second,
            microsecond=target_time.microsecond,
        )

        # If the target already passed today, nothing to wait for
        if now >= target_dt:
            logger.info('Target time reached: %s WIB', get_precise_timestamp())
            return

        remaining_seconds = (target_dt - now).total_seconds()

        # Heartbeat log every 30 s while waiting (keeps Railway logs alive)
        if (now - last_heartbeat[0]).total_seconds() >= 30:
            mins = int(remaining_seconds // 60)
            secs = int(remaining_seconds % 60)
            logger.info('Still waiting... %dm %ds remaining until %s WIB',
                        mins, secs, target_time.strftime('%H:%M:%S'))
            last_heartbeat[0] = now

        if remaining_seconds > 60:
            time.sleep(30)
        elif remaining_seconds > 1:
            time.sleep(0.5)
        elif remaining_seconds > 0.01:
            time.sleep(0.001)
        elif remaining_seconds > 0.0001:
            time.sleep(0.0001)
        else:
            # Busy-wait for final microseconds
            pass

# ---------------------------------------------------------------------------
# Main Logic Functions
# ---------------------------------------------------------------------------

# Jira returns timestamps in ISO-8601, e.g. "2026-02-23T08:00:00.000+0700"
_JIRA_TS_FORMATS = [
    '%Y-%m-%dT%H:%M:%S.%f%z',
    '%Y-%m-%dT%H:%M:%S%z',
]


def parse_issue_datetime(field_value: str) -> datetime.datetime:
    """
    Parse a Jira timestamp string into a timezone-aware datetime.
    Returns None if parsing fails.
    """
    if not field_value:
        return None
    for fmt in _JIRA_TS_FORMATS:
        try:
            return datetime.datetime.strptime(field_value, fmt)
        except ValueError:
            continue
    logger.warning('Could not parse Jira datetime value: %r', field_value)
    return None


def build_jql(from_status: str) -> str:
    """
    Builds JQL query string.
    """
    account_id = initialize_account_id()
    today = now_wib().strftime('%Y-%m-%d')
    jql = (
        f'assignee = "{account_id}" '
        f'AND status = "{from_status}" '
        f'AND cf[10093] >= "{today} 00:00" '
        f'AND cf[10093] <= "{today} 23:59"'
    )
    return jql


def _execute_transition_for_issue(issue: dict, transition_name: str) -> None:
    """
    Fetch transitions for a single issue, find the right one by name, and execute it.
    Logs success/failure with microsecond timestamps.
    """
    issue_key = issue['key']
    summary = issue.get('fields', {}).get('summary', '(no summary)')
    logger.info('Processing issue: %s - %s', issue_key, summary)

    transitions = get_transitions(issue_key)
    if not transitions:
        logger.warning('No transitions available for %s. Skipping.', issue_key)
        return

    transition_id = find_transition_id(transitions, transition_name)
    if transition_id is None:
        available = [t['name'] for t in transitions]
        logger.error(
            'Transition "%s" not found for %s. Available transitions: %s',
            transition_name, issue_key, available,
        )
        return

    logger.info('Executing transition "%s" (id=%s) on %s', transition_name, transition_id, issue_key)
    success, ts_before, ts_after = transition_issue(issue_key, transition_id)

    if success:
        logger.info(
            'SUCCESS: %s transitioned via "%s" | before=%s | after=%s',
            issue_key, transition_name, ts_before, ts_after,
        )
    else:
        logger.error(
            'FAILED: Could not transition %s via "%s" | before=%s | after=%s',
            issue_key, transition_name, ts_before, ts_after,
        )


def _resolve_target_time_for_issue(
    issue: dict, time_slot: str, fallback: datetime.time
) -> 'datetime.time | None':
    """
    For 8AM slot:  use cf[10093] (plan start) time component.
    For 5PM slot:  use cf[10094] (plan end) time component.
    For all other slots: return fallback (fixed time).

    Returns None if the plan date in the relevant field does not match
    today's WIB date — signalling run_automation to skip this issue.
    Returns the fallback time if the field is missing or unparseable.
    """
    fields = issue.get('fields', {})

    if time_slot == '8AM':
        raw = fields.get('customfield_10093')
    elif time_slot == '5PM':
        raw = fields.get('customfield_10094')
    else:
        # 12PM and 1PM use fixed times; JQL already guarantees cf[10093] is today
        return fallback

    dt = parse_issue_datetime(raw)
    if dt is None:
        logger.warning(
            '%s: could not read plan datetime for slot %s, falling back to %s',
            issue['key'], time_slot, fallback,
        )
        return fallback

    # Convert to WIB naive datetime so it matches now_wib()
    wib_dt = dt.astimezone(_WIB).replace(tzinfo=None)
    today_wib = now_wib().date()

    # Date guard: the plan date must be TODAY (WIB).
    # - For 8AM: cf[10093] date must be today   (JQL already enforces this,
    #            but we double-check here for safety)
    # - For 5PM: cf[10094] date must be today   (JQL only filters cf[10093],
    #            so this is the only place that validates the end date)
    if wib_dt.date() != today_wib:
        logger.warning(
            '%s: plan date for slot %s is %s — expected today (%s). '
            'Skipping this issue.',
            issue['key'], time_slot,
            wib_dt.strftime('%Y-%m-%d'), today_wib,
        )
        return None  # caller (run_automation) will skip this issue

    logger.info(
        '%s: plan datetime for slot %s = %s WIB ✓ (matches today)',
        issue['key'], time_slot, wib_dt.strftime('%Y-%m-%d %H:%M:%S'),
    )
    return wib_dt.time()


def run_automation(time_slot: str, wait_for_exact_time: bool = True) -> None:
    """
    Main automation function for a specific time slot.

    For 8AM and 5PM slots each issue is transitioned at its own plan
    start/end time read from cf[10093] / cf[10094] respectively.
    For 12PM and 1PM slots a fixed hold/resume time is used for all issues.

    Steps:
    1. Validate time_slot is in SCHEDULE dict
    2. Get config (from_status, transition_name, fallback target_time, description)
    3. Build JQL and search for issues (includes cf[10093] and cf[10094] fields)
    4. If no issues found, log and return
    5. For each issue:
       a. Resolve the target time (per-issue for 8AM/5PM, fixed for 12PM/1PM)
       b. If wait_for_exact_time is True, wait for that time
       c. Execute the transition
    """
    if time_slot not in SCHEDULE:
        logger.error('Invalid time slot: %s. Must be one of %s', time_slot, list(SCHEDULE.keys()))
        return

    config = SCHEDULE[time_slot]
    from_status = config['from_status']
    transition_name = config['transition_name']
    fallback_time = config['target_time']
    description = config['description']

    logger.info('=== Running automation for %s (%s) ===', time_slot, description)
    logger.info('Looking for issues with status: %s', from_status)
    logger.info('Will apply transition: %s', transition_name)

    jql = build_jql(from_status)
    logger.info('JQL: %s', jql)

    issues = search_issues(jql)
    if not issues:
        logger.info('No issues found for status "%s" today. Nothing to transition.', from_status)
        return

    # ── Task summary table ────────────────────────────────────────────────────
    logger.info('Found %d issue(s) to process today:', len(issues))
    logger.info('  %-20s %-16s %-22s %-22s %s',
                'Key', 'Status', 'Plan Start (WIB)', 'Plan End (WIB)', 'Summary')
    logger.info('  %s', '-' * 100)
    for iss in issues:
        f = iss.get('fields', {})
        start_raw = f.get('customfield_10093', '')
        end_raw   = f.get('customfield_10094', '')
        start_dt  = parse_issue_datetime(start_raw)
        end_dt    = parse_issue_datetime(end_raw)
        start_str = start_dt.astimezone(_WIB).strftime('%Y-%m-%d %H:%M') if start_dt else 'N/A'
        end_str   = end_dt.astimezone(_WIB).strftime('%Y-%m-%d %H:%M')   if end_dt   else 'N/A'
        summary   = f.get('summary', '(no summary)')[:45]
        status    = f.get('status', {}).get('name', 'unknown')
        logger.info('  %-20s %-16s %-22s %-22s %s',
                    iss['key'], status, start_str, end_str, summary)
    logger.info('  %s', '-' * 100)
    # ─────────────────────────────────────────────────────────────────────────

    for issue in issues:
        target_time = _resolve_target_time_for_issue(issue, time_slot, fallback_time)

        if target_time is None:
            # Plan date does not match today — warning already logged inside
            # _resolve_target_time_for_issue. Skip this issue entirely.
            continue

        if wait_for_exact_time:
            wait_for_precise_time(target_time)

        _execute_transition_for_issue(issue, transition_name)


def get_current_time_slot() -> str:
    """
    Auto-detect time slot based on current hour.

    Returns:
    - "8AM"  if hour < 12
    - "12PM" if hour < 13
    - "1PM"  if hour < 17
    - "5PM"  otherwise
    """
    hour = now_wib().hour
    if hour < 12:
        return '8AM'
    if hour < 13:
        return '12PM'
    if hour < 17:
        return '1PM'
    return '5PM'

# ---------------------------------------------------------------------------
# Utility Functions
# ---------------------------------------------------------------------------

def calculate_duration() -> None:
    """
    Prints duration calculation showing total working time.
    """
    period1_start = datetime.time(8, 0, 0)
    period1_end = datetime.time(12, 0, 0)
    lunch_start = datetime.time(12, 0, 0)
    lunch_end = datetime.time(13, 0, 0)
    period2_start = datetime.time(13, 0, 0)
    period2_end = datetime.time(17, 0, 0)

    period1 = datetime.timedelta(hours=4)
    lunch = datetime.timedelta(hours=1)
    period2 = datetime.timedelta(hours=4)
    total = period1 + period2

    total_us = int(total.total_seconds() * 1_000_000)

    print('\n=== Duration Calculation ===')
    print(f'Working Period 1: cf[10093] (plan start) - {period1_end} (hold) = {period1}')
    print(f'Lunch Break:      {lunch_start} - {lunch_end} = {lunch} (NOT counted, fixed)')
    print(f'Working Period 2: {period2_start} (resume) - cf[10094] (plan end) = {period2}')
    print(f'Example total:    {total} ({total_us:,} microseconds)  [assumes 8AM start / 5PM end]')
    print('Note: Actual start/end times are read per-issue from Jira custom fields.')
    print('============================\n')


def show_schedule() -> None:
    """
    Prints automation schedule table showing all 4 time slots.
    """
    print('\n=== Automation Schedule ===')
    print(f'{"Slot":<6} {"Target Time":<14} {"From Status":<22} {"Transition":<30} {"Description"}')
    print('-' * 100)
    for slot, cfg in SCHEDULE.items():
        print(
            f'{slot:<6} '
            f'{cfg["target_time"].strftime("%H:%M:%S"):<14} '
            f'{cfg["from_status"]:<22} '
            f'{cfg["transition_name"]:<30} '
            f'{cfg["description"]}'
        )
    print('===========================\n')


def verify_credentials() -> bool:
    """
    Calls get_current_user() and prints user info.
    Returns True if successful, False otherwise.
    """
    print('Verifying Jira credentials...')
    user = get_current_user()
    if not user:
        print('ERROR: Failed to authenticate. Check JIRA_EMAIL and JIRA_API_TOKEN.')
        return False

    print('\n=== Credential Verification ===')
    print(f'Display Name:  {user.get("displayName")}')
    print(f'Email:         {user.get("emailAddress")}')
    print(f'Account ID:    {user.get("accountId")}')
    print(f'Jira Domain:   {JIRA_DOMAIN}')
    print('================================\n')
    print('Credentials verified successfully.')
    return True

# ---------------------------------------------------------------------------
# Weekend Check
# ---------------------------------------------------------------------------

def check_weekday() -> None:
    """
    Exits gracefully if today is Saturday (5) or Sunday (6).
    """
    weekday = now_wib().weekday()
    if weekday >= 5:
        day_name = 'Saturday' if weekday == 5 else 'Sunday'
        logger.info('Today is %s. No automation runs on weekends. Exiting.', day_name)
        sys.exit(0)

# ---------------------------------------------------------------------------
# CLI Entry Point
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description='Jira Support Task Automation - transitions issues at precise times',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python jira_automation.py --verify
  python jira_automation.py --schedule
  python jira_automation.py --calc-duration
  python jira_automation.py --test --time-slot 8AM
  python jira_automation.py --no-wait --time-slot 8AM
  python jira_automation.py --time-slot auto
        """,
    )
    parser.add_argument(
        '--time-slot',
        choices=['8AM', '12PM', '1PM', '5PM', 'auto'],
        default='auto',
        help='Which time slot to run (default: auto-detect based on current hour)',
    )
    parser.add_argument(
        '--test',
        action='store_true',
        help='Search for issues only; do not execute any transitions',
    )
    parser.add_argument(
        '--no-wait',
        action='store_true',
        help='Skip waiting for the exact target time; execute transition immediately',
    )
    parser.add_argument(
        '--calc-duration',
        action='store_true',
        help='Show duration calculation and exit',
    )
    parser.add_argument(
        '--schedule',
        action='store_true',
        help='Show the automation schedule table and exit',
    )
    parser.add_argument(
        '--verify',
        action='store_true',
        help='Verify Jira credentials and exit',
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    # Informational-only flags (no weekend/credential checks needed)
    if args.calc_duration:
        calculate_duration()
        return

    if args.schedule:
        show_schedule()
        return

    if args.verify:
        try:
            success = verify_credentials()
            sys.exit(0 if success else 1)
        except ValueError as exc:
            print(f'ERROR: {exc}')
            sys.exit(1)

    # Validate required env vars before proceeding
    try:
        get_auth()  # raises ValueError if token missing
    except ValueError as exc:
        logger.error('%s', exc)
        sys.exit(1)

    # Weekend check
    check_weekday()

    # ── Startup banner ────────────────────────────────────────────────────────
    wib_now = now_wib()
    logger.info('=' * 60)
    logger.info('Jira Support Task Automation')
    logger.info('  Date/Time : %s WIB', wib_now.strftime('%Y-%m-%d %H:%M:%S'))
    logger.info('  Domain    : %s', JIRA_DOMAIN)
    logger.info('  Email     : %s', os.environ.get('JIRA_EMAIL', JIRA_EMAIL))
    logger.info('=' * 60)
    # ─────────────────────────────────────────────────────────────────────────

    # Determine time slot
    time_slot = args.time_slot
    if time_slot == 'auto':
        time_slot = get_current_time_slot()
        logger.info('Auto-detected time slot: %s', time_slot)

    if args.test:
        # Test mode: search only, no transitions
        logger.info('=== TEST MODE (no transitions will be executed) ===')
        try:
            jql = build_jql(SCHEDULE[time_slot]['from_status'])
        except ValueError as exc:
            logger.error('%s', exc)
            sys.exit(1)
        logger.info('JQL: %s', jql)
        issues = search_issues(jql)
        if issues:
            logger.info('Found %d issue(s):', len(issues))
            logger.info('  %-20s %-16s %-22s %-22s %s',
                        'Key', 'Status', 'Plan Start (WIB)', 'Plan End (WIB)', 'Summary')
            logger.info('  %s', '-' * 100)
            for issue in issues:
                f = issue.get('fields', {})
                start_raw = f.get('customfield_10093', '')
                end_raw   = f.get('customfield_10094', '')
                start_dt  = parse_issue_datetime(start_raw)
                end_dt    = parse_issue_datetime(end_raw)
                start_str = start_dt.astimezone(_WIB).strftime('%Y-%m-%d %H:%M') if start_dt else 'N/A'
                end_str   = end_dt.astimezone(_WIB).strftime('%Y-%m-%d %H:%M')   if end_dt   else 'N/A'
                status    = f.get('status', {}).get('name', 'unknown')
                summary   = f.get('summary', '(no summary)')[:45]
                logger.info('  %-20s %-16s %-22s %-22s %s',
                            issue['key'], status, start_str, end_str, summary)
            logger.info('  %s', '-' * 100)
        else:
            logger.info('No issues found.')
        return

    # Normal run
    try:
        run_automation(time_slot, wait_for_exact_time=not args.no_wait)
    except ValueError as exc:
        logger.error('%s', exc)
        sys.exit(1)


if __name__ == '__main__':
    main()
