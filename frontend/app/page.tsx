'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import ContractUploader from '@/components/ContractUploader';

const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL || 'http://localhost:8000';

const STATS = [
  { value: '510', label: 'CUAD clauses indexed' },
  { value: '41', label: 'Clause types' },
  { value: '768-dim', label: 'pgvector embeddings' },
  { value: '<5%', label: 'Hallucination threshold' },
];

const TECH_STACK = [
  { name: 'LangGraph', desc: 'Durable orchestration' },
  { name: 'PydanticAI', desc: 'Typed LLM outputs' },
  { name: 'FastMCP', desc: 'Decoupled tool server' },
  { name: 'pgvector', desc: 'Semantic clause search' },
  { name: 'Logfire', desc: 'Distributed tracing' },
  { name: 'Rust', desc: 'Clause deduplication' },
];

export default function HomePage() {
  const router = useRouter();
  const [isAnalysing, setIsAnalysing] = useState(false);

  const handleUpload = async (text: string, filename: string) => {
    setIsAnalysing(true);
    try {
      const res = await fetch(`${BACKEND_URL}/contracts/text`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ contract_text: text, filename }),
      });
      if (!res.ok) throw new Error(`API error ${res.status}: ${await res.text()}`);
      const data = await res.json();
      router.push(`/contracts/${data.contract_id}`);
    } catch (err) {
      console.error('Upload failed:', err);
      setIsAnalysing(false);
      alert(`Upload failed: ${err instanceof Error ? err.message : 'Unknown error'}`);
    }
  };

  const handleUploadFile = async (file: File) => {
    setIsAnalysing(true);
    try {
      const formData = new FormData();
      formData.append('file', file);
      const res = await fetch(`${BACKEND_URL}/contracts`, {
        method: 'POST',
        body: formData,
      });
      if (!res.ok) throw new Error(`API error ${res.status}: ${await res.text()}`);
      const data = await res.json();
      router.push(`/contracts/${data.contract_id}`);
    } catch (err) {
      console.error('PDF upload failed:', err);
      setIsAnalysing(false);
      alert(`Upload failed: ${err instanceof Error ? err.message : 'Unknown error'}`);
    }
  };

  return (
    <main>
      {/* ── Hero ─────────────────────────────────────────────── */}
      <section style={{ padding: '96px 0 64px', position: 'relative' }}>
        {/* Glow effect behind hero */}
        <div style={{ position: 'absolute', top: -100, left: '50%', transform: 'translateX(-50%)', 
          width: 600, height: 400, background: 'radial-gradient(ellipse at center, rgba(137, 206, 255, 0.15) 0%, transparent 70%)', 
          filter: 'blur(60px)', zIndex: 0, pointerEvents: 'none' }} />
          
        <div className="container" style={{ textAlign: 'center', maxWidth: 860, margin: '0 auto', position: 'relative', zIndex: 1 }}>
          <div style={{ marginBottom: 24, display: 'inline-flex', alignItems: 'center', gap: 10,
            background: 'rgba(137, 206, 255, 0.1)', border: '1px solid rgba(137, 206, 255, 0.25)',
            borderRadius: 99, padding: '8px 20px', fontSize: 13, color: 'var(--color-indigo)', fontWeight: 600, letterSpacing: '0.05em' }}>
            <span style={{ width: 8, height: 8, borderRadius: '50%', background: 'var(--color-indigo)',
              animation: 'pulse-dot 1.4s infinite', flexShrink: 0, boxShadow: '0 0 10px var(--color-indigo)' }} />
            Powered by Gemini · LangGraph · pgvector
          </div>

          <h1 style={{ fontSize: 'clamp(2.2rem, 5vw, 3.6rem)', fontWeight: 800, lineHeight: 1.15,
            marginBottom: 20 }}>
            <span className="text-gradient">Contract Intelligence</span>
            <br />
            <span style={{ color: 'var(--color-text-secondary)', fontWeight: 300, fontSize: '0.65em' }}>
              Autonomous legal-risk analyst for early-stage SaaS contracts
            </span>
          </h1>

          <p style={{ fontSize: 16, color: 'var(--color-text-secondary)', lineHeight: 1.8,
            maxWidth: 580, margin: '0 auto 40px' }}>
            Upload a contract. A LangGraph pipeline extracts clauses, searches 500+ CUAD precedents
            via pgvector, and delivers a cited risk report — no lawyer required.
          </p>

          {/* Stats bar */}
          <div style={{ display: 'flex', justifyContent: 'center', gap: 16,
            flexWrap: 'wrap', marginBottom: 64 }}>
            {STATS.map((s) => (
              <div key={s.label} className="glass-card"
                style={{ padding: '16px 24px', textAlign: 'center', minWidth: 160, display: 'flex', flexDirection: 'column', justifyContent: 'center' }}>
                <div style={{ fontSize: 24, fontWeight: 700, color: 'var(--color-indigo)' }}>{s.value}</div>
                <div style={{ fontSize: 12, color: 'var(--color-text-muted)', textTransform: 'uppercase',
                  letterSpacing: '0.08em', marginTop: 4, fontFamily: 'Geist, monospace' }}>{s.label}</div>
              </div>
            ))}
          </div>
        </div>

        {/* Upload zone */}
        <div className="container" style={{ maxWidth: 760, margin: '0 auto' }}>
          <ContractUploader onUpload={handleUpload} onUploadFile={handleUploadFile} isLoading={isAnalysing} />
        </div>
      </section>

      {/* ── Architecture signal strip ─────────────────────────── */}
      <section style={{ padding: '32px 0 80px' }}>
        <div className="container">
          <p style={{ textAlign: 'center', fontSize: 12, color: 'var(--color-text-muted)',
            textTransform: 'uppercase', letterSpacing: '0.15em', marginBottom: 24, fontFamily: 'Geist, monospace' }}>
            Architecture Overview
          </p>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 12, justifyContent: 'center', maxWidth: 900, margin: '0 auto' }}>
            {TECH_STACK.map((t) => (
              <div key={t.name} className="glass-card" style={{ padding: '12px 20px',
                display: 'flex', alignItems: 'center', gap: 12, background: 'rgba(30, 41, 59, 0.6)' }}>
                <span style={{ fontSize: 14, fontWeight: 600, color: 'var(--color-indigo)' }}>
                  {t.name}
                </span>
                <span style={{ width: 1, height: 16, background: 'rgba(255,255,255,0.1)' }} />
                <span style={{ fontSize: 13, color: 'var(--color-text-secondary)' }}>
                  {t.desc}
                </span>
              </div>
            ))}
          </div>

          {/* Pipeline diagram */}
          <div style={{ marginTop: 40, display: 'flex', alignItems: 'center',
            justifyContent: 'center', gap: 8, flexWrap: 'wrap' }}>
            {['PDF / Text Input', 'Clause Extractor', 'Precedent Retriever', 'Risk Scorer', 'Risk Report'].map((step, i, arr) => (
              <div key={step} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <div className="glass-card" style={{ padding: '8px 14px', fontSize: 12,
                  fontWeight: 500, color: i === 0 || i === arr.length - 1
                    ? 'var(--color-text-primary)' : 'var(--color-indigo-2)',
                  borderColor: i === 0 || i === arr.length - 1
                    ? 'rgba(0,0,0,0.1)' : 'rgba(79,70,229,0.3)' }}>
                  {step}
                </div>
                {i < arr.length - 1 && (
                  <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true">
                    <path d="M6 3L11 8L6 13" stroke="rgba(0,0,0,0.2)" strokeWidth="1.5"
                      strokeLinecap="round" strokeLinejoin="round" />
                  </svg>
                )}
              </div>
            ))}
          </div>
        </div>
      </section>
    </main>
  );
}
