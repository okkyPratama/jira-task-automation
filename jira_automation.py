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

# Schedule definition
SCHEDULE = {
    '8AM': {
        'target_time': datetime.time(8, 0, 0, 0),
        'from_status': 'SUPPORT OPEN',
        'transition_name': 'INPROGRESS SUPPORT',
        'description': 'Start work',
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
        'target_time': datetime.time(17, 0, 0, 0),
        'from_status': 'SUPPORT INPROGRESS',
        'transition_name': 'Support Done',
        'description': 'End work',
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
    try:
        response = requests.get(
            url,
            auth=get_auth(),
            headers={'Accept': 'application/json'},
            timeout=30,
        )
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
    """
    url = f'{JIRA_DOMAIN}/rest/api/3/search/jql'
    payload = {
        'jql': jql,
        'maxResults': 10,
        'fields': ['key', 'summary', 'status'],
    }
    try:
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
        response.raise_for_status()
        data = response.json()
        return data.get('issues', [])
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
    try:
        response = requests.get(
            url,
            auth=get_auth(),
            headers={'Accept': 'application/json'},
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()
        return data.get('transitions', [])
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
    timestamp_before = get_precise_timestamp()
    try:
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
        timestamp_after = get_precise_timestamp()
        response.raise_for_status()
        # 204 No Content on success
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
    return datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')


def get_microseconds_since_midnight() -> int:
    """
    Returns microseconds elapsed since midnight.
    Used for precision tracking.
    """
    now = datetime.datetime.now()
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
    logger.info('Waiting for target time: %s', target_time.strftime('%H:%M:%S'))

    while True:
        now = datetime.datetime.now()
        target_dt = now.replace(
            hour=target_time.hour,
            minute=target_time.minute,
            second=target_time.second,
            microsecond=target_time.microsecond,
        )

        # If the target already passed today, nothing to wait for
        if now >= target_dt:
            logger.info('Target time reached: %s', get_precise_timestamp())
            return

        remaining_seconds = (target_dt - now).total_seconds()

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

def build_jql(from_status: str) -> str:
    """
    Builds JQL query string.
    """
    account_id = initialize_account_id()
    today = datetime.datetime.now().strftime('%Y-%m-%d')
    jql = (
        f'assignee = "{account_id}" '
        f'AND status = "{from_status}" '
        f'AND cf[10093] >= "{today} 00:00" '
        f'AND cf[10093] <= "{today} 23:59"'
    )
    return jql


def run_automation(time_slot: str, wait_for_exact_time: bool = True) -> None:
    """
    Main automation function for a specific time slot.

    Steps:
    1. Validate time_slot is in SCHEDULE dict
    2. Get config (from_status, transition_name, target_time, description)
    3. Build JQL and search for issues
    4. If no issues found, log and return
    5. If wait_for_exact_time is True, call wait_for_precise_time()
    6. For each issue:
       a. Get available transitions
       b. Find matching transition by name
       c. Execute transition
       d. Log success/failure with timestamps
    """
    if time_slot not in SCHEDULE:
        logger.error('Invalid time slot: %s. Must be one of %s', time_slot, list(SCHEDULE.keys()))
        return

    config = SCHEDULE[time_slot]
    from_status = config['from_status']
    transition_name = config['transition_name']
    target_time = config['target_time']
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

    logger.info('Found %d issue(s): %s', len(issues), [i['key'] for i in issues])

    if wait_for_exact_time:
        wait_for_precise_time(target_time)

    for issue in issues:
        issue_key = issue['key']
        summary = issue.get('fields', {}).get('summary', '(no summary)')
        logger.info('Processing issue: %s - %s', issue_key, summary)

        transitions = get_transitions(issue_key)
        if not transitions:
            logger.warning('No transitions available for %s. Skipping.', issue_key)
            continue

        transition_id = find_transition_id(transitions, transition_name)
        if transition_id is None:
            available = [t['name'] for t in transitions]
            logger.error(
                'Transition "%s" not found for %s. Available transitions: %s',
                transition_name, issue_key, available,
            )
            continue

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


def get_current_time_slot() -> str:
    """
    Auto-detect time slot based on current hour.

    Returns:
    - "8AM"  if hour < 12
    - "12PM" if hour < 13
    - "1PM"  if hour < 17
    - "5PM"  otherwise
    """
    hour = datetime.datetime.now().hour
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
    print(f'Working Period 1: {period1_start} - {period1_end} = {period1}')
    print(f'Lunch Break:      {lunch_start} - {lunch_end} = {lunch} (NOT counted)')
    print(f'Working Period 2: {period2_start} - {period2_end} = {period2}')
    print(f'Total:            {total} ({total_us:,} microseconds)')
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
    weekday = datetime.datetime.now().weekday()
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
            for issue in issues:
                key = issue['key']
                summary = issue.get('fields', {}).get('summary', '(no summary)')
                status = issue.get('fields', {}).get('status', {}).get('name', 'unknown')
                logger.info('  [%s] %s (status: %s)', key, summary, status)
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
