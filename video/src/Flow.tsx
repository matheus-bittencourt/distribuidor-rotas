import React from "react";
import { AbsoluteFill, Sequence, random, useCurrentFrame } from "remotion";
import { C, Card, Chip, Eyebrow, FONT, MONO, PAD, ROUTES, Rise, Sfx, Voz, ease, useV } from "./ui";

export const STEP = 210; // 7 s por passo: cabe a locução mais longa (6,3 s)
const STEPS = [
  { t: "Carregue a lista", s: "Excel, CSV ou PDF" },
  { t: "Confira os endereços", s: "achados no mapa" },
  { t: "Calcule as rotas", s: "divisão e ordem" },
  { t: "Envie aos entregadores", s: "um por vez" },
];
export const FLOW = STEP * STEPS.length;

// ------------------------------------------------------------------ trilho de passos
const Rail: React.FC = () => {
  const f = useCurrentFrame();
  const V = useV();
  const active = Math.min(STEPS.length - 1, Math.floor(f / STEP));
  const within = (f - active * STEP) / STEP;
  const dot = (i: number, size: number) => {
    const done = i < active, on = i === active;
    const col = on ? C.accent : done ? C.ok : C.muted;
    return (
      <div style={{ width: size, height: size, borderRadius: size / 2, border: `3px solid ${col}`, background: on ? C.accentSoft : done ? C.okBg : "transparent", color: col, display: "grid", placeItems: "center", fontSize: size * 0.48, fontWeight: 800, flex: "none", opacity: on || done ? 1 : 0.5 }}>
        {done ? "✓" : i + 1}
      </div>
    );
  };
  const fill = (i: number) => (i < active ? 100 : i === active ? within * 100 : 0);

  if (V) {
    // em pé: trilho horizontal no topo
    return (
      <div style={{ position: "absolute", left: PAD.v.x, right: PAD.v.x, top: PAD.v.top + 64, display: "flex", alignItems: "center", gap: 14 }}>
        {STEPS.map((s, i) => (
          <React.Fragment key={s.t}>
            {dot(i, 76)}
            {i < STEPS.length - 1 && (
              <div style={{ flex: 1, height: 5, background: C.line, borderRadius: 3, overflow: "hidden" }}>
                <div style={{ height: 5, width: `${fill(i)}%`, background: i < active ? C.ok : C.accent }} />
              </div>
            )}
          </React.Fragment>
        ))}
      </div>
    );
  }
  return (
    <div style={{ position: "absolute", left: 110, top: 285, width: 440 }}>
      {STEPS.map((s, i) => {
        const done = i < active, on = i === active;
        return (
          <div key={s.t} style={{ display: "flex", gap: 22, opacity: on ? 1 : done ? 0.8 : 0.45 }}>
            <div style={{ display: "flex", flexDirection: "column", alignItems: "center" }}>
              {dot(i, 62)}
              {i < STEPS.length - 1 && (
                <div style={{ width: 4, height: 88, background: C.line, margin: "8px 0", borderRadius: 2, overflow: "hidden" }}>
                  <div style={{ width: 4, height: `${fill(i)}%`, background: done ? C.ok : C.accent }} />
                </div>
              )}
            </div>
            <div style={{ paddingTop: 2 }}>
              <div style={{ fontSize: 34, fontWeight: on ? 800 : 600, color: on ? C.ink : C.muted, lineHeight: 1.15 }}>{s.t}</div>
              <div style={{ fontSize: 24, color: C.muted, marginTop: 4 }}>{s.s}</div>
            </div>
          </div>
        );
      })}
    </div>
  );
};

