"""Configuração via variáveis de ambiente (ou arquivo .env na raiz do projeto)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _load_dotenv() -> None:
    env = Path(__file__).resolve().parent.parent / ".env"
    if not env.exists():
        return
    for line in env.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv()


def _f(name: str, default: float) -> float:
    return float(os.environ.get(name, default))


def _i(name: str, default: int) -> int:
    return int(os.environ.get(name, default))


@dataclass(frozen=True)
class Settings:
    # Extração
    claude_model: str = os.environ.get("CLAUDE_MODEL", "claude-opus-5-5")
    # Geocodificação: nominatim | google | fake
    geocoder: str = os.environ.get("GEOCODER", "nominatim")
    # GEOCODER=cache: lê endereço->coordenadas de um CSV local (query;lat;lon;precisao), sem rede
    geocache: str = os.environ.get("GEOCACHE", "data/geocache.csv")
    nominatim_url: str = os.environ.get("NOMINATIM_URL", "https://nominatim.openstreetmap.org")
    nominatim_rate: float = _f("NOMINATIM_RATE", 1.0)  # requisições/s (1 = política do servidor público)
    nominatim_user_agent: str = os.environ.get("NOMINATIM_USER_AGENT", "distribuidor-rotas-poc")
    google_api_key: str = os.environ.get("GOOGLE_MAPS_API_KEY", "")
    # Matriz de tempos: haversine | osrm
    matrix: str = os.environ.get("MATRIX", "haversine")
    osrm_url: str = os.environ.get("OSRM_URL", "http://localhost:5000")
    osrm_block: int = _i("OSRM_BLOCK", 100)     # pontos de origem e de destino por requisição (limite do servidor: 200 no total)
    osrm_workers: int = _i("OSRM_WORKERS", 8)
    # Estimativa usada quando não há OSRM
    avg_speed_kmh: float = _f("AVG_SPEED_KMH", 28.0)
    detour_factor: float = _f("DETOUR_FACTOR", 1.35)
    # Rotas
    service_seconds: int = _i("SERVICE_SECONDS", 120)  # tempo de parada em cada entrega
    delivery_tolerance_seconds: int = _i("DELIVERY_TOLERANCE_SECONDS", 60)  # folga somada a CADA entrega (padrão: 1 min)
    extra_delivery_seconds: int = _i("EXTRA_DELIVERY_SECONDS", 45)  # a cada entrega a mais no mesmo ponto
    solver_seconds: int = _i("SOLVER_SECONDS", 30)
    maps_waypoints_per_link: int = _i("MAPS_WAYPOINTS_PER_LINK", 9)
    # Ponto de partida padrão E ponto final de todas as rotas
    default_depot: str = os.environ.get(
        "DEFAULT_DEPOT", "Av. Mostardeiros, 322, Moinhos de Vento, Porto Alegre, RS"
    )
    # Extração com IA: auto | ollama | anthropic | none
    llm_provider: str = os.environ.get("LLM_PROVIDER", "auto")
    ollama_url: str = os.environ.get("OLLAMA_URL", "http://localhost:11434")
    ollama_model: str = os.environ.get("OLLAMA_MODEL", "qwen2.5:7b")
    ollama_chunk: int = _i("OLLAMA_CHUNK", 20)          # linhas por pedido (modelos pequenos pedem blocos curtos)
    ollama_timeout: int = _i("OLLAMA_TIMEOUT", 900)
    zone_weight: float = _f("ZONE_WEIGHT", 0.10)        # peso da zona (0 a 0,15): a carga vem antes
    km_tolerance: float = _f("KM_TOLERANCE", 0.15)       # faixa de km em torno da média (±15%); 0 = igualar os km
    zone_weight_max: float = 0.15                       # teto fixo (ver solver.MAX_ZONE_WEIGHT)
    default_city: str = os.environ.get("DEFAULT_CITY", "Porto Alegre")
    # Retenção: o job (com nomes/endereços) some da memória depois disso
    job_ttl_minutes: int = _i("JOB_TTL_MINUTES", 120)


SETTINGS = Settings()

# Entregas: SÓ dentro de Porto Alegre. Caixa aproximada do município (lat_min, lat_max, lon_min, lon_max);
# a checagem fina é feita pelo nome da cidade devolvido pelo geocodificador.
POA_BBOX = (-30.28, -29.92, -51.30, -51.00)
# Pontos de partida (casa dos entregadores) podem ficar na região metropolitana.
RMPA_BBOX = (-30.50, -29.60, -51.80, -50.60)

# Ponto de reserva se a geocodificação do ponto padrão falhar (Av. Mostardeiros, aprox. - conferir)
FALLBACK_DEPOT = (-30.0262, -51.2062)

RMPA_CITIES = [
    "porto alegre", "canoas", "gravataí", "gravatai", "viamão", "viamao", "alvorada",
    "cachoeirinha", "esteio", "sapucaia do sul", "são leopoldo", "sao leopoldo",
    "novo hamburgo", "campo bom", "sapiranga", "estância velha", "estancia velha",
    "ivoti", "dois irmãos", "dois irmaos", "guaíba", "guaiba", "eldorado do sul",
    "nova santa rita", "triunfo", "charqueadas", "montenegro", "portão", "portao",
    "taquara", "parobé", "parobe", "igrejinha", "glorinha", "santo antônio da patrulha",
    "santo antonio da patrulha", "são jerônimo", "sao jeronimo", "arroio dos ratos",
    "araricá", "ararica", "nova hartz", "capela de santana", "barra do ribeiro",
]
