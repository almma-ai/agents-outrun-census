EDITION ?= $(shell date -u +%Y-%m)
census: ; python -m census.cli scan --edition $(EDITION) && python -m census.cli aggregate --edition $(EDITION) && python -m census.cli publish
pilot:  ; python -m census.cli scan --edition $(EDITION) --max-items 120 --max-registry 400 --per-repo-cap 5 && python -m census.cli aggregate --edition $(EDITION) --per-repo-cap 8 && python -m census.cli publish
