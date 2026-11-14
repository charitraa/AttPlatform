import '@fontsource/barlow-condensed/600.css'
import '@fontsource/barlow-condensed/700.css'
import './landing.css'
import { Link } from 'react-router-dom'
import { env } from '@/lib/env'

const STEPS = [
  { name: 'Received', note: 'by WhatsApp at 07:12' },
  { name: 'Sorted', note: 'Refrigeration, critical (AI)' },
  { name: 'Assigned', note: 'Tariq, 4 km away' },
  { name: 'On site', note: '08:03, photos attached' },
  { name: 'Signed off', note: 'Ramesh K., 5 stars' },
]

const JOURNEY = [
  { title: 'The customer gets in touch', body: 'By email, WhatsApp or your customer portal. Every message becomes a ticket with its own reference.' },
  { title: 'AI sorts it', body: 'It suggests the category, the priority and the right person, and says why. Your team accepts or changes it.' },
  { title: 'Dispatch sends someone', body: 'Technicians ranked by skills, distance and workload, booked into their day without double-booking.' },
  { title: 'The technician does the job', body: 'On their phone: directions, each step of the visit, before-and-after photos and the parts used.' },
  { title: 'The customer signs off', body: 'They confirm the fix and rate the visit. If the problem is back, they reopen it with a note.' },
]

const ROLES = [
  { who: 'Support desk', what: 'One queue for every channel, the full history of each customer, and suggested replies you can edit before sending.' },
  { who: 'Dispatch and operations', what: 'A weekly schedule per technician, suggestions for who should go, and every job’s status as it changes.' },
  { who: 'Technicians', what: 'Today’s jobs on the phone, most urgent first, with the address, the history and a button for each step.' },
  { who: 'Customers', what: 'Raise requests, follow progress, reply to your team and confirm the fix, without phoning to ask.' },
  { who: 'Managers', what: 'Response and resolution times against your targets, technician workload, customer ratings, exported to CSV.' },
  { who: 'Your other systems', what: 'Signed webhooks keep your ERP or billing in sync; emails to a support address turn into tickets.' },
]

const LOCAL = [
  { title: 'Your working week', body: 'Deadlines count only working hours, Sunday to Friday by default, in Nepal time, with your public holidays.' },
  { title: 'Messages people read', body: 'Notifications by WhatsApp and email, as well as in the app, each person choosing what they get.' },
  { title: 'Costs in rupees', body: 'Labour and parts on every completed job, ready for invoicing.' },
  { title: 'People stay in charge of AI', body: 'Every suggestion shows its reasoning and confidence. Nothing changes unless someone accepts it or you allow it.' },
  { title: 'Your server, your data', body: 'Runs on your own infrastructure. Credentials are encrypted and every change is in the audit log.' },
  { title: 'Built for the field', body: 'The technician view works on a phone in a basement plant room as well as it does at a desk.' },
]

function Check() {
  return (
    <svg viewBox="0 0 12 12" aria-hidden="true"><path d="M2 6.5 5 9.2 10 3" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" /></svg>
  )
}

function WorkOrder() {
  return (
    <figure className="lp-slip-stack" aria-label="Example work order: a cold room repair from first message to customer sign-off">
      <div className="lp-slip">
        <div className="lp-slip-head">
          <span className="lp-slip-title">Work order</span>
          <span className="lp-slip-ref">TCK-000046</span>
        </div>
        <dl>
          <div className="lp-field"><dt>Customer</dt><dd>Hotel Annapurna, Pokhara</dd></div>
          <div className="lp-field"><dt>Problem</dt><dd>Walk-in cold room at 9 °C and rising</dd></div>
        </dl>
        <ol className="lp-steps">
          {STEPS.map((s, i) => (
            <li key={s.name} className="lp-step" style={{ '--i': i } as React.CSSProperties}>
              <span className="lp-tick"><Check /></span>
              <span className="lp-step-name">{s.name}</span>
              <span className="lp-step-note">{s.note}</span>
            </li>
          ))}
        </ol>
        <div className="lp-sla">
          Resolved in 1 h 50 m of a 4-hour target
          <div className="lp-sla-bar" aria-hidden="true"><div className="lp-sla-fill" /></div>
        </div>
        <div className="lp-stamp" aria-hidden="true">Signed off<small>12 Nov, 09:02</small></div>
      </div>
    </figure>
  )
}

