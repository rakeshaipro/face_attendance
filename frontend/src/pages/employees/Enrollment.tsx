import { useCallback, useEffect, useRef, useState } from "react";
import { useCapture, useEnrollmentProtocol, useEnrollmentStatus, useFinalizeEnrollment, useReEnroll, useRemoveCapture, useVerify, useCapturesSummary } from "@/lib/queries";
import { useFaceLandmarker } from "@/hooks/useFaceLandmarker";
import { poseInRange } from "@/lib/poseCheck";
import type { PoseStep } from "@/lib/types";
import { Badge, Button, Card, CardContent, CardDescription, CardHeader, CardTitle, Spinner } from "@/components/ui";
import { ErrorBanner } from "@/components/shared";
import { FacePoseGuide } from "@/components/FacePoseGuide";
import { Camera, CheckCircle2, ChevronDown, ChevronUp, Focus, Lightbulb, Maximize2, RotateCcw, ScanFace, Sun, Trash2, Video } from "lucide-react";
import { cn } from "@/lib/utils";

interface EnrollmentProps {
  employeeId: string;
  employeeName: string;
}

interface BackendDisagreementFrame {
  url: string;
  step: number;
  reason: string;
  clientYaw: number | null;
  clientPitch: number | null;
  clientFaceSize: number | null;
  serverYaw: number | null;
  serverPitch: number | null;
  serverFaceSize: number | null;
}

/**
 * Guided 7-pose enrollment flow (SRS §3.3).
 *
 * Uses the device webcam (getUserMedia), draws the video to a canvas each
 * frame, validates pose locally, and sends the current frame to the backend
 * only when the user clicks capture. One capture per step.
 *
 * Draw loop (~60 fps): draws video → canvas and updates local pose guidance.
 */

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

// Backend enforces engine.min_face_ratio (default 0.10). The frontend uses a
// slightly lower threshold so that a face the client considers "big enough" is
// reliably accepted by InsightFace on the server. MediaPipe and InsightFace
// measure bounding boxes slightly differently.
const MIN_FACE_SIZE_RATIO = 0.12;

