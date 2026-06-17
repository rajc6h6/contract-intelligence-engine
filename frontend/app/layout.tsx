import type { Metadata } from 'next';
import './globals.css';

export const metadata: Metadata = {
  title: 'Contract Intelligence Engine',
  description:
    'Autonomous legal-risk analyst for early-stage SaaS contracts. Powered by LangGraph, PydanticAI, and pgvector — without a lawyer in the loop.',
  keywords: ['contract analysis', 'legal AI', 'SaaS', 'risk scoring', 'LangGraph'],
  openGraph: {
    title: 'Contract Intelligence Engine',
    description: 'Upload a contract. Get a cited risk report in minutes.',
    type: 'website',
  },
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
        <link
          href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&family=JetBrains+Mono:wght@400;500&display=swap"
          rel="stylesheet"
        />
      </head>
      <body>
        <div className="page-wrapper">
          <nav className="nav">
            <div className="container nav-inner">
              <a href="/" className="nav-brand">
                <svg width="22" height="22" viewBox="0 0 22 22" fill="none" aria-hidden="true">
                  <path d="M11 2L3 6V11C3 15.4 6.4 19.5 11 20.9C15.6 19.5 19 15.4 19 11V6L11 2Z"
                    stroke="var(--color-indigo-2)" strokeWidth="1.5" strokeLinejoin="round" />
                  <path d="M8 11L10.5 13.5L14.5 9" stroke="var(--color-indigo-2)" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
                Contract Intelligence
              </a>
              <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                <span className="nav-badge">v0.1.0-alpha</span>
                <a
                  href="https://github.com"
                  className="btn btn-ghost"
                  style={{ padding: '6px 12px', fontSize: 13 }}
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  GitHub
                </a>
              </div>
            </div>
          </nav>
          {children}
        </div>
      </body>
    </html>
  );
}