/** Palco de um passo: título, subtítulo e o conteúdo; esmaece na troca. */
const Stage: React.FC<{ n: number; sub: string; children: React.ReactNode }> = ({ n, sub, children }) => {
  const f = useCurrentFrame();
  const V = useV();
  const o = Math.min(ease(f, 0, 10), 1 - ease(f, STEP - 10, STEP));
  const box = V ? { left: PAD.v.x, top: PAD.v.top + 190, width: 1080 - PAD.v.x * 2, height: 1200 } : { left: 620, top: 165, width: 1190, height: 900 };
  return (
    <AbsoluteFill style={{ ...box, opacity: o, fontFamily: FONT, color: C.ink }}>
      <div style={{ fontSize: V ? 68 : 62, fontWeight: 800, letterSpacing: -1, lineHeight: 1.1 }}><span style={{ color: C.accent }}>{n}.</span> {STEPS[n - 1].t}</div>
      <div style={{ fontSize: V ? 36 : 33, color: C.muted, marginTop: 8, marginBottom: V ? 40 : 44, lineHeight: 1.3 }}>{sub}</div>
      {children}
    </AbsoluteFill>
  );
};

// ------------------------------------------------------------------ 1. carregar a lista
const FIELDS = [
  { k: "Nome", v: "Maria S.", keep: true }, { k: "CPF", v: "000.000.000-00" }, { k: "Endereço", v: "Rua Padre Chagas, 80", keep: true },
  { k: "Valor", v: "R$ 1.250,00" }, { k: "Telefone", v: "(51) 90000-0000" }, { k: "Rastreio", v: "AA123456789BR", keep: true },
];
const Load: React.FC = () => {
  const f = useCurrentFrame();
  const V = useV();
  const red = ease(f, 70, 82), masked = f >= 96, settle = ease(f, 112, 128);
  return (
    <Stage n={1} sub="A planilha do dia, do jeito que ela vem.">
      <Voz name="passo1" at={8} />
      <Sfx at={96} name="tick" /><Sfx at={116} name="ding" volume={0.3} />
      <div style={{ display: "flex", gap: 14, marginBottom: 30 }}>
        {["Excel", "CSV", "PDF"].map((t, i) => <Rise key={t} at={8 + i * 5} dy={14}><Chip color={C.ink}>{t}</Chip></Rise>)}
      </div>
      <div style={{ display: "grid", gridTemplateColumns: V ? "1fr 1fr" : "repeat(3, 1fr)", gap: V ? 26 : 20 }}>
        {FIELDS.map((x, i) => {
          const bad = !x.keep;
          return (
            <Rise key={x.k} at={22 + i * 5} dy={20}>
              <div style={{ background: bad ? `rgba(53,26,24,${red})` : C.panel, border: "3px solid", borderColor: bad ? `rgba(255,154,144,${0.2 + red * 0.8})` : settle > 0 ? `rgba(98,212,155,${0.2 + settle * 0.8})` : C.line, borderRadius: 16, padding: V ? "32px 28px" : "22px 26px", opacity: bad ? 1 - settle * 0.6 : 1 }}>
                <div style={{ fontSize: V ? 30 : 26, color: C.muted, fontWeight: 600 }}>{x.k}</div>
                <div style={{ fontSize: V ? 36 : 32, marginTop: 8, whiteSpace: "nowrap", fontFamily: bad ? MONO : FONT, color: bad && masked ? C.bad : C.ink, fontWeight: 600 }}>{bad && masked ? "[removido]" : x.v}</div>
              </div>
            </Rise>
          );
        })}
      </div>
      <Rise at={122} style={{ marginTop: V ? 60 : 44 }}>
        <div style={{ fontSize: V ? 46 : 38, lineHeight: 1.35 }}>Ficam só <b style={{ color: C.ok }}>nome, endereço e rastreio</b>.<br /><span style={{ color: C.muted }}>CPF, valores e telefones são descartados na hora.</span></div>
      </Rise>
    </Stage>
  );
};

