export interface PoseRange {
  step: number;
  yaw: [number, number] | null;
  pitch: [number, number] | null;
}

export const POSE_STEPS_RANGES: PoseRange[] = [
  { step: 1, yaw: [-15, 15],  pitch: [-15, 15] },
  { step: 2, yaw: [-45, -30], pitch: null },
  { step: 3, yaw: [30, 45],   pitch: null },
  { step: 4, yaw: null,       pitch: [20, 35] },
  { step: 5, yaw: null,       pitch: [-35, -20] },
  { step: 6, yaw: [-35, -20], pitch: [15, 25] },
  { step: 7, yaw: [20, 35],   pitch: [-25, -15] },
];

export function poseInRange(step: number, yaw: number | null, pitch: number | null): boolean {
  const spec = POSE_STEPS_RANGES.find((s) => s.step === step);
  if (!spec) return false;

  if (spec.yaw !== null) {
    if (yaw === null || yaw < spec.yaw[0] || yaw > spec.yaw[1]) {
      return false;
    }
  }

  if (spec.pitch !== null) {
    if (pitch === null || pitch < spec.pitch[0] || pitch > spec.pitch[1]) {
      return false;
    }
  }

  return true;
}
