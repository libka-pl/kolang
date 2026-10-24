import sys

if __package__ is None and not hasattr(sys, 'frozen'):
    # direct call of __main__.py
    import os.path
    path = os.path.realpath(os.path.abspath(__file__))
    sys.path.insert(0, os.path.dirname(os.path.dirname(path)))


def _ensure_lxml():
    """Make lxml importable: use the private cache, install it there with pip on the first run (pyz has no lxml)."""
    try:
        from lxml import etree  # noqa: F401  (not just `lxml`: Debian shares dist-packages, etree is built per Python)
        return
    except ImportError:
        pass
    import os
    import shutil
    import subprocess
    import sysconfig
    from pathlib import Path
    if os.name == 'nt':
        base = Path(os.environ.get('LOCALAPPDATA') or Path.home() / 'AppData' / 'Local')
    else:
        base = Path(os.environ.get('XDG_CACHE_HOME') or Path.home() / '.cache')
    gil = 't' if sysconfig.get_config_var('Py_GIL_DISABLED') else ''
    target = base / 'kolang' / f'py{sys.version_info[0]}{sys.version_info[1]}{gil}-{sysconfig.get_platform()}'
    if not (target / 'lxml').is_dir():
        sys.stderr.write(f'kolang: installing lxml into {target}\n')
        tmp = target.with_name(f'{target.name}.tmp-{os.getpid()}')
        cmd = [sys.executable, '-m', 'pip', 'install', '--target', str(tmp), '--only-binary', ':all:', '--no-deps',
               '--disable-pip-version-check', '-q', 'lxml']
        ok = subprocess.run(cmd).returncode == 0
        if ok:
            try:
                os.replace(tmp, target)
            except OSError:  # concurrent first run won, use its copy
                pass
        shutil.rmtree(tmp, ignore_errors=True)
        if not ok or not (target / 'lxml').is_dir():
            sys.exit('kolang: lxml is required and could not be installed automatically.\n'
                     '  Debian/Ubuntu: sudo apt install python3-lxml\n'
                     '  other:         python -m pip install lxml\n'
                     f'  (cache: {target})')
    sys.path.insert(0, str(target))


_ensure_lxml()

import kolang  # noqa: E402

if __name__ == '__main__':
    kolang.main()
