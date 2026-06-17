'use client';

import { useCallback, useState } from 'react';

interface Props {
  onUpload: (text: string, filename: string) => void;
  onUploadFile: (file: File) => void;
  isLoading: boolean;
}

const SAMPLE_CONTRACT = `SOFTWARE AS A SERVICE AGREEMENT

This SaaS Agreement ("Agreement") is entered into between TechVendor Inc. ("Vendor") and your company ("Client").

1. SERVICES: Vendor will provide cloud-based software services as described in the applicable order form.

2. LIMITATION OF LIABILITY: IN NO EVENT SHALL EITHER PARTY'S AGGREGATE LIABILITY EXCEED THE GREATER OF (A) FEES PAID IN THE PRIOR 12 MONTHS OR (B) $500,000. NEITHER PARTY SHALL BE LIABLE FOR CONSEQUENTIAL, INCIDENTAL, OR SPECIAL DAMAGES.

3. INTELLECTUAL PROPERTY: Vendor retains all intellectual property rights in the Software. Client owns all data uploaded to the platform.

4. INDEMNIFICATION: Vendor shall indemnify Client against third-party claims alleging the Software infringes intellectual property rights. Client shall indemnify Vendor against claims arising from Client's data or use.

5. TERM AND RENEWAL: Initial term of 12 months. This Agreement automatically renews for successive 12-month periods unless either party provides written notice of non-renewal at least 60 days prior to term end.

6. GOVERNING LAW: This Agreement shall be governed by the laws of the State of Delaware.

7. CONFIDENTIALITY: Each party agrees to maintain the confidentiality of the other's Confidential Information for 3 years following disclosure.`;

