'use client';

import { useState } from 'react';

interface PrecedentCitation {
  clause_type: string;
  outcome: string;
  similarity_score: number;
  jurisdiction?: string;
}

interface RiskFactor {
  factor: string;
  severity: 'low' | 'medium' | 'high' | 'critical';
  clause_name: string;
  clause_excerpt: string;
  clause_span_start?: number;
  clause_span_end?: number;
  precedent_citation?: PrecedentCitation;
  financial_exposure?: string;
}

interface Props {
  riskFactors: RiskFactor[];
}

function SeverityBadge({ severity }: { severity: string }) {
  return (
    <span className={`badge badge-${severity}`}>
      {severity === 'critical' && '⚡ '}
      {severity === 'high' && '⚠️ '}
      {severity.charAt(0).toUpperCase() + severity.slice(1)}
    </span>
  );
}

export default function ClauseTable({ riskFactors }: Props) {
  const [expanded, setExpanded] = useState<number | null>(null);

  if (!riskFactors || riskFactors.length === 0) {
    return (
      <div style={{ textAlign: 'center', padding: '32px 0', color: 'var(--color-text-muted)', fontSize: 14 }}>
        No risk factors identified.
      </div>
    );
  }

  const sorted = [...riskFactors].sort((a, b) => {
    const order = { critical: 0, high: 1, medium: 2, low: 3 };
    return (order[a.severity] ?? 4) - (order[b.severity] ?? 4);
  });

  return (
    <div role="table" aria-label="Risk factors">
      {/* Header */}
      <div role="row" style={{ display: 'grid', gridTemplateColumns: '1fr 120px 140px',
        padding: '8px 16px', fontSize: 11, fontWeight: 600,
        color: 'var(--color-text-muted)', textTransform: 'uppercase', letterSpacing: '0.08em' }}>
        <span>Risk Factor</span>
        <span>Severity</span>
        <span>Financial Exposure</span>
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
        {sorted.map((factor, i) => (
          <div key={i} id={`risk-factor-${i}`} role="rowgroup">
            {/* Main row */}
            <div
              role="row"
              className={`clause-row ${expanded === i ? 'expanded' : ''}`}
              onClick={() => setExpanded(expanded === i ? null : i)}
              style={{ display: 'grid', gridTemplateColumns: '1fr 120px 140px',
                cursor: 'pointer', borderRadius: 10 }}
              aria-expanded={expanded === i}
            >
              <div className="clause-cell" role="cell">
                <div style={{ fontSize: 13, fontWeight: 500, marginBottom: 3 }}>
                  {factor.factor}
                </div>
                <div style={{ fontSize: 11, color: 'var(--color-text-muted)' }}>
                  {factor.clause_name}
                </div>
              </div>
              <div className="clause-cell" role="cell" style={{ display: 'flex', alignItems: 'center' }}>
                <SeverityBadge severity={factor.severity} />
              </div>
              <div className="clause-cell" role="cell" style={{ display: 'flex', alignItems: 'center',
                fontSize: 12, fontFamily: "'JetBrains Mono', monospace",
                color: factor.financial_exposure?.toLowerCase().includes('uncapped')
                  ? '#ba1a1a' : 'var(--color-text-secondary)' }}>
                {factor.financial_exposure || '—'}
              </div>
            </div>

            {/* Expanded detail */}
            {expanded === i && (
              <div className="clause-detail animate-in" role="cell">
                {/* Clause excerpt */}
                <div style={{ marginBottom: 12 }}>
                  <span style={{ fontSize: 10, fontWeight: 600, color: 'var(--color-text-muted)',
                    textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 6,
                    display: 'block' }}>
                    Clause Text
                  </span>
                  <div style={{ background: 'rgba(0,0,0,0.03)', borderRadius: 8,
                    padding: '10px 14px', fontFamily: "'JetBrains Mono', monospace",
                    fontSize: 12, lineHeight: 1.7, color: 'var(--color-text-secondary)',
                    borderLeft: `3px solid var(--color-risk-${factor.severity})` }}>
                    &ldquo;{factor.clause_excerpt}&rdquo;
                    {(factor.clause_span_start !== undefined && factor.clause_span_end !== undefined) && (
                      <span style={{ marginLeft: 8, fontSize: 10, color: 'var(--color-text-muted)' }}>
                        [chars {factor.clause_span_start}–{factor.clause_span_end}]
                      </span>
                    )}
                  </div>
                </div>

                {/* Precedent citation */}
                {factor.precedent_citation && (
                  <div className="precedent-box">
                    <div style={{ fontSize: 10, fontWeight: 600, color: 'var(--color-text-muted)',
                      textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 6 }}>
                      CUAD Precedent (similarity: {(factor.precedent_citation.similarity_score * 100).toFixed(0)}%)
                    </div>
                    <div>
                      <strong>{factor.precedent_citation.clause_type}</strong>
                      {factor.precedent_citation.jurisdiction && (
                        <span style={{ marginLeft: 8, fontSize: 11,
                          color: 'var(--color-text-muted)' }}>
                          · {factor.precedent_citation.jurisdiction}
                        </span>
                      )}
                    </div>
                    <div style={{ marginTop: 4, fontSize: 12 }}>
                      {factor.precedent_citation.outcome}
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
