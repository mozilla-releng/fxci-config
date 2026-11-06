import datetime

import jsonschema
import pytest
import requests.exceptions
import yaml

import build_decision.cron as cron
from build_decision.repository import NoPushesError

from . import TEST_DATA_DIR

_JOB = {
    "name": "j",
    "job": {
        "type": "decision-task",
        "treeherder-symbol": "J",
        "target-tasks-method": "j",
    },
}


def test_load_jobs(mocker):
    """Add cron load_jobs coverage."""
    with open(TEST_DATA_DIR / "cron.yml") as fh:
        cron_yml = yaml.safe_load(fh)

    fake_repo = mocker.MagicMock()
    fake_repo.get_file.return_value = cron_yml
    expected = {}
    for job in cron_yml["jobs"]:
        expected[job["name"]] = job

    assert cron.load_jobs(fake_repo, "rev") == expected


def test_load_jobs_404(mocker):
    fake_repo = mocker.MagicMock()
    fake_response = mocker.MagicMock()
    fake_response.status_code = 404
    fake_repo.get_file.side_effect = requests.exceptions.HTTPError(
        response=fake_response
    )
    assert cron.load_jobs(fake_repo, "rev") == {}


@pytest.mark.parametrize(
    "job, match_utc_bool, project, expected",
    (
        (
            # project doesn't match run-on-projects
            {
                "name": "name",
                "run-on-projects": ["project1", "project2"],
            },
            True,
            "invalid-project",
            False,
        ),
        (
            # project does match run-on-projects, time matches
            {
                "name": "name",
                "run-on-projects": ["project1", "project2"],
                "when": [{"hour": 4, "minute": 0}],
            },
            True,
            "project1",
            True,
        ),
        (
            # no run-on-projects, time doesn't match
            {
                "name": "name",
                "when": [{"hour": 4, "minute": 0}],
            },
            False,
            "project1",
            False,
        ),
        (
            # no run-on-projects, time matches
            {
                "name": "name",
                "when": [{"hour": 4, "minute": 0}],
            },
            True,
            "project1",
            True,
        ),
    ),
)
def test_should_run(mocker, job, match_utc_bool, project, expected):
    """Test the various branches in cron.should_run."""
    mocker.patch.object(cron, "match_utc", return_value=match_utc_bool)
    assert cron.should_run(job, time="fake_time", project=project) == expected


@pytest.mark.parametrize(
    "job, branch, expected",
    (
        # no run-on-branches: any branch
        ({"name": "n", "when": [{"hour": 4}]}, "anything", True),
        # exact match
        ({"name": "n", "run-on-branches": ["main"], "when": [{}]}, "main", True),
        ({"name": "n", "run-on-branches": ["main"], "when": [{}]}, "beta", False),
        # regexes must match the whole name
        ({"name": "n", "run-on-branches": ["esr.*"], "when": [{}]}, "esr140", True),
        ({"name": "n", "run-on-branches": ["esr"], "when": [{}]}, "esr140", False),
        ({"name": "n", "run-on-branches": ["main"], "when": [{}]}, "not-main", False),
        # no branch known: run-on-branches never matches
        ({"name": "n", "run-on-branches": ["main"], "when": [{}]}, None, False),
    ),
)
def test_should_run_branches(job, branch, expected):
    time = datetime.datetime(2026, 11, 4, 4, 0)
    assert cron.should_run(job, time=time, project="proj", branch=branch) == expected


@pytest.mark.parametrize(
    "branch, hour, expected",
    (
        ("main", 4, True),
        ("main", 10, False),
        ("release-1.0", 10, True),
        ("release-1.0", 4, False),
        ("other", 4, False),
        (None, 4, False),
    ),
)
def test_should_run_when_by_branch(branch, hour, expected):
    job = {
        "name": "n",
        "when": {
            "by-branch": {
                "main": [{"hour": 4, "minute": 0}],
                "release-.*": [{"hour": 10, "minute": 0}],
                "default": [],
            }
        },
    }
    time = datetime.datetime(2026, 11, 4, hour, 0)
    assert cron.should_run(job, time=time, project="proj", branch=branch) == expected


def test_should_run_when_nested_project_branch():
    job = {
        "name": "n",
        "when": {
            "by-project": {
                "proj": {"by-branch": {"main": [{"hour": 4}], "default": []}},
                "default": [],
            }
        },
    }
    time = datetime.datetime(2026, 11, 4, 4, 0)
    assert cron.should_run(job, time=time, project="proj", branch="main")
    assert not cron.should_run(job, time=time, project="proj", branch="beta")
    assert not cron.should_run(job, time=time, project="other", branch="main")