export default function ContractUploader({ onUpload, onUploadFile, isLoading }: Props) {
  const [dragOver, setDragOver] = useState(false);
  const [inputMode, setInputMode] = useState<'file' | 'text'>('file');
  const [contractText, setContractText] = useState('');
  const [fileName, setFileName] = useState('');

  const processFile = useCallback(async (file: File) => {
    setFileName(file.name);
    if (file.type === 'application/pdf' || file.name.endsWith('.pdf')) {
      // Send PDF as binary multipart — backend parses with pypdf
      onUploadFile(file);
    } else {
      const text = await file.text();
      if (text.trim()) onUpload(text, file.name);
      else alert('Could not read file text. Paste text directly instead.');
    }
  }, [onUpload, onUploadFile]);

  const onDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(false);
    const file = e.dataTransfer.files[0];
    if (file) processFile(file);
  }, [processFile]);

  const onFileInput = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) processFile(file);
  };

  const handleTextSubmit = () => {
    if (contractText.trim().length < 100) {
      alert('Contract text is too short (minimum 100 characters).');
      return;
    }
    onUpload(contractText.trim(), fileName || 'text-input.txt');
  };

  const loadSample = () => {
    setContractText(SAMPLE_CONTRACT);
    setInputMode('text');
    setFileName('sample-saas-agreement.txt');
  };

  return (
    <div className="card card-glow animate-in">
      {/* Mode toggle */}
      <div style={{ display: 'flex', gap: 4, marginBottom: 20,
        background: 'rgba(0,0,0,0.04)', borderRadius: 10, padding: 4 }}>
        {(['file', 'text'] as const).map((mode) => (
          <button
            key={mode}
            id={`upload-mode-${mode}`}
            onClick={() => setInputMode(mode)}
            style={{
              flex: 1, padding: '8px', borderRadius: 7, border: 'none', cursor: 'pointer',
              fontSize: 13, fontWeight: 500, transition: 'all 0.2s',
              background: inputMode === mode ? 'rgba(79,70,229,0.15)' : 'transparent',
              color: inputMode === mode ? 'var(--color-indigo-2)' : 'var(--color-text-muted)',
            }}
          >
            {mode === 'file' ? '📄 Upload PDF / TXT' : '✏️ Paste Text'}
          </button>
        ))}
      </div>

      {inputMode === 'file' ? (
        <label htmlFor="contract-file-input">
          <div
            className={`upload-zone ${dragOver ? 'drag-over' : ''}`}
            onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
            onDragLeave={() => setDragOver(false)}
            onDrop={onDrop}
          >
            <div className="upload-icon">
              <svg width="28" height="28" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"
                  stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" />
                <polyline points="14 2 14 8 20 8" stroke="currentColor" strokeWidth="1.5"
                  strokeLinejoin="round" />
                <line x1="12" y1="18" x2="12" y2="12" stroke="currentColor" strokeWidth="1.5"
                  strokeLinecap="round" />
                <polyline points="9 15 12 12 15 15" stroke="currentColor" strokeWidth="1.5"
                  strokeLinejoin="round" />
              </svg>
            </div>
            <h2 style={{ fontSize: 17, fontWeight: 600, marginBottom: 8 }}>
              Drop your contract here
            </h2>
            <p style={{ fontSize: 13, color: 'var(--color-text-secondary)', marginBottom: 20 }}>
              PDF or plain text — up to 50 pages
            </p>
            <input
              id="contract-file-input"
              type="file"
              accept=".pdf,.txt,.doc,.docx"
              onChange={onFileInput}
              style={{ display: 'none' }}
              disabled={isLoading}
            />
            <span className="btn btn-ghost" style={{ pointerEvents: 'none' }}>
              Browse files
            </span>
          </div>
        </label>
      ) : (
        <div>
          <textarea
            id="contract-text-area"
            value={contractText}
            onChange={(e) => setContractText(e.target.value)}
            placeholder="Paste contract text here…"
            rows={12}
            style={{
              width: '100%', background: 'rgba(0,0,0,0.03)',
              border: '1px solid var(--color-border)', borderRadius: 10,
              color: 'var(--color-text-primary)', fontFamily: "'JetBrains Mono', monospace",
              fontSize: 12, lineHeight: 1.7, padding: 16, resize: 'vertical',
              outline: 'none', transition: 'border-color 0.2s',
            }}
            onFocus={(e) => { e.target.style.borderColor = 'rgba(79,70,229,0.5)'; }}
            onBlur={(e) => { e.target.style.borderColor = 'var(--color-border)'; }}
            disabled={isLoading}
          />
          <div style={{ marginTop: 8, fontSize: 12, color: 'var(--color-text-muted)',
            textAlign: 'right' }}>
            {contractText.length} characters
          </div>
        </div>
      )}

      {/* Action buttons */}
      <div style={{ marginTop: 20, display: 'flex', gap: 10, alignItems: 'center' }}>
        <button
          id="analyse-contract-btn"
          className="btn btn-primary"
          onClick={inputMode === 'text' ? handleTextSubmit : undefined}
          disabled={isLoading || (inputMode === 'text' && contractText.trim().length < 100)}
          style={{ flex: 1, justifyContent: 'center' }}
        >
          {isLoading ? (
            <>
              <span style={{ width: 14, height: 14, border: '2px solid rgba(0,0,0,0.3)',
                borderTopColor: 'var(--color-indigo)', borderRadius: '50%', animation: 'spin 0.8s linear infinite',
                display: 'inline-block' }} />
              Initialising Analysis…
            </>
          ) : (
            <>
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                <path d="M12 2L3 7L12 12L21 7L12 2Z" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" />
                <path d="M3 17L12 22L21 17" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" />
                <path d="M3 12L12 17L21 12" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" />
              </svg>
              Analyse Contract
            </>
          )}
        </button>
        <button
          id="load-sample-btn"
          className="btn btn-ghost"
          onClick={loadSample}
          disabled={isLoading}
        >
          Load Sample
        </button>
      </div>

      <style jsx>{`
        @keyframes spin { to { transform: rotate(360deg); } }
      `}</style>
    </div>
  );
}
