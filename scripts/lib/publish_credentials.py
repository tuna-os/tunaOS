"""Choose the registry credential a publish job may use (#3801, RFC 016).

The decision reads only public facts: the effective publish destination, the
repository owner, the event, whether the run publishes, the credential scope
repository variable, and whether each credential secret is set. Secret values
never enter this module; callers pass presence flags.

Modes:
  none             the run does not publish; no destination login happens
  github-token     ghcr.io/<owner>[/...]; the existing GITHUB_TOKEN steps run
  registry-secret  any other destination; the TUNAOS_PUBLISH_* secrets apply

Every other outcome is a CredentialError. CI never falls back to
ghcr.io/<owner> when a non-owner destination lacks a usable credential.
"""
from __future__ import annotations

from dataclasses import dataclass
import re

from . import tunaos_config

USERNAME_SECRET = 'TUNAOS_PUBLISH_USERNAME'
PASSWORD_SECRET = 'TUNAOS_PUBLISH_PASSWORD'
SCOPE_VARIABLE = 'TUNAOS_PUBLISH_SCOPE'

# Events whose workflow source is already on a protected ref. Pull request,
# merge queue, comment and workflow_run events can carry unreviewed source.
TRUSTED_EVENTS = frozenset({'push', 'schedule', 'workflow_dispatch'})

# GitHub login names: ASCII letters, digits and single inner hyphens, 39 max.
OWNER = re.compile(r'[A-Za-z0-9](?:-?[A-Za-z0-9]){0,38}\Z')


class CredentialError(ValueError):
    """A publish credential cannot be selected; `code` names the reason."""

    def __init__(self, code: str, message: str):
        super().__init__(f'{code}: {message}')
        self.code = code


@dataclass(frozen=True)
class Selection:
    mode: str
    registry: str
    namespace: str

    @property
    def scope(self) -> str:
        return f'{self.registry}/{self.namespace}'


def _shown(value: str) -> str:
    # Untrusted text goes into a log line; repr() keeps a newline from starting
    # a new workflow command such as ::add-mask:: or ::stop-commands::.
    return repr(value)


def parse_destination(value: str, *, what: str = 'destination') -> tuple[str, str]:
    """Split "<registry>/<namespace>" and validate both parts like [build.publish]."""
    if not isinstance(value, str) or '/' not in value:
        raise CredentialError(f'invalid-{what}', f'{_shown(value)} is not "<registry>/<namespace>"')
    registry, namespace = value.split('/', 1)
    if not tunaos_config.REGISTRY.fullmatch(registry) or not tunaos_config.NAMESPACE.fullmatch(namespace):
        raise CredentialError(f'invalid-{what}', f'{_shown(value)} is not a lowercase registry host and namespace')
    return registry, namespace


def select(destination: str, *, owner: str, event: str, publish: bool, scope: str,
           has_username: bool, has_password: bool) -> Selection:
    """Return the credential mode for one publish destination."""
    if not isinstance(owner, str) or not OWNER.fullmatch(owner):
        raise CredentialError('invalid-owner', f'{_shown(owner)} is not a GitHub owner name')
    owner = owner.lower()
    # The workflow default is format('ghcr.io/{0}', github.repository_owner), which
    # keeps the owner's case; scripts/lib/publish-destination.sh lowercases the
    # namespace the same way before any image reference is written.
    if isinstance(destination, str) and '/' in destination:
        host, path = destination.split('/', 1)
        destination = f'{host}/{path.lower()}'
    registry, namespace = parse_destination(destination)
    selection = Selection('none', registry, namespace)
    if not publish:
        return selection
    if event not in TRUSTED_EVENTS:
        raise CredentialError('untrusted-event', f'{_shown(event)} runs may not publish; '
                              f'trusted events are {", ".join(sorted(TRUSTED_EVENTS))}')
    if scope:
        parse_destination(scope, what='scope')
    if registry == 'ghcr.io' and (namespace == owner or namespace.startswith(owner + '/')):
        if scope and scope != selection.scope:
            raise CredentialError('scope-mismatch', f'{SCOPE_VARIABLE}={_shown(scope)} but the destination is '
                                  f'{selection.scope}; correct [build.publish], IMAGE_REGISTRY or the variable')
        return Selection('github-token', registry, namespace)
    remedy = (f'set secrets {USERNAME_SECRET} and {PASSWORD_SECRET} and variable '
              f'{SCOPE_VARIABLE}={selection.scope}; CI does not fall back to ghcr.io/{owner}')
    if not has_username and not has_password:
        raise CredentialError('missing-credentials', f'{selection.scope} is not ghcr.io/{owner}; {remedy}')
    if not (has_username and has_password):
        absent = USERNAME_SECRET if not has_username else PASSWORD_SECRET
        raise CredentialError('partial-credentials', f'{absent} is not set; {remedy}')
    if not scope:
        raise CredentialError('missing-scope', f'{SCOPE_VARIABLE} is not set; {remedy}')
    if scope != selection.scope:
        raise CredentialError('scope-mismatch', f'{SCOPE_VARIABLE}={_shown(scope)} does not authorize '
                              f'{selection.scope}; the credential is used only for its exact scope')
    return Selection('registry-secret', registry, namespace)
