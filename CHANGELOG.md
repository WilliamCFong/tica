# Changelog

Human-readable summary of major changes and features/data that are added or removed.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]
### Changed
- All commands are Python modules in `src/tica/cli/`, installed as `[project.scripts]` entry points with argparse. Every command has `--help`.
  - The former bash wrappers take flags instead of `key=value` arguments: `tica-calibrate-spoc --input-dir D --caldir C`, `tica-calibrate-tso --o1 N --o2 None --orbseg o1a --dstem D --caldir C`, `tica-wcs-step1-allcam-allccd --sector S --reffin F --dstem D`, `tica-wcs-step2-allcam-allccd --sector S --dstem D`, `tica-wcs-spoc --sector S --dstem D`.
  - `step1_get_refimg_ctrlpts.py`, `step2_mkwcs.py` and `tica-dump-ephemeris.py` are renamed `tica-wcs-step1`, `tica-wcs-step2` and `tica-dump-ephemeris`.
  - `tica-doall-automate` takes options, each with a `TICA_*` environment variable, for every path, core count and email recipient list; the defaults are the previous hardcoded values.
  - `tica-production-table` writes to `--output` (default `production_table.md` in the current directory) instead of next to the installed script.
  - `wcs_build.step1_get_refimg_ctrlpts` and `wcs_build.step2_mkwcs` are now library modules only.