@pytest.mark.parametrize(
    "cron_yml, valid",
    (
        ({"jobs": [{**_JOB, "run-on-branches": ["main", "esr.*"]}]}, True),
        ({"jobs": [{**_JOB, "when": {"by-branch": {"main": [{"hour": 1}]}}}]}, True),
        (
            {
                "jobs": [
                    {
                        **_JOB,
                        "when": {
                            "by-branch": {
                                "main": {"by-project": {"p": [{"hour": 1}]}},
                                "default": [],
                            }
                        },
                    }
                ]
            },
            True,
        ),
        ({"jobs": [{**_JOB, "run-on-branches": "main"}]}, False),
        ({"jobs": [{**_JOB, "when": {"by-branch": {"main": [{"hr": 1}]}}}]}, False),
        ({"jobs": [{**_JOB, "when": {"by-colour": {"red": []}}}]}, False),
    ),
)
def test_schema_branches(mocker, cron_yml, valid):
    fake_repo = mocker.MagicMock()
    fake_repo.get_file.return_value = cron_yml
    if valid:
        cron.load_jobs(fake_repo, "rev")
    else:
        with pytest.raises(jsonschema.ValidationError):
            cron.load_jobs(fake_repo, "rev")


def test_run_passes_branch_to_should_run(mocker):
    fake_repo = mocker.MagicMock()
    mocker.patch.object(cron, "load_jobs", return_value={"j": {"name": "j"}})
    should_run = mocker.patch.object(cron, "should_run", return_value=False)
    cron.run(repository=fake_repo, branch="esr140", force_run=None, dry_run=True)
    assert should_run.call_args.kwargs["branch"] == "esr140"


@pytest.mark.parametrize(
    "job_type, raises",
    (("decision-task", False), ("trigger-action", False), ("unknown", Exception)),
)
def test_run_job(mocker, job_type, raises):
    """Raise if we have an invalid job_type."""
    job = {"job": {"type": job_type}}

    def fake_run(*args, **kwargs):
        pass

    fake_job_types = {
        "decision-task": fake_run,
        "trigger-action": fake_run,
    }

    mocker.patch.object(cron, "JOB_TYPES", new=fake_job_types)
    if raises:
        with pytest.raises(raises):
            cron.run_job("job_name", job, repository=None, push_info=None, dry_run=True)
    else:
        cron.run_job("job_name", job, repository=None, push_info=None, dry_run=True)


@pytest.mark.parametrize(
    "force_run, jobs",
    (
        (
            # Force run
            "job1",
            {
                "job1": {},
            },
        ),
        (
            # No force run, no jobs
            False,
            {},
        ),
        (
            # No force run, one job to run
            False,
            {
                "job1": {
                    "name": "job1",
                    "should_run": True,
                },
                "job2": {
                    "name": "job2",
                },
            },
        ),
        (
            # No force run, one failing job to run
            False,
            {
                "job1": {
                    "name": "job1",
                },
                "job2": {
                    "name": "job2",
                    "should_run": True,
                    "exception": Exception,
                },
            },
        ),
    ),
)
def test_run(mocker, force_run, jobs):
    """Add coverage for cron.run.

    ``jobs`` will look like
    {
        "job-name": {
            "name": "job-name",
            "exception": Exception,  # optional, if we want a failure
            "should_run": True,   # optional, if we want to run
        },
        ...
    }
    """
    fake_repo = mocker.MagicMock()

    def fake_run_job(job_name, job, **kwargs):
        if job.get("exception"):
            raise job["exception"]("raising")

    def fake_should_run(job, **kwargs):
        return job.get("should_run", False)

    mocker.patch.object(cron, "load_jobs", return_value=jobs)
    mocker.patch.object(cron, "run_job", new=fake_run_job)
    mocker.patch.object(cron, "should_run", new=fake_should_run)
    mocker.patch.object(cron, "_format_and_raise_error_if_any")
    cron.run(repository=fake_repo, branch="branch", force_run=force_run, dry_run=True)


def test_run_force_run_undefined_job(mocker):
    """Force-running a job this branch doesn't define names the job and branch."""
    fake_repo = mocker.MagicMock()
    mocker.patch.object(cron, "load_jobs", return_value={"nightly": {}})

    with pytest.raises(Exception, match="pinning-update is not defined"):
        cron.run(
            repository=fake_repo,
            branch="esr140",
            force_run="pinning-update",
            dry_run=True,
        )


def test_run_no_pushes(mocker):
    """Ensure that running cron.hook does nothing when no pushes are found,
    and doesn't raise an Exception."""
    fake_repo = mocker.MagicMock()

    def fake_get_push_info(*args, **kwargs):
        raise NoPushesError()

    fake_repo.get_push_info = fake_get_push_info

    mocker.patch.object(cron, "load_jobs")
    cron.run(repository=fake_repo, branch="branch", force_run=False, dry_run=False)
    assert cron.load_jobs.call_count == 0
    # no exceptions raised; nothing else to check!


def test_format_and_raise_error_if_any_with_failures():
    """Call _format_and_raise_error_if_any with failed_jobs."""
    with pytest.raises(RuntimeError):
        cron._format_and_raise_error_if_any(
            [
                ["one", Exception("one")],
                ["two", Exception("two")],
            ]
        )


def test_format_and_raise_error_if_any():
    """Call _format_and_raise_error_if_any without failed_jobs."""
    cron._format_and_raise_error_if_any([])
