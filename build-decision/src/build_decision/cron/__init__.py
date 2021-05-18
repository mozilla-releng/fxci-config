# -*- coding: utf-8 -*-

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.


from __future__ import absolute_import, print_function, unicode_literals

import logging
import traceback
from pathlib import Path

from ..util.keyed_by import evaluate_keyed_by
from ..util.schema import Schema
from . import action, decision
from .util import calculate_time, match_utc

# Functions to handle each `job.type` in `.cron.yml`.  These are called with
# the contents of the `job` property from `.cron.yml` and should return a
# sequence of (taskId, task) tuples which will subsequently be fed to
# createTask.
JOB_TYPES = {
    "decision-task": decision.run_decision_task,
    "trigger-action": action.run_trigger_action,
}

logger = logging.getLogger(__name__)

_cron_yml_schema = Schema.from_file(Path(__file__).with_name("schema.yml"))


def load_jobs(repository, revision):
    cron_yml = repository.get_file(".cron.yml", revision=revision)
    _cron_yml_schema.validate(cron_yml)

    # resolve keyed_by fields in each job
    jobs = cron_yml["jobs"]

    return {j["name"]: j for j in jobs}


def should_run(job, *, time, project):
    if "run-on-projects" in job:
        if project not in job["run-on-projects"]:
            return False
    # Resolve when key here, so we don't require it before we know that we
    # actually want to run on this branch.
    when = evaluate_keyed_by(
        job.get("when", []),
        "Cron job " + job["name"],
        {"project": project},
    )
    if not any(match_utc(time=time, sched=sched) for sched in when):
        return False
    return True


def run_job(job_name, job, *, repository, push_info, dry_run=False):
    job_type = job["job"]["type"]
    if job_type in JOB_TYPES:
        JOB_TYPES[job_type](
            job_name,
            job["job"],
            repository=repository,
            push_info=push_info,
            dry_run=dry_run,
        )
    else:
        raise Exception("job type {} not recognized".format(job_type))


def run(*, repository, branch, force_run, dry_run):
    time = calculate_time()

    push_info = repository.get_push_info(branch=branch)

    jobs = load_jobs(repository, revision=push_info["revision"])

    if force_run:
        job_name = force_run
        logger.info('force-running cron job "{}"'.format(job_name))
        run_job(
            job_name,
            jobs[job_name],
            repository=repository,
            push_info=push_info,
            dry_run=dry_run,
        )
        return

    failed_jobs = []
    for job_name, job in sorted(jobs.items()):
        if should_run(job, time=time, project=repository.project):
            logger.info('running cron job "{}"'.format(job_name))
            try:
                run_job(
                    job_name,
                    job,
                    repository=repository,
                    push_info=push_info,
                    dry_run=dry_run,
                )
            except Exception as exc:
                # report the exception, but don't fail the whole cron task, as that
                # would leave other jobs un-run.
                failed_jobs.append((job_name, exc))
                traceback.print_exc()
                logger.error(
                    'cron job "{}" run failed; continuing to next job'.format(job_name)
                )

        else:
            logger.info('not running cron job "{}"'.format(job_name))

    _format_and_raise_error_if_any(failed_jobs)


def _format_and_raise_error_if_any(failed_jobs):
    if failed_jobs:
        failed_job_names = [job_name for job_name, _ in failed_jobs]
        failed_job_names_with_exceptions = (
            '"{}": "{}"'.format(job_name, exc) for job_name, exc in failed_jobs
        )
        raise RuntimeError(
            "Cron jobs {} couldn't be triggered properly. "
            "Reason(s):\n * {}\nSee logs above for details.".format(
                failed_job_names, "\n * ".join(failed_job_names_with_exceptions)
            )
        )
