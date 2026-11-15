"""Gera a locução (Piper, voz pt_BR "faber", licença CC0) e anota a duração de cada trecho.

Uso:  .tts\\Scripts\\python scripts\\voz.py
Saída: public/audio/voz-<cena>.wav e src/voz.json (duração em segundos).
Roda só no computador; nenhum texto é enviado para fora.
"""
import json
import wave
from pathlib import Path

from piper import PiperVoice, SynthesisConfig

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "public" / "audio"

# Um trecho por cena (ou por passo). O texto acompanha o que aparece na tela.
FALAS = {
    "problema": "Novecentas entregas, quatorze entregadores. Quem leva o quê, e em que ordem?",
    "solucao": "O Distribuidor de rotas recebe a lista do dia e devolve as rotas prontas: "
               "divididas de forma equilibrada, ordenadas pelas ruas, e com os dados protegidos.",
    "passo1": "Primeiro, carregue a planilha. Só nome, endereço e rastreio são usados. O resto é descartado.",
    "passo2": "Depois, confira os endereços. Cada um é localizado no mapa, mesmo com erro de digitação.",
    "passo3": "Com um clique, as entregas são divididas, e cada rota é colocada em ordem.",
    "passo4": "Por fim, envie a rota de cada entregador pelo WhatsApp, um por vez.",
    "privacidade": "Tudo roda no seu computador: sem internet, sem instalação, e nada fica gravado.",
    "final": "Para começar: baixe, abra, e carregue a lista do dia. É gratuito.",
}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    voice = PiperVoice.load(str(ROOT / ".tts" / "voices" / "pt_BR-faber-medium.onnx"))
    cfg = SynthesisConfig(length_scale=1.0)
    durs = {}
    for nome, texto in FALAS.items():
        path = OUT / f"voz-{nome}.wav"
        with wave.open(str(path), "wb") as w:
            voice.synthesize_wav(texto, w, syn_config=cfg)
        with wave.open(str(path), "rb") as w:
            durs[nome] = round(w.getnframes() / w.getframerate(), 2)
        print(f"{nome:12s} {durs[nome]:5.2f} s")
    (ROOT / "src" / "voz.json").write_text(json.dumps(durs, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
