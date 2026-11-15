import React from "react";
import { useCurrentFrame } from "remotion";
import { C, Eyebrow, Glyph, Rise, Scene, Sfx, Voz, ease, useV } from "./ui";

const ITEMS = [
  { t: "Funciona sem internet", s: "O mapa de Porto Alegre vai junto com o programa.", icon: <><path d="M3 9a14 14 0 0 1 18 0M6.5 12.5a9 9 0 0 1 11 0M10 16a4 4 0 0 1 4 0" /><path d="M4 4l16 16" /></> },
  { t: "Roda de um pen drive", s: "Sem instalar nada no computador.", icon: <><rect x={7} y={9} width={10} height={12} rx={2} /><path d="M9 9V4h6v5M11 6.5h.01M13 6.5h.01" /></> },
  { t: "Nada fica gravado", s: "Fechou o programa, a lista some da memória.", icon: <><path d="M5 7h14M10 7V4h4v3M7 7l1 13h8l1-13" /></> },
  { t: "Gratuito", s: "Sem assinatura, sem conta e sem chave de acesso.", icon: <><circle cx={12} cy={12} r={9} /><path d="M8.5 12l2.5 2.5 4.5-5" /></> },
];
const AT = (i: number) => 40 + i * 28;

export const Privacy: React.FC<{ dur: number }> = ({ dur }) => {
  const f = useCurrentFrame();
  const V = useV();
  const glow = ease(f, 24, 50);
  return (
    <Scene dur={dur} center>
      <Voz name="privacidade" />
      {ITEMS.map((_, i) => <Sfx key={i} at={AT(i)} name="pop" volume={0.35} />)}

      <Rise at={4}><Eyebrow>Privacidade</Eyebrow></Rise>
      <Rise at={10}><div style={{ fontSize: V ? 80 : 72, fontWeight: 800, letterSpacing: -1, marginTop: 8, lineHeight: 1.1 }}>Os dados não saem do seu computador</div></Rise>

      <div style={{ position: "relative", marginTop: 76, padding: V ? "76px 40px 60px" : "70px 44px 60px", borderRadius: 28, border: `3px dashed rgba(98,212,155,${0.25 + glow * 0.6})`, background: `rgba(98,212,155,${glow * 0.04})` }}>
        <div style={{ position: "absolute", top: -24, left: 40, background: C.bg, padding: "0 18px", fontSize: 32, fontWeight: 700, color: C.ok }}>seu computador</div>
        <div style={{ display: "grid", gridTemplateColumns: V ? "1fr" : "1fr 1fr", gap: V ? 54 : "60px 40px" }}>
          {ITEMS.map((x, i) => (
            <Rise key={x.t} at={AT(i)} dy={24}>
              <div style={{ display: "flex", gap: 28, alignItems: "center" }}>
                <Glyph color={C.ok} size={V ? 108 : 92}>{x.icon}</Glyph>
                <div>
                  <div style={{ fontSize: V ? 46 : 42, fontWeight: 800 }}>{x.t}</div>
                  <div style={{ fontSize: V ? 33 : 30, color: C.muted, marginTop: 4, lineHeight: 1.35 }}>{x.s}</div>
                </div>
              </div>
            </Rise>
          ))}
        </div>
      </div>
    </Scene>
  );
};
