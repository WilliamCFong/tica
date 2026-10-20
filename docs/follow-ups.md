# Follow-ups

Open items found while reviewing installation and the production scripts (2026-10-19). Nothing here has been changed yet. Performance items are tracked separately in [performance-recommendations.md](performance-recommendations.md).

## `bin/tica-doall-automate` (production cron job)

This script runs the TICA production pipeline on MIT's POC machines. It finds the newest orbit in `/pdo/poc-data/orbits/`, skips segments already listed in `tica-processing-records.txt`, and then runs, in order: ephemeris refresh, `tica-calibrate-tso`, `tica-darktime`, WCS steps 1 (on `o1a` only) and 2, `tica-stage-delivery`, and `tica-check-delivery`. It emails a fixed list of recipients and appends to the processing records.

### Bugs

1. ~~**Exit codes are misread in every error handler**~~ *Fixed on `fix-doall-exit-codes`. That branch also fixes `tica-wcs-step1-allcam-allccd` and `tica-wcs-step2-allcam-allccd`: they set `errorflag` inside background jobs, where it never reached the parent shell, so they always exited 0.* (lines 172–180, 189–197, 215–223, 233–241). Inside `cmd || { if [[ $? == 2 ]] …; elif [[ $? == 1 ]] …; else …; fi }`, the second `$?` is the result of the first `[[ … ]]` test (1), not the command's exit code. As a result, every failure other than code 2 is treated as recoverable and processing continues, and the "Unknown error, abort!" branches can never run. Fix: capture the code once, e.g. `cmd || { rc=$?; case $rc in 2) …;; 1) …;; *) …;; esac; }`.
2. ~~**The duplicate-run guard checks the wrong `$?`**~~ *Fixed on `fix-doall-exit-codes`.* (line 144). `$?` there belongs to the preceding `echo`, so the condition is always true. The guard still works, because the regex match on the next line does the real check, but it reads as if grep's exit code were tested. Also, `[[ $compstr =~ $checkstr ]]` treats the record line as a regex. Use a quoted match (`== *"$checkstr"*`) or `grep -qF`.
3. **The records file is copied back to the repository only in the "major error" branch** (line 306). The success and ordinary-error branches never sync it, so `tica-processing-records.txt` in the repo lags behind production. Move the copy after the branches, or stop tracking the file in git.
4. **The ephemeris refresh and the ephemeris used by step 2 can diverge.** `tica-dump-ephemeris.py --outdir /pdo/users/faus/python/tica/src/btjd/` writes into the source checkout. Since the `fix-install-docker` branch, `step2_mkwcs.py` reads `tess_ephem.txt` from the installed `btjd` package. With an editable install (`pip install -e`) these are the same file. With a regular install, step 2 would silently use the ephemeris from install time. Either keep production on an editable install (and document why), or have the dump write to a configurable location that step 2 reads, e.g. an environment variable.

### Robustness and maintenance

5. **Arguments are run through `eval`** (line 100). Any argument becomes shell code. This is acceptable from cron, but risky if the script is ever run with untrusted input. Parse `key=value` pairs explicitly against an allow-list (`orbit`, `segment`).
6. **The orbit→sector and segment mappings are hardcoded** (lines 46–58, 109–126). The special cases for orbits 203–208 and the switch from `(orbit−7)/2` to `(orbit−11)/2` must be edited by hand whenever the mission timeline changes. Move them to a lookup table (orbit → sector, segment) that can be updated without code changes, or derive them from POC metadata if available.
7. **Site-specific configuration is hardcoded**: data paths (`/pdo/...`, `/data/tess/image_sub/...`), `CALDIR`, core counts (`NCORES=57`, `NCORES2=10`), and email recipients (lines 6, 154, 282, 296, 303). Move them to a config file or environment variables with the current values as defaults. Personal email addresses also shouldn't live in a public repository.
8. **No `set -euo pipefail` and no lock file.** Unquoted variables and unchecked commands (`cd`, `mv`, `mkdir`) can fail silently. If a run takes longer than the cron interval, two runs can overlap on the same segment. Consider `flock` around the whole run.
9. **Its runtime dependencies are undeclared.** It needs `mail`, the POC SPICE kernels, and the POC directory layout. None of this is documented.

### Docker

10. **Containerize the POC route if production should use the Docker image.** Mount `/pdo/poc-data`, the delivery directory, and the records file. Pass the config from item 7 as environment variables. Provide mail (or another notifier) inside the container, or move notification outside it. The current `tica` compose service only covers the public SPOC route.

## Packaging

11. **Internal operations scripts are installed for every user.** `pyproject.toml` installs `tica-doall-automate`, `tica-stage-delivery`, and `tica-check-delivery` into every environment, although they only work on MIT systems. Consider leaving them out of `script-files`, or installing them only through an `ops` extra.
12. **`bin/tica-overclock-stats` is not installed** and inserts a hardcoded `/pcds/users/faus/tica/` into `sys.path`. Remove it, or fix and install it.
13. **The scripts in `bin/` still modify `sys.path`** (`sys.path.insert(0, DIR/..)`). This is no longer needed once the package is installed, and it can make a script import a different copy of `tica` than the installed one. The README no longer documents running from a bare checkout via `PYTHONPATH`, so these lines can probably be removed. First confirm that no production setup relies on them.

## Code health

14. **Dead helpers reference an undefined `FitsFrame`** (`src/tica/tica.py`: `sum_frames`, `subtract_frames`, `mean_frames`, `median_frames`). Remove them, or point them at `CCD`.
15. **`src/wcs_build/step0_showquickbackground.py` uses `np.float`/`np.int`,** which were removed in numpy 1.24. It isn't installed or tested, so it fails only when run directly.
16. **Lint backlog:** `ruff check --select F401,F811 src bin/tica-cal-ccd2ccd` reports 28 unused imports and 5 redefinitions. Fix these mechanically in a separate commit (`ruff check --fix`), then run the regression test.

## Infrastructure

17. **The `tess.mit.edu` TLS chain is misconfigured** (since the certificate was renewed on 2026-10-19). The server sends the old Sectigo intermediate (InCommon RSA Server CA 2), but the new certificate is issued by InCommon Intermediate CA – DVG2C under emSign. OpenSSL clients, including DVC on Linux and DVC on macOS via certifi, fail with `CERTIFICATE_VERIFY_FAILED`. Report this to the server admins. Separately, the emSign root is not in Mozilla's or Debian's trust stores, so Linux clients may keep failing even after the chain is fixed. Local workaround: a CA bundle built from the macOS system roots plus the missing intermediates, set via `dvc remote modify --local tess_science ssl_verify <bundle>`.
