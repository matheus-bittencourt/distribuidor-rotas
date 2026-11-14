"""Sorteia endereços REAIS de Porto Alegre (ruas do OpenStreetMap) e gera o resto aleatoriamente.

Uso:
  python scripts/gen_real_sample.py 1400 amostras/ruas1.json [ruas2.json ...]

Os JSON são respostas da Overpass API (`out center tags`) com ruas nomeadas dentro do município.
Saídas em amostras/:
  porto_alegre_N.csv            ENDEREÇO;NOME;COD_RASTREIO;PROTOCOLO   (formato modelo + PROTOCOLO, que é ignorado)
  porto_alegre_N.geocache.csv   query;lat;lon;precisao  -> use GEOCODER=cache GEOCACHE=<este arquivo>

Entregas repetidas: parte dos endereços recebe de 2 a 4 entregas (taxa variável ao longo da lista), em
geral moradores de um mesmo condomínio (mesmo endereço, Bloco/apto diferentes). As linhas vêm embaralhadas.

Atenção: o número da casa é sorteado e a coordenada é o ponto central do trecho da rua; por isso a
precisão do geocache é "aproximado". Nomes, códigos e protocolos são fictícios.
"""
import csv
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.extract import to_query  # noqa: E402

NOMES = ["Ana", "Bruno", "Carla", "Diego", "Elisa", "Fábio", "Gabriela", "Henrique", "Isabel", "João", "Karina",
         "Lucas", "Marina", "Nicolas", "Olívia", "Paulo", "Queila", "Rafael", "Sabrina", "Thiago", "Úrsula",
         "Vitor", "Wesley", "Yasmin", "Zélia", "Alberto", "Beatriz", "Caio", "Denise", "Eduardo"]
SOBRE = ["Silva", "Souza", "Oliveira", "Santos", "Pereira", "Lima", "Costa", "Ribeiro", "Almeida", "Machado",
         "Rodrigues", "Ferreira", "Alves", "Martins", "Gomes", "Barbosa", "Rocha", "Dias", "Moreira", "Jota"]


def main():
    n = int(sys.argv[1])
    ways, seen = [], set()
    for path in sys.argv[2:]:
        for el in json.loads(Path(path).read_text(encoding="utf-8"))["elements"]:
            c, name = el.get("center"), el.get("tags", {}).get("name")
            if c and name and el["id"] not in seen:
                seen.add(el["id"])
                ways.append((name, c["lat"], c["lon"]))
    if len(ways) < n:
        raise SystemExit(f"Só {len(ways)} trechos de rua disponíveis para sortear {n}.")
    r = random.Random(2026)
    picked = r.sample(ways, min(len(ways), n))   # trechos de rua distintos: cada um vira no máximo um endereço-base

    out = Path("amostras"); out.mkdir(exist_ok=True)
    codes, rows, cache = set(), [], {}
    rate, stats = 0.25, {"enderecos": 0, "repetidos": 0, "condominios": 0, "max": 1}
    for i, (name, lat, lon) in enumerate(picked):
        if len(rows) >= n:
            break
        if i % 40 == 0:                       # a taxa de repetição varia ao longo da lista
            rate = r.uniform(0.05, 0.55)
        k = 1 if r.random() > rate else r.choices([2, 3, 4], weights=[55, 30, 15])[0]
        k = min(k, n - len(rows))
        num = r.randint(1, 2400)
        condo = (k >= 2 and r.random() < 0.65) or (k == 1 and r.random() < 0.08)   # prédio/condomínio
        used_units = set()
        for _ in range(k):
            addr = f"{name}, {num}"
            if condo:                         # moradores do mesmo condomínio: mesmo endereço, unidades diferentes
                while True:
                    unit = f"{r.randint(1, 12)}{r.randint(1, 8):02d}"
                    bloco = r.choice("ABCD") if r.random() < 0.5 else ""
                    if (bloco, unit) not in used_units:
                        used_units.add((bloco, unit))
                        break
                addr += (f", Bloco {bloco}" if bloco else "") + f", apto {unit}"
            code = f"BR{r.randint(0, 999999):06d}POA"
            while code in codes:
                code = f"BR{r.randint(0, 999999):06d}POA"
            codes.add(code)
            rows.append([addr, f"{r.choice(NOMES)} {r.choice(SOBRE)} {r.choice(SOBRE)}", code, str(r.randint(10**9, 10**10 - 1))])
            cache[to_query(addr)] = (lat, lon)
        stats["enderecos"] += 1
        stats["repetidos"] += k >= 2
        stats["condominios"] += bool(condo)
        stats["max"] = max(stats["max"], k)
    r.shuffle(rows)                           # a lista do dia não vem agrupada por endereço

    with open(out / f"porto_alegre_{n}.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, delimiter=";"); w.writerow(["ENDEREÇO", "NOME", "COD_RASTREIO", "PROTOCOLO"]); w.writerows(rows)
    with open(out / f"porto_alegre_{n}.geocache.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, delimiter=";"); w.writerow(["query", "lat", "lon", "precisao"])
        for q, (lat, lon) in cache.items():
            w.writerow([q, f"{lat:.6f}", f"{lon:.6f}", "aproximado"])
    print(f"{len(rows)} entregas em {stats['enderecos']} endereços distintos "
          f"({stats['repetidos']} com 2 a {stats['max']} entregas; {stats['condominios']} condomínios/prédios) -> {out.resolve()}")


if __name__ == "__main__":
    main()
