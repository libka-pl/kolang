# kolang tests

From the repository root, with kolang installed in the venv (`pip install -e . pytest`):

```bash
.venv/bin/python -m pytest tests/ -v
```

Or single file:
```bash
.venv/bin/python -m pytest tests/test_is_translatable.py -v
```

Each test file targets a feature or implementation step:

| File | Covers |
|---|---|
| `test_is_translatable.py` | `_is_translatable` heuristic, format/placeholder stripping |
| `test_translate_overrides.py` | `:translate=…:` parser & walk-back |
| `test_python_overrides.py` | `:python=…:` parser & walk-back |
| `test_l_comment.py` | `L(N, 'text')` comment parser & serializer (round-trip) |
| `test_fstring_extract.py` | `{…}` extraction with `{{` / `}}` escape |
| `test_python_mode.py` | python mode resolver (whitelist + override) |
| `test_matrix_g.py` | XML value vs L() comment decision matrix (read-side) |
| `test_l_write_idempotency.py` | auto-write L() comments, idempotency, `--` escape |
| `test_lvalues.py` | `lvalues` per-value support |
| `test_tail.py` | `node.tail` scan in xml_py |
| `test_template_skin.py` | skin templates: raw / fstring / overrides |
| `test_entities.py` | XML entities round-trip |

Functional tests use `tmp_path` to build minimal addon skeletons; the `kolang_run` fixture invokes `python -m kolang` from the venv.
