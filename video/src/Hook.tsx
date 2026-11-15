import React from "react";
import { useCurrentFrame } from "remotion";
import { C, MONO, PAD, Rise, Scene, Sfx, Voz, ease, useV } from "./ui";

// Planilha fictícia: [nome, CPF, endereço, valor, telefone].
const ROWS = [
  ["Maria S.", "000.000.000-00", "Rua Padre Chagas, 80", "R$ 1.250,00", "(51) 90000-0000"],
  ["João P.", "000.000.000-00", "Av. Ipiranga, 1200", "R$ 480,90", "(51) 90000-0000"],
  ["Ana L.", "000.000.000-00", "Rua da República, 45", "R$ 2.310,00", "(51) 90000-0000"],
  ["Carlos M.", "000.000.000-00", "Av. Protásio Alves, 3100", "R$ 96,40", "(51) 90000-0000"],
];
type Col = { h: string; w: number; bad?: boolean; cell: (r: string[]) => React.ReactNode };
const plain = (i: number) => (r: string[]) => r[i];
// Deitado: as cinco colunas. Em pé: nome e endereço na mesma célula, para caber na largura.
const COLS_H: Col[] = [
  { h: "Nome", w: 300, cell: plain(0) }, { h: "CPF", w: 290, bad: true, cell: plain(1) }, { h: "Endereço", w: 470, cell: plain(2) },
  { h: "Valor", w: 230, bad: true, cell: plain(3) }, { h: "Telefone", w: 300, bad: true, cell: plain(4) },
];
const COLS_V: Col[] = [
  { h: "Entrega", w: 420, cell: (r) => <><b>{r[0]}</b><br /><span style={{ color: C.muted, fontSize: 26 }}>{r[2]}</span></> },
  { h: "CPF", w: 290, bad: true, cell: plain(1) }, { h: "Valor", w: 226, bad: true, cell: plain(3) },
];

export const Hook: React.FC<{ dur: number }> = ({ dur }) => {
  const f = useCurrentFrame();
  const V = useV();
  const cols = V ? COLS_V : COLS_H;
  const pad = V ? PAD.v : PAD.h;
  const red = ease(f, 62, 76);      // colunas sensíveis ficam vermelhas
  const masked = f >= 88;           // e viram [removido]
  const dim = ease(f, 112, 128);    // a planilha recua para o nome entrar
  return (
    <Scene dur={dur}>
      <Voz name="problema" at={12} />
      <Sfx at={4} name="pop" /><Sfx at={88} name="tick" /><Sfx at={118} name="ding" volume={0.35} />

      <Rise at={4}><div style={{ fontSize: V ? 112 : 104, fontWeight: 800, letterSpacing: -2, lineHeight: 1.05 }}>900 entregas.{V ? <br /> : " "}14 entregadores.</div></Rise>
      <Rise at={20}><div style={{ fontSize: V ? 48 : 44, color: C.muted, marginTop: 22, lineHeight: 1.3 }}>Quem leva o quê, em que ordem, sem expor os dados de ninguém?</div></Rise>

      <Rise at={36} style={{ marginTop: V ? 70 : 56 }}>
        <div style={{ opacity: 1 - dim * 0.72, borderRadius: 18, overflow: "hidden", border: `2px solid ${C.line}`, background: C.panel, width: "fit-content" }}>
          <div style={{ display: "flex", background: C.panel2, fontWeight: 700, fontSize: 30 }}>
            {cols.map((c) => (
              <div key={c.h} style={{ width: c.w, padding: "18px 24px", color: c.bad ? `rgba(255,154,144,${0.55 + red * 0.45})` : C.ink }}>{c.h}</div>
            ))}
          </div>
          {ROWS.map((r, i) => (
            <div key={i} style={{ display: "flex", alignItems: "stretch", borderTop: `2px solid ${C.line}`, fontSize: 30 }}>
              {cols.map((c) => (
                <div key={c.h} style={{ width: c.w, padding: "17px 24px", whiteSpace: "nowrap", display: "flex", alignItems: "center", fontFamily: c.bad ? MONO : undefined, fontSize: c.bad ? (V ? 24 : 27) : 30,
                  background: c.bad ? `rgba(255,120,110,${red * 0.16})` : "transparent", color: c.bad && masked ? C.bad : C.ink }}>
                  <div>{c.bad && masked ? "[removido]" : c.cell(r)}</div>
                </div>
              ))}
            </div>
          ))}
        </div>
      </Rise>

      <div style={{ position: "absolute", left: pad.x, right: pad.x, bottom: pad.bottom }}>
        <Rise at={118}>
          <div style={{ fontSize: V ? 88 : 80, fontWeight: 800, color: C.accent, letterSpacing: -1, lineHeight: 1.05 }}>Distribuidor de rotas</div>
          <div style={{ fontSize: V ? 44 : 40, color: C.ink, marginTop: 10, lineHeight: 1.3 }}>Da planilha à rota de cada entregador, em minutos.</div>
        </Rise>
      </div>
    </Scene>
  );
};
