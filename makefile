# -*- makefile -*-
# this makefile contains rules for managing TICA code
# Copyright 2018 MIT
# Licensed under terms of the GPLv3

VERSION=$(shell cat VERSION)
PYTHON_VERSION=3.12

# docker compose reads these to tag images as tica:<VERSION> / tica-dev:<VERSION>
export TICA_VERSION=$(VERSION)
export TICA_UID=$(shell id -u)
export TICA_GID=$(shell id -g)
COMPOSE=docker compose
UV_IMAGE=ghcr.io/astral-sh/uv:python$(PYTHON_VERSION)-bookworm-slim
UV_COMPILE=uv pip compile pyproject.toml --universal --python-version $(PYTHON_VERSION) --generate-hashes --no-header -q

RELDIR=/sw/tica-versions
RELEASE_LABEL=tica-$(VERSION)

all: help

help:
	@echo "options include:"
	@echo "    build      build the tica:$(VERSION) runtime image"
	@echo "    build-dev  build the tica-dev:$(VERSION) development image"
	@echo "    test       run the installation smoke tests in the dev image"
	@echo "    reg-test   run the regression test in the dev image (needs DVC data, see README)"
	@echo "    shell      open a shell in the dev image on this checkout"
	@echo "    lock       regenerate requirements*.lock from pyproject.toml"
	@echo "    install    install the software"
	@echo "    release    install to the release space"
	@echo "    bless      make the latest release the blessed release"

info:
	@echo "    VERSION: $(VERSION)"
	@echo "    PYTHON_VERSION: $(PYTHON_VERSION)"

build:
	$(COMPOSE) build tica

build-dev:
	$(COMPOSE) build dev

test: build-dev
	$(COMPOSE) run --rm dev pytest

reg-test: build-dev
	# outputs left by a failed run already have a WCS, which changes the next fit
	rm -f reg_test/*.cal.fits.gz
	$(COMPOSE) run --rm -w /app/reg_test dev python run_reg_test.py

shell: build-dev
	$(COMPOSE) run --rm dev

lock:
	docker run --rm -v "$(CURDIR)":/src -w /src $(UV_IMAGE) sh -c '\
		$(UV_COMPILE) -o requirements.lock && \
		$(UV_COMPILE) --extra dev --extra data -c requirements.lock -o requirements-dev.lock'

ifndef $PREFIX
PREFIX=/opt/tica
endif
install:
	mkdir $(PREFIX)
	rsync -arv bin $(PREFIX)
	rsync -arv tica $(PREFIX)
#	rsync -arv examples $(PREFIX)
	rsync -arv calibration_* $(PREFIX)
	cp -p README.md LICENSE AUTHORS $(PREFIX)
	find $(PREFIX) -name "*~" -exec rm {} \;
	python -m compileall $(PREFIX)/tica

release:
	make install PREFIX=$(RELDIR)/$(RELEASE_LABEL)

bless:
	rm -f /sw/tica
	ln -s tica-versions/$(RELEASE_LABEL) /sw/tica

.PHONY: all help info build build-dev test reg-test shell lock install release bless
