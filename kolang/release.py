from __future__ import annotations

import re
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
from argparse import ArgumentParser

import polib as _polib


def main(argv: list[str] | None = None) -> None:
    p = ArgumentParser()
    p.add_argument('-f', '--force', action='store_true', help='force overwrite output pyz')
    args = p.parse_args(argv)

    path = Path(__file__).parent
    init = path / '__init__.py'
    ver = re.search(r'''^\s*__version__\s*=\s*(['"])([^'"]+)\1''', init.read_text(), flags=re.MULTILINE)[2]
    out = Path() / f'kolang-{ver}.pyz'
    if not args.force and out.exists():
        raise IOError(f'{out} exists')
    with ZipFile(out, 'w', compression=ZIP_DEFLATED, compresslevel=9) as z:
        for p in path.glob('*.py'):
            z.write(p, f'kolang/{p.name}')
        z.write(path / '__main__.py', '__main__.py')
        z.write(_polib.__file__, 'polib.py')


if __name__ == '__main__':
    main()
