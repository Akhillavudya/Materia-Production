import './Landing.css'
import Logo, { LogoMark } from '../../components/Logo'

const FEATURES = [
  { icon: '🔍', title: 'Search materials', body: 'Find candidates across Materials Project, C2DB and OQMD by formula, elements, band gap or dimensionality — ranked and returned in seconds.' },
  { icon: '🧊', title: 'Build & edit crystals', body: 'Cut slabs, build supercells, add vacancies, substitutions, interstitials and adsorbates, or generate random-alloy SQS — all from a sentence.' },
  { icon: '⚙️', title: 'Generate VASP inputs', body: 'Turn any structure into a ready-to-run input set — POSCAR, INCAR, KPOINTS, POTCAR — built automatically, with no hand-editing.' },
  { icon: '🔬', title: 'Optimize structures', body: 'Relax a crystal to its most stable arrangement with machine-learning potentials, as a background job while you keep chatting.' },
  { icon: '⚡', title: 'Run molecular dynamics', body: 'Launch MD simulations to watch how atoms move and behave over time — a virtual experiment, delivered as results.' },
  { icon: '📊', title: 'Compute properties', body: 'Get elastic moduli, phonon spectra and ion-migration (NEB) barriers — advanced analyses that once took days, now on demand.' },
]

const STEPS = [
  { n: '1', title: 'Describe your goal', body: 'Type your research question in plain language. No scripts, no config files, no command-line flags to memorize.' },
  { n: '2', title: 'Materia does the work', body: 'It searches databases, builds inputs, and runs simulations as tracked jobs — streaming progress back to you live.' },
  { n: '3', title: 'Get results instantly', body: 'Structures, simulation-ready files, and reports arrive directly in the conversation, ready to download.' },
]

const AUDIENCE = [
  { icon: '🎓', title: 'Academics', body: 'Run real simulations without years of expert software setup behind you.' },
  { icon: '🧪', title: 'Industries', body: 'Accelerate materials discovery without growing the team or the tooling overhead.' },
  { icon: '🛠️', title: 'Materials engineers', body: 'Prototype and screen new materials computationally before committing to physical tests.' },
]

