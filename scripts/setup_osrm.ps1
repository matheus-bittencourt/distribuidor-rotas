# Prepara o OSRM local (rotas por ruas) com o mapa do Sul do Brasil. Requer Docker Desktop em execução.
# Uso:  .\scripts\setup_osrm.ps1               carro/moto: baixa o mapa, processa e sobe em http://localhost:5000
#       .\scripts\setup_osrm.ps1 -Start        só sobe o servidor de carro, depois da primeira preparação
#       .\scripts\setup_osrm.ps1 -Foot         pedestre (entregador a pé do Centro): sobe em http://localhost:5001
#       .\scripts\setup_osrm.ps1 -Foot -Start  só sobe o servidor de pedestre
param([switch]$Start, [switch]$Foot)
$ErrorActionPreference = "Stop"
$dir = Join-Path $PSScriptRoot "..\osrm-data"
New-Item -ItemType Directory -Force $dir | Out-Null
$dir = (Resolve-Path $dir).Path
$image = "ghcr.io/project-osrm/osrm-backend:v5.27.1"

docker info *> $null
if ($LASTEXITCODE -ne 0) { throw "Docker não está em execução. Abra o Docker Desktop e tente de novo." }

if ($Foot) { $name = "osrm-foot"; $port = 5001; $base = "sul-foot"; $lua = "/opt/foot.lua" }
else { $name = "osrm-poa"; $port = 5000; $base = "sul-latest"; $lua = "/opt/car.lua" }

if (-not $Start) {
  if (-not (Test-Path "$dir\sul-latest.osm.pbf")) {
    Write-Host "Baixando o mapa do Sul do Brasil (Geofabrik, ~400 MB)..."
    Invoke-WebRequest "https://download.geofabrik.de/south-america/brazil/sul-latest.osm.pbf" -OutFile "$dir\sul-latest.osm.pbf"
  }
  # cada perfil gera arquivos .osrm próprios ao lado do .pbf: o de pedestre usa uma cópia
  if ($Foot -and -not (Test-Path "$dir\$base.osm.pbf")) { Copy-Item "$dir\sul-latest.osm.pbf" "$dir\$base.osm.pbf" }
  Write-Host "Extraindo (perfil $lua)..."
  docker run --rm -v "${dir}:/data" $image osrm-extract -p $lua /data/$base.osm.pbf
  Write-Host "Particionando e customizando (MLD)..."
  docker run --rm -v "${dir}:/data" $image osrm-partition /data/$base.osrm
  docker run --rm -v "${dir}:/data" $image osrm-customize /data/$base.osrm
}

docker rm -f $name *> $null
docker run -d --name $name --restart unless-stopped -p "${port}:5000" -v "${dir}:/data" $image `
  osrm-routed --algorithm mld --max-table-size 200 /data/$base.osrm
if ($Foot) { Write-Host "OSRM de pedestre no ar em http://localhost:$port (o app usa OSRM_FOOT_URL)." }
else { Write-Host "OSRM no ar em http://localhost:$port. Inicie o app com:  `$env:MATRIX='osrm'" }