const YEAR = new Date().getFullYear()

export function LandingPage() {
  const contact = env.contactEmail
  const demo = contact
    ? <a className="lp-btn lp-btn-line" href={`mailto:${contact}?subject=${encodeURIComponent('ATT Platform demo')}`}>Request a demo</a>
    : null

  return (
    <div className="lp lp-animate">
      <div className="lp-wrap">
        <header className="lp-header">
          <a className="lp-brand" href="#top" aria-label="ATT Platform, top of page"><span className="lp-mark" aria-hidden="true">ATT</span>ATT Platform</a>
          <nav className="lp-nav" aria-label="Page">
            <a className="lp-hide-sm" href="#how-it-works">How it works</a>
            <a className="lp-hide-sm" href="#who-its-for">Who it’s for</a>
            <Link className="lp-btn lp-btn-solid lp-btn-small" to="/login">Sign in</Link>
          </nav>
        </header>

        <main id="top">
          <section className="lp-hero" aria-labelledby="lp-title">
            <div>
              <h1 id="lp-title" className="lp-h1">Every job, from the first message to the customer’s signature.</h1>
              <p className="lp-lede">
                ATT Platform runs your service desk and your field team in one place: requests from email,
                WhatsApp and your customer portal, AI that sorts and routes them, technicians working from their
                phones, and deadlines everyone can see.
              </p>
              <div className="lp-actions">
                <Link className="lp-btn lp-btn-solid" to="/login">Sign in</Link>
                {demo}
              </div>
            </div>
            <WorkOrder />
          </section>
        </main>
      </div>

      <section id="how-it-works" className="lp-section" aria-labelledby="lp-how">
        <div className="lp-wrap">
          <h2 id="lp-how" className="lp-h2">How a job moves</h2>
          <p className="lp-section-intro">The same five steps for a printer jam or a failed generator, with nothing lost between the desk, the van and the customer.</p>
          <ol className="lp-journey">
            {JOURNEY.map((s) => (
              <li key={s.title}>
                <h3>{s.title}</h3>
                <p>{s.body}</p>
              </li>
            ))}
          </ol>
        </div>
      </section>

      <section id="who-its-for" className="lp-section" aria-labelledby="lp-who">
        <div className="lp-wrap">
          <h2 id="lp-who" className="lp-h2">One system, a view for everyone</h2>
          <p className="lp-section-intro">Each person signs in to the screen their job needs, and sees only what their role allows.</p>
          <dl className="lp-roles">
            {ROLES.map((r) => (
              <div key={r.who} className="lp-role"><dt>{r.who}</dt><dd>{r.what}</dd></div>
            ))}
          </dl>
        </div>
      </section>

      <section className="lp-section lp-local" aria-labelledby="lp-local">
        <div className="lp-wrap">
          <h2 id="lp-local" className="lp-h2">Set up for the way you work</h2>
          <p className="lp-section-intro">Made for service teams in Nepal, from Kathmandu Valley to Chitwan.</p>
          <div className="lp-local-grid">
            {LOCAL.map((l) => (
              <div key={l.title}><h3>{l.title}</h3><p>{l.body}</p></div>
            ))}
          </div>
        </div>
      </section>

      <section className="lp-section lp-close" aria-labelledby="lp-close">
        <div className="lp-wrap">
          <h2 id="lp-close" className="lp-h2">See your own jobs in it</h2>
          <p className="lp-section-intro">Sign in to your organization, or get in touch and we’ll set one up with your categories, working hours and team.</p>
          <div className="lp-actions">
            <Link className="lp-btn lp-btn-solid" to="/login">Sign in</Link>
            {demo}
          </div>
        </div>
      </section>

      <div className="lp-wrap">
        <footer className="lp-footer">
          <span>© {YEAR} ATT Platform</span>
          <Link to="/login">Sign in</Link>
          <Link to="/forgot-password">Forgot your password?</Link>
        </footer>
      </div>
    </div>
  )
}
