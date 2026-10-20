# Performance recommendations

Notes from profiling the regression test (`reg_test/run_reg_test.py`, 16 CCDs from Sector 35) on 2026-10-19. None of these changes have been made; they are candidates to evaluate later.

## Baseline

Measured on an Apple M5 Max (Docker Desktop, linux/arm64). Five back-to-back runs per stack, timed inside the container so Docker startup is excluded. Every run passed.

| Stack | Python / numpy / scipy / astropy / gwcs | Mean | Range |
|---|---|---|---|
| `fix-install-docker` (locked deps) | 3.12 / 2.5.4 / 1.18.1 / 8.0.2 / 1.0.3 | 28.2 s | 27.95–28.52 s |
| `main`, original pins | 3.10 / 1.22.1 / 1.7.3 / 5.0 / 0.15.0 | 29.6 s | 29.28–30.30 s |

## Profile

py-spy at 200 Hz on the locked stack. Percentages are shares of sampled CPU time.

| Share | What |
|---|---|
| ~50% | gzip compression of output files |
| ~33% | gzip decompression while reading inputs, outputs, and reference files |
| ~3% | calibration math (`CCD.calibrate`: bias, linearity, smear, flat field) |
| ~3% | WCS fit (`fit_wcs`) |

The compression time is split evenly between two writes of the same file:

- `src/tica/tica.py:733`: `write_calibrate` writes `*.cal.fits.gz` (25%).
- `src/wcs_build/step2_mkwcs.py:1222`: step 2 rewrites the whole file with the WCS added (25%).

`write_calibrate` gzips by default (unless `no_gzip`), using Python's default gzip level of 9. On one calibrated FFI:

| gzip level | Write | Read | Size |
|---|---|---|---|
| 9 (current) | 0.48 s | 0.06 s | 15.5 MB (87%) |
| 6 | 0.45 s | 0.06 s | 15.5 MB (87%) |
| 1 | 0.32 s | 0.06 s | 15.6 MB (87%) |

The file is 17.8 MB uncompressed. Float32 image data barely compresses, so gzip saves about 13% of disk space at a cost of roughly half the runtime.

## Recommendations

1. **Compress each output only once.** Write the calibrated file uncompressed, and gzip it only after step 2 adds the WCS. This removes one of the two compression passes, an estimated ~25% of runtime. Note that the WCS step runs as a separate script in production (`tica-wcs-step2-allcam-allccd`), so the final compression has to happen there or in a later step.
2. **Make compression cheaper or optional.** Use `compresslevel=1` (same size, ~35% faster writes), or default to uncompressed output and compress only for delivery. Skipping gzip entirely would remove an estimated ~50% of runtime. Check first what downstream consumers (MAST delivery, QLP) expect.
3. **Look into the cost of gzip reads.** Reads take ~33% of CPU, far more than one straight decompression (0.06 s per file) would explain. A likely but unconfirmed cause is astropy re-decompressing when it seeks backward within a gzip stream. Reading the whole file into memory first (`fits.open(io.BytesIO(gzip.open(f).read()))`) or using `lazy_load_hdus=False` may help.
4. **Make output writing explicit about existing files.** `write_calibrate` silently skips writing when the output already exists. A stale file left by an earlier run (which already has a WCS) is then reused, and the regression test fails confusingly. Consider an explicit `--overwrite` option, or a warning that names the file. `make reg-test` already clears stale outputs as a workaround.

The estimates above come from the profile, not from end-to-end measurements. Each change should be benchmarked against the baseline, and `make reg-test` must still pass. The test compares image data exactly, so changing the compression level is safe, but changing the arithmetic is not.

## How to reproduce

```
make build-dev
docker compose run --rm -T --cap-add SYS_PTRACE -w /app/reg_test dev sh -c '
  pip install -q --target /tmp/pyspy py-spy &&
  /tmp/pyspy/bin/py-spy record --rate 200 --subprocesses --format flamegraph \
      -o /app/profile.svg -- python run_reg_test.py'
```

Open `profile.svg` in a browser. Use `--format raw` for collapsed stacks that can be aggregated by function.
