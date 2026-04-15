"use client";

import { motion } from "framer-motion";
import { getFlowForVersion } from "@/data/execution-flows";
import { getChapterGuide } from "@/lib/chapter-guides";
import { useLocale } from "@/lib/i18n";
import { translateFlowText } from "@/lib/diagram-localization";

const NODE_WIDTH = 140;
const NODE_HEIGHT = 40;
const DIAMOND_SIZE = 50;

const NODE_COLORS: Record<string, string> = {
  start: "#3B82F6",
  process: "#10B981",
  decision: "#F59E0B",
  subprocess: "#8B5CF6",
  end: "#EF4444",
};

export function ExecutionFlow({ version }: { version: string }) {
  const locale = useLocale();
  const flow = getFlowForVersion(version);
  const guide = getChapterGuide(version, locale);

  if (!flow) {
    return (
      <div className="rounded-lg border border-zinc-200 p-8 text-center text-sm text-zinc-400 dark:border-zinc-700">
        No flow diagram for this chapter yet.
      </div>
    );
  }

  const maxY = Math.max(...flow.nodes.map((n) => n.y)) + 80;

  return (
    <div className="space-y-4">
      <div className="overflow-x-auto rounded-lg border border-zinc-200 bg-white p-4 dark:border-zinc-700 dark:bg-zinc-900">
        <svg
          width={600}
          height={maxY}
          viewBox={`0 0 600 ${maxY}`}
          className="mx-auto"
        >
          {/* Edges */}
          {flow.edges.map((edge, i) => {
            const from = flow.nodes.find((n) => n.id === edge.from);
            const to = flow.nodes.find((n) => n.id === edge.to);
            if (!from || !to) return null;
            const x1 = from.x;
            const y1 =
              from.y +
              (from.type === "decision" ? DIAMOND_SIZE / 2 : NODE_HEIGHT / 2);
            const x2 = to.x;
            const y2 =
              to.y -
              (to.type === "decision" ? DIAMOND_SIZE / 2 : NODE_HEIGHT / 2);
            const midY = (y1 + y2) / 2;
            return (
              <g key={i}>
                <motion.path
                  d={`M ${x1} ${y1} C ${x1} ${midY}, ${x2} ${midY}, ${x2} ${y2}`}
                  fill="none"
                  stroke="#94a3b8"
                  strokeWidth={1.5}
                  markerEnd="url(#arrow)"
                  initial={{ pathLength: 0 }}
                  animate={{ pathLength: 1 }}
                  transition={{ duration: 0.5, delay: i * 0.1 }}
                />
                {edge.label && (
                  <text
                    x={(x1 + x2) / 2 + 8}
                    y={midY}
                    fill="#64748b"
                    fontSize={10}
                    textAnchor="start"
                  >
                    {translateFlowText(edge.label, locale)}
                  </text>
                )}
              </g>
            );
          })}
          {/* Arrow marker */}
          <defs>
            <marker
              id="arrow"
              markerWidth="8"
              markerHeight="6"
              refX="8"
              refY="3"
              orient="auto"
            >
              <path d="M0,0 L8,3 L0,6" fill="#94a3b8" />
            </marker>
          </defs>
          {/* Nodes */}
          {flow.nodes.map((node, i) => {
            const color = NODE_COLORS[node.type] || "#6b7280";
            const label = translateFlowText(node.label, locale);
            if (node.type === "decision") {
              const half = DIAMOND_SIZE / 2;
              return (
                <motion.g
                  key={node.id}
                  initial={{ opacity: 0, scale: 0.8 }}
                  animate={{ opacity: 1, scale: 1 }}
                  transition={{ delay: i * 0.08 }}
                >
                  <polygon
                    points={`${node.x},${node.y - half} ${node.x + half},${node.y} ${node.x},${node.y + half} ${node.x - half},${node.y}`}
                    fill={color + "20"}
                    stroke={color}
                    strokeWidth={2}
                  />
                  <text
                    x={node.x}
                    y={node.y + 4}
                    fill={color}
                    fontSize={10}
                    fontWeight={600}
                    textAnchor="middle"
                  >
                    {label}
                  </text>
                </motion.g>
              );
            }
            return (
              <motion.g
                key={node.id}
                initial={{ opacity: 0, y: -10 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: i * 0.08 }}
              >
                <rect
                  x={node.x - NODE_WIDTH / 2}
                  y={node.y - NODE_HEIGHT / 2}
                  width={NODE_WIDTH}
                  height={NODE_HEIGHT}
                  rx={8}
                  fill={color + "20"}
                  stroke={color}
                  strokeWidth={2}
                />
                <text
                  x={node.x}
                  y={node.y + 4}
                  fill={color}
                  fontSize={11}
                  fontWeight={600}
                  textAnchor="middle"
                >
                  {label}
                </text>
              </motion.g>
            );
          })}
        </svg>
      </div>
      {/* Guide section */}
      {guide && (
        <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
          <div className="rounded-lg border border-emerald-200 bg-emerald-50 p-3 dark:border-emerald-900 dark:bg-emerald-950/30">
            <p className="text-[10px] font-bold uppercase tracking-wider text-emerald-600 dark:text-emerald-400">
              Focus
            </p>
            <p className="mt-1 text-xs text-emerald-800 dark:text-emerald-300">
              {guide.focus}
            </p>
          </div>
          <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 dark:border-amber-900 dark:bg-amber-950/30">
            <p className="text-[10px] font-bold uppercase tracking-wider text-amber-600 dark:text-amber-400">
              Confusion
            </p>
            <p className="mt-1 text-xs text-amber-800 dark:text-amber-300">
              {guide.confusion}
            </p>
          </div>
          <div className="rounded-lg border border-sky-200 bg-sky-50 p-3 dark:border-sky-900 dark:bg-sky-950/30">
            <p className="text-[10px] font-bold uppercase tracking-wider text-sky-600 dark:text-sky-400">
              Goal
            </p>
            <p className="mt-1 text-xs text-sky-800 dark:text-sky-300">
              {guide.goal}
            </p>
          </div>
        </div>
      )}
    </div>
  );
}
