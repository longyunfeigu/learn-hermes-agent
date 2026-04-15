"use client";

import { RotateCcw, ChevronLeft, Play, Pause, ChevronRight } from "lucide-react";
import { cn } from "@/lib/utils";

interface StepControlsProps {
  currentStep: number;
  totalSteps: number;
  isPlaying: boolean;
  onReset: () => void;
  onPrev: () => void;
  onNext: () => void;
  onTogglePlay: () => void;
  annotations?: { title: string; description: string }[];
  className?: string;
}

export function StepControls({
  currentStep,
  totalSteps,
  isPlaying,
  onReset,
  onPrev,
  onNext,
  onTogglePlay,
  annotations,
  className,
}: StepControlsProps) {
  const annotation = annotations?.[currentStep];

  return (
    <div className={cn("space-y-3", className)}>
      <div className="flex items-center justify-center gap-2">
        <button onClick={onReset} className="rounded-md p-1.5 text-zinc-400 hover:text-zinc-600 dark:hover:text-zinc-300" title="Reset">
          <RotateCcw size={16} />
        </button>
        <button onClick={onPrev} disabled={currentStep === 0} className="rounded-md p-1.5 text-zinc-400 hover:text-zinc-600 disabled:opacity-30 dark:hover:text-zinc-300" title="Previous">
          <ChevronLeft size={16} />
        </button>
        <button onClick={onTogglePlay} className="rounded-md p-1.5 text-zinc-400 hover:text-zinc-600 dark:hover:text-zinc-300" title={isPlaying ? "Pause" : "Play"}>
          {isPlaying ? <Pause size={16} /> : <Play size={16} />}
        </button>
        <button onClick={onNext} disabled={currentStep === totalSteps - 1} className="rounded-md p-1.5 text-zinc-400 hover:text-zinc-600 disabled:opacity-30 dark:hover:text-zinc-300" title="Next">
          <ChevronRight size={16} />
        </button>
        <span className="ml-2 text-xs text-zinc-400">
          {currentStep + 1} / {totalSteps}
        </span>
      </div>

      {/* Step dots */}
      <div className="flex justify-center gap-1">
        {Array.from({ length: totalSteps }).map((_, i) => (
          <span
            key={i}
            className={cn(
              "h-1.5 w-1.5 rounded-full transition-colors",
              i === currentStep ? "bg-blue-500" : i < currentStep ? "bg-blue-300 dark:bg-blue-700" : "bg-zinc-200 dark:bg-zinc-700"
            )}
          />
        ))}
      </div>

      {/* Annotation */}
      {annotation && (
        <div className="rounded-lg border border-blue-200 bg-blue-50 px-4 py-3 dark:border-blue-900 dark:bg-blue-950/40">
          <p className="text-xs font-semibold text-blue-700 dark:text-blue-300">{annotation.title}</p>
          <p className="mt-1 text-xs text-blue-600 dark:text-blue-400">{annotation.description}</p>
        </div>
      )}
    </div>
  );
}
