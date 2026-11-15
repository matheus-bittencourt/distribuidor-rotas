// Gera a locução e os efeitos sonoros pela ElevenLabs (skills text-to-speech e sound-effects).
//
// Uso:  npm run audio:elevenlabs            (locução + efeitos)
//       npm run audio:elevenlabs -- vozes   (lista as vozes que a conta pode usar)
//       npm run audio:elevenlabs -- voz     (só a locução)   |   -- fx   (só os efeitos)
//
// Precisa de ELEVENLABS_API_KEY no ambiente ou em video/.env.local (nunca no código).
// Atenção: o texto da locução é enviado aos servidores da ElevenLabs. Ele não contém dado de entrega.
import { ElevenLabsClient } from "@elevenlabs/elevenlabs-js";
import { execFileSync } from "node:child_process";
import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const OUT = join(ROOT, "public", "audio");

// ---- locução: tom calmo e confiante
const VOICE_ID = process.env.ELEVENLABS_VOICE_ID ?? "JBFqnCBsd6RMkjVDRZzb"; // George (narrativa), voz pré-pronta
const MODEL = "eleven_v4";
const TOM = "[calm]"; // etiqueta de direção do Eleven v4; se a voz chegar a LER a etiqueta, deixe ""
const SETTINGS = { stability: 0.7, similarityBoost: 0.75 }; // estabilidade alta = entrega firme, sem oscilar

// Um trecho por cena (ou por passo). Mesmo texto de scripts/voz.py, com pausas marcadas na pontuação.
const FALAS = {
  problema: "Novecentas entregas. Quatorze entregadores. Quem leva o quê... e em que ordem?",
  solucao: "O Distribuidor de rotas recebe a lista do dia e devolve as rotas prontas: divididas de forma equilibrada, ordenadas pelas ruas, e com os dados protegidos.",
  passo1: "Primeiro, carregue a planilha. Só nome, endereço e rastreio são usados. O resto é descartado.",
  passo2: "Depois, confira os endereços. Cada um é localizado no mapa, mesmo com erro de digitação.",
  passo3: "Com um clique, as entregas são divididas, e cada rota é colocada em ordem.",
  passo4: "Por fim, envie a rota de cada entregador pelo WhatsApp, um por vez.",
  privacidade: "Tudo roda no seu computador. Sem internet, sem instalação, e nada fica gravado.",
  final: "Para começar: baixe, abra, e carregue a lista do dia. É gratuito.",
};

// ---- efeitos: descrição em inglês (o modelo segue melhor) e duração em segundos (mínimo 0,5)
const EFEITOS = {
  whoosh: ["Soft short airy whoosh, clean subtle motion-graphics transition, no bass rumble", 0.6],
  pop: ["Soft gentle UI pop, short rounded bubble click, clean and dry", 0.5],
  tick: ["Two quick soft digital ticks, subtle interface confirmation, dry", 0.5],
  ding: ["Gentle warm notification chime, single soft bell note with a short tail", 1.2],
  click: ["Soft clean mouse click, very short, dry, no reverb", 0.5],
};

if (!process.env.ELEVENLABS_API_KEY) {
  console.error("Falta ELEVENLABS_API_KEY. Rode `npx -y @elevenlabs/cli@latest onboard init` nesta pasta, ou ponha a chave em video/.env.local.");
  process.exit(1);
}
const client = new ElevenLabsClient(); // lê ELEVENLABS_API_KEY do ambiente

async function save(name, stream) {
  const chunks = [];
  for await (const c of stream) chunks.push(c);
  writeFileSync(join(OUT, name), Buffer.concat(chunks));
}
function seconds(name) {
  const out = execFileSync("npx", ["remotion", "ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", join(OUT, name)], { cwd: ROOT, shell: true });
  return Number(String(out).trim());
}

async function vozes() {
  const { voices } = await client.voices.getAll();
  for (const v of voices) if (v.category === "premade") console.log(`${v.voiceId}  ${v.name}  (${[v.labels?.gender, v.labels?.description, v.labels?.use_case].filter(Boolean).join(", ")})`);
}

async function locucao() {
  const durs = {};
  for (const [nome, texto] of Object.entries(FALAS)) {
    const audio = await client.textToSpeech.convert(VOICE_ID, { text: `${TOM} ${texto}`.trim(), modelId: MODEL, languageCode: "pt", voiceSettings: SETTINGS });
    await save(`voz-${nome}.mp3`, audio);
    durs[nome] = seconds(`voz-${nome}.mp3`);
    console.log(`voz ${nome.padEnd(12)} ${durs[nome].toFixed(2)} s`);
  }
  return durs;
}

async function efeitos() {
  for (const [nome, [text, durationSeconds]] of Object.entries(EFEITOS)) {
    const audio = await client.textToSoundEffects.convert({ text, modelId: "eleven_text_to_sound_v3", durationSeconds, promptInfluence: 0.7 });
    await save(`fx-${nome}.mp3`, audio);
    console.log(`fx  ${nome}`);
  }
}

const what = process.argv[2] ?? "tudo";
mkdirSync(OUT, { recursive: true });
if (what === "vozes") await vozes();
else {
  // src/audio.json diz às cenas quais arquivos tocar (os .wav locais ou os .mp3 da ElevenLabs)
  const cfg = { voz: "wav", fx: "wav" };
  let durs;
  if (what === "tudo" || what === "voz") { durs = await locucao(); cfg.voz = "mp3"; }
  if (what === "tudo" || what === "fx") { await efeitos(); cfg.fx = "mp3"; }
  writeFileSync(join(ROOT, "src", "audio.json"), JSON.stringify(cfg, null, 2));
  if (durs) {
    writeFileSync(join(ROOT, "src", "voz.json"), JSON.stringify(durs, null, 2));
    const longo = Math.max(durs.passo1, durs.passo2, durs.passo3, durs.passo4);
    console.log(`\nPasso mais longo: ${longo.toFixed(2)} s. Cada passo tem 7 s (STEP = 210 em src/Flow.tsx); aumente se passar de 6,6 s.`);
  }
}
