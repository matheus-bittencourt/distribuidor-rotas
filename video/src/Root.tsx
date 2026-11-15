import React from "react";
import { AbsoluteFill, Audio, Composition, Sequence, staticFile, useCurrentFrame, useVideoConfig } from "remotion";
import { FLOW, Flow } from "./Flow";
import { Hook } from "./Hook";
import { Outro } from "./Outro";
import { Privacy } from "./Privacy";
import { Solution } from "./Solution";
import { Background, C, Sfx } from "./ui";

// Cenas em ordem, com a duração em quadros (30 fps). Ver ROTEIRO.md.
const SCENES: [React.FC<{ dur: number }>, number][] = [[Hook, 180], [Solution, 300], [Flow, FLOW], [Privacy, 240], [Outro, 300]];
export const TOTAL = SCENES.reduce((s, [, d]) => s + d, 0); // 1860 = 62 s
const MUSIC_VOLUME = 0.16; // baixa, para ficar atrás da locução

const Progress: React.FC = () => {
  const f = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();
  return <div style={{ position: "absolute", left: 0, bottom: 0, height: 8, width: `${(f / (durationInFrames - 1)) * 100}%`, background: C.accent }} />;
};

/** O mesmo vídeo serve às duas composições: as cenas se ajustam à proporção da tela. */
const Video: React.FC = () => {
  let from = 0;
  return (
    <AbsoluteFill>
      <Background />
      <Audio src={staticFile("audio/musica.wav")} volume={MUSIC_VOLUME} />
      {SCENES.map(([S, dur], i) => {
        const at = from;
        from += dur;
        return (
          <React.Fragment key={i}>
            {i > 0 && <Sfx at={at - 8} name="whoosh" volume={0.3} />}
            <Sequence from={at} durationInFrames={dur}><S dur={dur} /></Sequence>
          </React.Fragment>
        );
      })}
      <Progress />
    </AbsoluteFill>
  );
};

export const Root: React.FC = () => (
  <>
    <Composition id="Video" component={Video} durationInFrames={TOTAL} fps={30} width={1920} height={1080} />
    <Composition id="Reels" component={Video} durationInFrames={TOTAL} fps={30} width={1080} height={1920} />
  </>
);
