#!/usr/bin/env python3
"""Summarize explicit test reports without changing the test result."""
import argparse
import ast
import errno
import io
import json
import os
from pathlib import Path
import re
import stat
import tempfile
import xml.etree.ElementTree as ET

MAX_FILE = 8 * 1024 * 1024
MAX_TOTAL = 32 * 1024 * 1024
MAX_REPORTS = 256
MAX_FAILURES = 100
SOURCE_ROOT = Path(__file__).resolve().parents[1]
MAX_OUTPUT = 1024 * 1024


class ReportError(ValueError):
    """A fixed diagnostic code with optional numeric metadata, never content."""

    def __init__(self, code, size=None):
        super().__init__(code)
        self.code = code
        self.size = size


def bounded(value, limit):
    clean = re.sub(r'[\x00-\x1f\x7f]', ' ', str(value))
    return clean.encode('utf-8')[:limit].decode('utf-8', errors='ignore')


def read_report(root, relative, budget):
    parts = Path(relative).parts
    if not parts or any(part in ('..', '.') for part in parts) or Path(relative).is_absolute():
        raise ValueError('invalid report path')
    directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in parts[:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
            os.close(directory)
            directory = child
        descriptor = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        with os.fdopen(descriptor, 'rb') as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode):
                raise ReportError('nonregular-report')
            if info.st_size > MAX_FILE:
                raise ReportError('oversized-report', info.st_size)
            if budget[0] + info.st_size > MAX_TOTAL:
                raise ReportError('cumulative-report-size-limit', info.st_size)
            data = stream.read(MAX_FILE + 1)
            after = os.fstat(stream.fileno())
            if len(data) != info.st_size or (info.st_size, info.st_mtime_ns, info.st_ctime_ns) != (after.st_size, after.st_mtime_ns, after.st_ctime_ns):
                raise ReportError('report-changed-during-read', info.st_size)
            budget[0] += len(data)
            return data.decode('utf-8')
    finally:
        os.close(directory)


def empty():
    return {'tests': 0, 'failures': 0, 'errors': 0, 'skipped': 0,
            'failure_details': [], 'issues': [], 'truncated': False}


def issue(result, message):
    if len(result['issues']) < 100:
        result['issues'].append(bounded(message, 512))
    else:
        result['truncated'] = True


