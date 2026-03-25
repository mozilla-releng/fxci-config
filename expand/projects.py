"""Expand projects.yml into flat project dicts.

Takes the parsed projects.yml and produces a dict of:
    {alias: {project fields...}}
matching ciadmin's Project.fetch_all() format.

Merge semantics:
    - defaults: name    -- start with that default's fields
    - extends: name     -- in project-defaults, inherit from another default
    - features+: {...}  -- merge into features from defaults (additive)
    - features: {...}   -- replace features entirely (no merge)

Shorthand formats:

    branches:  Strings like "main@3" expand to {name: "main", level: 3}.
               Plain strings like "default" expand to {name: "default"}.
               Full dicts are passed through unchanged.

    features:  A list of strings means all values are true:
                 features: [feat-a, feat-b]
               expands to:
                 features: {feat-a: true, feat-b: true}
               A dict is passed through as-is (including nested dicts for
               things like github-pull-request: {policy: public}).
               Mixing is not supported: use either list or dict form.

    features+: Same shorthand rules as features.
"""

import copy

import yaml


def _expand_branch(entry):
    """Expand a branch entry from shorthand to full dict.

    "main@3"  -> {"name": "main", "level": 3}
    "default" -> {"name": "default"}
    dict      -> passed through unchanged
    """
    if isinstance(entry, dict):
        return entry
    if not isinstance(entry, str):
        raise ValueError(f"Invalid branch entry: {entry!r}")
    if "@" in entry:
        name, level_str = entry.rsplit("@", 1)
        return {"name": name, "level": int(level_str)}
    return {"name": entry}


def _expand_branches(branches):
    """Expand a list of branch entries."""
    if branches is None:
        return None
    return [_expand_branch(b) for b in branches]


def _expand_features(features):
    """Expand features from list shorthand to dict.

    ["a", "b"]           -> {"a": True, "b": True}
    {"a": True, "b": {}} -> passed through unchanged
    None                 -> None
    """
    if features is None:
        return None
    if isinstance(features, list):
        return {name: True for name in features}
    return features


def _normalize(defn):
    """Expand all shorthand in a project/default definition."""
    if "branches" in defn:
        defn["branches"] = _expand_branches(defn["branches"])
    if "features" in defn:
        defn["features"] = _expand_features(defn["features"])
    if "features+" in defn:
        defn["features+"] = _expand_features(defn["features+"])
    return defn


def _resolve_defaults(project_defaults):
    """Resolve 'extends' chains in project-defaults.

    Returns a new dict where each default has its full resolved fields.
    Supports multi-level extends chains (resolved iteratively).
    """
    resolved = {}

    # Topological resolve: keep processing until all are resolved
    unresolved = dict(project_defaults)
    max_iterations = len(unresolved) + 1

    for _ in range(max_iterations):
        if not unresolved:
            break
        progress = False
        still_unresolved = {}

        for name, defn in unresolved.items():
            defn = _normalize(copy.deepcopy(defn))
            parent_name = defn.get("extends")

            if parent_name is None:
                # No parent -- already resolved
                resolved[name] = defn
                progress = True
            elif parent_name in resolved:
                # Parent is resolved -- merge
                parent = copy.deepcopy(resolved[parent_name])
                del defn["extends"]

                # Handle features+ (additive merge into parent features)
                features_plus = defn.pop("features+", None)

                # Merge defn over parent
                result = parent
                for k, v in defn.items():
                    if k == "features":
                        # Replace entirely
                        result[k] = v
                    else:
                        result[k] = v

                if features_plus:
                    result.setdefault("features", {})
                    result["features"].update(features_plus)

                resolved[name] = result
                progress = True
            else:
                still_unresolved[name] = defn

        unresolved = still_unresolved
        if not progress:
            raise ValueError(
                f"Circular or missing extends in project-defaults: "
                f"{list(unresolved.keys())}"
            )

    return resolved


def _apply_defaults(project, resolved_defaults):
    """Apply defaults to a single project entry.

    Returns a new dict with defaults merged in.
    """
    project = _normalize(copy.deepcopy(project))
    defaults_name = project.pop("defaults", None)

    if defaults_name is None:
        # No defaults -- return as-is (but handle features+ without defaults)
        features_plus = project.pop("features+", None)
        if features_plus:
            project.setdefault("features", {})
            project["features"].update(features_plus)
        return project

    if defaults_name not in resolved_defaults:
        raise ValueError(
            f"Unknown defaults reference: {defaults_name!r}"
        )

    base = copy.deepcopy(resolved_defaults[defaults_name])

    # Handle features+ (additive merge on top of defaults' features)
    features_plus = project.pop("features+", None)

    # Merge project fields over base
    for k, v in project.items():
        if k == "features":
            # Explicit features replaces entirely
            base[k] = v
        else:
            base[k] = v

    # Apply features+ after everything else
    if features_plus:
        base.setdefault("features", {})
        base["features"].update(features_plus)

    return base


def expand_projects(config):
    """Expand compressed projects config into flat dict.

    Args:
        config: Parsed YAML from projects.yml

    Returns:
        Dict of {alias: {project_info}} matching ciadmin's Project format.
        The alias key is NOT included in the value dict.
    """
    project_defaults = config.get("project-defaults", {})
    projects = config.get("projects", {})

    resolved_defaults = _resolve_defaults(project_defaults)

    result = {}
    for alias, project_entry in projects.items():
        expanded = _apply_defaults(project_entry, resolved_defaults)
        result[alias] = expanded

    return result


def expand_projects_from_file(path="projects.yml"):
    """Load and expand projects from a YAML file."""
    with open(path) as f:
        config = yaml.safe_load(f)
    return expand_projects(config)
