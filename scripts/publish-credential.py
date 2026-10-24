#!/usr/bin/env python3
"""Print the publish credential mode for the current CI job (#3801, RFC 016).

Inputs are environment variables so a workflow step can pass presence flags
without the secret values:

  TUNAOS_PUBLISH_DESTINATION    effective "<registry>/<namespace>" (the job's IMAGE_REGISTRY)
  TUNAOS_PUBLISH                "true" or "false": whether this job publishes
  GITHUB_REPOSITORY_OWNER       repository owner
  TUNAOS_PUBLISH_EVENT          event that decides trust: github.event_name, or the
                                triggering run's event for a workflow_run job
  TUNAOS_PUBLISH_SCOPE          vars.TUNAOS_PUBLISH_SCOPE, may be empty
  TUNAOS_HAS_PUBLISH_USERNAME   "true" or "false": secrets.TUNAOS_PUBLISH_USERNAME != ''
  TUNAOS_HAS_PUBLISH_PASSWORD   "true" or "false": secrets.TUNAOS_PUBLISH_PASSWORD != ''

Output is mode, registry, namespace and scope lines on stdout. Workflow callers
append those lines to ``$GITHUB_OUTPUT``; this program does not write that file
directly. A refusal prints one ``::error::`` line and exits 1. No workflow calls
this until the maintainer approves RFC 016.
"""
import os
import sys

from lib import publish_credentials


def flag(name):
    value = os.environ.get(name, '')
    if value not in ('true', 'false'):
        raise publish_credentials.CredentialError('invalid-input', f'{name} must be "true" or "false", got {value!r}')
    return value == 'true'


def main():
    env = os.environ
    try:
        leaked = [name for name in (publish_credentials.USERNAME_SECRET, publish_credentials.PASSWORD_SECRET)
                  if name in env]
        if leaked:
            # The resolver needs presence flags only. Refusing the values here
            # keeps a wiring mistake from widening where secrets are exposed.
            raise publish_credentials.CredentialError(
                'secret-in-resolver', f'{", ".join(leaked)} must not be passed to the resolver; pass TUNAOS_HAS_* flags')
        selection = publish_credentials.select(
            env.get('TUNAOS_PUBLISH_DESTINATION', ''),
            owner=env.get('GITHUB_REPOSITORY_OWNER', ''),
            event=env.get('TUNAOS_PUBLISH_EVENT', ''),
            publish=flag('TUNAOS_PUBLISH'),
            scope=env.get('TUNAOS_PUBLISH_SCOPE', ''),
            has_username=flag('TUNAOS_HAS_PUBLISH_USERNAME'),
            has_password=flag('TUNAOS_HAS_PUBLISH_PASSWORD'),
        )
    except publish_credentials.CredentialError as exc:
        print(f'::error::publish credential: {exc}', file=sys.stderr)
        return 1
    print(f'mode={selection.mode}')
    print(f'registry={selection.registry}')
    print(f'namespace={selection.namespace}')
    print(f'scope={selection.scope}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
