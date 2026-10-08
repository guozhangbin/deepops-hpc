#!/usr/bin/env python3
"""Validate a DeepOps Open OnDemand portal deployment and report a verdict.

Run this on the portal host (``[ood-portal]`` inventory group, usually the
Slurm master) after deploying ``playbooks/ood-portal.yml``. It checks that
Apache/OnDemand is up, that a configured portal user can log in over HTTP
Basic auth, that Batch Connect apps are installed, and that the Slurm
cluster and branding configuration are in place.

The default output is one human-readable line per check. With ``--json`` the
script prints a JSON object with stable field names so automation and AI
agents can consume the result directly.

Exit codes: 0 = all checks passed, 1 = one or more checks failed,
2 = usage or environment error.
"""

import argparse
import base64
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request


def run(cmd, timeout=60):
    """Run a command, returning (rc, stdout, stderr) without raising."""
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout
        )
        return proc.returncode, proc.stdout.strip(), proc.stderr.strip()
    except subprocess.TimeoutExpired:
        return 124, "", "timeout after %ss" % timeout
    except FileNotFoundError:
        return 127, "", "command not found: %s" % cmd[0]


def http_get(url, auth=None, timeout=30):
    """GET a URL, returning (status, body) without raising on HTTP errors."""
    req = urllib.request.Request(url, method="GET")
    if auth:
        token = base64.b64encode(auth.encode()).decode()
        req.add_header("Authorization", "Basic %s" % token)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read(200000).decode("utf-8", "replace")
    except urllib.error.HTTPError as err:
        return err.code, ""
    except Exception as err:  # URLError, timeout, connection refused
        return -1, str(err)


def main():
    parser = argparse.ArgumentParser(
        description="Validate a DeepOps Open OnDemand portal deployment."
    )
    parser.add_argument("--json", action="store_true", help="emit one JSON object")
    parser.add_argument("--portal", default="http://127.0.0.1",
                        help="portal base URL (default: http://127.0.0.1)")
    parser.add_argument("--user", default="new", help="portal login user (default: new)")
    parser.add_argument("--password", default="123456", help="portal login password")
    parser.add_argument("--expected-apps", default="jupyter",
                        help="comma-separated app dirs expected under "
                             "/var/www/ood/apps/sys. Only the local Jupyter app is "
                             "installed by default; other catalog apps are optional "
                             "(enable them in ood_apps_catalog). Add any you enabled "
                             "here, e.g. --expected-apps=jupyter,feko")
    args = parser.parse_args()

    result = {
        "ok": False,
        "httpd_active": False,
        "portal_up": False,
        "portal_status_anon": -1,
        "login_ok": False,
        "login_status": -1,
        "branding_ok": False,
        "htpasswd_user_ok": False,
        "cluster_config_ok": False,
        "apps_found": [],
        "apps_missing": [],
        "failures": [],
    }

    # 1. Apache service
    rc, out, err = run(["systemctl", "is-active", "httpd"])
    if rc == 0 and out == "active":
        result["httpd_active"] = True
    else:
        result["failures"].append(
            "httpd is not active: %s" % (err or out or "rc=%s" % rc)
        )

    # 2. Portal answers (anonymous request; 401/302/200 all prove it is up)
    status, body = http_get(args.portal + "/")
    result["portal_status_anon"] = status
    if status > 0:
        result["portal_up"] = True
    else:
        result["failures"].append("portal not reachable: %s" % body)

    # 3. Login with the configured user
    status, body = http_get(
        args.portal + "/pun/sys/dashboard/", auth="%s:%s" % (args.user, args.password)
    )
    result["login_status"] = status
    if status == 200:
        result["login_ok"] = True
        if "UltraLAB" in body:
            result["branding_ok"] = True
    else:
        result["failures"].append(
            "login as %s failed: HTTP %s" % (args.user, status)
        )

    # 4. htpasswd entry (only verifiable as root on the portal host)
    rc, out, err = run(["test", "-f", "/etc/httpd/.htpasswd"])
    if rc == 0:
        rc, out, _ = run(["grep", "-E", "^[^#]*%s:" % args.user, "/etc/httpd/.htpasswd"])
        result["htpasswd_user_ok"] = bool(out)
    if not result["htpasswd_user_ok"] and not result["login_ok"]:
        result["failures"].append(
            "user %s missing from /etc/httpd/.htpasswd" % args.user
        )

    # 5. Slurm cluster configuration for the portal
    rc, out, _ = run([
        "sh", "-c",
        "grep -l 'adapter: slurm' /etc/ood/config/clusters.d/*.yml 2>/dev/null | head -1",
    ])
    if rc == 0 and out:
        result["cluster_config_ok"] = True
        result["cluster_config"] = out
    else:
        result["failures"].append(
            "no clusters.d/*.yml with 'adapter: slurm' under /etc/ood/config"
        )

    # 6. Batch Connect apps
    expected = [a for a in args.expected_apps.split(",") if a]
    for app in expected:
        path = "/var/www/ood/apps/sys/%s" % app
        if os.path.isdir(path):
            result["apps_found"].append(app)
        else:
            result["apps_missing"].append(app)
    if result["apps_missing"] and not result["apps_found"]:
        result["failures"].append(
            "no expected apps installed under /var/www/ood/apps/sys "
            "(expected: %s)" % ", ".join(expected)
        )

    # 7. Branding in nginx_stage.yml (title shown in app navbars)
    rc, out, _ = run([
        "sh", "-c",
        "grep -E '^ondemand_title:' /etc/ood/config/nginx_stage.yml 2>/dev/null",
    ])
    if rc == 0 and out:
        result["nginx_stage_title"] = out
    else:
        result["failures"].append("ondemand_title not set in nginx_stage.yml")

    result["ok"] = not result["failures"]

    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        for key in (
            "httpd_active",
            "portal_up",
            "portal_status_anon",
            "login_ok",
            "login_status",
            "branding_ok",
            "htpasswd_user_ok",
            "cluster_config_ok",
        ):
            print("%s: %s" % (key, result[key]))
        print("apps_found: %s" % (", ".join(result["apps_found"]) or "-"))
        print("apps_missing: %s" % (", ".join(result["apps_missing"]) or "-"))
        for failure in result["failures"]:
            print("FAIL: %s" % failure)
        print("ok: %s" % result["ok"])

    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
