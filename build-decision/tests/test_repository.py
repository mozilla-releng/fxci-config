import pytest
import redo
import requests
import yaml

import build_decision.repository as repository

from . import fake_redo_retry


@pytest.mark.parametrize(
    "repository_type, repo_url, revision, raises, expected_url",
    (
        (
            # HG, no revision
            "hg",
            "https://hg.mozilla.org/fake_repo",
            None,
            False,
            "https://hg.mozilla.org/fake_repo/raw-file/default/fake_path",
        ),
        (
            # HG, revision
            "hg",
            "https://hg.mozilla.org/fake_repo",
            "rev",
            False,
            "https://hg.mozilla.org/fake_repo/raw-file/rev/fake_path",
        ),
        (
            # Git, no revision
            "git",
            "https://github.com/org/repo",
            None,
            False,
            "https://api.github.com/repos/org/repo/contents/fake_path",
        ),
        (
            # Git, no revision, trailing slash
            "git",
            "https://github.com/org/repo/",
            None,
            False,
            "https://api.github.com/repos/org/repo/contents/fake_path",
        ),
        (
            # Git, revision
            "git",
            "https://github.com/org/repo",
            "rev",
            False,
            "https://api.github.com/repos/org/repo/contents/fake_path?ref=rev",
        ),
        (
            # Raise on private git url
            "git",
            "git@github.com:org/repo",
            "rev",
            Exception,
            None,
        ),
        (
            # Raise on unrecognized git url
            "git",
            "https://unknown-git-server.com:org/repo",
            "rev",
            Exception,
            None,
        ),
        (
            # Raise on unknown repository_type
            "unknown",
            None,
            None,
            Exception,
            None,
        ),
    ),
)
def test_get_file(mocker, repository_type, repo_url, revision, raises, expected_url):
    """Add coverage to ``Repository.get_file``."""

    fake_session = mocker.MagicMock()

    mocker.patch.object(repository, "SESSION", new=fake_session)
    mocker.patch.object(yaml, "safe_load")

    repo = repository.Repository(
        repo_url=repo_url,
        repository_type=repository_type,
    )
    if raises:
        with pytest.raises(raises):
            repo.get_file("fake_path", revision=revision)
    else:
        repo.get_file("fake_path", revision=revision)
        expected_headers = {}
        if repo_url.startswith("https://github.com"):
            expected_headers = {"Accept": "application/vnd.github.raw+json"}
        fake_session.get.assert_called_with(
            expected_url, headers=expected_headers, timeout=60
        )


def test_fetch_file_success(mocker):
    fake_response = mocker.MagicMock()
    fake_response.text = "file content"
    fake_session = mocker.MagicMock()
    fake_session.get.return_value = fake_response

    mocker.patch.object(repository, "SESSION", new=fake_session)
    mocker.patch.object(redo, "retry", new=fake_redo_retry)

    repo = repository.Repository(
        repo_url="https://hg.mozilla.org/fake_repo",
        repository_type="hg",
    )
    result = repo._fetch_file("https://example.com/file", {})
    assert result == "file content"


def test_fetch_file_non_404_error(mocker):
    fake_response = mocker.MagicMock()
    fake_response.status_code = 500
    fake_response.raise_for_status.side_effect = requests.HTTPError("500")
    fake_session = mocker.MagicMock()
    fake_session.get.return_value = fake_response

    mocker.patch.object(repository, "SESSION", new=fake_session)
    mocker.patch.object(redo, "retry", new=fake_redo_retry)

    repo = repository.Repository(
        repo_url="https://hg.mozilla.org/fake_repo",
        repository_type="hg",
    )
    with pytest.raises(requests.HTTPError):
        repo._fetch_file("https://example.com/file", {})


def test_fetch_file_404_delegates(mocker):
    fake_response = mocker.MagicMock()
    fake_response.status_code = 404
    fake_response.raise_for_status.side_effect = requests.HTTPError("404")
    fake_session = mocker.MagicMock()
    fake_session.get.return_value = fake_response

    mocker.patch.object(repository, "SESSION", new=fake_session)
    mocker.patch.object(redo, "retry", new=fake_redo_retry)

    repo = repository.Repository(
        repo_url="https://hg.mozilla.org/fake_repo",
        repository_type="hg",
    )
    mock_handle = mocker.patch.object(
        repository.Repository,
        "_handle_file_not_found",
        side_effect=repository.RetryableError("lag"),
    )
    with pytest.raises(repository.RetryableError):
        repo._fetch_file("https://example.com/file", {}, revision="rev")
    mock_handle.assert_called_once()


