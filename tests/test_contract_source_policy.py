"""Inherited source declarations remain migration debt, never new permission."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.contracts.sources import classify_policy, violations


@pytest.mark.parametrize('field', ['baseurl', 'uri'])
@pytest.mark.parametrize('url', ['https://repo.tunaos.org/repo/', 'https://tideforge.org/repo/'])
def test_factory_urls_allow_rpm_and_apt(field, url):
    assert violations({'repo': {field: url}}) == []


@pytest.mark.parametrize('field', ['baseurl', 'uri'])
@pytest.mark.parametrize('url', ['https://repo.tunaos.org.attacker.invalid/repo/',
                                 'https://attacker.invalid/repo.tunaos.org/repo/',
                                 'https://repo.tunaos.org@attacker.invalid/repo/',
                                 'https://username:secret@repo.tunaos.org/repo/'])
def test_lookalike_and_credential_urls_fail_without_retaining_credentials(field, url):
    errors = violations({'repo': {field: url}})
    assert len(errors) == 1
    assert 'secret' not in str(errors)
    assert 'username' not in str(errors)


@pytest.mark.parametrize('source', ['copr', 'ppa', 'obs', 'aur', 'PPA'])
def test_forbidden_source_types_apply_recursively(source):
    errors = violations({'repos': [{source: ['legacy/project']}]})
    assert errors == [f'repos[0].{source}: {source} is not an approved package source']


def test_inherited_and_new_sources_are_distinguished():
    baseline = {'el10': {'copr': ['legacy/project']}}
    current = {'el10': {'copr': ['legacy/project']}, 'ubuntu': {'ppa': ['new/project']}}
    assert classify_policy(current, baseline) == {
        'inherited': ['el10.copr: copr is not an approved package source'],
        'forbiddenNew': ['ubuntu.ppa: ppa is not an approved package source']}
    assert classify_policy(current, None) == {
        'inherited': [], 'forbiddenNew': ['el10.copr: copr is not an approved package source',
                                        'ubuntu.ppa: ppa is not an approved package source']}


def test_removed_legacy_source_is_not_retained_as_current_debt():
    assert classify_policy({}, {'el10': {'copr': []}}) == {'inherited': [], 'forbiddenNew': []}


def test_replacing_legacy_provider_is_a_new_forbidden_input():
    result = classify_policy({'el10': {'copr': [{'repo': 'attacker/new'}]}},
                             {'el10': {'copr': [{'repo': 'legacy/project'}]}})
    assert result['forbiddenNew'], 'changing a legacy provider must not inherit its permission'
    assert not result['inherited']


def test_adding_provider_inside_legacy_list_is_new():
    baseline = {'el10': {'copr': [{'repo': 'legacy/project'}]}}
    current = {'el10': {'copr': [{'repo': 'legacy/project'}, {'repo': 'attacker/new'}]}}
    assert classify_policy(current, baseline)['forbiddenNew']


def test_changing_disallowed_repository_endpoint_does_not_inherit_permission():
    baseline = {'repo': {'uri': 'https://foreign.invalid/old'}}
    current = {'repo': {'uri': 'https://foreign.invalid/new'}}
    result = classify_policy(current, baseline)
    assert result['forbiddenNew']
    assert not result['inherited']


def test_source_policy_messages_do_not_retain_uri_credentials():
    result = classify_policy({'repo': {'uri': 'https://user:secret@repo.tunaos.org/repo/'}}, None)
    assert 'secret' not in str(result)
    assert 'user:' not in str(result)
    assert result['forbiddenNew']
