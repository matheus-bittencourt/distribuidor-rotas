# Prepara o OSRM local (rotas por ruas) com o mapa do Sul do Brasil. Requer Docker Desktop em execução.
# Uso:  .\scripts\setup_osrm.ps1          (baixa o mapa, processa e sobe o servidor em http://localhost:5000)
#       .\scripts\setup_osrm.ps1 -Start   (só sobe o servidor, depois da primeira preparação)
param([switch]$Start)
$ErrorActionPreference = "Stop"
$dir = Join-Path $PSScriptRoot "..\osrm-data"
New-Item -ItemType Directory -Force $dir | Out-Null
$dir = (Resolve-Path $dir).Path
$pbf = "sul-latest.osrm.pbf"
$image = "ghcr.io/project-osrm/osrm-backend:v5.27.1"

docker info *> $null
if ($LASTEXITCODE -ne 0) { throw "Docker não está em execução. Abra o Docker Desktop e tente de novo." }

if (-not $Start) {
  if (-not (Test-Path "$dir\sul-latest.osm.pbf")) {
    Write-Host "Baixando o mapa do Sul do Brasil (Geofabrik, ~400 MB)..."
    Invoke-WebRequest "https://download.geofabrik.de/south-america/brazil/sul-latest.osm.pbf" -OutFile "$dir\sul-latest.osm.pbf"
  }
  Write-Host "Extraindo (perfil carro)..."
  docker run --rm -v "${dir}:/data" $image osrm-extract -p /opt/car.lua /data/sul-latest.osm.pbf
  Write-Host "Particionando e customizando (MLD)..."
  docker run --rm -v "${dir}:/data" $image osrm-partition /data/sul-latest.osrm
  docker run --rm -v "${dir}:/data" $image osrm-customize /data/sul-latest.osrm
}

docker rm -f osrm-poa *> $null
docker run -d --name osrm-poa --restart unless-stopped -p 5000:5000 -v "${dir}:/data" $image `
  osrm-routed --algorithm mld --max-table-size 200 /data/sul-latest.osrm
Write-Host "OSRM no ar em http://localhost:5000. Inicie o app com:  `$env:MATRIX='osrm'"