export default function Landing({ onGetStarted, onLogin }) {
  return (
    <div className="lp">
      {/* ── nav ── */}
      <nav className="lp-nav">
        <div className="lp-wrap lp-nav-inner">
          <Logo size={34} />
          <div className="lp-nav-links">
            <a href="#features">Features</a>
            <a href="#how">How it works</a>
            <a href="#who">For researchers</a>
          </div>
          <div className="lp-nav-cta">
            <button className="lp-linkbtn" onClick={onLogin}>Log in</button>
            <button className="lp-btn lp-btn-primary" onClick={onGetStarted}>
              Try Materia →
            </button>
          </div>
        </div>
      </nav>

      {/* ── hero ── */}
      <header className="lp-hero">
        <div className="lp-wrap lp-hero-grid">
          <div>
            <span className="lp-pill"><span className="lp-pill-dot" />AI research partner for materials science</span>
            <h1 className="lp-h1">
              Discover, simulate,<br />and analyze materials —<br /><span className="grad">just by chatting.</span>
            </h1>
            <p className="lp-sub">
              Materia turns expert-only computational materials workflows into a simple conversation.
            </p>
            <div className="lp-hero-actions">
              <button className="lp-btn lp-btn-primary lp-btn-lg" onClick={onGetStarted}>
                Start researching →
              </button>
              <button className="lp-btn lp-btn-ghost lp-btn-lg" onClick={onLogin}>
                Log in
              </button>
            </div>
            <p className="lp-hero-note">Free to start · Powered by Gemini · No setup required</p>
          </div>

          {/* chat mock */}
          <div className="lp-mock">
            <div className="lp-mock-bar">
              <span className="lp-dot" style={{ background: '#ff5f57' }} />
              <span className="lp-dot" style={{ background: '#febc2e' }} />
              <span className="lp-dot" style={{ background: '#28c840' }} />
              <span className="lp-mock-title">Materia · new chat</span>
            </div>
            <div className="lp-mock-body">
              <div className="lp-bubble lp-bubble-user">
                Find a 2D semiconductor with a band gap between 1 and 2 eV.
              </div>
              <div className="lp-bubble lp-bubble-ai">
                Found <b>3 candidates</b> in C2DB. Top match: <b>MoS₂</b> — 2D hexagonal, direct band gap 1.8 eV.
                <div className="lp-chip-row">
                  <span className="lp-chip">View structure</span>
                  <span className="lp-chip">Generate VASP inputs</span>
                </div>
              </div>
              <div className="lp-bubble lp-bubble-user">Relax the structure and run it.</div>
              <div className="lp-bubble lp-bubble-ai">
                <span className="lp-typing"><span /><span /><span /></span> Optimizing structure — job queued…
              </div>
            </div>
          </div>
        </div>
      </header>

      {/* ── trust bar ── */}
      <section className="lp-trust">
        <div className="lp-wrap lp-trust-inner">
          <span className="lp-trust-label">Searches across</span>
          <span className="lp-trust-item">Materials Project</span>
          <span className="lp-trust-sep" />
          <span className="lp-trust-item">C2DB</span>
          <span className="lp-trust-sep" />
          <span className="lp-trust-item">OQMD</span>
        </div>
      </section>

      {/* ── features ── */}
      <section className="lp-section" id="features">
        <div className="lp-wrap">
          <div className="lp-eyebrow">Capabilities</div>
          <h2 className="lp-h2">Everything a computational lab does. In one conversation.</h2>
          <p className="lp-lede">
            A full suite of materials tools, orchestrated by an AI agent that decides what to run and when — so you focus on the science, not the software.
          </p>
          <div className="lp-cards">
            {FEATURES.map(f => (
              <div className="lp-card" key={f.title}>
                <div className="lp-card-ico">{f.icon}</div>
                <h3>{f.title}</h3>
                <p>{f.body}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── how it works ── */}
      <section className="lp-section lp-section-soft" id="how">
        <div className="lp-wrap">
          <div className="lp-eyebrow">How it works</div>
          <h2 className="lp-h2">Research in three steps.</h2>
          <p className="lp-lede">From question to simulation-ready results — no terminal, no boilerplate.</p>
          <div className="lp-steps">
            {STEPS.map(s => (
              <div className="lp-step" key={s.n}>
                <div className="lp-step-num">{s.n}</div>
                <h3>{s.title}</h3>
                <p>{s.body}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── audience ── */}
      <section className="lp-section" id="who">
        <div className="lp-wrap">
          <div className="lp-eyebrow">Who it's for</div>
          <h2 className="lp-h2">Built for serious researchers.</h2>
          <p className="lp-lede">Whether you're starting out or running a lab, Materia removes the setup tax on computational work.</p>
          <div className="lp-aud">
            {AUDIENCE.map(a => (
              <div className="lp-aud-card" key={a.title}>
                <h3><span className="lp-aud-ico">{a.icon}</span>{a.title}</h3>
                <p>{a.body}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── final CTA ── */}
      <div className="lp-wrap">
        <section className="lp-cta">
          <h2>Start your next discovery today.</h2>
          <p>Create an account in seconds and run your first simulation from a single message.</p>
          <button className="lp-btn lp-btn-lg" onClick={onGetStarted}>Try Materia free →</button>
        </section>
      </div>

      {/* ── footer ── */}
      <footer className="lp-footer">
        <div className="lp-wrap">
          <div className="lp-footer-grid">
            <div>
              <Logo size={32} />
              <p className="lp-footer-blurb">
                The AI research partner for materials science. Discover, simulate, and analyze — just by chatting.
              </p>
            </div>
            <div>
              <h4>Product</h4>
              <ul>
                <li><a href="#features">Features</a></li>
                <li><a href="#how">How it works</a></li>
                <li><a href="#who">For researchers</a></li>
              </ul>
            </div>
            <div>
              <h4>Resources</h4>
              <ul>
                <li><a href="#features">Documentation</a></li>
                <li><a href="#features">Examples</a></li>
                <li><a href="#features">API</a></li>
              </ul>
            </div>
            <div>
              <h4>Get started</h4>
              <ul>
                <li><a onClick={onGetStarted} style={{ cursor: 'pointer' }}>Create account</a></li>
                <li><a onClick={onLogin} style={{ cursor: 'pointer' }}>Log in</a></li>
              </ul>
            </div>
          </div>
          <div className="lp-footer-bottom">
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}>
              <LogoMark size={20} radius={5} /> © cmclab
            </span>
            <span>Privacy · Terms</span>
          </div>
        </div>
      </footer>
    </div>
  )
}
