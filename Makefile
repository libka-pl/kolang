VER := $(shell sed -nE  '/^__version__/ { s/^.*=\s*(["'"'"'])(.*)\1.*$$/\2/; p }' kolang/__init__.py)
SRC := $(wildcard kolang/*.py)
PYZ := dist/kolang-$(VER).pyz

$(PYZ): $(SRC) Makefile
	rm -rf build/kolang
	mkdir -p build/kolang/kolang dist
	cp $(SRC) build/kolang/kolang/
	cp kolang/__main__.py build/kolang/
	python3 -m zipapp build/kolang -c -p '/usr/bin/env python3' -o $@

# Tag v$(VER) on a clean tree and build the pyz (push is up to you).
release:
	@test -z "$$(git status --porcelain --untracked-files=no)" || { echo 'Uncommitted changes' >&2; exit 1; }
	@! git rev-parse -q --verify 'refs/tags/v$(VER)' >/dev/null || { echo 'Tag v$(VER) exists' >&2; exit 1; }
	git tag -a 'v$(VER)' -m 'kolang $(VER)'
	$(MAKE) $(PYZ)

clean:
	rm -rf build dist

.PHONY: release clean
