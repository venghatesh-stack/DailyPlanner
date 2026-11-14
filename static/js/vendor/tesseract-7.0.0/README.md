# Tesseract.js 7.0.0 (self-hosted)

On-device OCR for Day Sheet → "Scan paper sheet". Everything runs in the
browser: no image or text is sent to any API.

- `tesseract.min.js`, `worker.min.js` — tesseract.js 7.0.0 (Apache-2.0)
- `core/` — tesseract.js-core 7.0.0, LSTM builds only (plain, SIMD,
  relaxed SIMD); the library picks the fastest the browser supports.
- `lang/eng.traineddata.gz` — @tesseract.js-data/eng 4.0.0_best_int.

Loaded only when a scan starts (static/js/day_sheet_scan.js). Needs
`'wasm-unsafe-eval'` in script-src (middleware/security.py).
