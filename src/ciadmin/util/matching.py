import attr


def listify(x):
    "Return a list, converting single items to singleton lists; but keep None"
    if x is None:
        return x
    if isinstance(x, list):
        return x
    return [x]


@attr.s(frozen=True)
class ProjectGrantee:
    access: list = attr.ib(type=list, converter=listify, default=None)
    level: list = attr.ib(type=list, converter=listify, default=None)
    alias: list = attr.ib(type=list, converter=listify, default=None)
    feature: list = attr.ib(type=list, converter=listify, default=None)
    repo_type: list = attr.ib(type=list, converter=listify, default=None)
    is_try: bool = attr.ib(type=bool, default=None)
    trust_domain: list = attr.ib(type=list, converter=listify, default=None)
    job: list = attr.ib(type=list, converter=listify, default="*")
    include_pull_requests: bool = attr.ib(type=bool, default=True)
    has_trust_project: bool = attr.ib(type=bool, default=None)


@attr.s(frozen=True)
class GroupGrantee:
    groups: list = attr.ib(type=list, converter=listify, default=None)


@attr.s(frozen=True)
class RoleGrantee:
    roles: list = attr.ib(type=list, converter=listify, default=None)


# convert grantees into instances..
def grantees(grant_to):
    if not isinstance(grant_to, list):
        raise ValueError(
            "grant `to` property must be a list (add `-` in yaml): {}".format(grant_to)
        )
    return [grantee_instance(ge) for ge in grant_to]


def grantee_instance(grantee):
    if len(grantee) != 1:
        raise ValueError("Malformed grantee (expected 1 key): {}".format(repr(grantee)))
    kind, content = list(grantee.items())[0]

    if kind == "project" or kind == "projects":
        if not isinstance(content, dict):
            raise ValueError(
                "grant `to.{}` property must be a dictionary "
                "(remove `-` in yaml): {}".format(kind, grantee)
            )
        return ProjectGrantee(**content)
    elif kind == "group" or kind == "groups":
        if not isinstance(content, (list, str)):
            raise ValueError(
                "grant `to.{}` property must be a list or string (add `-` "
                "in yaml): {}".format(kind, grantee)
            )
        return GroupGrantee(groups=content)
    elif kind == "role" or kind == "roles":
        if not isinstance(content, (list, str)):
            raise ValueError(
                "grant `to.{}` property must be a list or string (add `-` "
                "in yaml): {}".format(kind, grantee)
            )
        return RoleGrantee(roles=content)
    else:
        raise ValueError(
            "Malformed grantee (invalid top-level key): {}".format(repr(grantee))
        )


def match(grantee_values, proj_value):
    if grantee_values is None:
        return True
    if any(proj_value == grantee_value for grantee_value in grantee_values):
        return True
    return False


def feature_match(features, project):
    if features is None:
        return True
    for feature in features:
        if feature.startswith("!"):
            if project.feature(feature[1:]):
                return False
        else:
            if not project.feature(feature):
                return False
    return True


def glob_match(grantee_values, proj_value):
    if grantee_values is None:
        return True

    for grantee_value in grantee_values:
        if grantee_value == "*":
            return True
        elif grantee_value.endswith("*"):
            grantee_prefix = grantee_value[:-1]
            if proj_value.startswith(grantee_prefix):
                return True
        else:
            if proj_value == grantee_value:
                return True

    return False


def project_match(grantee, project):
    if not match(grantee.access, project.access):
        return False
    if not match(grantee.repo_type, project.repo_type):
        return False
    if not match(grantee.level, project.get_level(project.default_branch)):
        return False
    if not match(grantee.alias, project.alias):
        return False
    if not feature_match(grantee.feature, project):
        return False
    if grantee.is_try is not None:
        if project.is_try != grantee.is_try:
            return False
    if grantee.has_trust_project is not None:
        if grantee.has_trust_project != bool(project.trust_project):
            return False
    if not match(grantee.trust_domain, project.trust_domain):
        return False

    return True


def branch_match(grantee, branch):
    if not match(grantee.level, branch.level):
        return False

    return True
