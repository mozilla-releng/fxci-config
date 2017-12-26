# CI Configuration

This repository contains configuration for CI automation relating to the Gecko source code.

Specifically, this configuration does not "ride the trains".
Instead, the head of the default branch of this repository applies to all Gecko projects and products.
Previous revisions exist for historical context, but have no relevance to production.

Configuration in this repository includes:

* Information about the trains themselves -- Mercurial repositories, access levels, etc.
* Information about external resources -- URLs, pinned fingerprints, etc.
* Settings that should apply to all branches at once -- for example, proportional allocation of work across workerTypes

This repository was originally proposed in [Taskcluster RFC#91](https://github.com/taskcluster/taskcluster-rfcs/issues/91).

## Structure

Data is stored in distinct YAML files in the root of this repository.
Each file begins with a lengthy comment describing

* The purpose of the file
* The structure of the data in the file

## Access

Data in this repository is a "source of truth" about Gecko's CI automation.
It can be accessed from anywhere, including

* Decision tasks, action tasks, and cron tasks
* Hooks
* Utility scripts and other integrations with the automation

Typically such access is either by cloning the repository or by simply fetching a single file using the `raw` HTTP API method.

## Deprecation

Files in this directory are likely to live "forever".
It's difficult to determine whether any branch or product still refers to a file, so deleting a file always carries some risk of breakage.
Furthermore, regression bisection might build an old revision that refers to a file no longer referred to in the head commit.
