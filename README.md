# Distribuidor de rotas (POC) — 100% gratuito

Lê a lista de entregas do dia, guarda **só nome, endereço e código de rastreio**, divide as paradas
entre N entregadores **por zonas de Porto Alegre** e ordena cada rota. Partida e chegada padrão:
**Av. Mostardeiros, 322 – Moinhos de Vento** (editável). Entregas só dentro de Porto Alegre.

Nenhuma parte exige conta paga ou chave de API.

## Como rodar

```bash
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
copy .env.example .env          # opcional
.venv\Scripts\python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Abra http://127.0.0.1:8000. Para testar sem rede e sem dados reais:

```bash
.venv\Scripts\python scripts\gen_sample.py 900         # amostras/ com CPFs e valores FICTÍCIOS
set GEOCODER=fake                                      # coordenadas sintéticas, sem internet
.venv\Scripts\python -m pytest                         # 25 testes
```

## Formato de entrada

Modelo atual (`;` ou `,` como separador, `.csv` ou `.xlsx`):

```
ENDEREÇO;NOME;COD_RASTREIO
Rua x, 1237;João Silva;BR123456POA
Rua y, 543;Alberto Jota;BR00123POA
```

- Colunas extras (CPF, valor, telefone, **PROTOCOLO**, contrato…) são **descartadas** pelo cabeçalho.
- `COD_RASTREIO` é o identificador da entrega: aparece na lista, no CSV e no texto do WhatsApp; códigos
  repetidos são ignorados (com aviso).
- Formato diferente? A tela mostra uma amostra **mascarada** e você aponta as colunas (nome, endereço,
  código…). Marcando "lembrar", o formato é salvo em `data/templates.json` (só nomes de colunas, nunca
  dados) e nos dias seguintes é reconhecido sozinho.
- Texto livre / PDF / planilha sem colunas: usa IA local (Ollama) ou, sem ela, a heurística.

## Como cada requisito foi tratado

| Requisito | Solução |
|---|---|
| Só Porto Alegre | Endereço sem cidade é consultado "em Porto Alegre"; cidade da região metropolitana no texto ou no resultado do mapa, ou ponto fora do município, vai para **revisar**. Casas de entregadores podem ficar fora de POA. |
| Descartar CPF, dívida etc. | Colunas sensíveis caem pelo cabeçalho; o restante passa por regex local (CPF, CNPJ, valores, telefone, e-mail, datas, números longos) **antes** de qualquer uso de IA; a saída da IA é mascarada e conferida contra a linha original. |
| Arquivos apagados | O arquivo nunca vai para disco. Dados só em memória, somem em 2 h ou no botão "Apagar tudo agora". |
| Centenas de linhas, por zonas | Cada parada é associada a uma das 10 zonas da cidade (`app/zones.json`) e "puxada" para o centro dela antes do agrupamento (controle **Prioridade por zona**). Depois, k-means de tamanhos iguais + polimento global (OR-Tools). A tela mostra a zona principal de cada entregador e a % de paradas dentro dela. |
| Início/fim | Todos saem do ponto padrão (ou da casa, se informada) e **terminam no ponto de chegada**. Entregador listado só pelo nome sai do ponto padrão. |
| Distância por tempo | Matriz de tempos (OSRM por ruas, ou estimativa por linha reta) + tempo de parada. |
| Limite de pontos no Maps | Links encadeados de até 10 paradas (9 intermediárias + destino do trecho). O 1º link omite a origem, então o Maps usa a **localização atual**; o último termina no ponto de chegada. |

## IA local gratuita (Ollama) — só para formato livre / PDF

```bash
winget install Ollama.Ollama
ollama pull qwen2.5:7b          # ~5 GB; troque por outro modelo com OLLAMA_MODEL
```

O app detecta o Ollama sozinho (`LLM_PROVIDER=auto`). Tudo roda no seu computador. Sem GPU é lento
(dezenas de minutos para milhares de linhas): para planilhas no formato modelo **não é usado**.
Como modelos pequenos erram, cada resposta é conferida contra o texto da linha (endereço inventado é
descartado) e o que a IA deixa passar cai na heurística.

## Configuração (`.env`)

| Variável | Padrão | Para quê |
|---|---|---|
| `DEFAULT_DEPOT` | Av. Mostardeiros, 322… | Partida padrão e chegada. |
| `LLM_PROVIDER` | `auto` | `auto`, `ollama`, `anthropic` (opcional, exige chave) ou `none`. |
| `OLLAMA_URL` / `OLLAMA_MODEL` | `localhost:11434` / `qwen2.5:7b` | IA local. |
| `GEOCODER` | `nominatim` | `nominatim`, `google` (pago, opcional) ou `fake` (testes). |
| `NOMINATIM_URL` / `NOMINATIM_RATE` | servidor público / 1 req/s | Aponte para um Nominatim próprio e suba a taxa. |
| `MATRIX` / `OSRM_URL` | `haversine` / `http://localhost:5000` | `osrm` calcula tempos reais por ruas. |
| `ZONE_WEIGHT` | 0,5 | 0 = só proximidade; 1 = zonas mandam. |
| `SERVICE_SECONDS` / `SOLVER_SECONDS` | 120 / 30 | Tempo por parada; orçamento de cálculo. |

