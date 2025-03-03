## Simple Kodi translate tool

Handle `./resources/language/resource.language.*/strings.po` and XML files.

Licence: MIT.


### Install

Use `kolang.pyz` or follow next steps.

Clone.

Create virtual env.
```bash
python -m venv .venv
```

Activate virtual env, do it every time if you start work with the tool.
```bash
source .venv/bin/activate
```

Install dependencies.
```bash
pip instal -r requirements.txt
```

### Usage

Use `kolang.pyz` or activate venv (every time if you start new terminal session).

Simple use case is call `python kolang.pyz PATH_TO_ADDON`.

Run tool
```
python kolang.pyz --help

usage: kolang [-h] [--version] [--type {addon,skin}] [-t PATH] [-L LANG] [--mark-translated] [--remove]
              [--id-from NUM] [--id-policy {max,min}] [--id-reserve ID[-ID]...] [--get-localized-string]
              [--no-get-localized-string] [-f FUNC] [--addon-id ADDON.ID] [--no-addon-id]
              [--obsolete {keep,mark,remove}] [-s PATH] [--backup-pattern PATTERN] [--no-backup-pattern]
              [--encoding ENCODING] [--po-wrap-width WIDTH] [-c CONFIG] [--verbose]
              [--debug] [--dry-run] [--generate-kolang-py]
              PATH [PATH ...]

Translate tool for Kodi XML (like gettext)

positional arguments:
  PATH                  path XML or PY file or addon folder

options:
  -h, --help            show this help message and exit
  --version             show program's version number and exit
  --type {addon,skin}   add-on folder structure
  -t PATH, --translation PATH
                        path string.po or folder with it or to resource folder, default "."
  -L LANG, --language LANG
                        new language like "en", "en_US", "pl"
  --mark-translated     copy original string to all non-translated entries
  --remove              remove unsused translations : IGNORED
  --id-from NUM         lowest label ID (start from) [30100]
  --id-policy {max,min}
                        new label ID policy [max]
  --id-reserve ID[-ID]...
                        reserve IDs, move another to keep the range empty
  --get-localized-string
                        handle getLocalizedString() [default]
  --no-get-localized-string
                        skip getLocalizedString()
  -f FUNC, --localized-function FUNC
                        extra get-localized-string function name
  --addon-id ADDON.ID   force addon id for $ADDON[]
  --no-addon-id         disable addon id, skip $ADDON[]
  --obsolete {keep,mark,remove}
                        what to do with obsolete/non-used translations [keep]
  -s PATH, --skip PATH  skip path
  --backup-pattern PATTERN
                        pattern for backup files [{}~]
  --no-backup-pattern   no backup files
  --encoding ENCODING   force files encoding [utf8]
  --po-wrap-width WIDTH
                        .po wrap width [999999]
  -c CONFIG, --config CONFIG
                        load config [ADDON/.kolang.json]
  --verbose             be more verbose
  --debug               be much more verbose
  --dry-run             do not modify anything
  --generate-kolang-py  generate kolang.py to use its L() in addon/plugin
```


### Configuration

Same options could be set in addon's `.kolang.json` file (or any pointed by `--config`).

Here is a default options. There is not necessary to use all names.  
And same examples (`languages`, `sources`).

```json
{
	"options": {
		"addon-id": null,
		"id-from": 30100,
		"id-policy": "max",
		"mark-translated": false,
		"get-localized-string": true,
		"obsoleted": "mark",
		"backup-pattern": "{}~",
        "po-wrap-width": 999999,
        "encoding": "utf-8"
	},

	"languages": ["en", "pl"],
	"sources": [
        "path/to/py_and_xml/dir",
        "path/to/file.py",
		{
			"path": "resources/settings.xml"
		},
		{
			"path": "path/to/file.py"
		},
		{
			"path": "path/to/py_and_xml/folder"
		},
		{
			"glob": "path/to/**/files*.py"
		},
		{
			"addon": "../path/to/another/addon"
		}
	],
    "skip": [
        "path/to/skipped/file.py",
        "path/to/skipped/folder",
        "path/**/glob/*sss"
    ],
    "localized-functions": [
        "locale_func_name",
        {
            "name": "locale_func_name"
        },
        {
            "regex": "locale_\\w+_regex"
        },
        {
            "name": "locale_func_name",
            "path": "only/**/in/this/*glob.py"
        }
    ]
}
```

* `options` – default options, described in `--help`
* `languages` – list of output languages, like `pl`, `en_US`
* `sources` – list of sources to scan
    * direct `PATH` means `{"path": "PATH"}`
    * `path` – path to folder or file
    * `glob` – path glob
    * `addon` – path to another addon, use it carefully
* `skip` – list of files and folders to skip in glob, folder scan
* `localized-functions` – define custom functions
    * `regex` – function name regex
    * `name` – just name (if `regex` is not used)
    * `path` – path glob where function is used
    * `type` – set function type
        * `L` – libka/kolang `L()` function, takes number and text
        * `GetLocalizedString` – Kodi `getLocalizedString()` like function, take number [default]
        * `Localize` – skin `$LOCALIZE[]` like stuff

Main usecase is define some `options`, set `languages`, add custom `localized-functions` (as direct strings).
