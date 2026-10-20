# TESS Image CAlibration (TICA)

The TESS Image CAlibration (TICA) module is a python package for removing instrumental effects from raw TESS images.

TICA also includes a module to find bright, relatively isolated stars in TESS FFIs, measure their centroids, and derive World Coordinate Solutions.  

TICA calibrated Full Frame Images (FFIs) are publicly available at [MAST as a High Level Science Product](https://archive.stsci.edu/hlsp/tica), typically within 1 week of data downlink. TICA FFIs, calibration steps, and World Coordinate Solutions are described in [Fausnaugh et al. 2020](https://iopscience.iop.org/article/10.3847/2515-5172/abd63a).  More information about TESS can be found at https://tess.mit.edu/ and https://heasarc.gsfc.nasa.gov/docs/tess/. 

This git repository holds the codebase used to generate the TICA calibrated images. We encourage users to browse the code base should they have questions regarding the calibration steps. We also provide installation steps, procedures, and test cases for users that would like to customize the TESS calibrations for their own scientific research. This document assumes that the user is familiar with typical astronomical CCD calibration steps, FITS file storage, python programming, python package management, unux-based command line interfaces, and basic usage of `git`.

TICA applies six steps to raw TESS FFIs:

 1. 2d bias correction: Remove fixed-pattern noise.
 2. Scalar bias correction: Remove the time-dependent amplifier pedestal.
 3. Gain: Convert from ADU to photoelectrons.
 4. Linearity: Correct the non-linear detector response.
 5. Smear correction:  Remove contamination from the shutterless transfer to the frame-store.
 6. Flat-field correction: Correct for the non-uniform response of each pixel.

More information about the TESS instrument and detectors can be found in the [TESS Instrument Handbook](https://archive.stsci.edu/files/live/sites/mast/files/home/missions-and-data/active-missions/tess/_documents/TESS_Instrument_Handbook_v0.1.pdf).

If you have questions or are having trouble, feel free to contact the project owner Michael Fausnaugh at faus@mit.edu. Questions about TICA or TESS, including bug reports, should be submitted to the TESS help desk at tesshelp@bigbang.gsfc.nasa.gov.



## Installation

### 1. Environment and Codebase

TICA is distributed as a git repository, because the calibration models are tracked alongside the code (see below). Start by cloning it:

```
git clone https://github.com/mmfausnaugh/tica.git
cd tica
```

#### Docker (recommended)

The supported way to run TICA is in a Docker container. The image is built from hash-pinned lock files (`requirements.lock`, `requirements-dev.lock`), so every installation of a given TICA version gets exactly the same Python and package versions. This matters for reproducibility: calibrated outputs and WCS headers can change slightly with different versions of `numpy`, `astropy`, etc.

You need [Docker](https://docs.docker.com/get-docker/) with the Compose plugin and `make`. Then:

```
make build       # runtime image, tagged tica:<VERSION>
make build-dev   # development image with pytest, ruff, and DVC, tagged tica-dev:<VERSION>
make test        # installation smoke tests
```

Run TICA on your data with the `tica` service. The repository is mounted read-only at `/tica` (so the calibration directories are available as `/tica/calibration_<exptime>`), and the directory given by `TICA_DATA` (default `./data`) is mounted at `/data`:

```
export TICA_DATA=/path/to/my/ffis    # contains raw/ with the *ffir*.fits files
docker compose run --rm tica tica-calibrate-spoc --input-dir /data/raw --caldir /tica/calibration_10min
```

The makefile sets `TICA_UID`/`TICA_GID` to your user so that output files are owned by you. If you call `docker compose` directly, export them yourself (`export TICA_UID=$(id -u) TICA_GID=$(id -g) TICA_VERSION=$(cat VERSION)`).

`make shell` opens a shell in the development image with your checkout mounted at `/app`, installed in editable mode, so code changes take effect without rebuilding.

To update dependencies, edit `pyproject.toml` and run `make lock`, then rebuild and rerun the tests and the regression test before committing the new lock files.

#### pip

TICA can also be installed into a Python 3.11+ virtual environment. Installing from the clone in editable mode keeps the scripts next to the calibration models:

```
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest
```

This resolves the newest compatible dependency versions rather than the pinned ones. To reproduce the Docker environment exactly, use Python 3.12 and run `pip install --require-hashes --no-deps -r requirements.lock` before `pip install --no-deps -e .`.

Besides typical scientific computing packages (`numpy`, `scipy`, `matplotlib`, `h5py`, and `astropy`), TICA requires `gwcs` (https://github.com/spacetelescope/gwcs), `tess-point` (https://github.com/christopherburke/tess-point), and `spiceypy`; see `pyproject.toml`.

### 2. Calibration Models

2D-bias and flatfield calibration models are distributed by an application called [DVC](https://www.dvc.org) (Data Version Control).  DVC uses metadata files in the TICA git repository to track different versions of the calibration models.  The calibration models are stored on a server at MIT, which DVC pulls with https requests.

To retrieve the calibration models, use DVC. It is included in the development image, so you can run the commands below inside `make shell` (or prefix them with `docker compose run --rm dev`). For a pip installation, run `pip install -e ".[data]"` or install DVC using the directions on [the DVC website](https://dvc.org/doc/install).
<!---If you use `pip`, note that you need to install additional libraries necessary for Gdrive access:
```
pip install dvc
pip install dvc[gdrive]
```
-->
Then run the following commands and follow the prompts:

```
cd calibration_models
dvc pull flat_combine/780nm
dvc pull twodbias_<exptime>
```

where `<exptime>` corresponds to whatever exposure your FFIs are, `30min` for Sectors 1-26, `10min` for Sectors 37-55.

To see which calibration models are present, run `tica-healthcheck` from the top level `tica` directory (or `tica-healthcheck <calibration_dir>` for one directory, or add `--cadence 200sec`). It lists the missing models for each `calibration_<cadence>` directory and prints the `dvc pull` command that fetches them.

You can also pull all of the calibration models if you are at the top level `tica` directory and run

```
dvc pull
```
Note that there are 21G of total data in all of the calibration models, most of which are not needed to run the code, so we do not recommend this option.

## Quick Start

During installation, all TICA commands (`tica-*`) are installed in the `$PATH` of your working environment and are available from the command line.  Every command has a `--help` option.  Their source is in `src/tica/cli/`.

The workhorse script for calibrating raw TESS data is `tica-cal-ccd2ccd`, and can be run with `--help` to  see an explanation of the available options.  

A command that runs TICA on a directory of raw FFIs is `tica-calibrate-spoc` (run it with `--help` for its options).

Raw TESS FFIs should be downloaded from MAST (https://archive.stsci.edu/tess/bulk_downloads/bulk_downloads_ffi-tp-lc-dv.html). From that link, scroll down to "Uncalibrated FFIs," and you will be able to download a `.sh` script that uses `curl` to fetch raw SPOC FFI files (`*ffir*fits` files).  Note that the `.sh` script will download an entire sector of FFIs by default; you may want to edit the script to download just a few raw FFIs to start.

Once the raw data are downloaded, the user gives `tica-calibrate-spoc` the location of the FFIs and the location of the calibration models, for example:

```
mkdir tica_outputs
cd tica_outputs
tica-calibrate-spoc --input-dir /path/to/raw/data --caldir ~/python/tica/calibration_10min
```

`tica-calibrate-spoc` likely covers 99% of use cases.  Users can also write their own scripts to call `tica-cal-ccd2ccd`, or they can run `tica-cal-ccd2ccd` directly from the command line.

Several other commands are also installed by default.  These commands are used to calibrate FFIs for MIT's [Quick Look Pipeline](https://archive.stsci.edu/hlsp/qlp) at the Payload Operations Center/TESS Science Office (POC/TSO).  Note that the POC/TSO FFIs are formatted differently than the SPOC `*ffir*fits` files available at MAST.  However, the POC/TSO FFIs are not publicly available at this time.

### Setting the calibration directory

***Users must point to the appropriate calibration directory when running `tica-calibrate-spoc` or `tica-cal-ccd2ccd`.   The code will raise an error if the exposure time in the data files does not match the specified calibration directory.***

## Regression Test

There is a regression test in `tica/reg_test` that can be used to test your installation and any changes made to the code.  To run the regression test:

```
cd tica/calibration_models
dvc pull flat_combine/780nm
dvc pull twodbias_10min
dvc pull twodbias_30min
cd ../reg_test
dvc pull input output_checks ref_stars
python run_reg_test.py
```

With Docker, pull the data from `make shell` and then run `make reg-test`.

`run_reg_test.py` will take SPOC `*ffir*` files in `reg_test/input` and apply calibrations and WCSs.  The results of those calibrations are checked against the contents of `reg_test/output_checks`.  

The test will fail if there are any changes to the calibrated data, or if any header keywords differ by a relative error of more than 1.e-8.  We have found that header keywords (especially WCS parameters) can change by a small amount depending on python version and processor architecture, and so a warning is raised for relative differences are less than 1.e-8.  See `tica/reg_test/README` for more details.

To run `run_reg_test.py`, it is necessary to pull the input data, output checks, and tables of WCS stars using DVC.  The data are saved locally in the directories `input`, `output_checks`, and `ref_stars`, respectively.  DVC is used to retrieve these data in the same way as for the calibration models.  The regression test uses data from Sector 35 and 10 minute calibration models, and the test checks that the code fails when 30 minute calibration models are used on 10 minute data.

In very rare cases, `output_checks` will be updated if we implement changes that improve the TICA calibration or WCSs.  Changes to the output checks are under version control with the `reg_test/output_checks.dvc` file, and can be updated in the same way as the calibration models (see below).

Note that the regression test does not check `tica/src/wcs_build/step1_get_refimg_ctrlpts.py`, which generates the table of stars used for WCS fitting.  

## Updating and Reverting Calibration Models

With DVC, you can easily update to the latest calibration models.  You can also revert to old versions of the models if you need to reproduce previous results.  

To check for updates, run `git pull` in the top-level `tica` directory.  If new calibration models are available, then the `calibration_models/*.dvc` files will be updated.  If this is the case, do

```
cd tica/calibration_models
dvc pull
```  

Calibration models will be updated no more than once per year.

To revert to an old model, first use `git checkout` to get the version of the `.dvc` file that corresponds to the model that you need.  Then run `dvc checkout`.  DVC handles access to the cloud, and caches the downloads so that you can easily switch between different versions of the models.  See the [DVC docs](https://dvc.org/doc/start) for more information and tutorials.

There are directories at the top level of the repository for each calibration model (30 minute or 10 minute data).  Those directories link to the data in `calibration_models`. When you run TICA, you specify a single calibration directory, which will load all of the models that the code needs (based on what DVC has checked out in `calibration_models`).

Calibration models also exist for 20-second and 2-minute data, but calibrating raw pixels from SPOC Target Pixel Files is not supported at this time.

## Data Structures and Calibration Algorithms

Algorithms used for pixel calibrations can be found in `tica/src/tica/tica.py`.  In particular, `CCD.calibrate` is the function that produces the calibrated data.  

Some users may find the data structures in `tica.py` useful for their own scripts.  We recommend using `src/tica/cli/cal_ccd2ccd.py` or `src/tica/cli/cal_ffi2ccds.py` as a guide for scripting with TICA data structures.



## World Coordinate Solutions

There are two WCSs available to end-users: SPOC WCSs in the `*ffir*`/`*ffic*` files from MAST, and TICA WCSs in the [High Level Science Products](https://archive.stsci.edu/hlsp/tica).  There are small systematic differences between the SPOC and TICA WCSs that may be important for users with high astrometric requirements.

The WCS differences can be analyzed by comparing the transforms of stars using the two WCSs.  For TICA, astrometric residuals from the WCSs of the fitted stars are also given in a binary table extension for every FFI.

We recommend that users employ the existing WCSs to analyze these astrometric differences.  However, as a scripting example, we have provided a command that refits the TICA WCSs and overwrites the WCS keywords in the SPOC `*ffir*` files: `tica-wcs-spoc` (see `tica-wcs-spoc --help`).

