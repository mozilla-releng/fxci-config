# FooFrix Windows worker

FooFrix uses the `gecko-t/win11-64-25h2-gpu-perf-experiment` worker pool.
The pool keeps one worker active and can increase to three workers. Each worker
uses regular-priority `Standard_NV12ads_A10_v5` capacity on the West US 3 Azure
Dedicated Host.

Run FooFrix as a Taskcluster task. Set `payload.maxRunTime` to at most `345600`
seconds (four days). The task deadline and expiry must be later than the planned
run time. The Windows image contains the Firefox build prerequisites. The task
can download and install more tools in its task-user profile.

If an installer needs administrator access, add these values to the task:

```yaml
payload:
  features:
    runAsAdministrator: true
  osGroups:
    - Administrators
scopes:
  - generic-worker:os-group:gecko-t/win11-64-25h2-gpu-perf-experiment/Administrators
  - generic-worker:run-as-administrator:gecko-t/win11-64-25h2-gpu-perf-experiment
```
