$env:OCR_SHARDS = '2'
$env:OCR_DPI = '170'
$env:OCR_USE_CUDA = '1'
# Point these at your own Python (with CUDA) and this corpus directory.
$env:OCR_PY = 'C:\path\to\gpu_ocr_env\Scripts\python.exe'
$wd = $PSScriptRoot
& $env:OCR_PY -u (Join-Path $wd 'run_all.py') *> (Join-Path $wd 'gpu_run.log')
