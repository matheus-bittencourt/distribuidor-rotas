import React from "react";
import { C, Eyebrow, MONO, Rise, Scene, Sfx, Voz, useV } from "./ui";

const STEPS = [
  { t: "Baixe", s: "O arquivo .zip do programa, na página de download." },
  { t: "Abra", s: "Extraia a pasta e abra o programa. A tela aparece no navegador." },
  { t: "Use", s: "Carregue a lista do dia e envie as rotas." },
];
const AT = (i: number) => 36 + i * 30;

export const Outro: React.FC<{ dur: number }> = ({ dur }) => {
  const V = useV();
  return (
    <Scene dur={dur} center>
      <Voz name="final" />
      {STEPS.map((_, i) => <Sfx key={i} at={AT(i)} name="pop" />)}
      <Sfx at={150} name="ding" volume={0.35} />

      <Rise at={4}><Eyebrow>Comece hoje</Eyebrow></Rise>
      <Rise at={10}><div style={{ fontSize: V ? 80 : 72, fontWeight: 800, letterSpacing: -1, marginTop: 8, lineHeight: 1.1 }}>Três passos para a primeira rota</div></Rise>

      <div style={{ display: "grid", gridTemplateColumns: V ? "1fr" : "repeat(3, 1fr)", gap: 32, marginTop: 70 }}>
        {STEPS.map((x, i) => (
          <Rise key={x.t} at={AT(i)} dy={36}>
            <div style={{ background: C.panel, border: `2px solid ${C.line}`, borderRadius: 22, padding: V ? "34px 36px" : "36px 36px 40px", height: V ? undefined : 350, boxShadow: "0 24px 60px rgba(0,0,0,.35)",
              display: V ? "flex" : "block", gap: 32, alignItems: "center" }}>
              <div style={{ width: V ? 96 : 76, height: V ? 96 : 76, borderRadius: 48, background: C.accentSoft, border: `3px solid ${C.accent}`, color: C.accent, display: "grid", placeItems: "center", fontSize: V ? 46 : 38, fontWeight: 800, flex: "none" }}>{i + 1}</div>
              <div>
                <div style={{ fontSize: 48, fontWeight: 800, marginTop: V ? 0 : 22 }}>{x.t}</div>
                <div style={{ fontSize: V ? 33 : 31, color: C.muted, marginTop: 8, lineHeight: 1.4 }}>{x.s}</div>
              </div>
            </div>
          </Rise>
        ))}
      </div>

      <Rise at={150} style={{ marginTop: V ? 70 : 56 }}>
        <div style={{ display: "flex", flexDirection: V ? "column" : "row", alignItems: V ? "flex-start" : "center", justifyContent: "space-between", gap: 30 }}>
          <div>
            <div style={{ fontSize: V ? 80 : 60, fontWeight: 800, color: C.accent, letterSpacing: -1, lineHeight: 1.05 }}>Distribuidor de rotas</div>
            <div style={{ fontSize: V ? 34 : 30, color: C.muted, marginTop: 8 }}>Gratuito · Windows · entregas em Porto Alegre</div>
          </div>
          <div style={{ fontFamily: MONO, fontSize: 28, padding: "18px 26px", borderRadius: 16, background: C.panel, border: `2px solid ${C.line}` }}>
            github.com/matheus-bittencourt/distribuidor-rotas
          </div>
        </div>
      </Rise>
    </Scene>
  );
};