def source_test_id(classname, name, source_budget):
    # Only emit identifiers confirmed in repository source. Parameter values,
    # arbitrary failure text and dynamic test labels never enter the artifact.
    name = name.split('[', 1)[0]
    if len(classname) > 512 or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_.]*', classname):
        return 'unresolved-test'
    if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', name):
        return 'unresolved-test'
    parts = classname.split('.')
    for length in range(len(parts), 0, -1):
        relative = '/'.join(parts[:length]) + '.py'
        if not relative.startswith('tests/'):
            continue
        try:
            tree = ast.parse(read_report(SOURCE_ROOT, relative, source_budget))
        except (OSError, ValueError, SyntaxError, RecursionError, MemoryError):
            continue
        scope = parts[length:]
        body = tree.body
        for class_name in scope:
            classes = [node for node in body if isinstance(node, ast.ClassDef) and node.name == class_name]
            if len(classes) != 1:
                return relative + '::unresolved-test'
            body = classes[0].body
        names = {node.name for node in body
                 if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
        return relative + '::' + ('::'.join(scope + [name]) if name in names else 'unresolved-test')
    return 'unresolved-test'


def source_node_id(relative, scope, name, source_budget):
    # Direct reports carry an exact file boundary; never guess it from dots.
    if not re.fullmatch(r'tests/(?:[A-Za-z_][A-Za-z0-9_]*/)*[A-Za-z_][A-Za-z0-9_]*\.py', relative) or len(relative) > 480:
        return 'unresolved-test'
    if any(not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', part) for part in scope + [name]):
        return 'unresolved-test'
    try:
        body = ast.parse(read_report(SOURCE_ROOT, relative, source_budget)).body
    except (OSError, ValueError, SyntaxError, RecursionError, MemoryError):
        return 'unresolved-test'
    for class_name in scope:
        classes = [node for node in body if isinstance(node, ast.ClassDef) and node.name == class_name]
        if len(classes) != 1:
            return relative + '::unresolved-test'
        body = classes[0].body
    names = {node.name for node in body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
    return relative + '::' + ('::'.join(scope + [name]) if name in names else 'unresolved-test')


def source_collection_id(relative, source_budget):
    # Collection can fail before valid Python exists; confirm only the file.
    if len(relative) > 480 or not re.fullmatch(r'tests/(?:[A-Za-z_][A-Za-z0-9_]*/)*[A-Za-z_][A-Za-z0-9_]*\.py', relative):
        return 'unresolved-test'
    try:
        read_report(SOURCE_ROOT, relative, source_budget)
    except (OSError, ValueError):
        return 'unresolved-test'
    return relative + '::unresolved-test'


def source_report_id(relative, source_budget):
    value = relative.as_posix()
    if not value.startswith('bats/tests/') or not value.endswith('.bats.tap'):
        return None
    source = value[len('bats/'):-len('.tap')]
    if len(source) > 512 or not re.fullmatch(r'tests/[A-Za-z0-9_./-]+\.bats', source):
        return None
    try:
        read_report(SOURCE_ROOT, source, source_budget)
    except (OSError, ValueError):
        return None
    return source


def failure(result, identifier, kind):
    if len(result['failure_details']) < MAX_FAILURES:
        result['failure_details'].append({'test': bounded(identifier, 512), 'kind': kind})
    else:
        result['truncated'] = True


def parse_junit(text, result, source_budget):
    if re.search(r'<!\s*(?:DOCTYPE|ENTITY)', text, re.I) or '\x00' in text:
        raise ReportError('forbidden-xml-declaration-or-nul')
    depth = nodes = 0
    parser = ET.iterparse(io.StringIO(text), events=('start', 'end'))
    for event, node in parser:
        if event == 'start':
            depth += 1
            nodes += 1
            if depth > 64 or nodes > 100000:
                raise ReportError('xml-structure-limit')
            if nodes == 1 and node.tag not in ('testsuites', 'testsuite'):
                raise ReportError('unexpected-junit-root')
            continue
        depth -= 1
        if node.tag != 'testcase':
            continue
        result['tests'] += 1
        error = node.find('error')
        failed = node.find('failure')
        if error is not None or failed is not None:
            result['errors' if error is not None else 'failures'] += 1
            identifier = (source_test_id(node.get('classname', ''), node.get('name', ''), source_budget)
                          if len(result['failure_details']) < MAX_FAILURES else 'omitted')
            failure(result, identifier, 'error' if error is not None else 'failure')
        elif node.find('skipped') is not None:
            result['skipped'] += 1
        node.clear()


def parse_direct_summary(text, recorded_exit, source_budget):
    """Validate a bounded, source-checked summary; never trust arbitrary JSON."""
    if len(text.encode('utf-8')) > MAX_OUTPUT:
        raise ReportError('oversized-direct-summary')
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ReportError('invalid-direct-summary')
            result[key] = value
        return result
    try:
        document = json.loads(text, object_pairs_hook=pairs)
    except (ValueError, RecursionError) as error:
        raise ReportError('invalid-direct-summary') from error
    if not isinstance(document, dict) or set(document) != {'schema_version', 'kind', 'pytest'} or type(document['schema_version']) is not int or document['schema_version'] != 1 or document['kind'] != 'pytest-static-summary':
        raise ReportError('invalid-direct-summary')
    result = document['pytest']
    fields = set(empty()) | {'exit_code'}
    if not isinstance(result, dict) or set(result) != fields:
        raise ReportError('invalid-direct-summary')
    for key in ('tests', 'failures', 'errors', 'skipped'):
        if type(result[key]) is not int or not 0 <= result[key] <= 1000000000:
            raise ReportError('invalid-direct-summary')
    if type(result['exit_code']) is not int or not 0 <= result['exit_code'] <= 255 or result['exit_code'] != recorded_exit:
        raise ReportError('direct-exit-code-mismatch')
    if type(result['truncated']) is not bool or not isinstance(result['issues'], list) or len(result['issues']) > 100 or any(code != 'direct-reporter-error' for code in result['issues']):
        raise ReportError('invalid-direct-summary')
    details = result['failure_details']
    if not isinstance(details, list) or len(details) > MAX_FAILURES:
        raise ReportError('invalid-direct-summary')
    for detail in details:
        if not isinstance(detail, dict) or set(detail) != {'test', 'kind'} or detail['kind'] not in ('failure', 'error') or not isinstance(detail['test'], str):
            raise ReportError('invalid-direct-summary')
        identifier = detail['test']
        if identifier == 'unresolved-test':
            continue
        match = re.fullmatch(r'(tests/(?:[A-Za-z_][A-Za-z0-9_]*/)*[A-Za-z_][A-Za-z0-9_]*\.py)::((?:[A-Za-z_][A-Za-z0-9_]*::)*[A-Za-z_][A-Za-z0-9_]*|unresolved-test)', identifier)
        if not match or len(identifier) > 512:
            raise ReportError('invalid-direct-source-id')
        module, name = match.groups()
        if name == 'unresolved-test':
            if source_collection_id(module, source_budget) != identifier:
                raise ReportError('invalid-direct-source-id')
        elif source_node_id(module, name.split('::')[:-1], name.split('::')[-1], source_budget) != identifier:
            raise ReportError('invalid-direct-source-id')
    if any(sum(d['kind'] == kind for d in details) > result[count] for kind, count in (('failure', 'failures'), ('error', 'errors'))):
        raise ReportError('invalid-direct-summary')
    if len(details) < result['failures'] + result['errors'] and not result['truncated'] and not result['issues']:
        raise ReportError('incomplete-direct-summary')
    return result


def exit_code(text):
    if not re.fullmatch(r'(?:0|[1-9][0-9]{0,2})\n?', text) or int(text) > 255:
        raise ValueError('invalid recorded exit code')
    return int(text)


def parse_tap(text, result, identifier):
    count = 0
    plan = None
    for line in text.splitlines():
        if re.fullmatch(r'1\.\.[0-9]+(?:\s+#.*)?', line):
            if plan is not None:
                raise ValueError('duplicate TAP plan')
            plan = int(line.split('..', 1)[1].split()[0])
        match = re.match(r'^(not ok|ok)\s+([0-9]{1,6})(?:\s+(.*))?$', line)
        if match:
            count += 1
            result['tests'] += 1
            label = match.group(3) or ''
            if re.search(r'#\s*skip\b', label, re.I):
                result['skipped'] += 1
            elif match.group(1) == 'not ok':
                result['failures'] += 1
                failure(result, identifier + '::case-' + str(int(match.group(2))), 'failure')
        if line.startswith('Bail out!'):
            raise ValueError('TAP bailout')
    if plan is None or count != plan:
        raise ValueError('missing or incomplete TAP plan')


def summarize(root, direct=False):
    root = Path(root)
    result = {'schema_version': 1, 'pytest': empty(), 'bats': empty()}
    budget = [0]
    source_budget = [0]
    direct_result = None
    # Validate the compact report first so JUnit cannot exhaust its budget.
    try:
        result['pytest']['exit_code'] = exit_code(read_report(root, 'pytest.exit', budget))
    except (OSError, ValueError):
        issue(result['pytest'], 'invalid-or-missing-exit-code')
    if direct:
        try:
            if 'exit_code' not in result['pytest']:
                raise ReportError('missing-direct-exit-code')
            direct_result = parse_direct_summary(
                read_report(root, 'pytest-static.json', budget), result['pytest']['exit_code'], source_budget)
        except ReportError as error:
            issue(result['pytest'], error.code)
        except UnicodeDecodeError:
            issue(result['pytest'], 'invalid-utf8-direct-summary')
        except OSError as error:
            issue(result['pytest'], 'missing-direct-summary' if error.errno == errno.ENOENT else 'unreadable-direct-summary')
        except ValueError:
            issue(result['pytest'], 'invalid-direct-summary')
    try:
        parse_junit(read_report(root, 'pytest.xml', budget), result['pytest'], source_budget)
    except ReportError as error:
        issue(result['pytest'], error.code)
        if error.size is not None:
            result['pytest']['report_size_bytes'] = error.size
    except UnicodeDecodeError:
        issue(result['pytest'], 'invalid-utf8-junit')
    except ET.ParseError:
        issue(result['pytest'], 'invalid-xml-junit')
    except OSError as error:
        issue(result['pytest'], 'missing-junit' if error.errno == errno.ENOENT else
              'unsafe-junit-path' if error.errno in (errno.ELOOP, errno.ENOTDIR) else 'unreadable-junit')
    except ValueError:
        issue(result['pytest'], 'invalid-junit')
    if direct_result is not None:
        result['junit_issues'] = result['pytest']['issues']
        if 'report_size_bytes' in result['pytest']:
            result['junit_report_size_bytes'] = result['pytest']['report_size_bytes']
        result['pytest'] = direct_result
        result['pytest_source'] = 'direct'
    reports = []
    directory_limit = False
    bats = root / 'bats'
    if root.is_symlink() or bats.is_symlink():
        issue(result['bats'], 'symlink report directory')
    elif bats.is_dir():
        # Do not follow directory symlinks. Record each report by repository path.
        for index, (directory, dirs, files) in enumerate(os.walk(bats, followlinks=False)):
            if index >= MAX_REPORTS:
                directory_limit = True
                break
            if len(dirs) > MAX_REPORTS:
                directory_limit = True
            dirs[:] = sorted(dirs)[:MAX_REPORTS]
            for name in sorted(files):
                if name.endswith('.tap'):
                    reports.append((Path(directory) / name).relative_to(root))
                    if len(reports) > MAX_REPORTS:
                        break
            if len(reports) > MAX_REPORTS:
                break
    if directory_limit:
        result['bats']['truncated'] = True
        issue(result['bats'], 'directory count limit')
    if not reports:
        issue(result['bats'], 'no BATS reports')
    result['bats']['exit_codes'] = {}
    for relative in reports[:MAX_REPORTS]:
        identifier = source_report_id(relative, source_budget)
        if identifier is None:
            issue(result['bats'], 'unrecognized-source-report')
            continue
        try:
            parse_tap(read_report(root, relative, budget), result['bats'], identifier)
        except (OSError, ValueError):
            issue(result['bats'], identifier + ': invalid-or-missing-tap')
        try:
            code = exit_code(read_report(root, str(relative) + '.exit', budget))
            result['bats']['exit_codes'][bounded(identifier, 512)] = code
        except (OSError, ValueError):
            issue(result['bats'], identifier + ': invalid-or-missing-exit-code')
    if len(reports) > MAX_REPORTS:
        result['bats']['truncated'] = True
        issue(result['bats'], 'report count limit')
    result['input_bytes'] = budget[0]
    return result


def write_summary(path, data):
    """Publish complete bounded bytes without opening or replacing a target."""
    if len(data) > MAX_OUTPUT:
        raise ValueError('summary output limit')
    if path.parent.is_symlink():
        raise ValueError('symlink output directory')
    descriptor, temporary = tempfile.mkstemp(prefix='.test-summary-', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'wb') as output:
            if not stat.S_ISREG(os.fstat(output.fileno()).st_mode):
                raise ValueError('summary temporary file is not regular')
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        # Atomic no-overwrite publication: FIFO, directory, symlink and existing
        # regular targets all fail without being opened, truncated or removed.
        os.link(temporary, path, follow_symlinks=False)
    finally:
        os.unlink(temporary)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reports', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--direct', action='store_true')
    args = parser.parse_args()
    data = (json.dumps(summarize(args.reports, direct=args.direct), sort_keys=True, indent=2) + '\n').encode()
    write_summary(args.output, data)



if __name__ == '__main__':
    main()
