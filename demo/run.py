"""MisteR Dashboard on a fictional project, without a GitLab: builds the project's git repository, starts a fake
GitLab and SonarQube, then the dashboard pointed at them.

    python3 demo/run.py                       # opens the demo dashboard in the browser
    python3 demo/run.py --scenario <name>     # another project, from demo/scenarios
    python3 demo/run.py --gitlab-only         # only the fake GitLab, for a dashboard started by hand

The project, its team and its merge requests are invented (the scenario's dataset.py and history.py) and placed
relative to the moment the demo starts. The team keeps working while it runs (--activity): pipelines end,
approvals come in, main breaks and recovers, a merge request is merged, so that the refreshes, notifications and
sounds have something to show. The fake GitLab's page /demo breaks GitLab and brings it back, to show the
dashboard during an outage. Nothing is kept: every start begins afresh, in a temporary directory
that holds the repository, its clone and the dashboard's glab configuration.
"""
import argparse
import importlib
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import webbrowser
from pathlib import Path

from fakegitlab import repository, server as fakegitlab
from fakegitlab.activity import Activity

DEMO_DIR = Path(__file__).resolve().parent
SERVER = DEMO_DIR.parent / "mr_dashboard" / "server.py"
SCENARIOS_DIR = DEMO_DIR / "scenarios"
DEFAULT_SCENARIO = "folio"
# Another port than the dashboard's default (8765): the page keeps its data per origin, so a real dashboard saved
# in the browser never shows up in a screenshot of the demo, and both can run side by side.
DEFAULT_PORT = 8775
DEFAULT_GITLAB_PORT = 8776
DEFAULT_ACTIVITY_S = 90
# The dashboard only reads a token from a glab configuration host whose name contains "gitlab".
TOKEN_HOST = "gitlab.demo"
DEMO_TOKEN = "demo"
GLAB_CONFIG = f"hosts:\n    {TOKEN_HOST}:\n        token: {DEMO_TOKEN}\n"


def main():
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(
            encoding="utf-8",
            errors="replace"
        )
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--scenario", choices=scenarios(), default=DEFAULT_SCENARIO, help="project to serve (default: %(default)s)")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="dashboard's port (default: %(default)s)")
    parser.add_argument("--gitlab-port", type=int, default=DEFAULT_GITLAB_PORT, help="fake GitLab's port (default: %(default)s)")
    parser.add_argument("--activity", type=int, default=DEFAULT_ACTIVITY_S, help="average seconds between two changes by the team, 0 for none (default: %(default)s)")
    parser.add_argument("--launch-in", action="append", default=[], help="where the AI button can open its sessions, as the dashboard's --launch-in, once per target (default: auto)")
    parser.add_argument("--gitlab-only", action="store_true", help="only start the fake GitLab")
    parser.add_argument("--no-open", action="store_true", help="do not open the browser")
    parser.add_argument("--quiet", action="store_true", help="do not log every request")
    args = parser.parse_args()

    dataset, history = load(args.scenario)
    work_dir = Path(tempfile.mkdtemp(prefix="mister-dashboard-demo-"))
    started_at = time.time()
    try:
        repo = repository.build(
            work_dir,
            history,
            dataset.PEOPLE,
            dataset.EMAIL_DOMAIN,
            started_at
        )
        try:
            gitlab = fakegitlab.start(
                args.gitlab_port,
                dataset,
                history,
                repo,
                started_at,
                args.quiet
            )
        except OSError as error:
            sys.exit(f"Port {args.gitlab_port} unavailable for the fake GitLab ({error.strerror}): try --gitlab-port.")
        if args.activity:
            Activity(gitlab.project, args.activity, args.quiet).start()
        glab_config = work_dir / "glab-config.yml"
        glab_config.write_text(GLAB_CONFIG, encoding="utf-8")
        command = [
            sys.executable, str(SERVER),
            "--gitlab-host", gitlab.base_url,
            "--gitlab-token-host", TOKEN_HOST,
            "--glab-config", str(glab_config),
            "--gitlab-project", dataset.PROJECT_PATH,
            "--pipeline-branch", dataset.PIPELINE_BRANCH,
            "--sonar-host", gitlab.base_url,
            "--sonar-project", dataset.SONAR_PROJECT,
            "--sonar-job", dataset.SONAR_JOB,
            "--pit-job", dataset.PIT_JOB,
            "--pit-marker", dataset.PIT_MARKER,
            "--repo-dir", str(repo.clone),
            "--port", str(args.port),
        ]
        for target in args.launch_in:
            command += ["--launch-in", target]
        command += ["--quiet"] if args.quiet else []
        print(f"Demo GitLab: {gitlab.base_url}, controls (GitLab outage) at {gitlab.base_url}/demo", flush=True)
        if args.gitlab_only:
            print("Dashboard: SONAR_TOKEN=demo no_proxy=127.0.0.1 " + " ".join(command[1:]))
            wait_forever()
            return
        dashboard = subprocess.Popen(
            command,
            env={**os.environ, "SONAR_TOKEN": DEMO_TOKEN, "no_proxy": "127.0.0.1,localhost", "NO_PROXY": "127.0.0.1,localhost"}
        )
        url = f"http://localhost:{args.port}/"
        print(f"Demo dashboard: {url}", flush=True)
        if not args.no_open:
            webbrowser.open(url)
        # Stopped by kill rather than Ctrl+C: the dashboard would otherwise outlive the fake GitLab it reads.
        signal.signal(
            signal.SIGTERM,
            lambda *_: sys.exit(0)
        )
        try:
            dashboard.wait()
        except KeyboardInterrupt:
            # Ctrl+C reaches the dashboard too, from the same console: it only has to be waited for.
            dashboard.wait()
        finally:
            if dashboard.poll() is None:
                dashboard.terminate()
                dashboard.wait()
    finally:
        shutil.rmtree(
            work_dir,
            ignore_errors=True
        )


def scenarios():
    """Scenario names: the packages of demo/scenarios with a dataset and a history."""
    return sorted(path.parent.name for path in SCENARIOS_DIR.glob("*/dataset.py") if (path.parent / "history.py").exists())


def load(name):
    """A scenario's dataset and history modules."""
    return (
        importlib.import_module(f"scenarios.{name}.dataset"),
        importlib.import_module(f"scenarios.{name}.history"),
    )


def wait_forever():
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
