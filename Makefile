# Root Makefile — delegates all targets to src/Makefile.
# Exists so `make install`, `make test`, etc. work from the repo root (e.g. CI).
SHELL=/bin/bash -o pipefail

%:
	@$(MAKE) --no-print-directory -C src $@

.DEFAULT_GOAL := help
