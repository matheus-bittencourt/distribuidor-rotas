import React from "react";
import { AbsoluteFill, Audio, Easing, Sequence, interpolate, staticFile, useCurrentFrame, useVideoConfig } from "remotion";
import audio from "./audio.json";

// Mesmos tons do tema escuro do app (app/static/style.css).
export const C = {
  bg: "#0d1117", panel: "#182029", panel2: "#1f2935", ink: "#e8edf5", muted: "#9ba7ba", line: "#2a3441",
  accent: "#6aa5ff", accentSoft: "#1c2c47", ok: "#62d49b", okBg: "#123324", warn: "#f2b24a", bad: "#ff9a90", badBg: "#351a18",
};
export const ROUTES = ["#6aa5ff", "#62d49b", "#f2b24a", "#ff8fb1", "#b79cff"];
export const FONT = '"Segoe UI", system-ui, sans-serif';
export const MONO = '"Cascadia Code", Consolas, monospace';

/** Verdadeiro na versão vertical (reels, 1080×1920). */
export const useV = () => {
  const { width, height } = useVideoConfig();
  return height > width;
};
/** Margens da área útil. No vertical, sobra espaço para a interface do aplicativo de vídeo. */
export const PAD = { h: { x: 110, top: 90, bottom: 90 }, v: { x: 70, top: 230, bottom: 340 } };

export const ease = (f: number, from: number, to: number, a = 0, b = 1) =>
  interpolate(f, [from, to], [a, b], { extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: Easing.out(Easing.cubic) });

/** Entrada padrão: sobe alguns pixels enquanto aparece. */
export const Rise: React.FC<{ at: number; dy?: number; style?: React.CSSProperties; children: React.ReactNode }> = ({ at, dy = 28, style, children }) => {
  const p = ease(useCurrentFrame(), at, at + 18);
  return <div style={{ opacity: p, transform: `translateY(${(1 - p) * dy}px)`, ...style }}>{children}</div>;
};

/** Cena inteira: esmaece na entrada e na saída. `center` centraliza o conteúdo na vertical. */
export const Scene: React.FC<{ dur: number; center?: boolean; children: React.ReactNode }> = ({ dur, center, children }) => {
  const f = useCurrentFrame();
  const p = useV() ? PAD.v : PAD.h;
  const o = Math.min(ease(f, 0, 12), 1 - ease(f, dur - 12, dur));
  return (
    <AbsoluteFill style={{ opacity: o, padding: `${p.top}px ${p.x}px ${p.bottom}px`, fontFamily: FONT, color: C.ink, justifyContent: center ? "center" : undefined }}>
      {children}
    </AbsoluteFill>
  );
};

export const Background: React.FC = () => {
  const f = useCurrentFrame();
  const x = 50 + Math.sin(f / 240) * 18;
  return (
    <AbsoluteFill style={{ background: C.bg }}>
      <AbsoluteFill style={{ background: `radial-gradient(900px 620px at ${x}% 18%, rgba(106,165,255,.16), transparent 70%)` }} />
      <AbsoluteFill style={{ backgroundImage: `radial-gradient(${C.line} 1.5px, transparent 1.5px)`, backgroundSize: "48px 48px", opacity: 0.45 }} />
    </AbsoluteFill>
  );
};

export const Eyebrow: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <div style={{ color: C.accent, fontSize: 28, fontWeight: 700, letterSpacing: 3, textTransform: "uppercase" }}>{children}</div>
);

export const Chip: React.FC<{ color?: string; style?: React.CSSProperties; children: React.ReactNode }> = ({ color = C.muted, style, children }) => (
  <span style={{ display: "inline-block", padding: "8px 22px", borderRadius: 99, border: `2px solid ${color}55`, background: `${color}18`, color, fontSize: 28, fontWeight: 600, whiteSpace: "nowrap", ...style }}>
    {children}
  </span>
);

export const Card: React.FC<{ style?: React.CSSProperties; children: React.ReactNode }> = ({ style, children }) => (
  <div style={{ background: C.panel, border: `2px solid ${C.line}`, borderRadius: 20, padding: 32, boxShadow: "0 24px 60px rgba(0,0,0,.35)", ...style }}>{children}</div>
);

export const Glyph: React.FC<{ color: string; size?: number; children: React.ReactNode }> = ({ color, size = 96, children }) => (
  <div style={{ width: size, height: size, borderRadius: size / 4, background: `${color}1f`, border: `2px solid ${color}55`, display: "grid", placeItems: "center", flex: "none" }}>
    <svg width={size * 0.54} height={size * 0.54} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={1.9} strokeLinecap="round" strokeLinejoin="round">{children}</svg>
  </div>
);

// ---- áudio em public/audio. src/audio.json escolhe a fonte: "wav" (scripts locais) ou "mp3" (ElevenLabs)
/** Efeito sonoro no quadro `at` da cena. */
export const Sfx: React.FC<{ at: number; name: "whoosh" | "pop" | "tick" | "ding" | "click"; volume?: number }> = ({ at, name, volume = 0.45 }) => (
  <Sequence from={Math.max(0, at)} layout="none"><Audio src={staticFile(`audio/fx-${name}.${audio.fx}`)} volume={volume} /></Sequence>
);
/** Trecho da locução, começando no quadro `at` da cena. */
export const Voz: React.FC<{ name: string; at?: number }> = ({ name, at = 10 }) => (
  <Sequence from={at} layout="none"><Audio src={staticFile(`audio/voz-${name}.${audio.voz}`)} volume={1} /></Sequence>
);
