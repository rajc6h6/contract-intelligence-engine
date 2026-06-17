'use client';

import { useEffect, useRef, useState } from 'react';
import GraphProgress from '@/components/GraphProgress';
import RiskGauge from '@/components/RiskGauge';
import ClauseTable from '@/components/ClauseTable';
import EscalationBanner from '@/components/EscalationBanner';

const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL || 'http://localhost:8000';

interface RiskReport {
  risk_score: number;
  risk_level: string;
  risk_factors: any[];
  recommended_actions: any[];
  requires_escalation: boolean;
  escalation_reason?: string;
  clause_coverage_score?: number;
  analysis_timestamp?: string;
}

interface PageState {
  status: 'loading' | 'running' | 'completed' | 'escalated' | 'failed';
  currentNode: string | null;
  completedNodes: string[];
  riskScore: number | null;
  riskReport: RiskReport | null;
  errorMessage: string | null;
}

export default function ContractDetailPage({ params }: { params: { id: string } }) {
  const contractId = params.id;
  const [state, setState] = useState<PageState>({
    status: 'loading',
    currentNode: null,
    completedNodes: [],
    riskScore: null,
    riskReport: null,
    errorMessage: null,
  });
  const [activeTab, setActiveTab] = useState<'risks' | 'actions'>('risks');
  const eventSourceRef = useRef<EventSource | null>(null);

  useEffect(() => {
    // Connect to SSE stream
    const es = new EventSource(`${BACKEND_URL}/contracts/${contractId}/stream`);
    eventSourceRef.current = es;

    es.onmessage = (event) => {
      const data = JSON.parse(event.data);

      switch (data.type) {
        case 'heartbeat':
          break;

        case 'node_complete':
          setState((prev) => ({
            ...prev,
            status: 'running',
            currentNode: data.node,
            completedNodes: prev.completedNodes.includes(data.current_node)
              ? prev.completedNodes
              : [...prev.completedNodes, data.current_node],
            riskScore: data.risk_score ?? prev.riskScore,
          }));
          break;

        case 'complete':
          setState((prev) => ({
            ...prev,
            status: data.status === 'escalated' ? 'escalated' : 'completed',
            currentNode: null,
            completedNodes: data.status === 'escalated'
              ? [...prev.completedNodes, 'risk_scorer']
              : [...prev.completedNodes, 'auto_approve'],
            riskScore: data.risk_score ?? prev.riskScore,
            riskReport: data.risk_report ?? prev.riskReport,
          }));
          es.close();
          break;

        case 'error':
          setState((prev) => ({
            ...prev,
            status: 'failed',
            errorMessage: data.message,
          }));
          es.close();
          break;
      }
    };

    es.onerror = () => {
      // Try fetching existing state on SSE failure
      fetch(`${BACKEND_URL}/contracts/${contractId}`)
        .then((r) => r.json())
        .then((data) => {
          if (data.status in { completed: 1, escalated: 1, failed: 1 }) {
            setState((prev) => ({
              ...prev,
              status: data.status,
              riskScore: data.risk_score ?? prev.riskScore,
              riskReport: data.risk_report ?? prev.riskReport,
              errorMessage: data.error_message,
            }));
          }
        })
        .catch(() => {});
      es.close();
    };

    return () => es.close();
  }, [contractId]);

  const isRunning = state.status === 'loading' || state.status === 'running';
  const report = state.riskReport;

  return (
    <main style={{ padding: '32px 0 64px' }}>
      <div className="container">
        {/* Header */}
        <div style={{ marginBottom: 32, display: 'flex', alignItems: 'flex-start',
          justifyContent: 'space-between', flexWrap: 'wrap', gap: 16 }}>
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 8 }}>
              <a href="/" style={{ color: 'var(--color-text-muted)', fontSize: 13,
                textDecoration: 'none', display: 'flex', alignItems: 'center', gap: 4 }}>
                ← Back
              </a>
              <span style={{ color: 'var(--color-text-muted)' }}>/</span>
              <span style={{ fontSize: 13, color: 'var(--color-text-secondary)' }}>
                Contract Analysis
              </span>
            </div>
            <h1 style={{ fontSize: 22, fontWeight: 700 }}>
              {isRunning ? (
                <span className="text-gradient">Analysing contract…</span>
              ) : state.status === 'escalated' ? (
                <span className="text-gradient-risk">Review Required</span>
              ) : state.status === 'failed' ? (
                <span style={{ color: '#ef4444' }}>Analysis Failed</span>
              ) : (
                <span className="text-gradient">Analysis Complete</span>
              )}
            </h1>
            <p style={{ fontSize: 12, fontFamily: "'JetBrains Mono', monospace",
              color: 'var(--color-text-muted)', marginTop: 4 }}>
              ID: {contractId}
            </p>
          </div>

          {/* Status badge */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <span style={{
              fontSize: 11, fontWeight: 600, padding: '6px 14px', borderRadius: 99,
              textTransform: 'uppercase', letterSpacing: '0.08em',
              background: isRunning ? 'rgba(173,198,255,0.15)'
                : state.status === 'escalated' ? 'rgba(255,180,171,0.15)'
                : state.status === 'failed' ? 'rgba(255,180,171,0.15)'
                : 'rgba(16,185,129,0.15)',
              color: isRunning ? 'var(--color-indigo-2)'
                : state.status === 'escalated' || state.status === 'failed' ? 'var(--color-risk-critical)'
                : 'var(--color-risk-low)',
              border: `1px solid ${isRunning ? 'rgba(173,198,255,0.3)'
                : state.status === 'escalated' || state.status === 'failed' ? 'rgba(255,180,171,0.3)'
                : 'rgba(16,185,129,0.3)'}`,
            }}>
              {isRunning && <span style={{ display: 'inline-block', width: 6, height: 6,
                borderRadius: '50%', background: 'currentColor', marginRight: 6,
                animation: 'pulse-dot 1.4s infinite' }} />}
              {state.status}
            </span>
          </div>
        </div>

        {/* Main grid */}
        <div style={{ display: 'grid', gridTemplateColumns: '300px 1fr', gap: 20, alignItems: 'start' }}>
          {/* Left column */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
            {/* Graph progress */}
            <GraphProgress
              currentNode={state.currentNode}
              completedNodes={state.completedNodes}
              riskScore={state.riskScore}
            />

            {/* Risk gauge */}
            {(state.riskScore !== null || !isRunning) && (
              <div className="glass-card animate-in">
                <div style={{ marginBottom: 16, fontSize: 13, fontWeight: 600,
                  color: 'var(--color-text-secondary)', textTransform: 'uppercase',
                  letterSpacing: '0.08em' }}>
                  Risk Score
                </div>
                <RiskGauge score={state.riskScore} level={report?.risk_level} />
                {report && (
                  <div style={{ marginTop: 16, paddingTop: 14, borderTop: '1px solid var(--color-border)',
                    fontSize: 11, color: 'var(--color-text-muted)', display: 'flex', flexDirection: 'column', gap: 4 }}>
                    <div>Coverage: {report.clause_coverage_score !== undefined
                      ? `${(report.clause_coverage_score * 100).toFixed(0)}%` : '—'}</div>
                    <div>Factors: {report.risk_factors?.length ?? 0}</div>
                    <div>Actions: {report.recommended_actions?.length ?? 0}</div>
                  </div>
                )}
              </div>
            )}
          </div>

          {/* Right column */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
            {/* Escalation banner (shown before report) */}
            {state.status === 'escalated' && report && (
              <EscalationBanner
                contractId={contractId}
                riskScore={state.riskScore ?? report.risk_score}
                escalationReason={report.escalation_reason}
                onResumed={() => setState((prev) => ({ ...prev, status: 'completed' }))}
              />
            )}

            {/* Error state */}
            {state.status === 'failed' && (
              <div className="glass-card" style={{ borderColor: 'rgba(255,180,171,0.3)',
                background: 'rgba(255,180,171,0.05)' }}>
                <div style={{ fontSize: 14, fontWeight: 600, color: '#ba1a1a', marginBottom: 8 }}>
                  Analysis Failed
                </div>
                <div style={{ fontSize: 13, color: 'var(--color-text-secondary)' }}>
                  {state.errorMessage || 'An unexpected error occurred.'}
                </div>
                <a href="/" className="btn btn-ghost" style={{ marginTop: 16, fontSize: 13 }}>
                  Try Again
                </a>
              </div>
            )}

            {/* Running skeleton */}
            {isRunning && (
              <div className="glass-card animate-in">
                <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--color-text-secondary)',
                  textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 16 }}>
                  Risk Factors
                </div>
                {[100, 80, 90, 70].map((w, i) => (
                  <div key={i} style={{ marginBottom: 10 }}>
                    <div className="skeleton" style={{ height: 44, borderRadius: 8, width: `${w}%` }} />
                  </div>
                ))}
              </div>
            )}

            {/* Risk report */}
            {report && (
              <>
                {/* Tab nav */}
                <div style={{ display: 'flex', gap: 4, background: 'rgba(0,0,0,0.04)',
                  borderRadius: 10, padding: 4 }}>
                  {(['risks', 'actions'] as const).map((tab) => (
                    <button key={tab} id={`tab-${tab}`} onClick={() => setActiveTab(tab)}
                      style={{
                        flex: 1, padding: '8px', borderRadius: 7, border: 'none',
                        cursor: 'pointer', fontSize: 13, fontWeight: 500, transition: 'all 0.2s',
                        background: activeTab === tab ? 'rgba(173,198,255,0.15)' : 'transparent',
                        color: activeTab === tab ? 'var(--color-indigo)' : 'var(--color-text-muted)',
                      }}>
                      {tab === 'risks'
                        ? `⚠️ Risk Factors (${report.risk_factors?.length ?? 0})`
                        : `✅ Actions (${report.recommended_actions?.length ?? 0})`}
                    </button>
                  ))}
                </div>

                {/* Risk factors tab */}
                {activeTab === 'risks' && (
                  <div className="glass-card animate-in">
                    <ClauseTable riskFactors={report.risk_factors ?? []} />
                  </div>
                )}

                {/* Recommended actions tab */}
                {activeTab === 'actions' && (
                  <div className="glass-card animate-in">
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                      {(report.recommended_actions ?? []).map((action: any, i: number) => (
                        <div key={i} id={`action-${i}`} style={{
                          padding: '14px 16px', background: 'rgba(0,0,0,0.02)',
                          borderRadius: 10, border: '1px solid var(--color-border)',
                        }}>
                          <div style={{ display: 'flex', alignItems: 'flex-start',
                            gap: 12, marginBottom: action.suggested_language ? 10 : 0 }}>
                            <span className={`badge badge-${
                              action.priority === 'immediate' ? 'critical'
                              : action.priority === 'before_signing' ? 'high' : 'low'
                            }`} style={{ flexShrink: 0, marginTop: 1 }}>
                              {action.priority?.replace('_', ' ')}
                            </span>
                            <div>
                              <div style={{ fontSize: 13, fontWeight: 500, marginBottom: 4 }}>
                                {action.action}
                              </div>
                              <div style={{ fontSize: 11, color: 'var(--color-text-muted)' }}>
                                {action.target_clause}
                              </div>
                            </div>
                          </div>
                          {action.suggested_language && (
                            <div style={{ background: 'rgba(173,198,255,0.06)',
                              borderLeft: '3px solid var(--color-indigo)',
                              borderRadius: '0 6px 6px 0', padding: '8px 12px',
                              fontSize: 12, fontFamily: "'JetBrains Mono', monospace",
                              color: 'var(--color-text-secondary)', lineHeight: 1.7 }}>
                              {action.suggested_language}
                            </div>
                          )}
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </>
            )}
          </div>
        </div>
      </div>
    </main>
  );
}