// ------------------------------------------------------------------ 2. conferir endereços
const Addresses: React.FC = () => {
  const f = useCurrentFrame();
  const V = useV();
  const fixed = ease(f, 70, 84), drop = ease(f, 98, 114);
  const streets = [[40, 100, 520, 70], [20, 240, 540, 215], [60, 380, 520, 365], [130, 20, 160, 450], [310, 10, 320, 460], [460, 30, 450, 450]];
  return (
    <Stage n={2} sub="Cada endereço é localizado no mapa de Porto Alegre, sem internet.">
      <Voz name="passo2" at={8} />
      <Sfx at={72} name="ding" volume={0.3} /><Sfx at={110} name="pop" />
      <div style={{ display: "flex", flexDirection: V ? "column" : "row", gap: V ? 30 : 36 }}>
        <div style={{ flex: 1 }}>
          <Rise at={10}>
            <Card style={{ padding: V ? "32px 32px" : "24px 28px" }}>
              <div style={{ fontSize: 26, color: C.muted, fontWeight: 600 }}>Como veio na lista</div>
              <div style={{ fontSize: V ? 42 : 38, fontWeight: 700, marginTop: 4 }}>Rua <span style={{ color: C.warn, textDecoration: "underline wavy" }}>Pade</span> Chagas, 80</div>
            </Card>
          </Rise>
          <div style={{ fontSize: 44, color: C.accent, textAlign: "center", margin: "6px 0", opacity: fixed }}>↓</div>
          <div style={{ opacity: fixed, transform: `translateY(${(1 - fixed) * 20}px)` }}>
            <Card style={{ padding: V ? "32px 32px" : "24px 28px", borderColor: C.ok }}>
              <div style={{ fontSize: 26, color: C.ok, fontWeight: 700 }}>✓ Reconhecido</div>
              <div style={{ fontSize: V ? 42 : 38, fontWeight: 700, marginTop: 4 }}>Rua Padre Chagas, 80</div>
            </Card>
          </div>
          {!V && <Rise at={130} style={{ marginTop: 30 }}><Note /></Rise>}
        </div>
        <Rise at={20} style={V ? {} : { width: 560, flex: "none" }}>
          <div style={{ height: V ? 540 : 470, borderRadius: 20, border: `2px solid ${C.line}`, background: "#141b24", overflow: "hidden" }}>
            <svg width="100%" height="100%" viewBox="0 0 560 470" preserveAspectRatio="xMidYMid slice">
              {streets.map(([x1, y1, x2, y2], i) => <line key={i} x1={x1} y1={y1} x2={x2} y2={y2} stroke={i === 1 ? "#3a4a60" : "#273342"} strokeWidth={i === 1 ? 24 : 15} strokeLinecap="round" />)}
              <text x={170} y={212} fill={C.muted} fontSize={21} fontFamily={FONT} transform="rotate(-2.7 170 212)">Rua Padre Chagas</text>
              <ellipse cx={360} cy={224} rx={26 * drop} ry={8 * drop} fill="rgba(106,165,255,.35)" />
              <g transform={`translate(360 ${222 - (1 - drop) * 170})`} opacity={drop}>
                <path d="M0 0 C-36 -46 -36 -90 0 -90 C36 -90 36 -46 0 0 Z" fill={C.accent} stroke="#0d1117" strokeWidth={3} />
                <circle cx={0} cy={-60} r={12} fill="#0d1117" />
              </g>
            </svg>
          </div>
        </Rise>
        {V && <Rise at={130}><Note /></Rise>}
      </div>
    </Stage>
  );
};
const Note: React.FC = () => {
  const V = useV();
  return <div style={{ fontSize: V ? 36 : 31, lineHeight: 1.4 }}>Os que ficarem em dúvida aparecem numa lista para <b style={{ color: C.accent }}>você revisar</b> antes de calcular.</div>;
};