- The `tica`, `btjd`, and `wcs_build` packages moved to `src/` (src layout), so tests and scripts import the installed package rather than the checkout. Import names are unchanged. Existing checkouts need `pip install -e .` again. Production must also move the git-ignored `wcs_build/tic_postgres_param.py` to `src/wcs_build/`. `tica-doall-automate` now writes the ephemeris to `src/btjd/`.
- Scripts no longer add the repository to `sys.path`; they import the installed package.
- Require gwcs>=1.0. `wcs_from_points` is now called with a `SkyCoord` and `poly_degree`; WCS fits are bit-identical to gwcs 0.16. The previous pin (`<0.19`) allowed gwcs versions that broke WCS fitting and depended on the removed `pkg_resources`.
- `tica.tica.version` comes from the package metadata instead of reading `VERSION` from the source tree, so non-editable installs work.
- `step2_mkwcs.py` loads `tess_ephem.txt` from the installed `btjd` package, so the installed script works outside the repository.
- Background-subtracted stamps for WCS centroids are computed in the image's float32 precision, as numpy 1.x did implicitly. Under numpy 2 (NEP 50) they were promoted to float64, which changed star fluxes, centroids, and WCS coefficients relative to the regression outputs.
- `tica-calibrate-tso` resolves relative `dstem` and `CALDIR` paths from the directory it is run in. Previously they were resolved from inside `cam<i>_ccd1/`, so only absolute paths worked.
- `tica-doall-automate` writes each calibrated CCD image once, straight to the delivery directory, instead of three times (calibration, the in-place WCS rewrite, and the `tica-stage-delivery` copy). For a nominal segment (~2,800 cadences) that is ~800 GB written instead of ~2.4 TB, and no FFIs are re-read. No FFIs are kept in the work directory. The delivered files are the same apart from the time stamp in the calibration `COMMENT`. On `o1a`, the segment is calibrated twice, first without writing anything, so that `tica-darktime` can pick the WCS reference frame before any FFI is fitted. `--ncores` now sets the pool for calibration and WCS together; `--ncores-wcs` is unused.
- `tica-wcs-step1` reads the TIC through a provider interface (`wcs_build.tic_catalog`). A provider is given the CCD pointing (sector, camera, CCD and the 25 block cones) and returns the catalog fields for each cone. The PostgreSQL provider uses psycopg 3 and one connection per CCD, closed when done, instead of an unclosed psycopg2 connection per cone. **Production migration:** credentials now come from a libpq service file. Create a `[tic]` entry in `~/.pg_service.conf` and the password in `~/.pgpass` (chmod 600) for the cron user (see the README, "Reference stars from the TIC"), then delete `src/wcs_build/tic_postgres_param.py`. `--catalog` and `--tic-service` (`$TICA_TIC_SERVICE`) choose the provider and the service. The star selection is unchanged and is now documented in `wcs_build/tic_catalog.py`.
- **Changes star lists:** TIC proper motions are propagated to the reference FFI's mid-exposure time (`MIDTJD + TJD_ZERO`, or `TSTART`/`TSTOP` for SPOC files) instead of always to J2021.0. The epoch is saved as `pm_epoch_jd` in the reference star `.h5`, and the catalog source as `tic_source`. Positions move by at most ~0.5″ (0.025 px) for 100 mas/yr stars in 2026 sectors.
- Dependency: `psycopg[binary]>=3.1` replaces `psycopg2-binary`.
- Docker is the recommended installation: `runtime` and `dev` image targets built from hash-pinned lock files, compose services for running TICA and for development, and makefile targets (`build`, `build-dev`, `test`, `reg-test`, `shell`, `lock`).
### Added
- `requirements.lock` and `requirements-dev.lock`, generated by `make lock`.
- Installation smoke tests in `tests/`, including a WCS fit on synthetic stars.
- `data` extra that installs DVC.
- `tica-healthcheck` command, which reports missing calibration models in a calibration directory or a TICA checkout, with the `dvc pull` command that fetches them.
- `tica-cal-ffi2hlsp`, which calibrates raw camera FFIs, fits the WCS of each CCD in memory, and writes the delivery files with their HLSP names. It writes `cal_timeseries.txt`, `wcs_diags2/` and the per-CCD WCS logs the way the separate commands do, so `tica-darktime` and `tica-production-table` are unchanged. It skips CCD images already in the delivery directory and writes each file under a `.part` name before renaming it.
- `tica-calibrate-tso` modes: `--no_write` (diagnostics only), `--fin` (only the WCS reference frame), and `--hlspdir`/`--sector` (run `tica-cal-ffi2hlsp`). `tica-cal-ffi2ccds --no_write` and `tica-stage-delivery --ref-stars-only` support them. `tica-calibrate-tso` now exits 2 when a camera's run reports a configuration error.
- `--outdir` option for `tica-calibrate-tso`. It sets where outputs are written, instead of always using the current directory.
### Fixed
- Commands that crashed on current dependencies: `scipy` aliases of numpy functions (`tica-cal-ffi2ffi`, `tica-ccd-report`, `tica-ffi2ccds`, `tica-ccds2ffi`, `tica-trim-ccds2ffi`, `tica-overclock-stats`), `tica-ccds2ffi` reading a missing `--parallel`, and `.foramt` typos when writing full-frame output or rerunning over existing files.
- Parallel calibration on macOS: pool workers relied on a global that spawned processes never set. Worker errors are no longer silently dropped.
- `tica-wcs-step1` no longer crashes on a TIC cone with no stars or on a NULL Kmag/GAIAmag. It exits 2 with a message naming the service and files to check when the TIC can't be reached, instead of failing with `NameError` when `tic_postgres_param.py` was missing. `tica-wcs-step1-allcam-allccd` passes exit code 2 on.
- `tica-wcs-step1` read the reference FIN from the first `-` in the full path of the reference image, so a `-` in a directory name gave a wrong `ref_FIN`; it now uses the file name.
- `tica-wcs-step1` exited 0 when too few reference stars were found; it now exits 1. It also no longer truncates its output file while parsing arguments.
- `tica-production-table` raised `IndexError` instead of printing its mismatch warnings.
- `tica-darktime` no longer blocks on a plot window at the end (use `--show`).
- `tica-overclock-stats` works and is installed.
- Calibration directories are checked before use. A directory whose name doesn't end in a known cadence (`_30min`, `_10min`, `_02min`, `_20sec`, `_200sec`), or that is missing any of the 32 model files, raises `CalibrationError` naming the problem; the commands report it and exit 2 (configuration error). Before, a misnamed directory failed later with `AttributeError: 'Calibration' object has no attribute 'int_time'` (reported once per camera, as exit 1), and a missing model failed with a `TypeError` mid-calibration. `tica-calibrate-tso` and `tica-calibrate-spoc` check `--caldir` before doing any work.
- CCDs created without calibration models no longer build a placeholder `Calibration` pointing at a nonexistent `calibration/` directory; calibrating one raises `CalibrationError`.
- `tica-calibrate-tso` lists `ffi_fits-haho` files when no `--orbseg` is given (a brace typo meant it never did), and no longer misreads segment stamps when a parent directory contains "tess".
- `tica-wcs-spoc` works with any `--dstem`, not just `.`; matches star lists by zero-padded sector; only fits calibrated FFIs; and exits 1 when a CCD fails.
- `tica-calibrate-spoc` rewrites `inlist` instead of appending to it, so reruns don't list every FFI twice.
- `tica-doall-automate` moves each segment's `cal_timeseries_<segment>.png` and every CCD's `bad_calibration.txt` into the segment directory, and copies the records file to `--records-copy` after every finished run.
### Removed
- `bin/`: every script there is now a `tica.cli` entry point.
- `wcs_build/tic_local_conesearch.py` and the unused, broken `wcs_build/mast_filter_conesearch.py`, replaced by `wcs_build/tic_postgres.py` and `wcs_build/tic_mast.py`.
- Unused `gdrive` DVC remote, which made DVC commands fail without the dvc-gdrive plugin.
- `requirements.txt` (replaced by the lock files) and the outdated Python 3.10 `environment.yml`.

