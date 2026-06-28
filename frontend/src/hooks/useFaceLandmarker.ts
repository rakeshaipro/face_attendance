import { useEffect, useRef, useState } from "react";
import { FaceLandmarker, FilesetResolver } from "@mediapipe/tasks-vision";

let landmarkerInstance: FaceLandmarker | null = null;
let landmarkerLoading: Promise<FaceLandmarker> | null = null;

async function getFaceLandmarker(): Promise<FaceLandmarker> {
  if (landmarkerInstance) return landmarkerInstance;
  if (landmarkerLoading) return landmarkerLoading;

  landmarkerLoading = (async () => {
    const filesetResolver = await FilesetResolver.forVisionTasks(
      "https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.8/wasm"
    );
    const landmarker = await FaceLandmarker.createFromOptions(filesetResolver, {
      baseOptions: {
        modelAssetPath: "https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task",
        delegate: "GPU",
      },
      outputFaceBlendshapes: false,
      outputFacialTransformationMatrixes: true,
      runningMode: "VIDEO",
      numFaces: 1,
    });
    landmarkerInstance = landmarker;
    return landmarker;
  })();

  return landmarkerLoading;
}

export interface DetectionResult {
  faceDetected: boolean;
  yaw: number | null;
  pitch: number | null;
  roll: number | null;
  bbox: [number, number, number, number] | null;
  faceSizeRatio: number;
}

export function useFaceLandmarker() {
  const [ready, setReady] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const landmarkerRef = useRef<FaceLandmarker | null>(null);

  useEffect(() => {
    let active = true;
    getFaceLandmarker()
      .then((landmarker) => {
        if (active) {
          landmarkerRef.current = landmarker;
          setReady(true);
        }
      })
      .catch((err) => {
        if (active) {
          setError(err instanceof Error ? err.message : String(err));
        }
      });
    return () => {
      active = false;
    };
  }, []);

  const detect = (video: HTMLVideoElement): DetectionResult => {
    if (!landmarkerRef.current || video.readyState < 2) {
      return { faceDetected: false, yaw: null, pitch: null, roll: null, bbox: null, faceSizeRatio: 0 };
    }

    const timestamp = performance.now();
    const result = landmarkerRef.current.detectForVideo(video, timestamp);

    if (!result.faceLandmarks || result.faceLandmarks.length === 0) {
      return { faceDetected: false, yaw: null, pitch: null, roll: null, bbox: null, faceSizeRatio: 0 };
    }

    const landmarks = result.faceLandmarks[0];

    // Compute bounding box in normalized coordinates first
    let xMin = 1.0;
    let xMax = 0.0;
    let yMin = 1.0;
    let yMax = 0.0;

    for (const lm of landmarks) {
      if (lm.x < xMin) xMin = lm.x;
      if (lm.x > xMax) xMax = lm.x;
      if (lm.y < yMin) yMin = lm.y;
      if (lm.y > yMax) yMax = lm.y;
    }

    const width = video.videoWidth;
    const height = video.videoHeight;

    const x1 = Math.floor(xMin * width);
    const y1 = Math.floor(yMin * height);
    const x2 = Math.ceil(xMax * width);
    const y2 = Math.ceil(yMax * height);

    const bbox: [number, number, number, number] = [x1, y1, x2, y2];
    const faceSizeRatio = (x2 - x1) / width;

    // Get rotation Euler angles (yaw, pitch, roll) from facialTransformationMatrixes
    let yaw: number | null = null;
    let pitch: number | null = null;
    let roll: number | null = null;

    if (result.facialTransformationMatrixes && result.facialTransformationMatrixes.length > 0) {
      const matrix = result.facialTransformationMatrixes[0].data; // Float32Array of 16 items
      // Column-major layout:
      // m[0] = r00, m[4] = r01, m[8] = r02
      // m[1] = r10, m[5] = r11, m[9] = r12
      // m[2] = r20, m[6] = r21, m[10] = r22

      const r00 = matrix[0];
      const r10 = matrix[1];
      const r20 = matrix[2];
      const r01 = matrix[4];
      const r11 = matrix[5];
      const r21 = matrix[6];
      const r02 = matrix[8];
      const r12 = matrix[9];
      const r22 = matrix[10];

      // Standard decomposition to Tait-Bryan angles:
      // yaw: rotation around Y-axis (left-right)
      // pitch: rotation around X-axis (up-down)
      // roll: rotation around Z-axis (tilt)
      
      const calculatedPitch = Math.asin(-r12) * (180 / Math.PI);
      const calculatedYaw = Math.atan2(r02, r22) * (180 / Math.PI);
      const calculatedRoll = Math.atan2(r10, r11) * (180 / Math.PI);

      // Calibrate signs to match InsightFace angles:
      // Turn left => negative yaw
      // Turn right => positive yaw
      // Tilt up => positive pitch
      // Tilt down => negative pitch
      yaw = -calculatedYaw;
      pitch = -calculatedPitch;
      roll = calculatedRoll;
    }

    return {
      faceDetected: true,
      yaw,
      pitch,
      roll,
      bbox,
      faceSizeRatio,
    };
  };

  return { ready, error, detect };
}
