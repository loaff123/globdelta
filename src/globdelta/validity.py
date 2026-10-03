"""Finite dangerous-prefix DFA; no full component names or depths are stored."""
_DANGERS = ('.', '..', '.git')
_PREFIXES = tuple(sorted({'', *[word[:i] for word in (*_DANGERS, '.gitignore') for i in range(1, len(word) + 1)]}))
_STATES = tuple((root, prefix) for root in (True, False) for prefix in (*_PREFIXES, None) if root or prefix is None or prefix == '' or any(word.startswith(prefix) for word in _DANGERS))
_IDS = {state: number for number, state in enumerate(_STATES)}
START = _IDS[(True, '')]


def terminal(state: int) -> bool:
    _, prefix = _STATES[state]
    return prefix not in ('', '.', '..', '.git')


def step(state: int, byte: int) -> int | None:
    if not 32 <= byte <= 126:
        return None
    root, prefix = _STATES[state]
    if byte == 47:
        if not terminal(state) or (root and prefix == '.gitignore'):
            return None
        return _IDS[(False, '')]
    if prefix is None:
        return state
    next_prefix = prefix + chr(byte)
    if (root, next_prefix) in _IDS:
        return _IDS[(root, next_prefix)]
    return _IDS[(root, None)]
