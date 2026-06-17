'use client';

import { useEffect, useRef } from 'react';

interface Props {
  score: number | null;
  level?: string | null;
}

function getGaugeColor(score: number): string {
  if (score >= 76) return '#ef4444';
  if (score >= 51) return '#f97316';
  if (score >= 26) return '#f59e0b';
  return '#10b981';
}

function getLevelLabel(level?: string | null, score?: number | null): string {
  if (level) return level.charAt(0).toUpperCase() + level.slice(1);
  if (score === null || score === undefined) return '—';
  if (score >= 76) return 'Critical';
  if (score >= 51) return 'High';
  if (score >= 26) return 'Moderate';
  return 'Low';
}

// Arc params: semicircle, radius=80, viewBox 0 0 200 120
const RADIUS = 80;
const CX = 100;
const CY = 100;
const START_ANGLE = 180; // degrees
const END_ANGLE = 0;
const CIRCUMFERENCE = Math.PI * RADIUS; // half circle

function scoreToOffset(score: number): number {
  // 0 score → full offset (empty arc), 100 → 0 offset (full arc)
  const fraction = Math.max(0, Math.min(100, score)) / 100;
  return CIRCUMFERENCE * (1 - fraction);
}

export default function RiskGauge({ score, level }: Props) {
  const fillRef = useRef<SVGPathElement>(null);
  const valueRef = useRef<HTMLSpanElement>(null);
  const prevScore = useRef<number>(0);

  useEffect(() => {
    if (score === null || score === undefined) return;

    const target = score;
    const start = prevScore.current;
    const duration = 1000;
    const startTime = performance.now();

    const color = getGaugeColor(target);

    const animate = (now: number) => {
      const elapsed = now - startTime;
      const progress = Math.min(elapsed / duration, 1);
      // Ease out cubic
      const eased = 1 - Math.pow(1 - progress, 3);
      const current = Math.round(start + (target - start) * eased);

      if (fillRef.current) {
        fillRef.current.style.strokeDashoffset = String(scoreToOffset(current));
        fillRef.current.style.stroke = color;
      }
      if (valueRef.current) {
        valueRef.current.textContent = String(current);
        valueRef.current.style.color = color;
      }

      if (progress < 1) requestAnimationFrame(animate);
      else prevScore.current = target;
    };

    requestAnimationFrame(animate);
  }, [score]);

  const displayColor = score !== null ? getGaugeColor(score ?? 0) : 'rgba(0,0,0,0.15)';

  // Arc path: semicircle left-to-right along top
  const arcPath = `M ${CX - RADIUS} ${CY} A ${RADIUS} ${RADIUS} 0 0 1 ${CX + RADIUS} ${CY}`;

  return (
    <div style={{ textAlign: 'center' }}>
      <div className="gauge-container" aria-label={`Risk score: ${score ?? 'loading'}`}>
        <svg className="gauge-svg" viewBox="0 0 200 110" aria-hidden="true">
          {/* Track */}
          <path
            d={arcPath}
            fill="none"
            stroke="rgba(0,0,0,0.06)"
            strokeWidth="14"
            strokeLinecap="round"
          />
          {/* Fill */}
          <path
            ref={fillRef}
            d={arcPath}
            fill="none"
            stroke={displayColor}
            strokeWidth="14"
            strokeLinecap="round"
            strokeDasharray={CIRCUMFERENCE}
            strokeDashoffset={score !== null ? scoreToOffset(score) : CIRCUMFERENCE}
            style={{ transition: 'none', filter: `drop-shadow(0 0 8px ${displayColor}55)` }}
          />
          {/* Tick marks */}
          {[0, 25, 50, 75, 100].map((tick) => {
            const angle = (180 - (tick / 100) * 180) * (Math.PI / 180);
            const innerR = RADIUS - 10;
            const outerR = RADIUS + 2;
            const x1 = CX + innerR * Math.cos(angle);
            const y1 = CY - innerR * Math.sin(angle);
            const x2 = CX + outerR * Math.cos(angle);
            const y2 = CY - outerR * Math.sin(angle);
            return (
              <line key={tick} x1={x1} y1={y1} x2={x2} y2={y2}
                stroke="rgba(0,0,0,0.12)" strokeWidth="1" />
            );
          })}
        </svg>

        {/* Score value overlay */}
        <div className="gauge-score">
          <span
            ref={valueRef}
            className="gauge-value"
            style={{ color: displayColor, transition: 'color 0.5s' }}
          >
            {score ?? '—'}
          </span>
          <div className="gauge-label">/ 100</div>
        </div>
      </div>

      {/* Risk level badge */}
      <div style={{ marginTop: 12 }}>
        <span
          className={`badge badge-${level || (score !== null ? getLevelLabel(level, score).toLowerCase() : 'low')}`}
          style={{ fontSize: 12 }}
        >
          {getLevelLabel(level, score)} Risk
        </span>
      </div>

      {/* Scale labels */}
      <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 8,
        fontSize: 10, color: 'var(--color-text-muted)', padding: '0 8px' }}>
        <span style={{ color: '#10b981' }}>Low</span>
        <span style={{ color: '#f59e0b' }}>Moderate</span>
        <span style={{ color: '#f97316' }}>High</span>
        <span style={{ color: '#ef4444' }}>Critical</span>
      </div>
    </div>
  );
}
