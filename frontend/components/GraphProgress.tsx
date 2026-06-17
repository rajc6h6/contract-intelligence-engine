'use client';

interface NodeConfig {
  id: string;
  label: string;
  sublabel: string;
}

const NODES: NodeConfig[] = [
  { id: 'clause_extractor',     label: 'Clause Extractor',     sublabel: 'PydanticAI · Gemini 2.0 Flash' },
  { id: 'precedent_retriever',  label: 'Precedent Retriever',  sublabel: 'MCP Client → pgvector cosine search' },
  { id: 'risk_scorer',          label: 'Risk Scorer',          sublabel: 'PydanticAI · conditional routing' },
  { id: 'auto_approve',         label: 'Auto-Approved',        sublabel: 'Score < 40 · no human review needed' },
  { id: 'escalate',             label: 'Escalation Review',    sublabel: 'Score ≥ 40 · interrupt_before triggered' },
];

type NodeStatus = 'idle' | 'active' | 'done' | 'error';

interface Props {
  currentNode: string | null;
  completedNodes: string[];
  errorNodes?: string[];
  riskScore?: number | null;
}

function getNodeStatus(
  nodeId: string,
  currentNode: string | null,
  completedNodes: string[],
  errorNodes: string[],
): NodeStatus {
  if (errorNodes.includes(nodeId)) return 'error';
  if (completedNodes.includes(nodeId)) return 'done';
  if (currentNode === nodeId) return 'active';
  return 'idle';
}

function NodeIcon({ status }: { status: NodeStatus }) {
  if (status === 'done') {
    return (
      <svg width="14" height="14" viewBox="0 0 14 14" fill="none" aria-hidden="true">
        <circle cx="7" cy="7" r="6" fill="rgba(13,148,136,0.3)" />
        <path d="M4.5 7L6.5 9L9.5 5.5" stroke="#0d9488" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    );
  }
  if (status === 'error') {
    return (
      <svg width="14" height="14" viewBox="0 0 14 14" fill="none" aria-hidden="true">
        <circle cx="7" cy="7" r="6" fill="rgba(186,26,26,0.3)" />
        <path d="M5 5L9 9M9 5L5 9" stroke="#ba1a1a" strokeWidth="1.5" strokeLinecap="round" />
      </svg>
    );
  }
  return <span className="node-dot" />;
}

export default function GraphProgress({ currentNode, completedNodes, errorNodes = [], riskScore }: Props) {
  const visibleNodes = NODES.filter((n) => {
    // Only show terminal nodes if they are active or complete
    if (n.id === 'auto_approve' || n.id === 'escalate') {
      return currentNode === n.id || completedNodes.includes(n.id) || errorNodes.includes(n.id);
    }
    return true;
  });

  return (
    <div className="card animate-in">
      <div style={{ marginBottom: 16, display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <h3 style={{ fontSize: 13, fontWeight: 600, color: 'var(--color-text-secondary)',
          textTransform: 'uppercase', letterSpacing: '0.08em' }}>
          LangGraph Pipeline
        </h3>
        {riskScore !== null && riskScore !== undefined && (
          <span style={{ fontSize: 12, fontFamily: "'JetBrains Mono', monospace",
            color: riskScore >= 70 ? '#ba1a1a' : riskScore >= 40 ? '#ea580c' : '#0d9488',
            fontWeight: 600 }}>
            Score: {riskScore}
          </span>
        )}
      </div>

      <div className="graph-progress" role="list" aria-label="Analysis pipeline progress">
        {visibleNodes.map((node, i) => {
          const status = getNodeStatus(node.id, currentNode, completedNodes, errorNodes);
          const isLast = i === visibleNodes.length - 1;

          return (
            <div key={node.id} role="listitem">
              <div className={`graph-node ${status}`} id={`graph-node-${node.id}`}>
                <NodeIcon status={status} />
                <div style={{ flex: 1 }}>
                  <div className="node-label">{node.label}</div>
                  <div className="node-sublabel">{node.sublabel}</div>
                </div>
                {status === 'active' && (
                  <span style={{ fontSize: 10, color: 'var(--color-indigo-2)', fontWeight: 500,
                    background: 'rgba(79,70,229,0.15)', padding: '2px 8px', borderRadius: 99 }}>
                    RUNNING
                  </span>
                )}
              </div>
              {!isLast && <div className="node-connector" />}
            </div>
          );
        })}
      </div>

      {/* Legend */}
      <div style={{ marginTop: 16, paddingTop: 12, borderTop: '1px solid var(--color-border)',
        display: 'flex', gap: 16, flexWrap: 'wrap' }}>
        {[
          { color: 'rgba(0,0,0,0.15)', label: 'Pending' },
          { color: 'var(--color-indigo-2)', label: 'Running' },
          { color: '#0d9488', label: 'Complete' },
          { color: '#ba1a1a', label: 'Error' },
        ].map((l) => (
          <div key={l.label} style={{ display: 'flex', alignItems: 'center', gap: 6,
            fontSize: 11, color: 'var(--color-text-muted)' }}>
            <span style={{ width: 8, height: 8, borderRadius: '50%', background: l.color,
              flexShrink: 0 }} />
            {l.label}
          </div>
        ))}
      </div>
    </div>
  );
}
