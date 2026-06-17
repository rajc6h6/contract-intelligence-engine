'use client';

import { useState } from 'react';

interface Props {
  contractId: string;
  riskScore: number;
  escalationReason?: string;
  onResumed: () => void;
}

const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL || 'http://localhost:8000';

export default function EscalationBanner({ contractId, riskScore, escalationReason, onResumed }: Props) {
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [notes, setNotes] = useState('');
  const [done, setDone] = useState(false);

  const handleDecision = async (approved: boolean) => {
    setIsSubmitting(true);
    try {
      const res = await fetch(`${BACKEND_URL}/contracts/${contractId}/resume`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ approved, reviewer_notes: notes }),
      });
      if (!res.ok) throw new Error(`API error ${res.status}`);
      setDone(true);
      onResumed();
    } catch (err) {
      alert(`Failed to submit decision: ${err instanceof Error ? err.message : 'Unknown error'}`);
    } finally {
      setIsSubmitting(false);
    }
  };

  if (done) {
    return (
      <div className="card animate-in" style={{
        background: 'rgba(16,185,129,0.06)', border: '1px solid rgba(16,185,129,0.25)',
        borderRadius: 16, padding: '20px 24px',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" aria-hidden="true">
            <circle cx="12" cy="12" r="10" stroke="#10b981" strokeWidth="1.5" />
            <path d="M8 12L11 15L16 9" stroke="#10b981" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
          <span style={{ fontSize: 14, fontWeight: 500, color: '#34d399' }}>
            Decision submitted — graph resumed
          </span>
        </div>
      </div>
    );
  }

  return (
    <div className="escalation-banner animate-in" id="escalation-review-panel">
      {/* Header */}
      <div className="escalation-banner-header">
        <span className="escalation-pulse" />
        <div>
          <h3 style={{ fontSize: 15, fontWeight: 700, color: '#ba1a1a', marginBottom: 2 }}>
            Human Review Required
          </h3>
          <p style={{ fontSize: 12, color: 'rgba(186,26,26,0.8)' }}>
            Risk score <strong>{riskScore}/100</strong> exceeded escalation threshold.
            LangGraph graph is paused at <code className="code">interrupt_before=[&quot;escalate&quot;]</code>
          </p>
        </div>
        <div style={{ marginLeft: 'auto', textAlign: 'right' }}>
          <div style={{ fontSize: 2.5 + 'rem', fontWeight: 800, color: '#ba1a1a', lineHeight: 1 }}>
            {riskScore}
          </div>
          <div style={{ fontSize: 10, color: 'rgba(186,26,26,0.6)', textTransform: 'uppercase',
            letterSpacing: '0.08em' }}>Risk Score</div>
        </div>
      </div>

      {/* Escalation reason */}
      {escalationReason && (
        <div style={{ background: 'rgba(186,26,26,0.06)', borderRadius: 8, padding: '10px 14px',
          fontSize: 13, color: '#ba1a1a', marginBottom: 16, lineHeight: 1.6,
          borderLeft: '3px solid rgba(186,26,26,0.4)' }}>
          {escalationReason}
        </div>
      )}

      {/* Reviewer notes */}
      <div style={{ marginBottom: 16 }}>
        <label htmlFor="reviewer-notes" style={{ fontSize: 12, fontWeight: 500,
          color: 'rgba(186,26,26,0.8)', display: 'block', marginBottom: 6 }}>
          Reviewer Notes (optional)
        </label>
        <textarea
          id="reviewer-notes"
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          placeholder="Add notes about your review decision…"
          rows={3}
          style={{
            width: '100%', background: 'rgba(0,0,0,0.05)',
            border: '1px solid rgba(186,26,26,0.2)', borderRadius: 8,
            color: 'var(--color-text-primary)', fontSize: 13, padding: 12,
            fontFamily: 'Inter, sans-serif', resize: 'vertical', outline: 'none',
          }}
          disabled={isSubmitting}
        />
      </div>

      {/* Action buttons */}
      <div style={{ display: 'flex', gap: 10 }}>
        <button
          id="escalation-approve-btn"
          className="btn"
          onClick={() => handleDecision(true)}
          disabled={isSubmitting}
          style={{
            flex: 1, justifyContent: 'center',
            background: 'rgba(16,185,129,0.15)', border: '1px solid rgba(16,185,129,0.35)',
            color: '#34d399', fontWeight: 600,
          }}
        >
          {isSubmitting ? 'Submitting…' : (
            <>
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                <path d="M20 6L9 17L4 12" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
              Approve & Resume
            </>
          )}
        </button>
        <button
          id="escalation-reject-btn"
          className="btn btn-danger"
          onClick={() => handleDecision(false)}
          disabled={isSubmitting}
          style={{ flex: 1, justifyContent: 'center' }}
        >
          <>
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" aria-hidden="true">
              <path d="M18 6L6 18M6 6L18 18" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
            </svg>
            Reject Contract
          </>
        </button>
      </div>

      <p style={{ marginTop: 12, fontSize: 11, color: 'rgba(186,26,26,0.5)', textAlign: 'center' }}>
        Resuming will continue the LangGraph graph from the escalate checkpoint (AsyncPostgresSaver)
      </p>
    </div>
  );
}
