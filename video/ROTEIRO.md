# Roteiro — "Distribuidor de rotas: apresentação da solução"

- **Objetivo:** apresentar a solução para quem decide e para quem opera: que problema resolve, o que entrega e como se usa.
- **Tom:** de negócio. Sem código, sem nomes de arquivo e sem jargão técnico.
- **Duração:** 62 s (1.860 quadros a 30 fps).
- **Dois formatos, mesmo conteúdo:** `Video` (1920×1080, deitado) e `Reels` (1080×1920, em pé). As cenas se rearranjam conforme a proporção; no formato em pé há margem livre em cima (230 px) e embaixo (340 px) para a interface do aplicativo.
- **Dados na tela:** todos fictícios (nomes, CPF `000.000.000-00`, telefone `90000-0000`).

## Cenas e locução

| # | Cena | Tempo | Na tela | Locução |
|---|---|---|---|---|
| 1 | O problema | 0–6 s | "900 entregas. 14 entregadores." Na planilha, CPF e valor viram `[removido]`. Entra o nome da solução. | "Novecentas entregas, quatorze entregadores. Quem leva o quê, e em que ordem?" |
| 2 | A solução | 6–16 s | Três cartões: divide de forma equilibrada, ordena cada rota, protege os dados. Cada um entra quando a locução chega nele. | "O Distribuidor de rotas recebe a lista do dia e devolve as rotas prontas: divididas de forma equilibrada, ordenadas pelas ruas, e com os dados protegidos." |
| 3.1 | Carregue a lista | 16–23 s | Excel, CSV ou PDF. Dos seis campos, ficam nome, endereço e rastreio. | "Primeiro, carregue a planilha. Só nome, endereço e rastreio são usados. O resto é descartado." |
| 3.2 | Confira os endereços | 23–30 s | Endereço com erro de digitação é reconhecido e o pino cai no mapa. | "Depois, confira os endereços. Cada um é localizado no mapa, mesmo com erro de digitação." |
| 3.3 | Calcule as rotas | 30–37 s | Os pontos ganham a cor de cada entregador e as rotas são desenhadas. | "Com um clique, as entregas são divididas, e cada rota é colocada em ordem." |
| 3.4 | Envie aos entregadores | 37–44 s | Fila de envio com contador e a mensagem no WhatsApp. | "Por fim, envie a rota de cada entregador pelo WhatsApp, um por vez." |
| 4 | Privacidade | 44–52 s | Moldura "seu computador": sem internet, pen drive, nada gravado, gratuito. | "Tudo roda no seu computador: sem internet, sem instalação, e nada fica gravado." |
| 5 | Encerramento | 52–62 s | "Três passos para a primeira rota": baixe, abra, use. Endereço do GitHub. | "Para começar: baixe, abra, e carregue a lista do dia. É gratuito." |

## Áudio

Todo o áudio é gerado no próprio computador e fica em `public/audio/`.

| Camada | Como é feita | Direitos |
|---|---|---|
| Locução | `scripts/voz.py`: sintetizador Piper, voz masculina `pt_BR-faber-medium`. Roda sem internet. | Voz com licença CC0 (domínio público). |
| Música | `scripts/som.py`: trilha leve de 92 bpm (cama, dedilhado, bumbo macio), sintetizada do zero com numpy. | Original deste projeto; não usa amostras de terceiros. |
| Efeitos | `scripts/som.py`: passagem de cena (sopro), entrada de cartão (estalo), mascaramento (tique), confirmação (sino) e clique. | Idem. |

- A música toca a 16% do volume, cerca de 12 dB abaixo da voz.
- Para trocar um texto da locução, edite `FALAS` em `scripts/voz.py` e rode `npm run audio`. Se o trecho passar de 6,5 s, aumente `STEP` em `src/Flow.tsx` ou a duração da cena em `src/Root.tsx`.

## Comandos

```bash
npm run studio          # editor interativo
npm run audio           # refaz locução, música e efeitos
npm run preview         # prévia deitada: 960×540
npm run preview:reels   # prévia em pé: 540×960
npm run render          # final deitado: 1920×1080 em out/video.mp4
npm run render:reels    # final em pé: 1080×1920 em out/reels.mp4
```