## [1.4.0] - 2023-11-3
Code auotomatically finds a good reference image for step1_wcs.  Other aspects of logging and checking for automated configuration.
### Changed
- tica-cal-ffi2ccds now writes a file `cal_timeseries.txt`, which has the mode of the background level and 1D bias correction (overclock correction) as a function of time.
- tica/tica.py has a function to calculate mode of an image.
- Fixed some issues with error codes for parallelization in tica-check-delivery.
- Fixed retrieval of parallelized output of step2_mkwcs.py.
- Changed parameters for tica-stage-delivery so that it can automatically infer and make output directory.
- Fixed issue with production table logging; wcs_step1 now outputs individual log files per CCD, and tica-production-table reads those files.
### Added
- Added exit codes to bash scripts and python scripts for auotmation.
- Script `tica-darktime` which finds intervales of dark time, and writes out reffin.txt which are suitable for WCS.  Will also write a list of files for the reference image and rms images (difference iamging).
- Script `tica-doall-automate` that can run on chron to automatically configure and run TICA on each new data delivery from POC. Also updates `tica-processing-records.txt` and `production-table.md`. Emails users whe script completes.
- File to track processing in tica-processing-records.txt.
- Script `btjd/tica-dump-ephemeris.py`, which automatically updates `btjd/tess_ephem.txt`. Assumes SPICE kernels are set up in /pdo/poc-data/kernels/pdo_tess_setup.tm, along with associated files. Also adds dependency on spiceypy==6.0.0.
- Added tica-processing-records.txt.
	
	
## [1.3.0] - 2022-5-8
Parallelized wcs step2, changed step1 to do local database querries
### Changed
- Invalid logging directories are made rather than crashing the scripts.
- Fixed versions of dependencies, for reproducibility
### Added
- Added `parallel` argument to step2_mkwcs.py.
- Added tic_local_conesearch.py, and changed step1 of wcs to use local server database. Now querries 16 CCDs in parallel.
- added psycopg2 (v2.9.5) dependency for local query
- Added function in tica.CCD to calculate mode of science pixels.

	
## [1.2.0] - 2022-09-09
Added 200sec models, and keyword specifying which half of an orbit FFIs came from.
### Changed
- Fixed issue with check on total integration times.
- Changed tica-calibrate-tso to deal withi new directory structure from POC.
- Changed details of output logs and production table.
### Added
- dvc file for twodbias_200s.dvc
- added relevant 200 sec exposures where needed.  
- added keyword ORB_SEG in headers for o1a, o1b, o2a, o2b, 
- added tica-cal-ffi2ccds command line argument --orb_seg to add ORB_SEG
- tica-calibrate-tso can now do orbit segments independently.  Includes catches for weird combinations (i.e., o2 is set but requesting o1a)
- added option to force .fits file, even if input is gzipped (default is to write as .gz if input is .gz)
### Removed

