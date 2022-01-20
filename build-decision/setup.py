from setuptools import find_packages, setup

with open("requirements/base.in", "r") as fp:
    requirements = fp.read().splitlines()

setup(
    name="build-decision",
    version="1.0.0",
    description="Administration of runtime configuration "
    "(Taskcluster settings) for Firefox CI",
    author="Dustin Mitchell",
    author_email="dustin@mozilla.com",
    url="https://hg.mozilla.org/ci/ci-configuration",
    packages=find_packages("src"),
    package_dir={"": "src"},
    install_requires=requirements,
    classifiers=["Programming Language :: Python :: 3"],
    entry_points={"console_scripts": ["build-decision = build_decision.cli:main"]},
    package_data={"build_decision.cron": ["schema.yml"]},
)