def test_handle_file_not_found_hg_revision_exists(mocker):
    json_rev_response = mocker.MagicMock()
    json_rev_response.status_code = 200
    fake_session = mocker.MagicMock()
    fake_session.get.return_value = json_rev_response

    mocker.patch.object(repository, "SESSION", new=fake_session)

    repo = repository.Repository(
        repo_url="https://hg.mozilla.org/fake_repo",
        repository_type="hg",
    )
    original_error = requests.HTTPError("404")
    with pytest.raises(requests.HTTPError) as exc_info:
        repo._handle_file_not_found(original_error, "https://example.com/file", "rev")
    assert exc_info.value is original_error


def test_handle_file_not_found_hg_revision_not_replicated(mocker):
    json_rev_response = mocker.MagicMock()
    json_rev_response.status_code = 404
    fake_session = mocker.MagicMock()
    fake_session.get.return_value = json_rev_response

    mocker.patch.object(repository, "SESSION", new=fake_session)

    repo = repository.Repository(
        repo_url="https://hg.mozilla.org/fake_repo",
        repository_type="hg",
    )
    with pytest.raises(repository.RetryableError):
        repo._handle_file_not_found(
            requests.HTTPError("404"), "https://example.com/file", "rev"
        )


def test_handle_file_not_found_hg_probe_fails(mocker):
    fake_session = mocker.MagicMock()
    fake_session.get.side_effect = requests.ConnectionError("probe failed")

    mocker.patch.object(repository, "SESSION", new=fake_session)

    repo = repository.Repository(
        repo_url="https://hg.mozilla.org/fake_repo",
        repository_type="hg",
    )
    with pytest.raises(repository.RetryableError):
        repo._handle_file_not_found(
            requests.HTTPError("404"), "https://example.com/file", "rev"
        )


def test_handle_file_not_found_hg_no_revision(mocker):
    fake_session = mocker.MagicMock()
    mocker.patch.object(repository, "SESSION", new=fake_session)

    repo = repository.Repository(
        repo_url="https://hg.mozilla.org/fake_repo",
        repository_type="hg",
    )
    with pytest.raises(repository.RetryableError):
        repo._handle_file_not_found(
            requests.HTTPError("404"), "https://example.com/file", None
        )
    fake_session.get.assert_not_called()


def test_handle_file_not_found_git(mocker):
    fake_session = mocker.MagicMock()
    mocker.patch.object(repository, "SESSION", new=fake_session)

    repo = repository.Repository(
        repo_url="https://github.com/org/repo",
        repository_type="git",
    )
    with pytest.raises(repository.RetryableError):
        repo._handle_file_not_found(
            requests.HTTPError("404"), "https://example.com/file", "rev"
        )
    fake_session.get.assert_not_called()


@pytest.mark.parametrize(
    "branch, revision, pushes, raises, expected",
    (
        (
            # NoPushesError on empty pushes
            "branch",
            None,
            {"pushes": []},
            repository.NoPushesError,
            None,
        ),
        (
            # ValueError on >1 pushes
            None,
            None,
            {"pushes": ["one", "two"]},
            ValueError,
            None,
        ),
        (
            # ValueError if rev and rev is not tip of changesets
            None,
            "secondary_rev",
            None,
            ValueError,
            None,
        ),
        (
            None,
            "rev",
            None,
            None,
            {
                "owner": "me",
                "pushlog_id": 1,
                "pushdate": "now",
                "revision": "rev",
                "base_revision": "baserev",
                "files": ["file1.py"],
            },
        ),
        (
            None,
            None,
            {
                "pushes": {
                    "1": {
                        "changesets": [
                            {"parents": ["baserev"], "files": ["a.py"]},
                            {"node": "rev", "files": ["b.py"]},
                        ],
                        "user": "me",
                        "date": "now",
                    }
                }
            },
            None,
            {
                "owner": "me",
                "pushlog_id": "1",
                "pushdate": "now",
                "revision": "rev",
                "base_revision": "baserev",
                "files": ["a.py", "b.py"],
            },
        ),
    ),
)
def test_hg_push_info(mocker, branch, revision, pushes, raises, expected):
    """Add coverage for hg Repository.get_push_info"""

    if pushes is None:
        pushes = {
            "pushes": {
                1: {
                    "user": "me",
                    "date": "now",
                    "changesets": [
                        {"node": "rev", "parents": ["baserev"], "files": ["file1.py"]}
                    ],
                }
            }
        }

    repo = repository.Repository(
        repo_url="https://hg.mozilla.org/fake_repo",
        repository_type="hg",
    )

    fake_session = mocker.MagicMock()
    fake_response = mocker.MagicMock()
    fake_session.get.return_value = fake_response
    fake_response.json.return_value = pushes

    mocker.patch.object(repository, "SESSION", new=fake_session)
    # We can't seem to mock the @redo.retriable decorator before it wraps the
    # function, but we can reach into @redo.retriable, which calls redo.retry,
    # and mock redo.retry
    mocker.patch.object(redo, "retry", new=fake_redo_retry)

    if raises:
        with pytest.raises(raises):
            repo.get_push_info(revision=revision, branch=branch)
    else:
        assert repo.get_push_info(revision=revision, branch=branch) == expected


