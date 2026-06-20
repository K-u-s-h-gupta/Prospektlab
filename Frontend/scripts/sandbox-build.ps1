param(
  [string]$BindHost = '127.0.0.1',
  [int]$Port = 4173,
  [switch]$Serve,
  [switch]$Watch
)

$ErrorActionPreference = 'Stop'

$scriptsDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$frontendRoot = Resolve-Path (Join-Path $scriptsDir '..')
$distDir = Join-Path $frontendRoot 'dist-sandbox'
$assetsDir = Join-Path $distDir 'assets'

New-Item -ItemType Directory -Path $distDir -Force | Out-Null
New-Item -ItemType Directory -Path $assetsDir -Force | Out-Null

$publicDir = Join-Path $frontendRoot 'public'
if (Test-Path $publicDir) {
  Copy-Item -Path (Join-Path $publicDir '*') -Destination $distDir -Recurse -Force
}

$indexPath = Join-Path $frontendRoot 'index.html'
$indexRaw = Get-Content -LiteralPath $indexPath -Raw
$patchedIndex = $indexRaw -replace '<script type="module" src="/src/main.tsx"></script>', '<script type="module" src="/assets/main.js"></script>'
Set-Content -LiteralPath (Join-Path $distDir 'index.html') -Value $patchedIndex -Encoding UTF8

$envConfigPath = Join-Path $distDir 'env-config.js'
if (-not (Test-Path $envConfigPath)) {
  Set-Content -LiteralPath $envConfigPath -Value 'window.__BACKEND_URL = "http://127.0.0.1:8000";' -Encoding UTF8
}

$esbuildBinary = Join-Path $frontendRoot 'node_modules/vite/node_modules/@esbuild/win32-x64/esbuild.exe'
if (-not (Test-Path $esbuildBinary)) {
  $esbuildBinary = Join-Path $frontendRoot 'node_modules/@esbuild/win32-x64/esbuild.exe'
}
if (-not (Test-Path $esbuildBinary)) {
  throw "Could not find esbuild.exe in node_modules. Run npm install in frontend first."
}

$mainEntry = Join-Path $frontendRoot 'src/main.tsx'
$tsConfig = Join-Path $frontendRoot 'tsconfig.json'
$outFile = Join-Path $assetsDir 'main.js'

$args = @(
  $mainEntry,
  '--bundle',
  '--platform=browser',
  '--format=esm',
  '--jsx=automatic',
  '--jsx-import-source=react',
  '--target=es2020',
  '--sourcemap',
  '--allow-overwrite',
  "--tsconfig=$tsConfig",
  "--outfile=$outFile",
  '--asset-names=[name]-[hash]',
  '--public-path=/',
  '--define:process.env.NODE_ENV=\"development\"',
  '--loader:.png=file',
  '--loader:.jpg=file',
  '--loader:.jpeg=file',
  '--loader:.gif=file',
  '--loader:.svg=file',
  '--loader:.webp=file',
  '--loader:.ico=file',
  '--loader:.woff=file',
  '--loader:.woff2=file',
  '--loader:.ttf=file',
  '--loader:.eot=file',
  '--loader:.mp4=file',
  '--loader:.webm=file',
  '--loader:.csv=text',
  '--loader:.md=text'
)

if ($Watch) {
  $args += '--watch=forever'
}
if ($Serve) {
  $args += "--serve=$BindHost`:$Port"
  $args += "--servedir=$distDir"
  $args += "--serve-fallback=$distDir/index.html"
}

Write-Host "Building sandbox bundle in $distDir"
if ($Serve) {
  Write-Host "Serving on http://$BindHost`:$Port"
}

& $esbuildBinary @args
