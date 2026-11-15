import React from "react";
import { C, Eyebrow, Glyph, Rise, Scene, Sfx, Voz, useV } from "./ui";

const ITEMS = [
  {
    color: C.accent, title: "Divide de forma equilibrada",
    text: "Cada entregador sai com uma carga parecida, agrupada por região da cidade.",
    icon: <><circle cx={6} cy={7} r={2.5} /><circle cx={18} cy={7} r={2.5} /><circle cx={12} cy={17} r={2.5} /><path d="M8.5 7h7M7.5 9l3 6M16.5 9l-3 6" /></>,
  },
  {
    color: C.warn, title: "Ordena cada rota",
    text: "A sequência das paradas segue as ruas de verdade, saindo e voltando ao ponto de partida.",
    icon: <><path d="M5 19c0-6 14-4 14-10a3 3 0 0 0-6 0" /><circle cx={5} cy={19} r={1.8} /><path d="M16 5l3-2v4z" /></>,
  },
  {
    color: C.ok, title: "Protege os dados",
    text: "Só nome, endereço e rastreio são usados. O resto é descartado e nada sai do computador.",
    icon: <><path d="M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z" /><path d="M8.5 12l2.5 2.5 4.5-5" /></>,
  },
];
const AT = (i: number) => 60 + i * 70; // cada cartão entra quando a locução chega nele

export const Solution: React.FC<{ dur: number }> = ({ dur }) => {
  const V = useV();
  return (
    <Scene dur={dur} center>
      <Voz name="solucao" />
      {ITEMS.map((_, i) => <Sfx key={i} at={AT(i)} name="pop" />)}

      <Rise at={4}><Eyebrow>A solução</Eyebrow></Rise>
      <Rise at={10}><div style={{ fontSize: V ? 80 : 72, fontWeight: 800, letterSpacing: -1, marginTop: 8, lineHeight: 1.1 }}>A lista do dia entra.{V ? <br /> : " "}As rotas saem prontas.</div></Rise>

      <div style={{ display: "grid", gridTemplateColumns: V ? "1fr" : "repeat(3, 1fr)", gap: 32, marginTop: 70 }}>
        {ITEMS.map((x, i) => (
          <Rise key={x.title} at={AT(i)} dy={40}>
            <div style={{ background: C.panel, border: `2px solid ${C.line}`, borderTop: `6px solid ${x.color}`, borderRadius: 22, padding: V ? "36px 36px" : "40px 36px 44px", height: V ? undefined : 470,
              boxShadow: "0 24px 60px rgba(0,0,0,.35)", display: V ? "flex" : "block", gap: 32, alignItems: "center" }}>
              <Glyph color={x.color} size={V ? 120 : 96}>{x.icon}</Glyph>
              <div>
                <div style={{ fontSize: V ? 46 : 44, fontWeight: 800, marginTop: V ? 0 : 30, lineHeight: 1.15 }}>{x.title}</div>
                <div style={{ fontSize: V ? 34 : 31, color: C.muted, marginTop: 14, lineHeight: 1.4 }}>{x.text}</div>
              </div>
            </div>
          </Rise>
        ))}
      </div>
    </Scene>
  );
};
