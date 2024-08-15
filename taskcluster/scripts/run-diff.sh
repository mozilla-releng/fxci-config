#!/bin/bash

pip install --user -r requirements/test.txt &&
pip install --user --no-deps . &&
tc-admin diff --environment $ENVIRONMENT
