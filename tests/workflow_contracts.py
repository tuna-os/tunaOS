"""Small lexical helpers for static workflow contracts, not an evaluator.

Only literal leaves of ``condition && value || fallback`` are understood.
Conditions are opaque: no context, function, truthiness or numeric coercion is
executed. Unknown value forms raise instead of being guessed from substrings.
"""

import re

_TOKEN = re.compile(
    r"\s+|'(?:[^']|'')*'|[A-Za-z_][A-Za-z0-9_-]*|[0-9]+"
    r"|&&|\|\||==|!=|<=|>=|[!<>().,\[\]*+-]"
)


def tokens(expression):
    result = []
    offset = 0
    stack = []
    for match in _TOKEN.finditer(expression):
        if match.start() != offset:
            raise ValueError(f"unsupported expression syntax: {expression!r}")
        offset = match.end()
        token = match.group()
        if token.isspace():
            continue
        if token in ("(", "["):
            stack.append(token)
        elif token in (")", "]"):
            if not stack or stack.pop() != {')': '(', ']': '['}[token]:
                raise ValueError(f"unbalanced expression: {expression!r}")
        result.append(token)
    if offset != len(expression) or stack or not result:
        raise ValueError(f"unsupported expression syntax: {expression!r}")
    return result


def split_top_level(parts, operator):
    groups = [[]]
    depth = 0
    for part in parts:
        if part in ("(", "["):
            depth += 1
        elif part in (")", "]"):
            depth -= 1
        if depth == 0 and part == operator:
            groups.append([])
        else:
            groups[-1].append(part)
    if any(not group for group in groups):
        raise ValueError("empty expression operand")
    return groups


def unparenthesized(parts):
    while len(parts) >= 2 and parts[0] == "(" and parts[-1] == ")":
        depth = 0
        for index, part in enumerate(parts):
            depth += (part == "(") - (part == ")")
            if depth == 0:
                break
        if index != len(parts) - 1:
            break
        parts = parts[1:-1]
    return parts


def expression_body(value):
    value = value.strip()
    if not (value.startswith("${{") and value.endswith("}}")):
        raise ValueError(f"expected one complete expression: {value!r}")
    return value[3:-2].strip()


def literal_choices(parts):
    """Conservative output set for truthy literals and bounded selectors.

    The truthy literal on each && arm is essential: an empty string or zero
    would fall through to the || arm. Reject unsupported leaves entirely.
    """
    parts = unparenthesized(parts)
    if len(parts) == 1:
        if re.fullmatch(r"[1-9][0-9]*", parts[0]):
            return [int(parts[0])]
        if parts[0].startswith("'"):
            literal = parts[0][1:-1].replace("''", "'")
            if literal:
                return [literal]
        raise ValueError("expected a nonempty string or positive integer literal")
    alternatives = split_top_level(parts, "||")
    if len(alternatives) == 2:
        selected_parts = unparenthesized(alternatives[0])
        # Removing parentheses must not expose an earlier OR which could
        # return an untrusted value before reaching the final literal arm.
        if len(split_top_level(selected_parts, "||")) != 1:
            raise ValueError("selector condition can bypass its literal arm")
        selected = split_top_level(selected_parts, "&&")
        if len(selected) >= 2:
            return literal_choices(selected[-1]) + literal_choices(alternatives[1])
    raise ValueError("unsupported value expression; use literal selector branches")


def interpolations(value):
    """Yield ${{ ... }} bodies, respecting quoted strings containing }}."""
    offset = 0
    while (start := value.find("${{", offset)) != -1:
        position = start + 3
        quoted = False
        while position < len(value):
            if value[position] == "'":
                if quoted and value[position:position + 2] == "''":
                    position += 2
                    continue
                quoted = not quoted
            elif not quoted and value[position:position + 2] == "}}":
                yield value[start + 3:position]
                offset = position + 2
                break
            position += 1
        else:
            raise ValueError("unterminated workflow expression")