## [1.1.2] - 2022-06-07
Fixed some issues related to reprocessing old TICA products.
### Changed
- EXPTIME header keyword now depends on sector.
- Remved `header.extend` from wcs step2, so duplicate keywords should never be added.
### Added
### Removed

## [1.1.1] - 2022-04-27
Extended same capabilities on the production table logging.
### Changed
- Changed FLXWIN header keyword to blkHlfCent variable, as per issue 14.
- Updated tica-production-table to deal with logs that capture reruns.
- Updated tica-production-table to deal with logs from multiple orbits/segments (as in em2).	
- Updated regression test to check ext 1 data and headers.  Renamed ref star files to v02.
### Added
### Removed

## [1.1.0] - 2022-04-13
Improves configuration control, adds a file that tracks HLSP processing by sector.  Added header kewords and info in reference .h5 files, defaults to "fixed" apertures for WCS.  Adds Ref star flux and bkg estimates to ext 1 table of individual images.
### Changed
- wingFAC and contrastFAC in `step1_get_refimg_ctrlpts.py` are now command line arguments, and are stored in the .h5 files.
- Number of processers in `Pool` are command line arguments in `bin/tica-cal-ffi2ccds` and similar.
- Reg test now ignores patch number in image header `TICAVER` keyword.
- Removed np.int from `step1_get_refimg_ctrlpts.py` and `step1_mkwcs.py`, which was deprecated in numpy 1.20.
- WCS diagnostic info in the .h5 files now appends from files already with a WCS, rather than skipping those files and leaving the diagnostic info as zero.
- WCS .h5 star files now saves the Row/Col used in the reference, and forces the same row col when deriving the WCS unless the user disables this at the command line.
- Duplicates in the TIC are filtered out of the MAST query for reference stars.
- Updated regression test for fixed apertures and new ref_star files.
- Changed WCS plotting defaults.
- Changed stale SPOC header keywords to 'HISTORY' keywords.
- Added measured flux and backgrounds of WCS stars to extension 1.
### Added
- Header keywords for RMS scatter of faint stars in WCS fits.
- Script to see if the data in two reference star h5 files is the same.
- Script to make a "production table," which tracks configuration and important stats from each sector.
- Production table in Markdown format.
	
## [1.0.2] - 2022-02-04
Initial release on public github.  Primarily based on branch `faus_fix_requirements`.
### Changed
- Updated to python 3.10 and associated dependencies.
- DVC tracking of flatfields is now for individual flatfield models.
- Updated README and help menus based on MIT POC code review.
- `bin/tica-calibrate-spoc` no longer organizes outputs by camera and CCD, in order to match inputs of `bin/tica-wcs-spoc`.
- Regression tests updated to match python version 3.10 and associated dependencies.
- Regression test Header Keywords now have a 1.e-8 relative tolerance, in order to accomodate differences in Intel and M1 processors.
- Regression test directory now has a README to  log previous tests.
- Regression test now includes a verbose mode, to either display or silence warnings.
### Added
- Added MIT server to DVC remote, and set to default.
### Removed


## [1.0.1] - 2021-12-03
Refactored code to install TICA as a python package.  Added regression tests.  Primarily based on branch `faus_setup_dist`.
### Changed
- `setup.py` now resolves dependencies.
- The user can now install TICA libraries as a python package and access scripts in `tica/bin` from the command line.
- The bash scripts in `bin/` now have help functions.
### Added
- `tica/tica/tica.py` now enforces calibration of 30min/10min FFIs with the appropriate 2D bias model.
- Binary data in this repository are now tracked with DVC.
- Added the `reg_test` directory, which includes a python script to run regression test in order to test for changes in TICA data products.
### Removed
