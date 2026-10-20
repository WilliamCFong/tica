# Follow-ups

Open items found while reviewing installation and the production scripts (2026-10-19). Items that have since been fixed are struck through. Performance items are tracked separately in [performance-recommendations.md](performance-recommendations.md).

## `tica-doall-automate` (production cron job)

This command (`src/tica/cli/doall_automate.py`; a bash script in `bin/` until the `cli-entry-points` branch) runs the TICA production pipeline on MIT's POC machines. It finds the newest orbit in `/pdo/poc-data/orbits/`, skips segments already listed in `tica-processing-records.txt`, and then runs, in order: ephemeris refresh, `tica-calibrate-tso`, `tica-darktime`, WCS steps 1 (on `o1a` only) and 2, `tica-stage-delivery`, and `tica-check-delivery`. (Since the `single-write-pipeline` branch, calibration and WCS step 2 run together and write straight to the delivery directory; see `tica-doall-automate --help`.) It emails a fixed list of recipients and appends to the processing records.

### Bugs

1. ~~**Exit codes are misread in every error handler**~~ *Fixed on `fix-doall-exit-codes`. That branch also fixes `tica-wcs-step1-allcam-allccd` and `tica-wcs-step2-allcam-allccd`: they set `errorflag` inside background jobs, where it never reached the parent shell, so they always exited 0.* (lines 172–180, 189–197, 215–223, 233–241). Inside `cmd || { if [[ $? == 2 ]] …; elif [[ $? == 1 ]] …; else …; fi }`, the second `$?` is the result of the first `[[ … ]]` test (1), not the command's exit code. As a result, every failure other than code 2 is treated as recoverable and processing continues, and the "Unknown error, abort!" branches can never run. Fix: capture the code once, e.g. `cmd || { rc=$?; case $rc in 2) …;; 1) …;; *) …;; esac; }`.
2. ~~**The duplicate-run guard checks the wrong `$?`**~~ *Fixed on `fix-doall-exit-codes`.* (line 144). `$?` there belongs to the preceding `echo`, so the condition is always true. The guard still works, because the regex match on the next line does the real check, but it reads as if grep's exit code were tested. Also, `[[ $compstr =~ $checkstr ]]` treats the record line as a regex. Use a quoted match (`== *"$checkstr"*`) or `grep -qF`.
3. ~~**The records file was copied back to the repository only in an unreachable "major error" branch**~~ *Fixed: `tica-doall-automate` copies it to `--records-copy` (default: the production checkout) after every finished run.*
4. **The ephemeris refresh and the ephemeris used by step 2 can diverge.** `tica-dump-ephemeris --outdir /pdo/users/faus/python/tica/src/btjd/` (the default of `--ephemeris-outdir`) writes into the source checkout. Since the `fix-install-docker` branch, `step2_mkwcs.py` reads `tess_ephem.txt` from the installed `btjd` package. With an editable install (`pip install -e`) these are the same file. With a regular install, step 2 would silently use the ephemeris from install time. Either keep production on an editable install (and document why), or have the dump write to a configurable location that step 2 reads, e.g. an environment variable. The Docker image uses a regular install.

### Robustness and maintenance

5. ~~**Arguments are run through `eval`**~~ *Fixed: all commands parse their arguments with argparse.*
6. **The orbit→sector and segment mappings are hardcoded** (`sector_from_orbit` and `segment_from_orbit` in `doall_automate.py`). The special cases for orbits 203–208 and the switch from `(orbit−7)/2` to `(orbit−11)/2` must be edited by hand whenever the mission timeline changes. Move them to a lookup table (orbit → sector, segment) that can be updated without code changes, or derive them from POC metadata if available.
7. ~~**Site-specific configuration is hardcoded**~~ *Fixed: paths, core counts and recipients are options with `TICA_*` environment variables (see `tica-doall-automate --help`).* The defaults are still the MIT production values, including personal email addresses, which shouldn't live in a public repository. Consider moving the defaults into the production cron environment.
8. **No lock file.** If a run takes longer than the cron interval, two runs can overlap on the same segment. Consider `flock` around the cron command, or a lock file in `--workdir`. (The shell-specific issues, such as unquoted variables, went away with the Python port.)
9. **Its runtime dependencies are undeclared.** It needs `mail`, the POC SPICE kernels, and the POC directory layout. None of this is documented.

### Docker

10. **Containerize the POC route if production should use the Docker image.** Mount `/pdo/poc-data`, the delivery directory, and the records file. Pass the settings from item 7 as `TICA_*` environment variables. Provide mail (or another notifier) inside the container, or move notification outside it. The current `tica` compose service only covers the public SPOC route.

## Packaging

11. **Internal operations scripts are installed for every user.** `pyproject.toml` installs `tica-doall-automate`, `tica-stage-delivery`, and `tica-check-delivery` into every environment, although they only work on MIT systems. Consider moving them to a separate `tica.ops` entry-point group or package that only production installs.
12. ~~**`bin/tica-overclock-stats` is not installed and doesn't work**~~ *Fixed: rewritten as the `tica-overclock-stats` command.*
13. ~~**The scripts in `bin/` still modify `sys.path`**~~ *Fixed: removed after the move to the src layout.* (`sys.path.insert(0, DIR/..)`). This is no longer needed once the package is installed, and it can make a script import a different copy of `tica` than the installed one. The README no longer documents running from a bare checkout via `PYTHONPATH`, so these lines can probably be removed. First confirm that no production setup relies on them.

## Code health

14. **Dead helpers reference an undefined `FitsFrame`** (`src/tica/tica.py`: `sum_frames`, `subtract_frames`, `mean_frames`, `median_frames`). Remove them, or point them at `CCD`.
15. **`src/wcs_build/step0_showquickbackground.py` uses `np.float`/`np.int`,** which were removed in numpy 1.24. It isn't installed or tested, so it fails only when run directly.
16. **Lint backlog:** `ruff check --select F401,F811 src/tica/tica.py src/btjd src/wcs_build` reports unused imports and redefinitions (`src/tica/cli` is clean). Fix these mechanically in a separate commit (`ruff check --fix`), then run the regression test.

18. **The exposure time of the calibration models comes from the directory name.** `check_calibration_dir` in `src/tica/tica.py` reads it from the `_<cadence>` suffix, so models in a differently named directory (e.g. `/pdo/qlp-data/tica-calibration-models` in a TSO test run) need a `calibration_<cadence>` directory or symlink. `calibration_04min` is in the repository but `04min` is not a recognised cadence, so it can't be used. Consider reading the exposure time from the FFI header (`INT_TIME`/`EXPOSURE`) or an explicit option, and adding 04min if those models are meant to be used.

## Infrastructure

17. **The `tess.mit.edu` TLS chain is misconfigured** (since the certificate was renewed on 2026-10-19). The server sends the old Sectigo intermediate (InCommon RSA Server CA 2), but the new certificate is issued by InCommon Intermediate CA – DVG2C under emSign. OpenSSL clients, including DVC on Linux and DVC on macOS via certifi, fail with `CERTIFICATE_VERIFY_FAILED`. Report this to the server admins. Separately, the emSign root is not in Mozilla's or Debian's trust stores, so Linux clients may keep failing even after the chain is fixed. Local workaround: a CA bundle built from the macOS system roots plus the missing intermediates, set via `dvc remote modify --local tess_science ssl_verify <bundle>`.
