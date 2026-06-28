import { useCallback, useEffect, useRef, useState } from "react";
import { useCapture, useEnrollmentProtocol, useEnrollmentStatus, useFinalizeEnrollment, useReEnroll, useRemoveFace, useVerify, useCapturesSummary } from "@/lib/queries";
import { useFaceLandmarker } from "@/hooks/useFaceLandmarker";
import { poseInRange } from "@/lib/poseCheck";
import type { PoseStep } from "@/lib/types";
import { Badge, Button, Card, CardContent, CardDescription, CardHeader, CardTitle, Spinner } from "@/components/ui";
import { ErrorBanner } from "@/components/shared";
import { FacePoseGuide } from "@/components/FacePoseGuide";
import { Camera, CheckCircle2, ChevronDown, ChevronUp, RotateCcw, Trash2 } from "lucide-react";
import { cn } from "@/lib/utils";

interface EnrollmentProps {
  employeeId: string;
  employeeName: string;
}

/**
 * Guided 7-pose enrollment flow (SRS §3.3).
 *
 * Uses the device webcam (getUserMedia), draws the video to a canvas each
 * frame, calls /face/pose-check, and when the pose is in range + quality
 * acceptable, captures on eye-blink via /face/capture. One capture per step.
 *
 * Two independent loops:
 *  - Draw loop  (~60 fps): draws video → canvas, runs blink detection
 *  - API loop   (≤5 fps):  reads canvas → pose-check → setLive, blink-captures
 */

// ─── Blink detection helper ───────────────────────────────────────────────────

/**
 * Sample the perceived luminance of the approximate eye-band region.
 * Works on the unmirrored canvas (backend frame). The eye band is at roughly
 * y = 18–36%, x = 22–78% of the frame.
 */
function sampleEyeLuminance(ctx: CanvasRenderingContext2D, w: number, h: number): number {
  const x  = Math.floor(w * 0.22);
  const y  = Math.floor(h * 0.18);
  const sw = Math.floor(w * 0.56);
  const sh = Math.floor(h * 0.18);
  try {
    const px = ctx.getImageData(x, y, sw, sh).data;
    let lum = 0;
    const n = px.length / 4;
    if (n === 0) return 128;
    for (let i = 0; i < px.length; i += 4) {
      lum += px[i] * 0.299 + px[i + 1] * 0.587 + px[i + 2] * 0.114;
    }
    return lum / n;
  } catch {
    return 128;
  }
}

// ─── Component ────────────────────────────────────────────────────────────────

function canvasToJpegBlob(canvas: HTMLCanvasElement, quality = 0.85, maxWidth?: number): Promise<Blob | null> {
  if (!maxWidth || canvas.width <= maxWidth) {
    return new Promise((res) => canvas.toBlob((b) => res(b), "image/jpeg", quality));
  }

  const scale = maxWidth / canvas.width;
  const resized = document.createElement("canvas");
  resized.width = maxWidth;
  resized.height = Math.round(canvas.height * scale);
  resized.getContext("2d")?.drawImage(canvas, 0, 0, resized.width, resized.height);
  return new Promise((res) => resized.toBlob((b) => res(b), "image/jpeg", quality));
}

const POSE_CHECK_INTERVAL_MS = 100;
const RECENT_VALID_POSE_MS = 4000;

