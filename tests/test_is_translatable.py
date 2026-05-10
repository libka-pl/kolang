"""H.1 + H.5: `_is_translatable` heuristic with format/placeholder stripping."""
import pytest

from kolang import Translate as T


@pytest.mark.parametrize('text, expected', [
    ('Hello', True),
    ('', False),
    ('   ', False),
    ('30100', False),
    ('.,!?', False),
    ('[B]Hello[/B]', True),
    ('[B][/B]', False),
    ('[CR]', False),
    ('[COLOR=0xff112233][/COLOR]', False),
    ('[COLOR red]Hello[/COLOR]', True),
    # Placeholder-aware (per-command):
    ('$INFO[X]', False),
    ('$INFO[X, prefix, suffix]', True),
    ('$INFO[X, [B], [/B]]', False),
    ("$INFO[X, 'Title: ', '']", True),  # v2 keeps prefix/suffix
    ('$INFO[X, " / ", ""]', False),
    ('$LOCALIZE[31000]', False),
    ('$ADDON[plugin.x 30100]', False),
    ('$NUMBER[X, format]', False),
    ('$LABEL[10]', False),
    ('$VAR[name]', False),
    ('Title: $INFO[X]', True),
    ('Hello $LOCALIZE[31000]', True),
    ('[B]$INFO[ListItem.Property(item.indent.label)][/B]', False),
])
def test_is_translatable(text, expected):
    assert T._is_translatable(text) is expected
