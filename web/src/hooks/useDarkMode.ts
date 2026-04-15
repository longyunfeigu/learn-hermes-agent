"use client";

import { useState, useEffect } from "react";

export interface SvgPalette {
  nodeFill: string;
  nodeStroke: string;
  nodeText: string;
  activeNodeFill: string;
  activeNodeStroke: string;
  activeNodeText: string;
  endNodeFill: string;
  endNodeStroke: string;
  edgeStroke: string;
  activeEdgeStroke: string;
  labelText: string;
  labelBg: string;
  bg: string;
}

const LIGHT: SvgPalette = {
  nodeFill: "#f8fafc",
  nodeStroke: "#e2e8f0",
  nodeText: "#334155",
  activeNodeFill: "#dbeafe",
  activeNodeStroke: "#3b82f6",
  activeNodeText: "#1e40af",
  endNodeFill: "#f3e8ff",
  endNodeStroke: "#a855f7",
  edgeStroke: "#cbd5e1",
  activeEdgeStroke: "#3b82f6",
  labelText: "#64748b",
  labelBg: "#ffffff",
  bg: "#ffffff",
};

const DARK: SvgPalette = {
  nodeFill: "#18181b",
  nodeStroke: "#27272a",
  nodeText: "#d4d4d8",
  activeNodeFill: "#1e3a5f",
  activeNodeStroke: "#3b82f6",
  activeNodeText: "#93c5fd",
  endNodeFill: "#2e1065",
  endNodeStroke: "#a855f7",
  edgeStroke: "#3f3f46",
  activeEdgeStroke: "#3b82f6",
  labelText: "#a1a1aa",
  labelBg: "#09090b",
  bg: "#09090b",
};

export function useSvgPalette(): SvgPalette {
  const [isDark, setIsDark] = useState(false);

  useEffect(() => {
    setIsDark(document.documentElement.classList.contains("dark"));
    const observer = new MutationObserver(() => {
      setIsDark(document.documentElement.classList.contains("dark"));
    });
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ["class"] });
    return () => observer.disconnect();
  }, []);

  return isDark ? DARK : LIGHT;
}
