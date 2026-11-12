"""Plain text presentation shared by overview and save confirmation."""
from .specs import SPECS

def format_value(value):
    if value is None:
        return 'Unknown'
    if isinstance(value, bool):
        return 'On' if value else 'Off'
    if isinstance(value, float):
        return '{:.2f}'.format(value).rstrip('0').rstrip('.')
    return str(value)

def equivalent(old, new):
    if isinstance(old, bool) or isinstance(new, bool):
        return type(old) is type(new) and old == new
    if isinstance(old, (int, float)) and isinstance(new, (int, float)):
        return abs(old - new) <= max(0.0001, abs(old) * 1e-6)
    return old == new

def change_summary(current, proposed):
    lines = []
    for spec in SPECS:
        key = spec.key
        if key not in proposed or key not in current:
            continue
        old, new = current[key], proposed[key]
        if not equivalent(old, new):
            lines.append('{}: {} -> {}{}'.format(spec.title, format_value(old),
                format_value(new), ' (restart)' if spec.restart else ''))
    return '\n'.join(lines) if lines else 'No setting changes.'
