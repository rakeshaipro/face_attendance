/**
 * FacePoseGuide — animated SVG overlay that guides the user into the
 * correct head pose during face enrollment.
 *
 * Shows:
 *  - A grey "target" face silhouette at the desired yaw / pitch position
 *  - A coloured live ellipse that tracks the user's current head orientation
 *  - Directional arrow hints indicating which way to turn / tilt
 *  - A pulsing green ring when the pose is accepted (inRange = true)
 *  - A faint dashed reticle to anchor the expected head position
 *
 * When `mirrored` is true (video display is horizontally flipped) the
 * left/right arrows and the horizontal ellipse positions are also flipped so
 * they match what the user sees on screen.
 */

import { useMemo } from "react";

// ─── Constants ────────────────────────────────────────────────────────────────

const W = 180;
const H = 180;
const CX = W / 2;
const CY = H / 2 - 4;

const MAX_YAW_PX   = 38;
const MAX_PITCH_PX = 28;

const FACE_RX = 34;
const FACE_RY = 44;

// ─── Types ────────────────────────────────────────────────────────────────────

export interface FacePoseGuideProps {
  liveYaw:      number | null;
  livePitch:    number | null;
  inRange:      boolean;
  targetYaw:    [number, number] | null;
  targetPitch:  [number, number] | null;
  instruction:  string;
  /**
   * Set to true when the video element is displayed with a CSS
   * horizontal mirror (scaleX(-1)).  When true, the left/right arrow
   * directions and the horizontal ellipse positions are flipped so they
   * correspond to what the user sees on screen.
   */
  mirrored?:    boolean;
}

// ─── Helpers ─────────────────────────────────────────────────────────────────

function angleToOffset(angle: number, maxPx: number, clampDeg = 90): number {
  const clamped = Math.max(-clampDeg, Math.min(clampDeg, angle));
  return (clamped / clampDeg) * maxPx;
}

function midpoint(range: [number, number]): number {
  return (range[0] + range[1]) / 2;
}

// ─── Sub-components ───────────────────────────────────────────────────────────

function FaceShape({
  cx, cy, rx, ry, fill, stroke, strokeWidth, opacity, style,
}: {
  cx: number; cy: number; rx: number; ry: number;
  fill: string; stroke: string; strokeWidth: number;
  opacity?: number; style?: React.CSSProperties;
}) {
  return (
    <ellipse
      cx={cx} cy={cy} rx={rx} ry={ry}
      fill={fill} stroke={stroke} strokeWidth={strokeWidth}
      opacity={opacity ?? 1} style={style}
    />
  );
}

function Arrow({ direction, visible }: { direction: "left" | "right" | "up" | "down"; visible: boolean }) {
  if (!visible) return null;

  const size = 18;
  const gap  = FACE_RX + 14;

  const positions: Record<string, { x: number; y: number; rotate: number }> = {
    left:  { x: CX - gap - size / 2, y: CY, rotate: 180 },
    right: { x: CX + gap + size / 2, y: CY, rotate: 0   },
    up:    { x: CX, y: CY - FACE_RY - 14, rotate: -90   },
    down:  { x: CX, y: CY + FACE_RY + 14, rotate:  90   },
  };

  const { x, y, rotate } = positions[direction];
  const hw = size / 2;
  const hh = size / 2;
  const points = `${-hw},${-hh} ${hw},0 ${-hw},${hh}`;

  return (
    <polygon
      points={points}
      fill="rgba(255,255,255,0.9)"
      stroke="rgba(255,255,255,0.3)"
      strokeWidth={1}
      transform={`translate(${x},${y}) rotate(${rotate})`}
      style={{ animation: "fa-arrow-pulse 0.8s ease-in-out infinite" }}
    />
  );
}

// ─── Main Component ───────────────────────────────────────────────────────────

