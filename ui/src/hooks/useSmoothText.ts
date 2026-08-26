import { useEffect, useRef, useState } from "react";

interface SmoothTextOptions {
  /** Server đã hoàn thành (nhận event done) */
  isComplete?: boolean;
  /** Callback khi buffer đã gõ xong toàn bộ */
  onComplete?: () => void;
}

/** Hook tạo hiệu ứng nhả chữ (token smoothing / typewriter) mượt mà như ChatGPT / Claude.
 * Thay vì giật cục từng block lớn khi SSE nhận data, hook này nhả từng ký tự ở 60fps,
 * tự động tăng tốc khi có nhiều chữ dồn về để không bị chậm.
 */
export function useSmoothText(
  targetText: string,
  options?: SmoothTextOptions
): string {
  const [displayedText, setDisplayedText] = useState("");
  const targetCharsRef = useRef<string[]>([]);
  const displayedCountRef = useRef(0);
  const animFrameRef = useRef<number | null>(null);
  const completedFiredRef = useRef(false);
  const optionsRef = useRef(options);
  optionsRef.current = options;

  // Cập nhật target text (unicode-safe để không lỗi ký tự tiếng Việt)
  useEffect(() => {
    if (!targetText) {
      targetCharsRef.current = [];
      displayedCountRef.current = 0;
      completedFiredRef.current = false;
      setDisplayedText("");
      return;
    }

    const chars = Array.from(targetText);
    targetCharsRef.current = chars;

    if (displayedCountRef.current > chars.length) {
      displayedCountRef.current = chars.length;
      setDisplayedText(targetText);
    }
  }, [targetText]);

  // Vòng lặp animation mượt mà nhả chữ
  useEffect(() => {
    let lastTime = performance.now();

    const tick = (now: number) => {
      const elapsed = now - lastTime;
      const targetLen = targetCharsRef.current.length;
      const currentCount = displayedCountRef.current;

      if (currentCount < targetLen) {
        if (elapsed >= 14) {
          lastTime = now;
          const remaining = targetLen - currentCount;
          const isComplete = optionsRef.current?.isComplete;

          let step = 1;
          if (isComplete) {
            // Khi server đã xong, xả chữ nhanh nhưng vẫn mượt (khoảng 150-250ms là xong)
            step = Math.max(3, Math.ceil(remaining / 6));
          } else if (remaining <= 4) {
            step = 1;
          } else if (remaining <= 15) {
            step = 2;
          } else if (remaining <= 40) {
            step = 3;
          } else if (remaining <= 90) {
            step = Math.ceil(remaining / 8);
          } else {
            // Burst lớn từ server, tăng tốc để không bị trễ
            step = Math.ceil(remaining / 5);
          }

          const nextCount = Math.min(currentCount + step, targetLen);
          displayedCountRef.current = nextCount;
          setDisplayedText(targetCharsRef.current.slice(0, nextCount).join(""));

          if (nextCount >= targetLen && isComplete && !completedFiredRef.current) {
            completedFiredRef.current = true;
            optionsRef.current?.onComplete?.();
          }
        }
      } else if (optionsRef.current?.isComplete && !completedFiredRef.current) {
        completedFiredRef.current = true;
        optionsRef.current?.onComplete?.();
      }

      animFrameRef.current = requestAnimationFrame(tick);
    };

    animFrameRef.current = requestAnimationFrame(tick);

    return () => {
      if (animFrameRef.current !== null) {
        cancelAnimationFrame(animFrameRef.current);
      }
    };
  }, [targetText, options?.isComplete]);

  return displayedText;
}
