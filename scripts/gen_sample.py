"""Gera planilhas FICTÍCIAS para testar (nomes, CPFs e valores inventados).

Uso:  python scripts/gen_sample.py [quantidade] [pasta_saida]
Cria três arquivos:
  amostra_modelo.csv    -> o formato modelo:  ENDEREÇO;NOME;COD_RASTREIO
  amostra_colunas.xlsx  -> planilha larga, com CPF, dívida, telefone, PROTOCOLO (devem ser descartados)
  amostra_livre.csv     -> uma coluna de texto livre com tudo misturado
"""
import csv
import random
import sys
from pathlib import Path

import openpyxl

RUAS = ["Rua dos Andradas", "Avenida Ipiranga", "Rua Sarmento Leite", "Avenida Osvaldo Aranha",
        "Rua Voluntários da Pátria", "Avenida Protásio Alves", "Rua Padre Chagas", "Avenida Assis Brasil",
        "Rua Lima e Silva", "Avenida Bento Gonçalves", "Rua Cristóvão Colombo", "Avenida Cavalhada",
        "Rua Dr. Timóteo", "Avenida Wenceslau Escobar", "Rua Barão do Amazonas"]
BAIRROS = ["Centro Histórico", "Cidade Baixa", "Moinhos de Vento", "Petrópolis", "Menino Deus", "Tristeza",
           "Partenon", "Sarandi", "Cavalhada", "Passo d'Areia"]
NOMES = ["Ana", "Bruno", "Carla", "Diego", "Elisa", "Fábio", "Gabriela", "Henrique", "Isabel", "João", "Karina", "Lucas"]
SOBRE = ["Silva", "Souza", "Oliveira", "Santos", "Pereira", "Lima", "Costa", "Ribeiro", "Almeida", "Machado"]


def cpf(r):
    d = [r.randint(0, 9) for _ in range(11)]
    return "{}{}{}.{}{}{}.{}{}{}-{}{}".format(*d)


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 50
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("amostras")
    out.mkdir(parents=True, exist_ok=True)
    r = random.Random(42)
    rows = []
    for i in range(n):
        rows.append({
            "nome": f"{r.choice(NOMES)} {r.choice(SOBRE)} {r.choice(SOBRE)}",
            "cpf": cpf(r), "rua": r.choice(RUAS), "num": r.randint(1, 3000),
            "bairro": r.choice(BAIRROS), "cidade": "Porto Alegre",
            "valor": f"R$ {r.randint(100, 9000):,}".replace(",", ".") + f",{r.randint(0, 99):02d}",
            "tel": f"(51) 9{r.randint(1000, 9999)}-{r.randint(1000, 9999)}",
            "protocolo": str(r.randint(10**9, 10**10 - 1)), "cod": f"BR{i + 1:06d}POA",
        })
    if n > 5:
        rows[3]["rua"] = "Rua Inexistente do Teste"      # vai para a revisão no modo fake
    if n > 8:
        rows[7]["cidade"] = "Canoas"                      # fora de Porto Alegre: revisão

    with open(out / "amostra_modelo.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, delimiter=";"); w.writerow(["ENDEREÇO", "NOME", "COD_RASTREIO"])
        for x in rows:
            tail = f", {x['cidade']}" if x["cidade"] != "Porto Alegre" else ""
            w.writerow([f"{x['rua']}, {x['num']}{tail}", x["nome"], x["cod"]])

    wb = openpyxl.Workbook(); ws = wb.active
    ws.append(["PROTOCOLO", "Nome", "CPF", "ENDEREÇO", "Bairro", "Valor da dívida", "Telefone", "COD_RASTREIO"])
    for x in rows:
        ws.append([x["protocolo"], x["nome"], x["cpf"], f"{x['rua']}, {x['num']}", x["bairro"], x["valor"], x["tel"], x["cod"]])
    wb.save(out / "amostra_colunas.xlsx")

    with open(out / "amostra_livre.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, delimiter=";"); w.writerow(["registro"])
        for x in rows:
            w.writerow([f"{x['nome']} CPF {x['cpf']} deve {x['valor']} - {x['rua']}, {x['num']}, {x['bairro']}, Porto Alegre - tel {x['tel']}"])
    print(f"{n} linhas em {out.resolve()}")


if __name__ == "__main__":
    main()