export function Enrollment({ employeeId }: EnrollmentProps) {
  const videoRef   = useRef<HTMLVideoElement>(null);
  const canvasRef  = useRef<HTMLCanvasElement>(null);
  const streamRef  = useRef<MediaStream | null>(null);
  const drawRafRef = useRef<number | null>(null);   // draw-loop RAF id
  const captureLockRef = useRef<boolean>(false);    // prevents overlapping captures

  // ── Captured-steps ref (always current, readable inside effects) ──
  const capturedRef = useRef<Set<number>>(new Set());

  const { data: protocol } = useEnrollmentProtocol();
  const status    = useEnrollmentStatus(employeeId);
  const capturesSummary = useCapturesSummary(employeeId);
  const { ready: landmarkerReady, error: landmarkerError, detect } = useFaceLandmarker();
  const capture   = useCapture(employeeId);
  const finalize  = useFinalizeEnrollment(employeeId);
  const reEnroll  = useReEnroll(employeeId);
  const removeCapture = useRemoveCapture(employeeId);
  const verify    = useVerify(employeeId);

  const capturesMap = new Map<number, string>();
  const capturesQuality = new Map<number, number>();
  if (capturesSummary.data) {
    for (const c of capturesSummary.data) {
      capturesMap.set(c.step, c.image_path);
      capturesQuality.set(c.step, c.quality);
    }
  }

  // Cache-buster: the backend reuses the same filename when a pose is
  // re-captured ({employee}_{step}.jpg overwrites in place), so an identical
  // URL would serve the browser's stale thumbnail. `dataUpdatedAt` changes on
  // every successful refetch (capture and remove both invalidate this query),
  // forcing a fresh image fetch.
  const captureImgVersion = capturesSummary.dataUpdatedAt ?? 0;
  const captureImg = (path: string) => `/media/enrollment/${path}?v=${captureImgVersion}`;

  const [currentStep, setCurrentStep] = useState(1);
  // Drives auto-advance: set only when a capture succeeds, cleared on manual
  // navigation or after the advance fires. Prevents jumping away from a
  // captured step the user clicked to review/remove.
  const [justCapturedStep, setJustCapturedStep] = useState<number | null>(null);
  const [live, setLive]               = useState<{ yaw: number | null; pitch: number | null; inRange: boolean; quality: number | null } | null>(null);
  const [camError, setCamError]       = useState<string | null>(null);
  const [finalResult, setFinalResult] = useState<{ overall: number; warning: string | null } | null>(null);
  const [verifyScore, setVerifyScore] = useState<number | null>(null);
  const [active, setActive]           = useState(false);
  const [showDetails, setShowDetails] = useState(false);
  const [tipsOpen, setTipsOpen]       = useState(true);
  const [videoDevices, setVideoDevices] = useState<MediaDeviceInfo[]>([]);
  const [selectedDeviceId, setSelectedDeviceId] = useState<string | null>(null);
  const [switching, setSwitching]     = useState(false);
  const [backendDisagreementFrame, setBackendDisagreementFrame] = useState<BackendDisagreementFrame | null>(null);
  // True once the user has kicked off a re-enroll on an already-enrolled
  // employee, lifting the lock on camera/capture controls until finalize.
  const [reEnrollInitiated, setReEnrollInitiated] = useState(false);

  const steps = protocol?.steps ?? [];
  const step: PoseStep | undefined = steps.find((s) => s.step === currentStep);

  const capturedSteps = status.data?.steps_captured;
  const captured = new Set(capturedSteps ?? []);

  // Keep capturedRef in sync with react-query data for async camera callbacks.
  useEffect(() => {
    capturedRef.current = new Set(capturedSteps ?? []);
  }, [capturedSteps]);

  useEffect(() => {
    return () => {
      setBackendDisagreementFrame((prev) => {
        if (prev) URL.revokeObjectURL(prev.url);
        return null;
      });
    };
  }, []);

  const setDisagreementFrame = useCallback((blob: Blob, frame: Omit<BackendDisagreementFrame, "url">) => {
    const url = URL.createObjectURL(blob);
    setBackendDisagreementFrame((prev) => {
      if (prev) URL.revokeObjectURL(prev.url);
      return { ...frame, url };
    });
  }, []);

  const clearDisagreementFrame = useCallback(() => {
    setBackendDisagreementFrame((prev) => {
      if (prev) URL.revokeObjectURL(prev.url);
      return null;
    });
  }, []);

  // --- enumerate available video input devices ---
  const enumerateCameras = useCallback(async () => {
    try {
      const devices = await navigator.mediaDevices.enumerateDevices();
      setVideoDevices(devices.filter((d) => d.kind === "videoinput"));
    } catch {
      /* enumerateDevices not supported — dropdown stays hidden */
    }
  }, []);

  // --- start/stop camera ---
  const startCamera = useCallback(async (deviceId?: string) => {
    setCamError(null);
    try {
      const id = deviceId ?? selectedDeviceId;
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { width: 1280, height: 720, ...(id ? { deviceId: { exact: id } } : {}) },
        audio: false,
      });
      streamRef.current = stream;
      if (videoRef.current) {
        videoRef.current.srcObject = stream;
        await videoRef.current.play();
      }
      // Permission has now been granted → labels are available.
      await enumerateCameras();
      // Remember the device the stream actually opened (default if none selected).
      const activeId = stream.getVideoTracks()[0]?.getSettings().deviceId ?? null;
      setSelectedDeviceId(activeId);
      setActive(true);
    } catch (e) {
      setCamError(e instanceof Error ? e.message : "Could not access webcam. (Requires HTTPS or localhost.)");
    }
  }, [enumerateCameras, selectedDeviceId]);

  // --- switch the active camera without leaving the capture loop ---
  const switchCamera = useCallback(async (deviceId: string) => {
    setSwitching(true);
    try {
      // Tear down the current stream so the device is released.
      streamRef.current?.getTracks().forEach((t) => t.stop());
      streamRef.current = null;

      const stream = await navigator.mediaDevices.getUserMedia({
        video: { width: 1280, height: 720, deviceId: { exact: deviceId } },
        audio: false,
      });
      streamRef.current = stream;
      if (videoRef.current) {
        videoRef.current.srcObject = stream;
        await videoRef.current.play();
      }
      setSelectedDeviceId(deviceId);
    } catch (e) {
      setCamError(e instanceof Error ? e.message : "Could not switch camera.");
    } finally {
      setSwitching(false);
    }
  }, []);

  // Refresh the device list on plug/unplug (Google-Meet behavior) and on mount.
  useEffect(() => {
    if (!navigator.mediaDevices?.addEventListener) return;
    const handler = () => { void enumerateCameras(); };
    navigator.mediaDevices.addEventListener("devicechange", handler);
    return () => navigator.mediaDevices.removeEventListener("devicechange", handler);
  }, [enumerateCameras]);

  const stopCamera = useCallback(() => {
    setActive(false);
    setLive(null);
    if (drawRafRef.current) cancelAnimationFrame(drawRafRef.current);
    drawRafRef.current = null;
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
  }, []);

  useEffect(() => () => stopCamera(), [stopCamera]);

  const captureCurrentFrame = useCallback(async () => {
    const canvas = canvasRef.current;
    if (!canvas || captureLockRef.current || capturedRef.current.has(currentStep)) return;
    const blob = await canvasToJpegBlob(canvas, 0.92, 1280);
    if (!blob) return;
    captureLockRef.current = true;
    capture.mutate(
      { step: currentStep, file: blob },
      {
        onSuccess: () => {
          clearDisagreementFrame();
          setJustCapturedStep(currentStep);
        },
        onError: (error) => {
          setDisagreementFrame(blob, {
            step: currentStep,
            reason: error instanceof Error ? error.message : "Backend rejected this clicked capture.",
            clientYaw: live?.yaw ?? null,
            clientPitch: live?.pitch ?? null,
            clientFaceSize: live?.quality ?? null,
            serverYaw: null,
            serverPitch: null,
            serverFaceSize: null,
          });
        },
        onSettled: () => { captureLockRef.current = false; },
      }
    );
  }, [capture, clearDisagreementFrame, currentStep, live, setDisagreementFrame]);

  // ─── Loop 1: Draw video → canvas at ~60 fps + local face landmark checking ──────────
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

          // ── Real-time face detection + local pose check ──────
          if (!capturedRef.current.has(currentStep)) {
            const result = detect(video);
            if (result.faceDetected) {
              const poseOk = poseInRange(currentStep, result.yaw, result.pitch);
              const faceBigEnough = result.faceSizeRatio >= MIN_FACE_SIZE_RATIO;
              setLive({
                yaw: result.yaw,
                pitch: result.pitch,
                inRange: poseOk && faceBigEnough,
                quality: result.faceSizeRatio,
              });
            } else {
              setLive(null);
            }
          } else {
            setLive({ yaw: null, pitch: null, inRange: true, quality: null });
          }
        }
      }
      drawRafRef.current = requestAnimationFrame(draw);
    };

    drawRafRef.current = requestAnimationFrame(draw);
    return () => {
      if (drawRafRef.current) cancelAnimationFrame(drawRafRef.current);
    };
  }, [active, currentStep, detect]);

  // Auto-advance ONLY right after the current step was just captured (not when
  // the user navigates back to an already-captured step to review/remove it).
  useEffect(() => {
    if (justCapturedStep == null || justCapturedStep !== currentStep || currentStep >= 7) return;
    const t = setTimeout(() => {
      setCurrentStep((s) => Math.min(7, s + 1));
      setJustCapturedStep(null);
    }, 600);
    return () => clearTimeout(t);
  }, [justCapturedStep, currentStep]);

  const onFinalize = async () => {
    try {
      const res = await finalize.mutateAsync();
      setFinalResult({ overall: res.overall_quality, warning: res.warning });
      setReEnrollInitiated(false);
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
    const blob = await canvasToJpegBlob(canvas, 0.92, 1280);
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
    setReEnrollInitiated(true);
    setFinalResult(null);
    setCurrentStep(1);
  };

  const onRemovePose = async () => {
    if (!captured.has(currentStep)) return;
    if (!confirm(`Remove the captured photo for pose ${currentStep}? You can re-capture it.`)) return;
    await removeCapture.mutateAsync(currentStep);
    setFinalResult(null);
  };

  // ── Derived UI flags ────────────────────────────────────────────────────────
  // An enrolled employee is locked until the user explicitly re-enrolls; this
  // prevents mutating a finalized enrollment (camera start, capture, finalize).
  const locked = !!status.data?.is_enrolled && !reEnrollInitiated;
  const faceDetected = live !== null && live.yaw !== null;
  const inRange      = live?.inRange ?? false;
  const faceTooSmall = faceDetected && live?.quality != null && live.quality < MIN_FACE_SIZE_RATIO;
  const captureReady = faceDetected && inRange && !captured.has(currentStep) && !capture.isPending;

  // Per-pose quality for the step currently in focus (for inline guidance).
  const currentStepQuality = step ? capturesQuality.get(step.step) : undefined;
  const currentStepTier    = currentStepQuality != null ? qualityTier(currentStepQuality) : null;

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

        {/* ── Tips for best capture quality (guideline) ── */}
        <div className="rounded-md border bg-muted/30">
          <button
            type="button"
            onClick={() => setTipsOpen((v) => !v)}
            className="flex w-full items-center justify-between gap-2 p-3 text-left"
          >
            <span className="flex items-center gap-2 text-sm font-medium">
              <Lightbulb className="h-4 w-4 text-amber-500" />
              Tips for best capture quality
            </span>
            <span className="text-xs text-muted-foreground">
              {tipsOpen ? "Hide" : "Show"}
              {tipsOpen ? <ChevronUp className="ml-1 inline h-3.5 w-3.5" /> : <ChevronDown className="ml-1 inline h-3.5 w-3.5" />}
            </span>
          </button>
          {tipsOpen && (
            <div className="grid gap-3 border-t p-3 sm:grid-cols-2">
              <Tip icon={<Focus className="h-4 w-4 text-blue-500" />} title="Hold still" weight="45%">
                Motion blur lowers quality the most — freeze for a moment when you click the capture button.
              </Tip>
              <Tip icon={<Maximize2 className="h-4 w-4 text-indigo-500" />} title="Fill the oval" weight="35%">
                Sit about an arm's length (50–70&nbsp;cm) away and let your face fill the on-screen oval. Too far = face too small.
              </Tip>
              <Tip icon={<Sun className="h-4 w-4 text-amber-500" />} title="Face the light" weight="20%">
                Face a window or lamp. Avoid backlight (light behind you) and very dim or harsh direct glare.
              </Tip>
              <Tip icon={<ScanFace className="h-4 w-4 text-emerald-500" />} title="Clear your face">
                Remove sunglasses, masks, or hair covering your face. Capture only when the oval ring is green.
              </Tip>
            </div>
          )}
        </div>

        {/* Step indicators */}
        <div className="flex items-center justify-center gap-2">
          {steps.map((s) => {
            const sq = capturesQuality.get(s.step);
            const tier = sq != null ? qualityTier(sq) : null;
            return (
            <div key={s.step} className="group relative">
              <button
                onClick={() => { setJustCapturedStep(null); setCurrentStep(s.step); }}
                className={cn(
                  "flex h-10 w-10 items-center justify-center rounded-full border text-sm font-medium transition-all duration-200 overflow-hidden",
                  captured.has(s.step)
                    ? cn(tier?.border ?? "border-emerald-500", "shadow-sm hover:opacity-80")
                    : currentStep === s.step
                      ? "border-primary bg-primary/10 text-primary ring-2 ring-primary/20"
                      : "border-border text-muted-foreground hover:border-muted-foreground/60",
                )}
                title={s.instruction}
              >
                {capture.isPending && s.step === currentStep ? (
                  <Spinner className="h-5 w-5" />
                ) : captured.has(s.step) && capturesMap.has(s.step) ? (
                  <img
                    src={captureImg(capturesMap.get(s.step)!)}
                    alt={`Step ${s.step}`}
                    className="h-full w-full object-cover"
                  />
                ) : captured.has(s.step) ? (
                  <CheckCircle2 className={cn("h-4 w-4", tier?.text ?? "text-emerald-500")} />
                ) : (
                  s.step
                )}
              </button>
              {captured.has(s.step) && capturesMap.has(s.step) && (
                <div className="pointer-events-none absolute bottom-full left-1/2 z-50 mb-2 w-32 -translate-x-1/2 scale-95 rounded-lg border bg-popover p-1 shadow-md opacity-0 group-hover:opacity-100 group-hover:scale-100 transition-all duration-200">
                  <img
                    src={captureImg(capturesMap.get(s.step)!)}
                    alt={`Preview Step ${s.step}`}
                    className="aspect-square w-full rounded-md object-cover"
                  />
                  <div className={cn("mt-1 flex items-center justify-center gap-1 text-[10px] text-center font-medium", tier?.text ?? "text-popover-foreground")}>
                    <span className={cn("h-1.5 w-1.5 rounded-full", tier?.dot ?? "bg-emerald-500")} />
                    Step {s.step}{tier ? ` · ${tier.label}` : ""}{sq != null ? ` (${sq.toFixed(2)})` : ""}
                  </div>
                </div>
              )}
            </div>
            );
          })}
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
              {locked ? (
                <p className="max-w-xs text-center text-sm text-white/70">
                  Already enrolled. Click <span className="font-medium text-white">Re-enroll</span> to start over.
                </p>
              ) : (
                <Button size="sm" onClick={() => startCamera()}>
                  Start camera
                </Button>
              )}
            </div>
          )}

          {/* ── Face oval guide + click-to-capture prompt ── */}
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
                  <rect x={326} y={14} width={84} height={22} rx={11} fill={inRange ? "rgba(34,197,94,0.85)" : faceTooSmall ? "rgba(255,180,50,0.85)" : "rgba(255,255,255,0.12)"} style={{ transition: "fill 0.3s ease" }} />
                  <text x={368} y={29} textAnchor="middle" fontSize={11} fontWeight="600" fill={inRange ? "#fff" : faceTooSmall ? "#fff" : "rgba(255,255,255,0.5)"} fontFamily="system-ui">{inRange ? "✓ In range" : faceTooSmall ? "Too far" : "Align pose"}</text>
                </g>

                {/* Bottom hints */}
                {captureReady && (
                  <text x={320} y={458} textAnchor="middle" fontSize={16} fontWeight="500" fill="#22c55e" fontFamily="system-ui" style={{ animation: "fa-capture-hint 1.2s ease-in-out infinite" }}>
                    Click 📸 below to send this frame
                  </text>
                )}
                {active && !faceDetected && (
                  <text x={320} y={458} textAnchor="middle" fontSize={14} fill="rgba(255,255,255,0.45)" fontFamily="system-ui">
                    Position your face inside the oval
                  </text>
                )}
                {active && faceDetected && !inRange && (
                  <text x={320} y={458} textAnchor="middle" fontSize={14} fill="rgba(255,200,50,0.9)" fontFamily="system-ui">
                    {faceTooSmall ? "Move closer — face is too small" : "Adjust your head pose"}
                  </text>
                )}

                <style>{`
                  @keyframes fa-capture-hint {
                    0%, 100% { opacity: 1; }
                    50%       { opacity: 0.45; }
                  }
                `}</style>
              </svg>
            </>
          )}

          {/* ── Manual capture button — appears centred at the bottom of the oval ── */}
          {captureReady && (
            <button
              onClick={() => void captureCurrentFrame()}
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

          {/* ── Upload-in-flight overlay (waiting sign while image uploads) ── */}
          {capture.isPending && (
            <div
              className="absolute inset-0 z-30 flex flex-col items-center justify-center gap-2 bg-black/60 text-white"
              style={{ pointerEvents: "none" }}
            >
              <Spinner className="h-8 w-8 text-primary" />
              <span className="text-sm font-medium tracking-wide">Uploading capture…</span>
            </div>
          )}

          {/* ── Capture-failed overlay (shows the real backend error message) ── */}
          {capture.isError && !capture.isPending && (
            <div className="absolute inset-0 z-30 flex flex-col items-center justify-center gap-3 bg-black/80 p-6 text-center text-white">
              <span className="text-sm font-semibold" style={{ color: "#fca5a5" }}>
                Capture failed
              </span>
              <span className="max-w-md text-sm text-white/90">
                {(capture.error as Error)?.message || "Could not capture this pose. Please try again."}
              </span>
              <Button size="sm" variant="outline" onClick={() => capture.reset()}>
                Dismiss
              </Button>
            </div>
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
            {currentStepTier && currentStepQuality != null && (
              <div className="mt-3 flex items-start gap-2 rounded-md bg-muted/40 p-2">
                <span className={cn("mt-1 h-2 w-2 shrink-0 rounded-full", currentStepTier.dot)} />
                <div className="text-xs">
                  <span className={cn("font-medium", currentStepTier.text)}>
                    Captured quality {currentStepQuality.toFixed(2)} · {currentStepTier.label}
                  </span>
                  <span className="ml-1 text-muted-foreground">{currentStepTier.suggestion}</span>
                </div>
              </div>
            )}
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
            {backendDisagreementFrame && (
              <div className="mt-3 grid gap-3 rounded-md border border-amber-300/60 bg-amber-50 p-3 text-xs text-amber-950 md:grid-cols-[180px_1fr] dark:border-amber-400/30 dark:bg-amber-950/20 dark:text-amber-100">
                <img
                  src={backendDisagreementFrame.url}
                  alt={`Frame sent to backend for step ${backendDisagreementFrame.step}`}
                  className="w-full rounded border border-amber-300/60 bg-black object-contain"
                />
                <div className="space-y-2">
                  <div>
                    <p className="font-semibold">Backend disagreed with this sent frame</p>
                    <p className="mt-1">{backendDisagreementFrame.reason}</p>
                  </div>
                  <div className="grid gap-1 sm:grid-cols-2">
                    <Readout label="Client yaw" value={backendDisagreementFrame.clientYaw != null ? `${backendDisagreementFrame.clientYaw.toFixed(0)}°` : "—"} />
                    <Readout label="Server yaw" value={backendDisagreementFrame.serverYaw != null ? `${backendDisagreementFrame.serverYaw.toFixed(0)}°` : "—"} />
                    <Readout label="Client pitch" value={backendDisagreementFrame.clientPitch != null ? `${backendDisagreementFrame.clientPitch.toFixed(0)}°` : "—"} />
                    <Readout label="Server pitch" value={backendDisagreementFrame.serverPitch != null ? `${backendDisagreementFrame.serverPitch.toFixed(0)}°` : "—"} />
                    <Readout label="Client face size" value={backendDisagreementFrame.clientFaceSize != null ? backendDisagreementFrame.clientFaceSize.toFixed(2) : "—"} />
                    <Readout label="Server face size" value={backendDisagreementFrame.serverFaceSize != null ? backendDisagreementFrame.serverFaceSize.toFixed(2) : "—"} />
                  </div>
                  <a
                    href={backendDisagreementFrame.url}
                    download={`backend-disagreed-step-${backendDisagreementFrame.step}.jpg`}
                    className="inline-flex text-xs font-medium underline underline-offset-2"
                  >
                    Download exact JPEG sent to backend
                  </a>
                </div>
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
              <Button variant="outline" size="sm" onClick={() => startCamera()} disabled={locked} className="gap-2">
                <Camera className="h-4 w-4" /> Start
              </Button>
            )}
            {/* Camera source selector — only when multiple cameras are available (Google-Meet style) */}
            {active && videoDevices.length > 1 && (
              <div className="relative flex items-center">
                <Video className="pointer-events-none absolute left-2.5 h-4 w-4 text-muted-foreground" />
                <select
                  value={selectedDeviceId ?? ""}
                  onChange={(e) => void switchCamera(e.target.value)}
                  disabled={switching}
                  className="h-8 rounded-md border border-input bg-background py-0 pl-8 pr-3 text-xs focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50"
                  title="Select camera"
                >
                  {videoDevices.map((d, i) => (
                    <option key={d.deviceId || i} value={d.deviceId}>
                      {d.label || `Camera ${i + 1}`}
                    </option>
                  ))}
                </select>
              </div>
            )}
            {!step?.mandatory && (
              <Button variant="ghost" size="sm" onClick={() => setCurrentStep((s) => Math.min(7, s + 1))} disabled={locked}>
                Skip step
              </Button>
            )}
          </div>
          <div className="flex gap-2">
            <Button
              size="sm"
              onClick={onFinalize}
              disabled={locked || finalize.isPending || (status.data?.capture_count ?? 0) < 5}
            >
              {finalize.isPending ? <Spinner className="h-4 w-4" /> : "Finalize enrollment"}
            </Button>
            <Button size="sm" variant="outline" onClick={onVerify} disabled={!active || verify.isPending}>
              Verify
            </Button>
            <Button size="sm" variant="ghost" onClick={onReEnroll} className="gap-2">
              <RotateCcw className="h-4 w-4" /> Re-enroll
            </Button>
            <Button
              size="sm"
              variant="ghost"
              onClick={onRemovePose}
              disabled={!captured.has(currentStep) || removeCapture.isPending}
              className="gap-2"
              title={captured.has(currentStep) ? `Remove captured photo for pose ${currentStep}` : "No captured photo for the current pose"}
            >
              <Trash2 className="h-4 w-4 text-destructive" />
              {removeCapture.isPending ? <Spinner className="h-4 w-4" /> : "Remove pose"}
            </Button>
          </div>
        </div>

        {finalResult && (() => {
          const verdict = finalizeVerdict(finalResult.overall);
          return (
            <div className="rounded-md border p-4">
              <div className="flex items-center justify-between gap-2">
                <p className="font-medium">Enrollment finalized</p>
                <span className={cn("text-sm font-semibold", verdict.text)}>
                  {verdict.label}
                </span>
              </div>
              <p className="text-sm text-muted-foreground">
                Overall quality: <span className={cn("font-semibold", verdict.text)}>{finalResult.overall.toFixed(3)}</span>
                <span className="ml-1 text-muted-foreground">(min recommended 0.40)</span>
              </p>
              <p className={cn("mt-1 text-xs", verdict.text)}>{verdict.tip}</p>
              {finalResult.warning && <ErrorBanner message={finalResult.warning} className="mt-2" />}
            </div>
          );
        })()}

        {verifyScore != null && (
          <div className="rounded-md border p-4 text-sm">
            Verification best score: <span className="font-semibold">{verifyScore.toFixed(4)}</span>
          </div>
        )}

        {(finalize.isError || removeCapture.isError) && (
          <ErrorBanner
            message={(finalize.error as Error)?.message || (removeCapture.error as Error)?.message || "Enrollment error."}
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

function Tip({ icon, title, weight, children }: { icon: React.ReactNode; title: string; weight?: string; children: React.ReactNode }) {
  return (
    <div className="flex items-start gap-2">
      <span className="mt-0.5 shrink-0">{icon}</span>
      <div className="text-xs">
        <p className="font-medium text-foreground">
          {title}{weight && <span className="ml-1 font-normal text-muted-foreground">· {weight} of score</span>}
        </p>
        <p className="mt-0.5 text-muted-foreground">{children}</p>
      </div>
    </div>
  );
}

// ─── Quality guidance ────────────────────────────────────────────────────────
// Per-capture quality = 0.45·sharpness + 0.20·brightness + 0.35·face_size.
// Tiers map a score to a colour + actionable suggestion. The full Tailwind
// class names appear literally below so the JIT compiler includes them.

interface QualityTier {
  label: string;
  tone: "good" | "ok" | "low";
  border: string;     // captured-step circle border
  text: string;       // inline accent text
  dot: string;        // small status dot bg
  suggestion: string; // targeted tip
}

function qualityTier(score: number): QualityTier {
  if (score >= 0.6) {
    return {
      label: "Good", tone: "good",
      border: "border-emerald-500", text: "text-emerald-600", dot: "bg-emerald-500",
      suggestion: "Good quality — no change needed.",
    };
  }
  if (score >= 0.4) {
    return {
      label: "Acceptable", tone: "ok",
      border: "border-amber-500", text: "text-amber-600", dot: "bg-amber-500",
      suggestion: "Could be sharper — hold still, fill the oval, and face a light source.",
    };
  }
  return {
    label: "Low", tone: "low",
    border: "border-red-500", text: "text-red-600", dot: "bg-red-500",
    suggestion: "Re-capture this pose: fill the oval with your face, hold steady, and improve the lighting.",
  };
}

interface FinalizeVerdict {
  label: string;
  text: string;
  tip: string;
}

function finalizeVerdict(score: number): FinalizeVerdict {
  if (score >= 0.7) {
    return { label: "Excellent", text: "text-emerald-600", tip: "High-quality enrollment — recognition will be reliable." };
  }
  if (score >= 0.55) {
    return { label: "Good", text: "text-emerald-600", tip: "Solid quality. For even better matching, fill the oval and hold still on each capture." };
  }
  if (score >= 0.4) {
    return { label: "Acceptable", text: "text-amber-600", tip: "Workable, but re-enrolling with better lighting, focus, and a larger face would improve recognition." };
  }
  return { label: "Below recommended", text: "text-red-600", tip: "Below the recommended minimum. Re-enroll: fill the oval, hold steady, and face a light source." };
}