export function FacePoseGuide({
  liveYaw, livePitch, inRange,
  targetYaw, targetPitch,
  instruction,
  mirrored = false,
}: FacePoseGuideProps) {
  const faceDetected = liveYaw !== null && livePitch !== null;

  // Horizontal sign: flip when mirrored so positions match on-screen direction
  const sign = mirrored ? -1 : 1;

  const targetMidYaw   = targetYaw   ? midpoint(targetYaw)   : 0;
  const targetMidPitch = targetPitch ? midpoint(targetPitch) : 0;
  const targetDx = sign * angleToOffset(targetMidYaw,   MAX_YAW_PX);
  const targetDy =        angleToOffset(targetMidPitch, MAX_PITCH_PX);

  const liveDx = faceDetected ? sign * angleToOffset(liveYaw!,  MAX_YAW_PX)   : 0;
  const liveDy = faceDetected ?        angleToOffset(livePitch!, MAX_PITCH_PX) : 0;

  // Arrow hints — left/right swapped when mirrored
  const arrows = useMemo(() => {
    if (!faceDetected || inRange) return { left: false, right: false, up: false, down: false };

    const rawRight = targetYaw   != null && liveYaw!   < targetYaw[0]   - 3;
    const rawLeft  = targetYaw   != null && liveYaw!   > targetYaw[1]   + 3;

    return {
      right: mirrored ? rawLeft  : rawRight,
      left:  mirrored ? rawRight : rawLeft,
      down:  targetPitch != null && livePitch! < targetPitch[0] - 3,
      up:    targetPitch != null && livePitch! > targetPitch[1] + 3,
    };
  }, [faceDetected, inRange, liveYaw, livePitch, targetYaw, targetPitch, mirrored]);

  let liveStroke = "#6366f1";
  if (!faceDetected) liveStroke = "rgba(255,255,255,0.25)";
  else if (inRange)  liveStroke = "#22c55e";

  const liveRxSquash = faceDetected
    ? FACE_RX * Math.max(0.45, 1 - Math.abs(liveYaw!) / 120)
    : FACE_RX;

  return (
    <div
      style={{
        position: "absolute",
        top: 12,
        right: 12,
        width: W,
        height: H + 22,
        userSelect: "none",
        pointerEvents: "none",
      }}
    >
      <style>{`
        @keyframes fa-ring-pulse {
          0%   { r: ${FACE_RX + 6};  opacity: 0.9; stroke-width: 3; }
          70%  { r: ${FACE_RX + 18}; opacity: 0;   stroke-width: 1; }
          100% { r: ${FACE_RX + 6};  opacity: 0;   stroke-width: 1; }
        }
        @keyframes fa-arrow-pulse {
          0%,100% { opacity: 1;   transform: scale(1);    }
          50%     { opacity: 0.4; transform: scale(0.85); }
        }
        @keyframes fa-no-face {
          0%,100% { opacity: 0.35; }
          50%     { opacity: 0.15; }
        }
      `}</style>

      <svg
        viewBox={`0 0 ${W} ${H}`}
        width={W}
        height={H}
        xmlns="http://www.w3.org/2000/svg"
        style={{ display: "block" }}
      >
        {/* Background pill */}
        <rect
          x={2} y={2} width={W - 4} height={H - 4}
          rx={14} ry={14}
          fill="rgba(0,0,0,0.42)"
          stroke="rgba(255,255,255,0.08)"
          strokeWidth={1}
        />

        {/* Cross-hair reticle */}
        <line x1={CX} y1={CY - FACE_RY - 2} x2={CX} y2={CY + FACE_RY + 2}
          stroke="rgba(255,255,255,0.12)" strokeWidth={1} strokeDasharray="3 4" />
        <line x1={CX - FACE_RX - 2} y1={CY} x2={CX + FACE_RX + 2} y2={CY}
          stroke="rgba(255,255,255,0.12)" strokeWidth={1} strokeDasharray="3 4" />

        {/* Target silhouette (dashed grey) */}
        <FaceShape
          cx={CX + targetDx} cy={CY + targetDy}
          rx={FACE_RX * Math.max(0.45, 1 - Math.abs(targetMidYaw) / 120)}
          ry={FACE_RY}
          fill="rgba(255,255,255,0.04)"
          stroke="rgba(255,255,255,0.30)"
          strokeWidth={1.5}
          opacity={0.7}
          style={{ strokeDasharray: "4 3" }}
        />

        {/* Corner dots at target boundary */}
        {[[-1, -1], [1, -1], [1, 1], [-1, 1]].map(([sx, sy], i) => (
          <circle
            key={i}
            cx={CX + targetDx + sx * (FACE_RX + 5)}
            cy={CY + targetDy + sy * (FACE_RY + 5)}
            r={2}
            fill="rgba(255,255,255,0.25)"
          />
        ))}

        {/* Pulsing ring when inRange */}
        {inRange && faceDetected && (
          <circle
            cx={CX + liveDx} cy={CY + liveDy}
            r={FACE_RX + 6}
            fill="none"
            stroke="#22c55e"
            strokeWidth={3}
            style={{ animation: "fa-ring-pulse 0.9s ease-out infinite" }}
          />
        )}

        {/* Live face ellipse */}
        <FaceShape
          cx={CX + liveDx} cy={CY + liveDy}
          rx={liveRxSquash} ry={FACE_RY}
          fill={
            !faceDetected ? "rgba(255,255,255,0.04)"
            : inRange      ? "rgba(34,197,94,0.12)"
            :                "rgba(99,102,241,0.12)"
          }
          stroke={liveStroke}
          strokeWidth={faceDetected ? 2.5 : 1.5}
          opacity={faceDetected ? 1 : 0.4}
          style={
            !faceDetected
              ? { animation: "fa-no-face 1.4s ease-in-out infinite" }
              : { transition: "cx 150ms ease, cy 150ms ease, rx 120ms ease" }
          }
        />

        {/* Eyes on live face */}
        {faceDetected && (
          <>
            <ellipse
              cx={CX + liveDx - liveRxSquash * 0.32} cy={CY + liveDy - FACE_RY * 0.18}
              rx={liveRxSquash * 0.14} ry={4}
              fill={inRange ? "rgba(34,197,94,0.6)" : "rgba(99,102,241,0.6)"}
            />
            <ellipse
              cx={CX + liveDx + liveRxSquash * 0.32} cy={CY + liveDy - FACE_RY * 0.18}
              rx={liveRxSquash * 0.14} ry={4}
              fill={inRange ? "rgba(34,197,94,0.6)" : "rgba(99,102,241,0.6)"}
            />
          </>
        )}

        {/* Directional arrows (mirror-aware) */}
        <Arrow direction="left"  visible={arrows.left}  />
        <Arrow direction="right" visible={arrows.right} />
        <Arrow direction="up"    visible={arrows.up}    />
        <Arrow direction="down"  visible={arrows.down}  />

        {/* Status badge */}
        {faceDetected ? (
          inRange ? (
            <text x={CX} y={H - 10} textAnchor="middle" fontSize={10} fontWeight="600"
              fill="#22c55e" style={{ fontFamily: "system-ui, sans-serif" }}>
              ✓ Pose locked
            </text>
          ) : (
            <text x={CX} y={H - 10} textAnchor="middle" fontSize={10}
              fill="rgba(255,255,255,0.65)" style={{ fontFamily: "system-ui, sans-serif" }}>
              Align to target
            </text>
          )
        ) : (
          <text x={CX} y={H - 10} textAnchor="middle" fontSize={10}
            fill="rgba(255,255,255,0.4)"
            style={{ fontFamily: "system-ui, sans-serif", animation: "fa-no-face 1.4s ease-in-out infinite" }}>
            No face detected
          </text>
        )}
      </svg>

      {/* Instruction label */}
      <div
        style={{
          textAlign: "center",
          fontSize: 11,
          fontWeight: 500,
          color: "rgba(255,255,255,0.75)",
          marginTop: 2,
          fontFamily: "system-ui, sans-serif",
          lineHeight: 1.3,
          padding: "0 4px",
        }}
      >
        {instruction}
      </div>
    </div>
  );
}
