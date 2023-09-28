
import re
from pathlib import Path
from zipfile import ZipFile
# from argparse import ArgumentParser
from typing import Optional


def main(argv: Optional[list[str]] = None) -> None:
    # p = ArgumentParser()
    path = Path(__file__).parent
    init = path / '__init__.py'
    ver = re.search(r'''^\s*__version__\s*=\s*(['"])([^'"]+)\1''', init.read_text(), flags=re.MULTILINE)[2]
    out = Path() / f'kolang-{ver}.pyz'
    if out.exists():
        raise IOError(f'{out} exists')
    with ZipFile(out, 'w') as z:
        for p in path.glob('*.py'):
            z.write(p, f'kolang/{p.name}')
        z.write(path / '__main__.py', '__main__.py')
        p = next(path.glob('../.venv/lib/python3.*/site-packages/polib-*-py3.*.egg/polib.py'))
        z.write(p, 'polib.py')


if __name__ == '__main__':
    main()
