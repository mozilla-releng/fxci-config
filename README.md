# CI Configuration

This repository contains configuration for CI automation relating to the Gecko
source code.

Specifically, this configuration does not "ride the trains".  Instead, the head
of the default branch of this repository applies to all Gecko projects and
products.  Previous revisions exist for historical context, but have no
relevance to production.

Configuration in this repository includes:

* Information about the trains themselves -- Mercurial repositories, access
  levels, etc.
* Information about external resources -- URLs, pinned fingerprints, etc.
* Settings that should apply to all branches at once -- for example,
  proportional allocation of work across workerTypes

This repository was originally proposed in [Taskcluster
RFC#91](https://github.com/taskcluster/taskcluster-rfcs/issues/91).

## Structure

Data is stored in distinct YAML files in the root of this repository.  Each
file begins with a lengthy comment describing

* The purpose of the file
* The structure of the data in the file

Code to implement this configuration is in `src/ciadmin`.  The implementation
of `fxci` is in `src/fxci`.

## Access

Data in this repository is a "source of truth" about Gecko's CI automation.  It
can be accessed from anywhere, including

* Decision tasks, action tasks, and cron tasks
* Hooks
* Utility scripts and other integrations with the automation

Typically such access is either by cloning the repository or by simply fetching
a single file using the `raw` HTTP API method.

## Deprecation

Files in this directory are likely to live "forever".  It's difficult to
determine whether any branch or product still refers to a file, so deleting a
file always carries some risk of breakage.  Furthermore, regression bisection
might build an old revision that refers to a file no longer referred to in the
head commit.

# Managing CI Configuration

This repository introduces a management tool, `tc-admin`, for the management of
taskcluster resources, such as roles and hooks. It can download existing
resources and compare them to a stored configuration.  A collection of
resources also specifies the set of managed resources: this allows controlled
deletion of resources that are no longer expected.  It is based on
[`tc-admin`](https://github.com/taskcluster/tc-admin), the standard Taskcluster
administrative tool; see that library's documentation for more details than are
provided here.

## Initial Setup

1. Create and activate a new python virtualenv
1. pip install -e .
1. pip install -r requirements/local.txt
1. If you will be applying changes, ensure you have a way of generating
   taskcluster credentials, such as
   [taskcluster-cli](https://github.com/taskcluster/taskcluster/releases)

## Starting Concepts

This tool examines the contents of the `ci-configuration` repository, as well
as examining and applying changes to the running taskcluster configuration.

The `environment` describes the cluster being affected, such as `firefoxci` or
`staging`. There is also a
[community](https://github.com/mozilla/community-tc-config/) environment which
is managed separately.

You will usually want to check the changes that will be applied using `tc-admin
diff` and then apply them using `tc-admin apply`

You can supply `--grep` to both 'diff' and 'apply' options to limit the effects
to specific changes.

## Making Config Changes

1. Make changes in a local clone of this repository
1. Determine which taskcluster environment is relevant, such as `firefoxci`;
   the options are in `environments.yml`.
1. Use the `tc-admin diff` and `tc-admin check` to ensure the changes are what
   you expect, passing the appropriate `--environment`.

   Examples:

   * `tc-admin diff --environment=firefoxci`
   * `tc-admin diff --environment=firefoxci --ids-only` - only show the id's of
     the resources to be modified (much shorter!)
   * `tc-admin check --environment=firefoxci`

1. Submit changes to Phabricator for review.  On landing, the changes will be
   applied automaticallyi.

To apply changes locally (not recommended):

1. Generate some taskcluster credentials, such as `taskcluster signin`.
1. Apply the generated configuration using **either**
   * `tc-admin apply --environment=firefoxci` to apply all of the generated
     configuration **or**
   * `tc-admin apply --environment=firefoxci --grep my-changes` to apply only
     the selected areas of new configuration.

   Which you choose will depend on the current state of the repository and
   whether there are multiple changes waiting to be applied at a later time.

   You will be shown a summary of the changes that have been applied.

## More Information

* **`tc-admin diff --environment=firefoxci`**

   Generate a diff of the currently running taskcluster configuration, and the
   one generated from the tip of the ci-configuration repository.

* **`tc-admin diff --environment=firefoxci --grep somestring`**

   The `grep` option will return full configuration entries relating to the
   provided string. For example, if you have added a new action called `my-action`
   then `--grep my-action` will show only those entries.

* **`tc-admin generate`**

   Generates the expected CI configuration. Use `--json` to get JSON output.

* **`tc-admin current`**

   Produces the currently running CI configuration. This also understands
   `--json`.

   `generate` and `current` are two steps run automatically when using `tc-admin
   diff`

* **`tc-admin <sub-command> --help`**

  Each command should have helpful text here.  These commands are defined in
  [tc-admin](https://github.com/taskcluster/tc-admin); see that tool for more
  information and to report bugs.

* **`ci-admin <sub-command> ..`**

  For backward compatibility, the `ci-admin` command behaves exactly the same
  as `tc-admin`.

# Development

To update dependencies, make changes to `requirements/*.in`, then install
`pip-compile-multi` from PyPI and run `pip-compile-multi -s -g
requirements/base.in`.
