# Distribuidor de rotas (POC) — 100% gratuito

Lê a lista de entregas do dia, guarda **só nome, endereço e código de rastreio**, divide as paradas
entre N entregadores **por zonas de Porto Alegre** e ordena cada rota. Partida e chegada padrão:
**Av. Mostardeiros, 322 – Moinhos de Vento** (editável). Entregas só dentro de Porto Alegre.

Nenhuma parte exige conta paga ou chave de API.

## Uso isolado (pen drive) — recomendado para dados reais

O executável roda **só no computador onde é aberto, sem instalar nada e sem enviar nenhum dado**:

1. Baixe `DistribuidorRotas-windows.zip` na página de [Releases](https://github.com/matheus-bittencourt/distribuidor-rotas/releases)
   e extraia a pasta no pen drive. Ela já traz o mapa offline mais recente.
2. Abra `DistribuidorRotas.exe`. O navegador abre em `http://127.0.0.1:8765` (só nesta máquina).
   Na primeira vez, o Windows pode avisar que o programa não é assinado: “Mais informações” → “Executar assim mesmo”.
3. Fechar a janela preta encerra o app e apaga da memória tudo o que foi carregado.

O que garante o isolamento:

| Proteção | Como |
|---|---|
| Nenhuma conexão para fora | Bloqueio no nível do sistema (`app/netguard.py`): resolução de nomes e conexões para qualquer endereço que não seja o próprio computador falham, para qualquer biblioteca. Tentativas aparecem no log. |
| Endereços achados sem internet | Índice de ruas e números de Porto Alegre do OpenStreetMap, dentro do pacote de mapa (`app/localgeo.py`). |
| Rotas por ruas sem servidor | Malha viária do pacote de mapa + Dijkstra do scipy (`app/router.py`). Tempos e km ficaram a 1% do OSRM. |
| Fundo do mapa local | Recorte de Porto Alegre do mapa vetorial do Protomaps, servido pelo próprio app. |
| Nada gravado em disco | A lista fica só na memória (o envio do arquivo não usa arquivo temporário) e as respostas não entram no cache do navegador. Executável em pasta, não em arquivo único (que se descompactaria em `%TEMP%`). |
| Única saída: atualização do mapa | Ao abrir, **antes** de qualquer lista ser carregada, o app baixa um manifesto assinado do GitHub. Nada sobre as entregas é enviado. Desligue em “Procurar atualização do mapa ao abrir” no rodapé. |

### Atualização do mapa

Todo mês uma automação (`.github/workflows/mapa.yml`) gera o pacote a partir do OpenStreetMap, assina com
Ed25519 e publica nos releases (`mapa-AAAA.MM.DD` + o canal fixo `mapa-atual`). Ao abrir, o app mostra
**“Existe uma atualização do mapa disponível”** e o botão **Baixar**. O download é retomável, só é usado
se a assinatura e o SHA-256 conferem, a troca é atômica e a versão anterior fica guardada.
Sem internet ou com a verificação desligada: copie a pasta `mapa` de outro pen drive atualizado.

### Limites do modo offline

- **Números de casa:** o OpenStreetMap tem números em poucas ruas de Porto Alegre. Fora delas o ponto é o
  meio da rua e aparece como “aproximado” (a ordem das paradas continua valendo). Ruas com o mesmo nome em
  bairros diferentes são desempatadas pelo bairro do endereço; sem bairro, pela numeração (métrica).
- **Sem trânsito:** tempos de rua livre, como no OSRM.
- **PDF / texto livre:** sem IA no executável; planilhas e CSV no formato modelo não precisam dela.

## Como rodar (desenvolvimento)

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
| Centenas de linhas, por zonas | Cada parada é associada a uma das 10 zonas da cidade (`app/zones.json`). **A zona pesa no máximo 15%** (controle "Peso das zonas", padrão 10%): ela puxa as paradas para o centro da zona e penaliza levemente paradas fora da zona do entregador, mas a carga (km, entregas e tempo) vem antes. A tela mostra a zona principal de cada entregador e a % de paradas dentro dela. |
| Enviar ao entregador | Dois botões por entregador: **Rota** (paradas na ordem, com nome, endereço e código) e **Links** (só os links do Maps, em trechos de até 10 paradas), para enviar em duas mensagens seguidas no WhatsApp. **Imprimir** gera a lista **completa** do entregador (todas as paradas e entregas, sem o corte de 10 dos links), em A4, com coluna de conferência; "Imprimir todas" põe um entregador por folha. |
| Várias entregas no mesmo endereço | Entregas no mesmo ponto (casa ou condomínio, com Bloco/apto diferentes) viram **uma parada só**: o entregador para uma vez, o Maps não repete o ponto e o tempo parado soma `EXTRA_DELIVERY_SECONDS` (45 s) por entrega a mais. A lista e o CSV continuam com uma linha por entrega. |
| Equilíbrio entre entregadores | Iguala a **carga** (km rodados, entregas e tempo juntos); o seletor "Igualar entre os entregadores" escolhe qual pesa mais (padrão: **km**, peso 6:1:1). Método: fatias a partir da partida → largura ajustada por uma medida combinada → paradas movidas da rota mais sobrecarregada para as folgadas, medindo o efeito real em cada rota, em 3 passadas com reordenação. "Quanto igualar" vai de 0% (só proximidade) a 100% (igualar tudo). A tela mostra a diferença menor×maior de km, entregas e tempo. |
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

## Rotas por ruas (OSRM local, gratuito)

Sem OSRM o app estima tempos e km por linha reta. Com o OSRM local, usa a malha viária real
(mapa OpenStreetMap do Sul do Brasil). Requer Docker Desktop em execução.

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\scripts\setup_osrm.ps1          # 1ª vez: baixa o mapa (~400 MB), processa e sobe o servidor
.\scripts\setup_osrm.ps1 -Start   # depois: só sobe o servidor
$env:MATRIX = "osrm"              # e inicie o app normalmente
```

O servidor fica no container `osrm-poa` (`http://localhost:5000`, reinicia com o Docker). Os dados
ficam em `osrm-data/` (fora do git). A matriz é pedida em blocos de `OSRM_BLOCK` × `OSRM_BLOCK` pontos,
`OSRM_WORKERS` em paralelo; um par sem rota mantém a estimativa por linha reta.

Medido com os 1400 endereços de teste (~960 pontos distintos) e 14 entregadores: matriz em ~30 s,
cálculo completo em ~48 s. Em 150 pares reais, a distância por ruas deu ≈ 1,36 × a linha reta (o fator
1,35 da estimativa está bem calibrado) e o tempo do OSRM ≈ 0,76 × o estimado (~37 km/h médios, **sem
trânsito**; a estimativa assume 28 km/h).

## Entregador a pé no Centro

Uma parte do Centro Histórico é atendida por **um único entregador a pé**. Toda entrega que cai dentro da
zona vai para ele; as demais seguem para as motos, como antes.

- **Zona:** o contorno do print de referência, em `app/pedestrian_zone.json` (polígono em latitude/longitude).
  Foi georreferenciado por 9 pontos do mapa (Mercado Público, Praça da Alfândega etc.): erro médio de ~40 m e
  máximo de ~75 m, então **uma entrega na rua que limita a zona pode cair de um lado ou do outro**. Para ajustar,
  edite os vértices do arquivo. Entrega exatamente sobre a borda conta como dentro.
- **Rota:** a pé, saindo e voltando ao mesmo ponto dentro da zona (padrão: Praça da Alfândega, editável na tela).
  Os links do Maps saem em modo "a pé". A rota soma aos entregadores informados (14 motos viram 15 rotas) e fica
  **fora do equilíbrio** de km, entregas e tempo: o veredito e as faixas comparam só as motos. O app avisa se a
  rota a pé passar de `PEDESTRIAN_MAX_HOURS` (8 h).
- **Tempos a pé:** com OSRM de pedestre (`.\scripts\setup_osrm.ps1 -Foot`, container `osrm-foot` em
  `http://localhost:5001`, perfil `foot`, ~5 km/h) vêm das calçadas e ruas; sem ele, a estimativa é linha reta ×
  `WALK_DETOUR_FACTOR` (1,25) ÷ `WALK_SPEED_KMH` (4,5).
- **Desligar:** a caixa "Um entregador a pé no Centro" (etapa 2) ou `PEDESTRIAN=0`.

Medido com os 1400 endereços de teste e 14 entregadores: 32 entregas em 22 paradas na zona, rota a pé de
~2h53 e ~7 km; as 14 motos ficaram com 95–101 entregas, 7h09–7h34 e 89–104 km. Cálculo completo em ~52 s.

## Configuração (`.env`)

| Variável | Padrão | Para quê |
|---|---|---|
| `DEFAULT_DEPOT` | Av. Mostardeiros, 322… | Partida padrão e chegada. |
| `LLM_PROVIDER` | `auto` | `auto`, `ollama`, `anthropic` (opcional, exige chave) ou `none`. |
| `OLLAMA_URL` / `OLLAMA_MODEL` | `localhost:11434` / `qwen2.5:7b` | IA local. |
| `GEOCODER` | `nominatim` | `nominatim`, `google` (pago, opcional) ou `fake` (testes). |
| `NOMINATIM_URL` / `NOMINATIM_RATE` | servidor público / 1 req/s | Aponte para um Nominatim próprio e suba a taxa. |
| `MATRIX` / `OSRM_URL` | `haversine` / `http://localhost:5000` | `osrm` calcula tempos e km reais por ruas. |
| `OSRM_BLOCK` / `OSRM_WORKERS` | 100 / 8 | Pontos de origem e de destino por requisição (o servidor aceita até 200 no total) e requisições simultâneas. |
| `PEDESTRIAN` / `OSRM_FOOT_URL` | 1 / `http://localhost:5001` | Liga o entregador a pé do Centro e aponta para o OSRM de pedestre. |
| `WALK_SPEED_KMH` / `WALK_DETOUR_FACTOR` / `PEDESTRIAN_MAX_HOURS` | 4,5 / 1,25 / 8 | Estimativa a pé (sem OSRM de pedestre) e limite do aviso de rota longa. |
| `KM_TOLERANCE` | 0,15 | Faixa de km em torno da média (±15%); 0 = tentar igualar os km. Editável na tela. |
| `ZONE_WEIGHT` | 0,10 | Peso das zonas, de 0 a 0,15 (teto fixo: valores maiores são cortados em 0,15). |
| `SERVICE_SECONDS` / `SOLVER_SECONDS` | 120 / 30 | Tempo por parada; orçamento de cálculo. |
| `DELIVERY_TOLERANCE_SECONDS` | 60 | Folga somada a **cada entrega** no tempo parado (ajustável na tela, em "Ajustes da divisão"). Paradas com várias entregas recebem a folga de cada uma. |
| `EXTRA_DELIVERY_SECONDS` | 45 | Tempo parado a mais por entrega adicional no mesmo ponto. |

## Limites conhecidos (leia antes de confiar)

- **Zonas são aproximadas.** `app/zones.json` tem 10 centros de zona escritos de memória (Centro,
  Moinhos/Petrópolis, Norte Central, Norte, Nordeste, Leste, Sul Central, Sul, Sudeste/Restinga,
  Extremo Sul). Cada parada vai para o centro mais próximo, sem polígonos de bairro. Confira e ajuste.
- **Ponto padrão não confirmado no mapa.** A geocodificação resolve "Av. Mostardeiros, 322"; se falhar,
  usa uma coordenada de reserva aproximada (`FALLBACK_DEPOT` em `app/config.py`).
- **Geocodificação gratuita é lenta.** O Nominatim público permite ~1 req/s: 900 endereços ≈ 15 min,
  2000 ≈ 35 min, e é uso pesado para um servidor gratuito. Para a rotina diária, um Nominatim próprio
  (recorte do Sul do Brasil) resolve; o app precisaria de Docker, que não está instalado nesta máquina.
- **Igualar custa km no total.** Medido com 1400 entregas reais e 14 entregadores saindo do mesmo ponto:
  agrupar por manchas de bairro deixa km 33–120, entregas 90–112 e tempo 5,3–8,7 h (soma ~750 km); igualar só
  os km deixa entregas de 8 a 170; o método atual (km prioritário, 100%) deixa km 79–86 (9%), entregas 97–103
  (6%) e tempo 7,1–7,3 h (3%), mas com ~1140 km no total (+50%) e rotas que se cruzam pela cidade, porque quem
  moraria perto passa a rodar mais para igualar. Intensidades menores trocam equilíbrio por menos km.
- **Tolerância na diferença de km (padrão: ±15%).** Em branco, o app tenta igualar os km. Com um valor (ex.: ±30%),
  entregas e tempo viram o alvo e o km só é penalizado fora da faixa. Medido na mesma amostra: km igual →
  km 76–85 (11%), entregas 5%, tempo 7%, 1119 km no total; faixa de ±30% → km 62–93 (33%), entregas 6%,
  tempo 10%, 988 km (−12%). A maior parte do custo de km vem de equilibrar entregas e tempo (cerca de +30%
  sobre o agrupamento por bairro); igualar também os km soma ~+12%.
- **Km também são estimados** sem OSRM (linha reta × 1,35). Igualar km tem custo: nos 1400 endereços de
  teste a soma de km subiu ~14% e a quantidade de paradas passou a variar de 10 a 156 por entregador.
- **Tempos por estimativa** sem OSRM (linha reta × 1,35 ÷ 28 km/h): bom para dividir regiões,
  impreciso para ETA. Com OSRM os tempos vêm das ruas, mas **sem trânsito** (horário de pico demora mais).
- **Ollama não testado com modelo real** (não está instalado aqui). O caminho foi testado com uma
  resposta simulada: extração correta, descarte de endereço inventado, queda para a heurística
  quando o servidor está fora do ar. A qualidade com o modelo real precisa de amostra real.
- **Testes de rota usam geocodificador fictício e dados sintéticos.** Nada foi medido com endereços
  reais de Porto Alegre.
- **"Primeiro ponto = o mais próximo do entregador"** é atendido pela estrutura da rota (sai do ponto
  de partida rumo à chegada), não como regra rígida.
- **Localização atual dos entregadores** em tempo real exige um link hospedado (próximo passo); a POC
  usa o ponto padrão ou o endereço informado.
- **Sessão sobrevive a recarregar a página.** O navegador guarda só o id do processamento (`sessionStorage`);
  o servidor mantém lista e resultado por `JOB_TTL_MINUTES` (2 h). Reiniciar o servidor apaga tudo.
- **Marcador de "já copiei".** O ✓ em "Copiar rota" e "Copiar links" vale só para esta tela e some ao
  recalcular; não registra se a mensagem foi de fato enviada no WhatsApp.
- **Elenco lembrado no navegador.** Ao calcular, nomes e casas dos entregadores e os ajustes ficam no
  `localStorage` deste navegador (nunca no servidor). "Esquecer" remove; "Apagar dados da sessão" apaga a
  lista do dia, mas não o elenco.
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