@pytest.mark.parametrize(
    "branch, revision, repo_url, token, raises, expected",
    (
        (
            # Die if git rev is specified
            None,
            "rev",
            "https://github.com/org/repo",
            None,
            Exception,
            None,
        ),
        (
            # Die on git@github
            "main",
            None,
            "git@github.com:org/repo",
            None,
            Exception,
            None,
        ),
        (
            # Die on non-github
            None,
            None,
            "https://some-other-git-server.com:org/repo",
            None,
            Exception,
            None,
        ),
        (
            # Use a token on main
            "main",
            None,
            "https://github.com/org/repo",
            "token",
            None,
            {"branch": "main", "revision": "rev"},
        ),
    ),
)
def test_git_push_info(mocker, branch, revision, repo_url, token, raises, expected):
    """Add coverage for git Repository.get_push_info"""

    repo = repository.Repository(
        repo_url=repo_url,
        repository_type="git",
        github_token=token,
    )

    objects = {
        "object": {
            "sha": "rev",
        },
    }

    fake_session = mocker.MagicMock()
    fake_response = mocker.MagicMock()
    fake_session.get.return_value = fake_response
    fake_response.json.return_value = objects

    mocker.patch.object(repository, "SESSION", new=fake_session)

    # We can't seem to mock the @redo.retriable decorator before it wraps the
    # function, but we can reach into @redo.retriable, which calls redo.retry,
    # and mock redo.retry
    mocker.patch.object(redo, "retry", new=fake_redo_retry)

    if raises:
        with pytest.raises(raises):
            repo.get_push_info(revision=revision, branch=branch)
    else:
        assert repo.get_push_info(revision=revision, branch=branch) == expected


@pytest.mark.parametrize(
    "branch, revision, raises",
    (
        (
            # Raise on both branch and revision
            "branch",
            "revision",
            ValueError,
        ),
        (
            # Die on unknown repository_type
            None,
            None,
            Exception,
        ),
    ),
)
def test_unknown_push_info(branch, revision, raises):
    """Add coverage for non-hg non-git Repository.get_push_info"""
    repo = repository.Repository(
        repo_url="url",
        repository_type="unknown",
    )
    with pytest.raises(raises):
        repo.get_push_info(revision=revision, branch=branch)


@pytest.mark.parametrize(
    "repository_type, repo_url, raises, expected",
    (
        (
            "hg",
            "https://hg.mozilla.org/repo/path/",
            None,
            "repo/path",
        ),
        (
            "git",
            "https://github.com/org/repo/",
            None,
            "org/repo",
        ),
        (
            "unknown",
            "",
            AttributeError,
            None,
        ),
    ),
)
def test_repo_path(repository_type, repo_url, raises, expected):
    """Add coverage to Repository.repo_path"""
    repo = repository.Repository(
        repo_url=repo_url,
        repository_type=repository_type,
    )
    if raises:
        with pytest.raises(raises):
            repo.repo_path
    else:
        assert repo.repo_path == expected


@pytest.mark.parametrize(
    "kwargs, expected",
    (
        (
            {"repo_url": "https://repo.url", "repository_type": "git"},
            {"url": "https://repo.url", "project": None, "level": None, "type": "git"},
        ),
    ),
)
def test_to_json(kwargs, expected):
    """Add coverage to ``Repository.to_json``."""
    repo = repository.Repository(**kwargs)
    assert repo.to_json() == expected
