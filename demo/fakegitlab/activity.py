"""The team at work while the demo runs: the steps of the scenario's ACTIVITY, one every interval or so, so that the
dashboard's refreshes, notifications and sounds have something to show.

A step is a tuple whose first item names what happens:

    ("finish", iid)                      the merge request's running pipeline ends green
    ("approve", iid, username)           someone approves the merge request
    ("push", iid)                        its author pushes the commits the history keeps for later (LATER)
    ("reply", iid, thread, username, body, resolve)
                                         a reply in the scenario's thread number `thread`, resolving it or not
    ("merge", iid, username)             the merge request is merged, which starts the target's pipeline
    ("main", status)                     a pipeline of main ends with that status, "success" or "failed"
    ("finish main",)                     main's running pipeline ends green

The steps run once, in order: the last one leaves the project as it is.
"""
import random
import threading
import time

from .project import MAIN_JOBS
from .repository import MAIN

# A step lands within this fraction of the interval around it: changes do not tick like a clock.
JITTER = 0.4


class Activity:

    def __init__(
            self,
            project,
            interval_s,
            quiet
    ):
        self._project = project
        self._interval_s = interval_s
        self._quiet = quiet

    def start(self):
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        for step in self._project.dataset.ACTIVITY:
            time.sleep(self._interval_s * random.uniform(1 - JITTER, 1 + JITTER))
            with self._project.lock:
                self._apply(step)
            if not self._quiet:
                print(f"Demo activity: {' '.join(str(item) for item in step[:3])}", flush=True)

    def _apply(self, step):
        project = self._project
        kind, *args = step
        mr = project.mrs.get(args[0]) if args and isinstance(args[0], int) else None
        if kind == "finish":
            project.finish_pipeline(mr.pipelines[-1], project.dataset.JOBS, mr=mr)
        elif kind == "approve":
            project.approve(mr, args[1])
        elif kind == "push":
            project.push(mr)
        elif kind == "reply":
            project.reply(mr, *args[1:])
        elif kind == "merge":
            project.merge(mr, args[1])
        elif kind == "main":
            run = project.start_pipeline(MAIN, project.repository.tip(MAIN), "schedule", None, MAIN_JOBS)
            project.finish_pipeline(run, MAIN_JOBS, "unit_tests" if args[0] == "failed" else None)
        elif kind == "finish main":
            project.finish_pipeline(project.main_pipelines[-1], MAIN_JOBS)
        else:
            raise ValueError(f"unknown activity step: {kind}")