## Limites conhecidos (leia antes de confiar)

- **Zonas são aproximadas.** `app/zones.json` tem 10 centros de zona escritos de memória (Centro,
  Moinhos/Petrópolis, Norte Central, Norte, Nordeste, Leste, Sul Central, Sul, Sudeste/Restinga,
  Extremo Sul). Cada parada vai para o centro mais próximo, sem polígonos de bairro. Confira e ajuste.
- **Ponto padrão não confirmado no mapa.** A geocodificação resolve "Av. Mostardeiros, 322"; se falhar,
  usa uma coordenada de reserva aproximada (`FALLBACK_DEPOT` em `app/config.py`).
- **Geocodificação gratuita é lenta.** O Nominatim público permite ~1 req/s: 900 endereços ≈ 15 min,
  2000 ≈ 35 min, e é uso pesado para um servidor gratuito. Para a rotina diária, um Nominatim próprio
  (recorte do Sul do Brasil) resolve; o app precisaria de Docker, que não está instalado nesta máquina.
- **Tempos por estimativa** sem OSRM (linha reta × 1,35 ÷ 28 km/h): bom para dividir regiões,
  impreciso para ETA. O cliente OSRM está implementado, mas **não foi testado contra um servidor real**.
- **Ollama não testado com modelo real** (não está instalado aqui). O caminho foi testado com uma
  resposta simulada: extração correta, descarte de endereço inventado, queda para a heurística
  quando o servidor está fora do ar. A qualidade com o modelo real precisa de amostra real.
- **Testes de rota usam geocodificador fictício e dados sintéticos.** Nada foi medido com endereços
  reais de Porto Alegre.
- **"Primeiro ponto = o mais próximo do entregador"** é atendido pela estrutura da rota (sai do ponto
  de partida rumo à chegada), não como regra rígida.
- **Localização atual dos entregadores** em tempo real exige um link hospedado (próximo passo); a POC
  usa o ponto padrão ou o endereço informado.
- **PDF escaneado** não é lido (sem OCR). O limite de 9 intermediários por link do Maps é o documentado:
  confirme no seu uso. O app não tem login: rode só em `127.0.0.1`.

## Estrutura

```
app/sanitize.py   mascaramento local         app/solver.py    zonas → grupos → ordem → polimento
app/extract.py    leitura, modelos, IA       app/zones.py     zonas de Porto Alegre (zones.json)
app/templates.py  formatos salvos            app/matrix.py    tempos (estimativa / OSRM)
app/geocode.py    endereço → coordenadas     app/links.py     links do Maps fragmentados
app/jobs.py       estado em memória          app/main.py      API + páginas estáticas
scripts/          amostras fictícias e teste ponta a ponta (e2e_api.py)
```
