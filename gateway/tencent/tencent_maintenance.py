"""Server-side Tencent token maintenance for every authorization profile.

Reads and rotates OAuth tokens only. Never calls an advertising endpoint, never
creates, edits, pauses or deletes an ad, and never prints a credential.

Invoked by the systemd timer as `tencent_maintenance.py --refresh`; the owner can
also run it by hand. A refresh that cannot be completed is reported and left for
inspection instead of being retried in a loop, because Tencent rotates the refresh
token and a blind retry can invalidate the profile.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import tencent_runtime as runtime

# The refresh window is shared with on-demand refresh in tencent_runtime, so the
# timer and a live API call can never disagree about whether a token is due.
REFRESH_WINDOW_SECONDS = runtime.ACCESS_REFRESH_LEAD_SECONDS
SERVICE = 'tencent-token-refresh'


def profiles(root):
    """Every configured authorization identity, default identity first.

    The default identity has no profile name; isolated third-party identities live
    under private/tencent/profiles/<name>/. Only validated names are enumerated so a
    stray directory can never be treated as an identity.
    """
    base = Path(root) / 'private/tencent'
    found = []
    if (base / 'config.json').exists():
        found.append(None)
    directory = base / 'profiles'
    if directory.is_dir():
        for entry in sorted(directory.iterdir()):
            if not entry.is_dir() or not (entry / 'config.json').exists():
                continue
            try:
                found.append(runtime.profile_name(entry.name))
            except runtime.Rejected:
                continue
    return found


def account_remaining(token, now):
    """Seconds left on each credential, or None when the lifetime is unknown."""
    access = token.get('access_token_expires_in')
    refresh = token.get('refresh_token_expires_in')
    received = token.get('received_at')
    if not isinstance(received, (int, float)) or isinstance(received, bool):
        return None, None
    left = lambda value: value - (now - received) if isinstance(value, (int, float)) else None
    return left(access), left(refresh)


def inspect(root, profile_id, *, now=None):
    """Report or refresh one identity without exposing any token material."""
    now = time.time() if now is None else now
    name = profile_id or 'default'
    cfg = runtime.load_config(root, require_accounts=False, profile_id=profile_id)
    folder = runtime.directory(root, cfg)
    file = folder / 'tokens.json'
    summary = {'profile_id': name, 'authorized': file.exists()}
    if not file.exists():
        return dict(summary, action='authorization_required')
    if (folder / 'refresh-pending.json').exists():
        # A previous attempt is unresolved; refreshing again could invalidate the
        # profile's only refresh token, so this is inspection work, not a retry.
        return dict(summary, action='uncertain')
    token = json.loads(file.read_text())
    access_left, refresh_left = account_remaining(token, now)
    if refresh_left is not None and refresh_left <= 0:
        return dict(summary, action='reauthorization_required',
                    reason='refresh token expired')
    if access_left is None:
        return dict(summary, action='failed', reason='token lifetime missing from saved credentials')
    if access_left > REFRESH_WINDOW_SECONDS:
        return dict(summary, action='valid', access_expires_in=int(access_left))
    # runtime.access_token takes the profile lock, checks the pending marker and
    # refreshes exactly once, so the timer cannot rotate a token twice at once.
    # It leaves a token alone while more than ten minutes remain, so compare
    # received_at afterwards instead of assuming a rotation happened.
    previous = token.get('received_at')
    runtime.access_token(root, cfg)
    fresh = json.loads(file.read_text())
    rotated = fresh.get('received_at') != previous
    access_left, refresh_left = account_remaining(fresh, now)
    return dict(summary, action='refreshed' if rotated else 'valid',
                access_expires_in=int(access_left) if access_left is not None else None,
                refresh_expires_in=int(refresh_left) if refresh_left is not None else None)


def maintain_tokens(root):
    """Check every identity; one failure must not hide the others."""
    report = []
    failures = []
    for profile_id in profiles(root):
        try:
            report.append(inspect(root, profile_id))
        except runtime.Rejected as error:
            name = profile_id or 'default'
            failures.append(name)
            report.append({'profile_id': name, 'action': 'failed', 'reason': str(error)[:200]})
        except Exception as error:
            name = profile_id or 'default'
            failures.append(name)
            report.append({'profile_id': name, 'action': 'failed', 'reason': type(error).__name__})
    needs_attention = [row['profile_id'] for row in report
                       if row['action'] in ('uncertain', 'reauthorization_required', 'failed')]
    print(json.dumps({'checked_at': int(time.time()), 'profiles': report,
                      'needs_attention': needs_attention}, ensure_ascii=False), flush=True)
    if failures:
        raise RuntimeError('Tencent token checks failed for ' + ', '.join(failures)
                           + '; inspect the saved markers before reauthorizing.')
    return report


def units(script):
    """Systemd units for the gateway directory the caller installed into."""
    script = Path(script).resolve()
    service = '''[Unit]
Description=Refresh Tencent OAuth tokens when due
After=network-online.target
Wants=network-online.target
[Service]
Type=oneshot
User=ocean-callback
Group=ocean-callback
WorkingDirectory=%s
ExecStart=/usr/bin/python3 %s --refresh
UMask=0077
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=%s
''' % (script.parent, script, script.parent / 'private')
    timer = '''[Unit]
Description=Check Tencent token expiry every 15 minutes
[Timer]
OnBootSec=5min
OnUnitActiveSec=15min
[Install]
WantedBy=timers.target
'''
    return service, timer


def install():
    if os.geteuid() != 0:
        raise RuntimeError('Run the token timer installer with sudo.')
    # The unit points at this very file, so refuse to install a timer for a path
    # that does not exist. Tencent must already be configured; otherwise there is
    # nothing to maintain and the timer is not installed at all.
    target = Path(__file__).resolve().parent
    script = target / 'tencent_maintenance.py'
    if not script.exists():
        raise RuntimeError('Install tencent_maintenance.py in the gateway directory first.')
    if not (target / 'private/tencent').is_dir():
        raise RuntimeError('Tencent is not configured on this server; the timer was not installed.')
    service, timer = units(script)
    Path('/etc/systemd/system/%s.service' % SERVICE).write_text(service)
    Path('/etc/systemd/system/%s.timer' % SERVICE).write_text(timer)
    subprocess.run(['systemctl', 'daemon-reload'], check=True)
    subprocess.run(['systemctl', 'enable', '--now', SERVICE + '.timer'], check=True)
    subprocess.run(['runuser', '-u', 'ocean-callback', '--', '/usr/bin/python3', str(script), '--refresh'],
                   check=True)
    print('Tencent token timer installed. No advertising setting was read or changed.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Maintain Tencent OAuth tokens only.')
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--refresh', action='store_true', help='check and refresh every identity when due')
    group.add_argument('--install', action='store_true', help='install the fifteen-minute timer')
    args = parser.parse_args()
    try:
        if args.install:
            install()
        else:
            maintain_tokens(Path(__file__).resolve().parent)
    except (RuntimeError, runtime.Rejected) as error:
        print('Tencent token maintenance needs attention:', str(error)[:300], file=sys.stderr, flush=True)
        sys.exit(1)
