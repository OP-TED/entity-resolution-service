# Root Makefile — delegates all targets to src/Makefile.
# Exists so `make install`, `make test`, etc. work from the repo root (e.g. CI).
SHELL=/bin/bash -o pipefail

.PHONY: $(MAKECMDGOALS) _forward
.DEFAULT_GOAL := _forward

$(MAKECMDGOALS):
	@$(MAKE) -C src $@

_forward:
	@$(MAKE) -C src
