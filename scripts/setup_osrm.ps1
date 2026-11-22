# Prepara o OSRM local (rotas por ruas) com o mapa do Sul do Brasil. Requer Docker Desktop em execução.
# Uso:  .\scripts\setup_osrm.ps1                      carro/moto: baixa o mapa, processa e sobe em http://localhost:5000
#       .\scripts\setup_osrm.ps1 -Start               só sobe o servidor de carro, depois da primeira preparação
#       .\scripts\setup_osrm.ps1 -Foot                pedestre (entregador a pé do Centro): sobe em http://localhost:5001
#       .\scripts\setup_osrm.ps1 -Foot -Start         só sobe o servidor de pedestre
#       .\scripts\setup_osrm.ps1 -Recorte             usa só Porto Alegre e arredores (bem menos disco, RAM e tempo de preparo)
#       .\scripts\setup_osrm.ps1 -Recorte -Foot       idem para o pedestre ( -Recorte também vale com -Start )
#       .\scripts\setup_osrm.ps1 -Bbox "-51.35,-30.32,-50.95,-29.88"   recorte com outra caixa: oeste,sul,leste,norte
# O recorte só serve para entregas dentro da caixa: rota que sai dela não existe no mapa recortado.
param([switch]$Start, [switch]$Foot, [switch]$Recorte, [string]$Bbox = "")
$ErrorActionPreference = "Stop"
$dir = Join-Path $PSScriptRoot "..\osrm-data"
New-Item -ItemType Directory -Force $dir | Out-Null
$dir = (Resolve-Path $dir).Path
$image = "ghcr.io/project-osrm/osrm-backend:v5.27.1"
$osmium = "iboates/osmium:latest"
$defaultBbox = "-51.35,-30.32,-50.95,-29.88"   # Porto Alegre + Canoas, Viamão, Alvorada, Cachoeirinha, Gravataí...

docker info *> $null
if ($LASTEXITCODE -ne 0) { throw "Docker não está em execução. Abra o Docker Desktop e tente de novo." }

if ($Recorte -and -not $Bbox) { $Bbox = $defaultBbox }
$source = "sul-latest"                      # mapa inteiro baixado do Geofabrik
$prefix = if ($Bbox) { "poa" } else { $source }
if ($Foot) { $name = "osrm-foot"; $port = 5001; $base = "$prefix-foot"; $lua = "/opt/foot.lua" }
else { $name = "osrm-poa"; $port = 5000; $base = $prefix; $lua = "/opt/car.lua" }

function Step($label, [scriptblock]$run) {
  $sw = [Diagnostics.Stopwatch]::StartNew()
  Write-Host $label
  & $run
  if ($LASTEXITCODE -ne 0) { throw "Falhou: $label" }
  Write-Host ("  {0:N0} s" -f $sw.Elapsed.TotalSeconds)
}

if (-not $Start) {
  if (-not (Test-Path "$dir\$source.osm.pbf")) {
    Write-Host "Baixando o mapa do Sul do Brasil (Geofabrik, ~400 MB)..."
    Invoke-WebRequest "https://download.geofabrik.de/south-america/brazil/sul-latest.osm.pbf" -OutFile "$dir\$source.osm.pbf"
  }
  if ($Bbox) {
    # recorte feito uma vez; carro e pedestre partem do mesmo arquivo
    $cut = "$dir\poa.osm.pbf"
    $mark = "$dir\poa.bbox"   # caixa usada no recorte existente: se mudou, recorta e processa de novo
    if (-not (Test-Path $cut) -or -not (Test-Path $mark) -or ((Get-Content $mark -Raw).Trim() -ne $Bbox)) {
      Step "Recortando o mapa na caixa $Bbox..." {
        docker run --rm -v "${dir}:/data" $osmium extract --bbox $Bbox --overwrite -o /data/poa.osm.pbf /data/$source.osm.pbf
      }
      Set-Content $mark $Bbox
      Remove-Item "$dir\poa.osrm*", "$dir\poa-foot.*" -Force -ErrorAction SilentlyContinue
    }
    $src = "poa"
  } else { $src = $source }
  # cada perfil gera arquivos .osrm próprios ao lado do .pbf: o de pedestre usa uma cópia
  if ($Foot -and -not (Test-Path "$dir\$base.osm.pbf")) { Copy-Item "$dir\$src.osm.pbf" "$dir\$base.osm.pbf" }
  Step "Extraindo (perfil $lua)..." { docker run --rm -v "${dir}:/data" $image osrm-extract -p $lua /data/$base.osm.pbf }
  Step "Particionando (MLD)..." { docker run --rm -v "${dir}:/data" $image osrm-partition /data/$base.osrm }
  Step "Customizando (MLD)..." { docker run --rm -v "${dir}:/data" $image osrm-customize /data/$base.osrm }
}

docker rm -f $name *> $null
docker run -d --name $name --restart unless-stopped -p "${port}:5000" -v "${dir}:/data" $image `
  osrm-routed --algorithm mld --max-table-size 200 /data/$base.osrm
if ($Foot) { Write-Host "OSRM de pedestre no ar em http://localhost:$port (o app usa OSRM_FOOT_URL)." }
else { Write-Host "OSRM no ar em http://localhost:$port. Inicie o app com:  `$env:MATRIX='osrm'" }