// ------------------------------------------------------------------ 3. calcular
// Pontos fictícios em 5 grupos, num quadro de 1190×520; no vertical o mesmo desenho é esticado na altura.
const BASE_W = 1190, BASE_H = 520, DEPOT = [595, 270];
const CENTERS = [[245, 150], [930, 135], [980, 385], [550, 425], [195, 385]];
const POINTS = CENTERS.flatMap(([cx, cy], k) =>
  Array.from({ length: 12 }, (_, i) => ({ k, x: cx + (random(`x${k}-${i}`) - 0.5) * 290, y: cy + (random(`y${k}-${i}`) - 0.5) * 180 })),
);
// ordem de visita: volta ao redor do centro do grupo, saindo do ponto mais próximo da partida
const ORDERS = CENTERS.map(([cx, cy], k) => {
  const pts = POINTS.filter((p) => p.k === k).sort((a, b) => Math.atan2(a.y - cy, a.x - cx) - Math.atan2(b.y - cy, b.x - cx));
  const near = pts.reduce((best, p, i) => (Math.hypot(p.x - DEPOT[0], p.y - DEPOT[1]) < Math.hypot(pts[best].x - DEPOT[0], pts[best].y - DEPOT[1]) ? i : best), 0);
  return [...pts.slice(near), ...pts.slice(0, near)];
});
const Calculate: React.FC = () => {
  const f = useCurrentFrame();
  const V = useV();
  const W = V ? 940 : BASE_W, H = V ? 720 : BASE_H;
  const X = (x: number) => (x * W) / BASE_W, Y = (y: number) => (y * H) / BASE_H;
  const r = V ? 12 : 9;
  return (
    <Stage n={3} sub="Um clique divide as entregas e define a ordem de cada rota.">
      <Voz name="passo3" at={8} />
      <Sfx at={50} name="pop" /><Sfx at={86} name="whoosh" volume={0.3} />
      <div style={{ borderRadius: 20, border: `2px solid ${C.line}`, background: "#141b24", overflow: "hidden", height: H }}>
        <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`}>
          {ORDERS.map((pts, k) => {
            const d = `M${X(DEPOT[0])} ${Y(DEPOT[1])} ` + pts.map((p) => `L${X(p.x).toFixed(1)} ${Y(p.y).toFixed(1)}`).join(" ") + ` L${X(DEPOT[0])} ${Y(DEPOT[1])}`;
            const p = ease(f, 90 + k * 6, 150 + k * 6);
            return <path key={k} d={d} pathLength={1} fill="none" stroke={ROUTES[k]} strokeWidth={V ? 5 : 4} strokeLinejoin="round" strokeLinecap="round" strokeDasharray={1} strokeDashoffset={1 - p} opacity={0.9} />;
          })}
          {POINTS.map((p, i) => {
            const show = ease(f, 8 + (i % 20), 20 + (i % 20));
            const tint = ease(f, 50 + p.k * 6, 64 + p.k * 6);
            return <circle key={i} cx={X(p.x)} cy={Y(p.y)} r={r * show} fill={tint > 0.5 ? ROUTES[p.k] : "#7d8aa0"} stroke="#141b24" strokeWidth={2} />;
          })}
          <rect x={X(DEPOT[0]) - 17} y={Y(DEPOT[1]) - 17} width={34} height={34} rx={7} fill={C.ink} stroke="#141b24" strokeWidth={3} />
          <text x={X(DEPOT[0]) + 28} y={Y(DEPOT[1]) + 9} fill={C.ink} fontSize={V ? 28 : 23} fontWeight={700} fontFamily={FONT}>ponto de partida</text>
        </svg>
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: 16, marginTop: 30, flexWrap: "wrap", fontSize: V ? 34 : 30 }}>
        <Rise at={46} dy={14} style={V ? { width: "100%" } : {}}><span style={{ color: C.muted }}>Você escolhe a prioridade:</span></Rise>
        <Rise at={56} dy={14}><Chip color={C.accent} style={V ? { fontSize: 32 } : {}}>Carga parecida</Chip></Rise>
        <Rise at={66} dy={14}><Chip color={C.ok} style={V ? { fontSize: 32 } : {}}>Menos km no total</Chip></Rise>
      </div>
    </Stage>
  );
};

// ------------------------------------------------------------------ 4. enviar
const DRIVERS = ["Bruno", "Carla", "Diego", "Eduarda", "Felipe"];
const SEND_AT = (k: number) => 40 + k * 30; // quadro em que o k-ésimo envio é marcado
const Send: React.FC = () => {
  const f = useCurrentFrame();
  const V = useV();
  const count = Math.min(DRIVERS.length - 1, DRIVERS.filter((_, k) => f >= SEND_AT(k)).length);
  const total = 14;
  return (
    <Stage n={4} sub="Cada entregador recebe a própria rota, em ordem, com os links do mapa.">
      <Voz name="passo4" at={8} />
      {DRIVERS.slice(0, -1).map((_, k) => <Sfx key={k} at={SEND_AT(k)} name="click" volume={0.5} />)}
      <div style={{ display: "flex", flexDirection: V ? "column" : "row", gap: V ? 28 : 36 }}>
        <Rise at={8} style={{ flex: 1 }}>
          <Card>
            <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between" }}>
              <span style={{ fontSize: V ? 38 : 34, fontWeight: 800 }}>Fila de envio</span>
              <span style={{ fontSize: V ? 36 : 32, fontWeight: 700, color: C.accent }}>{count} de {total}</span>
            </div>
            <div style={{ height: 12, borderRadius: 6, background: C.panel2, marginTop: 14, overflow: "hidden" }}>
              <div style={{ height: 12, width: `${(count / total) * 100}%`, background: C.accent, borderRadius: 6 }} />
            </div>
            <div style={{ marginTop: 20, display: "grid", gap: 10 }}>
              {DRIVERS.map((d, i) => {
                const ok = i < count;
                return (
                  <div key={d} style={{ display: "flex", alignItems: "center", gap: 16, padding: "13px 16px", borderRadius: 12, background: i === count ? C.accentSoft : C.panel2 }}>
                    <span style={{ width: 42, height: 42, borderRadius: 21, background: ROUTES[i % ROUTES.length], color: "#0d1117", display: "grid", placeItems: "center", fontWeight: 800, fontSize: 23, flex: "none" }}>{i + 1}</span>
                    <span style={{ fontSize: V ? 33 : 30, fontWeight: 600, flex: 1 }}>{d}</span>
                    <span style={{ fontSize: V ? 28 : 24, fontWeight: 700, color: ok ? C.ok : C.muted }}>{ok ? "✓ enviada" : i === count ? "próxima" : ""}</span>
                  </div>
                );
              })}
            </div>
          </Card>
        </Rise>
        <Rise at={30} style={V ? {} : { width: 490, flex: "none" }}>
          <div style={{ background: "#0f2a22", border: "2px solid #1f4d3e", borderRadius: "22px 22px 22px 6px", padding: "26px 30px", fontSize: V ? 31 : 28, lineHeight: 1.5 }}>
            <div style={{ fontWeight: 800, color: C.ok, fontSize: V ? 28 : 25, marginBottom: 8 }}>WhatsApp · {DRIVERS[count]}</div>
            <div style={{ fontWeight: 700 }}>Rota {count + 1} · 64 paradas</div>
            <div style={{ color: C.muted }}>1. Rua Padre Chagas, 80<br />2. Rua Dinarte Ribeiro, 150{!V && <><br />3. Av. Goethe, 21</>}<br />…</div>
            <div style={{ color: C.accent, marginTop: 10, fontWeight: 600 }}>Abrir no mapa ›</div>
          </div>
        </Rise>
      </div>
      <Rise at={140} style={{ marginTop: V ? 30 : 34 }}>
        <div style={{ fontSize: V ? 36 : 33 }}>Um botão por vez, e o app marca <b style={{ color: C.ok }}>quem já recebeu</b>.</div>
      </Rise>
    </Stage>
  );
};

export const Flow: React.FC<{ dur: number }> = ({ dur }) => {
  const f = useCurrentFrame();
  const V = useV();
  const o = Math.min(ease(f, 0, 12), 1 - ease(f, dur - 12, dur));
  const parts = [Load, Addresses, Calculate, Send];
  return (
    <AbsoluteFill style={{ opacity: o, fontFamily: FONT, color: C.ink }}>
      <div style={{ position: "absolute", left: V ? PAD.v.x : 110, top: V ? PAD.v.top : 175 }}><Eyebrow>Como se usa</Eyebrow></div>
      <Rail />
      {parts.map((P, i) => (
        <React.Fragment key={i}>
          {i > 0 && <Sfx at={i * STEP - 6} name="whoosh" volume={0.25} />}
          <Sequence from={i * STEP} durationInFrames={STEP}><P /></Sequence>
        </React.Fragment>
      ))}
    </AbsoluteFill>
  );
};