export function Enrollment({ employeeId }: EnrollmentProps) {
  const videoRef   = useRef<HTMLVideoElement>(null);
  const canvasRef  = useRef<HTMLCanvasElement>(null);
  const streamRef  = useRef<MediaStream | null>(null);
  const drawRafRef = useRef<number | null>(null);   // draw-loop RAF id
  const captureLockRef = useRef<boolean>(false);    // prevents overlapping captures

  // ── Blink-detection refs (mutated inside rAF; not React state) ──
  const brightnessHistRef  = useRef<number[]>([]);
  const blinkStateRef      = useRef<"open" | "closing">("open");
  const blinkStartTimeRef  = useRef<number | null>(null);
  const blinkFiredRef      = useRef<boolean>(false);
  const latestValidPoseRef = useRef<{ step: number; at: number } | null>(null);

  // ── Captured-steps ref (always current, readable inside effects) ──
  const capturedRef = useRef<Set<number>>(new Set());

  const { data: protocol } = useEnrollmentProtocol();
  const status    = useEnrollmentStatus(employeeId);
  const capturesSummary = useCapturesSummary(employeeId);
  const { ready: landmarkerReady, error: landmarkerError, detect } = useFaceLandmarker();
  const capture   = useCapture(employeeId);
  const finalize  = useFinalizeEnrollment(employeeId);
  const reEnroll  = useReEnroll(employeeId);
  const removeFace = useRemoveFace(employeeId);
  const verify    = useVerify(employeeId);

  const capturesMap = new Map<number, string>();
  if (capturesSummary.data) {
    for (const c of capturesSummary.data) {
      capturesMap.set(c.step, c.image_path);
    }
  }

  const [currentStep, setCurrentStep] = useState(1);
  const [live, setLive]               = useState<{ yaw: number | null; pitch: number | null; inRange: boolean; quality: number | null } | null>(null);
  const [camError, setCamError]       = useState<string | null>(null);
  const [finalResult, setFinalResult] = useState<{ overall: number; warning: string | null } | null>(null);
  const [verifyScore, setVerifyScore] = useState<number | null>(null);
  const [active, setActive]           = useState(false);
  const [showDetails, setShowDetails] = useState(false);

  const steps = protocol?.steps ?? [];
  const step: PoseStep | undefined = steps.find((s) => s.step === currentStep);

  // Keep capturedRef in sync with react-query data (runs every render, no effect needed)
  capturedRef.current = new Set(status.data?.steps_captured ?? []);
  const captured = capturedRef.current; // alias for JSX

  // --- start/stop camera ---
  const startCamera = useCallback(async () => {
    setCamError(null);
    // Reset blink state
    brightnessHistRef.current = [];
    blinkStateRef.current     = "open";
    blinkStartTimeRef.current = null;
    blinkFiredRef.current     = false;
    latestValidPoseRef.current = null;
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ video: { width: 640, height: 480 }, audio: false });
      streamRef.current = stream;
      if (videoRef.current) {
        videoRef.current.srcObject = stream;
        await videoRef.current.play();
      }
      setActive(true);
    } catch (e) {
      setCamError(e instanceof Error ? e.message : "Could not access webcam. (Requires HTTPS or localhost.)");
    }
  }, []);

  const stopCamera = useCallback(() => {
    setActive(false);
    setLive(null);
    if (drawRafRef.current) cancelAnimationFrame(drawRafRef.current);
    drawRafRef.current = null;
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
  }, []);

  useEffect(() => () => stopCamera(), [stopCamera]);

  const hasRecentValidPose = useCallback((now = performance.now()) => {
    const latest = latestValidPoseRef.current;
    return !!latest && latest.step === currentStep && now - latest.at <= RECENT_VALID_POSE_MS;
  }, [currentStep]);

  const captureCurrentFrame = useCallback(async () => {
    const canvas = canvasRef.current;
    if (!canvas || captureLockRef.current || capturedRef.current.has(currentStep)) return;
    const blob = await canvasToJpegBlob(canvas, 0.85);
    if (!blob) return;
    captureLockRef.current = true;
    capture.mutate(
      { step: currentStep, file: blob },
      { onSettled: () => { captureLockRef.current = false; } }
    );
  }, [capture, currentStep]);

  // ─── Loop 1: Draw video → canvas at ~60 fps + run blink detection & face landmark checking ──────────
  useEffect(() => {
    if (!active) return;
    const video  = videoRef.current;
    const canvas = canvasRef.current;
    if (!video || !canvas) return;

    const draw = () => {
      if (video.readyState >= 2 && video.videoWidth > 0) {
        // Resize canvas only when dimensions change (avoids flickering)
        if (canvas.width !== video.videoWidth || canvas.height !== video.videoHeight) {
          canvas.width  = video.videoWidth;
          canvas.height = video.videoHeight;
        }
        const ctx = canvas.getContext("2d");
        if (ctx) {
          ctx.drawImage(video, 0, 0);

          // ── Real-time face detection & pose check (client-side) ───────
          if (!capturedRef.current.has(currentStep)) {
            const result = detect(video);
            if (result.faceDetected) {
              const inRange = poseInRange(currentStep, result.yaw, result.pitch);
              setLive({
                yaw: result.yaw,
                pitch: result.pitch,
                inRange,
                quality: result.faceSizeRatio,
              });

              if (inRange) {
                const now = performance.now();
                latestValidPoseRef.current = { step: currentStep, at: now };

                // If a blink was recently fired (or we blink now), trigger capture
                if (blinkFiredRef.current && !captureLockRef.current) {
                  blinkFiredRef.current = false;
                  void captureCurrentFrame();
                }
              }
            } else {
              setLive(null);
            }
          } else {
            setLive({ yaw: null, pitch: null, inRange: true, quality: null });
          }

          // ── Blink detection (runs every rAF frame, ~60 fps) ──────────
          // Skip if this step is already captured or a capture is in flight
          if (!capturedRef.current.has(currentStep) && !captureLockRef.current) {
            const lum  = sampleEyeLuminance(ctx, canvas.width, canvas.height);
            const hist = brightnessHistRef.current;
            hist.push(lum);
            if (hist.length > 20) hist.shift();

            // Rolling baseline (exclude the last 3 samples to avoid blink contamination)
            const baseline =
              hist.length >= 8
                ? hist.slice(0, hist.length - 3).reduce((a, b) => a + b, 0) / (hist.length - 3)
                : lum;

            const now = performance.now();

            if (blinkStateRef.current === "open") {
              // Eye closes: brightness drops below 68% of baseline
              if (hist.length >= 8 && lum < baseline * 0.68) {
                blinkStateRef.current     = "closing";
                blinkStartTimeRef.current = now;
              }
            } else {
              const elapsed = now - (blinkStartTimeRef.current ?? now);
              if (lum >= baseline * 0.85) {
                // Eye opened again
                blinkStateRef.current = "open";
                // Valid blink: 60–500 ms
                if (elapsed >= 60 && elapsed <= 500) {
                  if (hasRecentValidPose(now)) {
                    void captureCurrentFrame();
                  } else {
                    blinkFiredRef.current = true;
                    setTimeout(() => { blinkFiredRef.current = false; }, RECENT_VALID_POSE_MS);
                  }
                }
                blinkStartTimeRef.current = null;
              } else if (elapsed > 650) {
                // Not a blink (eyes held closed) — reset
                blinkStateRef.current     = "open";
                blinkStartTimeRef.current = null;
              }
            }
          }
        }
      }
      drawRafRef.current = requestAnimationFrame(draw);
    };

    drawRafRef.current = requestAnimationFrame(draw);
    return () => {
      if (drawRafRef.current) cancelAnimationFrame(drawRafRef.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active, currentStep, detect]);

  // Auto-advance once a step is captured.
  useEffect(() => {
    if (captured.has(currentStep) && currentStep < 7) {
      const t = setTimeout(() => setCurrentStep((s) => Math.min(7, s + 1)), 600);
      return () => clearTimeout(t);
    }
  }, [captured, currentStep]);

  const onFinalize = async () => {
    try {
      const res = await finalize.mutateAsync();
      setFinalResult({ overall: res.overall_quality, warning: res.warning });
      stopCamera();
    } catch (e) {
      setFinalResult({ overall: 0, warning: e instanceof Error ? e.message : "Finalize failed." });
    }
  };

  const onVerify = async () => {
    const video  = videoRef.current;
    const canvas = canvasRef.current;
    if (!video || !canvas) return;
    canvas.width  = video.videoWidth;
    canvas.height = video.videoHeight;
    canvas.getContext("2d")?.drawImage(video, 0, 0);
    const blob = await new Promise<Blob | null>((res) => canvas.toBlob((b) => res(b), "image/jpeg", 0.85));
    if (!blob) return;
    try {
      const res = await verify.mutateAsync(blob);
      setVerifyScore(res.best_score);
    } catch {
      /* surfaced via mutation error */
    }
  };

  const onReEnroll = async () => {
    await reEnroll.mutateAsync();
    setFinalResult(null);
    setCurrentStep(1);
  };

  const onRemove = async () => {
    if (!confirm("Remove all face data for this employee?")) return;
    await removeFace.mutateAsync();
    setFinalResult(null);
    setCurrentStep(1);
  };

  // ── Derived UI flags ────────────────────────────────────────────────────────
  const faceDetected = live !== null && live.yaw !== null;
  const inRange      = live?.inRange ?? false;
  const blinkReady   = faceDetected && inRange && !captured.has(currentStep) && !captureLockRef.current;

  /** Manual one-shot capture — fires immediately from the current canvas frame. */
  const onManualCapture = async () => {
    const canvas = canvasRef.current;
    if (!canvas || captureLockRef.current || captured.has(currentStep)) return;
    const blob = await new Promise<Blob | null>((res) => canvas.toBlob((b) => res(b), "image/jpeg", 0.85));
    if (!blob) return;
    captureLockRef.current = true;
    capture.mutate(
      { step: currentStep, file: blob },
      { onSettled: () => { captureLockRef.current = false; } }
    );
  };

  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between space-y-0">
        <div>
          <CardTitle>Face enrollment</CardTitle>
          <CardDescription>Guided 7-pose protocol via webcam</CardDescription>
        </div>
        {status.data && (
          <Badge variant={status.data.is_enrolled ? "success" : "outline"}>
            {status.data.is_enrolled ? `Enrolled · ${(status.data.overall_quality ?? 0).toFixed(2)}` : "Not enrolled"}
          </Badge>
        )}
      </CardHeader>
      <CardContent className="space-y-4">
        {camError && <ErrorBanner message={camError} />}
        {landmarkerError && <ErrorBanner message={`Detector initialization failed: ${landmarkerError}`} />}

        {/* Step indicators */}
        <div className="flex items-center justify-center gap-2">
          {steps.map((s) => (
            <div key={s.step} className="group relative">
              <button
                onClick={() => setCurrentStep(s.step)}
                className={cn(
                  "flex h-10 w-10 items-center justify-center rounded-full border text-sm font-medium transition-all duration-200 overflow-hidden",
                  captured.has(s.step)
                    ? "border-emerald-500 hover:border-emerald-600 shadow-sm"
                    : currentStep === s.step
                      ? "border-primary bg-primary/10 text-primary ring-2 ring-primary/20"
                      : "border-border text-muted-foreground hover:border-muted-foreground/60",
                )}
                title={s.instruction}
              >
                {captured.has(s.step) && capturesMap.has(s.step) ? (
                  <img
                    src={`/media/enrollment/${capturesMap.get(s.step)}`}
                    alt={`Step ${s.step}`}
                    className="h-full w-full object-cover"
                  />
                ) : captured.has(s.step) ? (
                  <CheckCircle2 className="h-4 w-4 text-emerald-500" />
                ) : (
                  s.step
                )}
              </button>
              {captured.has(s.step) && capturesMap.has(s.step) && (
                <div className="pointer-events-none absolute bottom-full left-1/2 z-50 mb-2 w-28 -translate-x-1/2 scale-95 rounded-lg border bg-popover p-1 shadow-md opacity-0 group-hover:opacity-100 group-hover:scale-100 transition-all duration-200">
                  <img
                    src={`/media/enrollment/${capturesMap.get(s.step)}`}
                    alt={`Preview Step ${s.step}`}
                    className="aspect-square w-full rounded-md object-cover"
                  />
                  <div className="mt-1 text-[10px] text-center font-medium text-popover-foreground">
                    Step {s.step} captured
                  </div>
                </div>
              )}
            </div>
          ))}
        </div>

        {/* ── Video + overlays ── */}
        <div className="relative mx-auto max-w-2xl overflow-hidden rounded-lg bg-black">
          {/* Mirror effect: scaleX(-1) flips display only; canvas stays unmirrored for the API */}
          <video
            ref={videoRef}
            className="w-full"
            playsInline
            muted
            style={{ transform: "scaleX(-1)", display: "block" }}
          />
          <canvas ref={canvasRef} className="hidden" />

          {/* ── Detector Loading Overlay ── */}
          {active && !landmarkerReady && (
            <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 text-white/85 bg-black/75 z-20">
              <Spinner className="h-8 w-8 text-primary" />
              <span className="text-sm font-medium tracking-wide">Loading detector (approx. 8MB)...</span>
            </div>
          )}

          {/* ── Camera-off placeholder ── */}
          {!active && (
            <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 text-white/80">
              <Camera className="h-10 w-10" />
              <Button size="sm" onClick={startCamera}>
                Start camera
              </Button>
            </div>
          )}

          {/* ── Face oval guide + blink prompt ── */}
          {active && (
            <>
              {/* Radial vignette darkens the corners so the oval pops */}
              <div
                aria-hidden
                style={{
                  position: "absolute",
                  inset: 0,
                  background:
                    "radial-gradient(ellipse 54% 68% at 50% 48%, transparent 96%, rgba(0,0,0,0.55) 100%)",
                  pointerEvents: "none",
                }}
              />

              {/* Oval outline SVG */}
              <svg
                aria-hidden
                style={{ position: "absolute", inset: 0, width: "100%", height: "100%", pointerEvents: "none" }}
                viewBox="0 0 640 480"
                preserveAspectRatio="xMidYMid meet"
              >
                <defs>
                  <filter id="oval-glow" x="-25%" y="-25%" width="150%" height="150%">
                    <feGaussianBlur stdDeviation="5" result="blur" />
                    <feMerge>
                      <feMergeNode in="blur" />
                      <feMergeNode in="SourceGraphic" />
                    </feMerge>
                  </filter>
                  {/* Captured-step flash filter */}
                  <filter id="oval-flash" x="-25%" y="-25%" width="150%" height="150%">
                    <feGaussianBlur stdDeviation="8" result="blur" />
                    <feMerge>
                      <feMergeNode in="blur" />
                      <feMergeNode in="SourceGraphic" />
                    </feMerge>
                  </filter>
                </defs>

                {/* Corner tick marks at oval boundary */}
                {([
                  [-148, -200, -22, 0],
                  [148, -200, 22, 0],
                  [148, 200, 22, 0],
                  [-148, 200, -22, 0],
                ] as [number, number, number, number][]).map(([ox, oy, dx, dy], i) => (
                  <line
                    key={i}
                    x1={320 + ox} y1={240 + oy}
                    x2={320 + ox + dx} y2={240 + oy + dy}
                    strokeWidth="3"
                    strokeLinecap="round"
                    style={{
                      stroke: inRange && faceDetected ? "#22c55e" : "rgba(255,255,255,0.6)",
                      transition: "stroke 0.3s ease",
                    }}
                  />
                ))}

                {/* Main oval — all paint props in style so CSS transitions work */}
                <ellipse
                  cx={320} cy={240}
                  rx={148} ry={200}
                  filter={(inRange && faceDetected) || captured.has(currentStep) ? "url(#oval-glow)" : undefined}
                  style={{
                    fill:
                      (inRange && faceDetected) || captured.has(currentStep)
                        ? "rgba(34,197,94,0.08)"
                        : "none",
                    stroke:
                      captured.has(currentStep) || (inRange && faceDetected)
                        ? "#22c55e"
                        : faceDetected
                        ? "rgba(255,255,255,0.70)"
                        : "rgba(255,255,255,0.30)",
                    strokeWidth: inRange && faceDetected ? 4 : 2,
                    strokeDasharray: !faceDetected ? "10 6" : undefined,
                    transition: "fill 0.3s ease, stroke 0.3s ease, stroke-width 0.25s ease",
                  }}
                />

                {/* Status pills — top centre */}
                <g>
                  {/* Face-detected pill */}
                  <rect x={230} y={14} width={84} height={22} rx={11} fill={faceDetected ? "rgba(34,197,94,0.85)" : "rgba(255,255,255,0.12)"} style={{ transition: "fill 0.3s ease" }} />
                  <text x={272} y={29} textAnchor="middle" fontSize={11} fontWeight="600" fill={faceDetected ? "#fff" : "rgba(255,255,255,0.5)"} fontFamily="system-ui">{faceDetected ? "✓ Face detected" : "No face"}</text>
                  {/* In-range pill */}
                  <rect x={326} y={14} width={84} height={22} rx={11} fill={inRange ? "rgba(34,197,94,0.85)" : "rgba(255,255,255,0.12)"} style={{ transition: "fill 0.3s ease" }} />
                  <text x={368} y={29} textAnchor="middle" fontSize={11} fontWeight="600" fill={inRange ? "#fff" : "rgba(255,255,255,0.5)"} fontFamily="system-ui">{inRange ? "✓ In range" : "Align pose"}</text>
                </g>

                {/* Bottom hints */}
                {blinkReady && (
                  <text x={320} y={458} textAnchor="middle" fontSize={16} fontWeight="500" fill="#22c55e" fontFamily="system-ui" style={{ animation: "fa-blink-hint 1.2s ease-in-out infinite" }}>
                    Blink  ·  or click 📸 below
                  </text>
                )}
                {active && !faceDetected && (
                  <text x={320} y={458} textAnchor="middle" fontSize={14} fill="rgba(255,255,255,0.45)" fontFamily="system-ui">
                    Position your face inside the oval
                  </text>
                )}
                {active && faceDetected && !inRange && (
                  <text x={320} y={458} textAnchor="middle" fontSize={14} fill="rgba(255,200,50,0.9)" fontFamily="system-ui">
                    Adjust your head pose
                  </text>
                )}

                <style>{`
                  @keyframes fa-blink-hint {
                    0%, 100% { opacity: 1; }
                    50%       { opacity: 0.45; }
                  }
                `}</style>
              </svg>
            </>
          )}

          {/* ── Manual capture button — appears centred at the bottom of the oval ── */}
          {blinkReady && (
            <button
              onClick={onManualCapture}
              style={{
                position: "absolute",
                bottom: "10%",
                left: "50%",
                transform: "translateX(-50%)",
                background: "rgba(34,197,94,0.92)",
                border: "2px solid #22c55e",
                borderRadius: 999,
                color: "#fff",
                fontWeight: 700,
                fontSize: 15,
                padding: "8px 28px",
                cursor: "pointer",
                display: "flex",
                alignItems: "center",
                gap: 8,
                boxShadow: "0 0 20px rgba(34,197,94,0.6)",
                animation: "fa-btn-pulse 1.4s ease-in-out infinite",
                zIndex: 10,
              }}
            >
              <span style={{ fontSize: 18 }}>📸</span> Capture
            </button>
          )}

          {/* ── Corner directional guide (mirrored-aware) ── */}
          {active && step && (
            <FacePoseGuide
              liveYaw={live?.yaw ?? null}
              livePitch={live?.pitch ?? null}
              inRange={inRange}
              targetYaw={step.yaw}
              targetPitch={step.pitch}
              instruction={step.instruction}
              mirrored
            />
          )}

          {/* Global keyframes used by the capture button */}
          <style>{`
            @keyframes fa-btn-pulse {
              0%, 100% { box-shadow: 0 0 18px rgba(34,197,94,0.6); }
              50%       { box-shadow: 0 0 32px rgba(34,197,94,0.95); }
            }
          `}</style>
        </div>

        {/* Step instruction + collapsible raw readout */}
        {step && (
          <div className="rounded-md border p-4">
            <div className="flex items-start justify-between gap-2">
              <div>
                <p className="text-sm font-medium">
                  Step {step.step}: {step.instruction}
                </p>
                <p className="mt-1 text-xs text-muted-foreground">
                  {step.mandatory ? "Mandatory" : "Optional"} · yaw{" "}
                  {step.yaw ? `[${step.yaw[0]}°, ${step.yaw[1]}°]` : "—"} · pitch{" "}
                  {step.pitch ? `[${step.pitch[0]}°, ${step.pitch[1]}°]` : "—"}
                </p>
              </div>
              <button
                className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground transition-colors"
                onClick={() => setShowDetails((v) => !v)}
                title={showDetails ? "Hide details" : "Show live readings"}
              >
                {showDetails ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
                {showDetails ? "Hide" : "Details"}
              </button>
            </div>
            {showDetails && (
              <div className="mt-3 flex flex-wrap gap-4 text-sm">
                <Readout label="Yaw"     value={live?.yaw   != null ? `${live.yaw.toFixed(0)}°`   : "—"} />
                <Readout label="Pitch"   value={live?.pitch  != null ? `${live.pitch.toFixed(0)}°`  : "—"} />
                <Readout label="Quality" value={live?.quality != null ? live.quality.toFixed(2)      : "—"} />
                <Readout
                  label="In range"
                  value={
                    live?.inRange ? (
                      <span className="text-emerald-600">yes</span>
                    ) : (
                      <span className="text-muted-foreground">no</span>
                    )
                  }
                />
              </div>
            )}
          </div>
        )}

        {/* Controls */}
        <div className="flex flex-wrap justify-between gap-2">
          <div className="flex gap-2">
            {active ? (
              <Button variant="outline" size="sm" onClick={stopCamera}>
                Stop camera
              </Button>
            ) : (
              <Button variant="outline" size="sm" onClick={startCamera} className="gap-2">
                <Camera className="h-4 w-4" /> Start
              </Button>
            )}
            {!step?.mandatory && (
              <Button variant="ghost" size="sm" onClick={() => setCurrentStep((s) => Math.min(7, s + 1))}>
                Skip step
              </Button>
            )}
          </div>
          <div className="flex gap-2">
            <Button
              size="sm"
              onClick={onFinalize}
              disabled={finalize.isPending || (status.data?.capture_count ?? 0) < 5}
            >
              {finalize.isPending ? <Spinner className="h-4 w-4" /> : "Finalize enrollment"}
            </Button>
            <Button size="sm" variant="outline" onClick={onVerify} disabled={!active || verify.isPending}>
              Verify
            </Button>
            <Button size="sm" variant="ghost" onClick={onReEnroll} className="gap-2">
              <RotateCcw className="h-4 w-4" /> Re-enroll
            </Button>
            <Button size="sm" variant="ghost" onClick={onRemove} className="gap-2">
              <Trash2 className="h-4 w-4 text-destructive" /> Remove
            </Button>
          </div>
        </div>

        {finalResult && (
          <div className="rounded-md border p-4">
            <p className="font-medium">Enrollment finalized</p>
            <p className="text-sm text-muted-foreground">Overall quality: {finalResult.overall.toFixed(3)}</p>
            {finalResult.warning && <ErrorBanner message={finalResult.warning} className="mt-2" />}
          </div>
        )}

        {verifyScore != null && (
          <div className="rounded-md border p-4 text-sm">
            Verification best score: <span className="font-semibold">{verifyScore.toFixed(4)}</span>
          </div>
        )}

        {(capture.isError || finalize.isError) && (
          <ErrorBanner
            message={(capture.error as Error)?.message || (finalize.error as Error)?.message || "Enrollment error."}
          />
        )}
      </CardContent>
    </Card>
  );
}

function Readout({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div>
      <span className="text-muted-foreground">{label}: </span>
      <span className="font-medium">{value}</span>
    </div>
  );
}
