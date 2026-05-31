import Link from "next/link";
import { ArrowLeft, Film, Clock, Eye, Camera } from "lucide-react";

export default function ScriptsPage() {
  return (
    <div className="mx-auto max-w-3xl px-2 py-8">
      <div className="mb-6 flex items-center gap-3">
        <Link
          href="/"
          className="inline-flex items-center gap-1 text-sm text-neutral-500 hover:text-neutral-800"
        >
          <ArrowLeft className="h-4 w-4" />
          Home
        </Link>
        <span className="text-neutral-300">/</span>
        <h1 className="text-lg font-semibold text-neutral-900">Scripts</h1>
        <span className="text-xs text-neutral-400">
          operator-facing reference
        </span>
      </div>

      <BeverlyLoomScript />
    </div>
  );
}

function BeverlyLoomScript() {
  return (
    <article className="space-y-6">
      <header className="rounded-xl border border-neutral-200 bg-white p-5">
        <div className="flex items-start gap-3">
          <div className="rounded-lg bg-amber-100 p-2 text-amber-700">
            <Film className="h-5 w-5" />
          </div>
          <div className="min-w-0">
            <h2 className="text-base font-semibold text-neutral-900">
              Loom — Beverly Law / Michael Shemtoub
            </h2>
            <p className="mt-1 text-sm text-neutral-600">
              Reply to step 1 of the 4-step sequence. Michael said{" "}
              <em>&ldquo;send me a loom of what you think can help us?&rdquo;</em>
              {" "}— this is the script for that Loom.
            </p>
            <div className="mt-3 flex flex-wrap gap-2 text-[11px]">
              <Badge>~5 min target · 6 min hard cap</Badge>
              <Badge>screen + face cam · no slides</Badge>
              <Badge>tone mirrors the cold-call script</Badge>
            </div>
          </div>
        </div>
      </header>

      <Section title="Style notes" icon={<Eye className="h-4 w-4" />}>
        <p>
          First-person, conversational, no slides. Screen-share + face cam.
          You&apos;re talking to <em>one</em> person, not pitching to a board.
          Lowercase, peer-tone, mirrors his reply.
        </p>
      </Section>

      <ScriptSection
        timestamp="0:00 — 0:25"
        title="Open"
        cue="(face cam, no screen share yet)"
      >
        <p>
          Hey Michael, Pranav from Possible Minds. You replied yesterday — said
          send a Loom of what we think could help. So that&apos;s what this is.
          Five-ish minutes. I&apos;m gonna show you the system we built for
          Precise Imaging, then walk through how the same shape would work at
          Beverly Law specifically, based on what I noticed reading through
          your reviews.
        </p>
        <p>Not a sales pitch. Just a real read on whether there&apos;s something here.</p>
      </ScriptSection>

      <ScriptSection
        timestamp="0:25 — 1:30"
        title="What I noticed in Beverly Law's reviews"
        cue="(switch to screen share — open Beverly Law's Yelp page; have LaTrice N.'s review scrolled into view)"
      >
        <p>
          Real quick on what got me to reach out in the first place. I went
          through Beverly&apos;s reviews — Yelp, Google, all of it. There&apos;s a
          pattern that comes up over and over.
        </p>
        <Stage>highlight LaTrice's review on screen</Stage>
        <p>
          This one from a few years back:{" "}
          <em>
            &ldquo;Nobody from Beverly Law Firm will keep in contact to let me
            know what&apos;s going on.&rdquo;
          </em>{" "}
          That sentiment shows up in maybe a third of your one-star reviews —{" "}
          <em>
            &ldquo;if I don&apos;t call to check status, they don&apos;t call me,&rdquo;
            &ldquo;communication stopped completely on their end,&rdquo;
            &ldquo;every time I call, my case is being handled by a new rep.&rdquo;
          </em>
        </p>
        <p>
          I&apos;m not bringing this up to point fingers. Honestly, this is the
          most common pattern across every PI firm we look at — Yelp&apos;s full
          of it. It&apos;s not anyone being lazy. It&apos;s that case-status
          communication is a queue nobody quite owns. The case manager&apos;s
          heads-down on the case work; the client&apos;s calling for an update;
          nobody has a system that says &ldquo;this client is overdue for a
          check-in.&rdquo;
        </p>
        <p>That&apos;s a fixable problem, and it&apos;s the kind of thing we actually build.</p>
      </ScriptSection>

      <ScriptSection
        timestamp="1:30 — 3:00"
        title="The Precise system, live"
        cue="(switch to your actual Precise inbox / dashboard — show real production traffic. Blur client names if needed; do NOT mock data)"
      >
        <p>
          So before I describe what we&apos;d build for you, here&apos;s what we
          built for Precise Imaging. This is live — production. Real attorney
          offices emailing in.
        </p>
        <Stage>scroll through the inbox, point to a few examples</Stage>
        <p>
          Each one of these is an attorney&apos;s office asking for something —{" "}
          <em>&ldquo;what&apos;s the status on so-and-so&apos;s MRI?&rdquo;</em>,{" "}
          <em>&ldquo;can you send the imaging report for case #X?&rdquo;</em>,{" "}
          <em>&ldquo;when is the appointment?&rdquo;</em>. Used to take Precise&apos;s
          intake team about a hundred hours a week to triage and respond to all
          of this. Real number — they measured it.
        </p>
        <Stage>click on one to show the auto-reply</Stage>
        <p>
          Now what happens is: the email comes in, our system reads it, pulls
          the answer out of Precise&apos;s case management system, and drafts a
          reply. For two weeks at the start, a human reviewed every single one
          before it went out — they wanted to see it being right before they
          trusted it. After two weeks, accuracy was solid. They handed it the
          keys.
        </p>
        <p>
          Hundred hours a week back. Same response quality. No headcount
          change. Doesn&apos;t replace anyone — it just removes the part of the
          job that nobody likes doing anyway.
        </p>
      </ScriptSection>

      <ScriptSection
        timestamp="3:00 — 4:30"
        title="How this works for Beverly Law"
        cue="(face cam first, then switch to a tablet / Figjam / Excalidraw and sketch live as you talk — don't pre-make slides)"
      >
        <p>
          Okay, so the Beverly Law version. The shape is the same, the inputs
          are different.
        </p>
        <Stage>
          start sketching: client → email/call → case management → drafted reply
        </Stage>
        <p>
          Inbound from a client — could be email, could be a call that gets
          transcribed, could be a contact-form submission. System reads it.
          Figures out what they&apos;re asking — &ldquo;where is my case at,&rdquo;
          &ldquo;did the demand letter go out,&rdquo; &ldquo;when&apos;s the next
          check-in&rdquo; — and pulls the answer out of whatever case management
          you&apos;re using. Could be Filevine, Litify, MyCase, Clio — we plug
          into whatever you have.
        </p>
        <p>
          Then it drafts a reply. Status, next steps, expected timeline. Either
          auto-sends or queues for a paralegal to glance at and click send.
          Same review-then-trust pattern Precise used.
        </p>
        <p>
          The win isn&apos;t replacing case managers — they&apos;re not the
          bottleneck, they&apos;re already busy. The win is taking the{" "}
          <em>&ldquo;client called for an update&rdquo;</em> loop off their plate
          entirely. Client gets a same-day, accurate answer. Case manager gets
          to focus on the case. The Yelp problem stops being a Yelp problem.
        </p>
        <p>
          If intake&apos;s actually the bigger pain at Beverly than
          post-retainer, the same kind of system works there too — reading
          inbound leads, qualifying, scheduling. I just defaulted to
          post-retainer because that&apos;s what your reviews point at. Happy
          to point it at intake instead if that&apos;s where the time&apos;s
          really going.
        </p>
      </ScriptSection>

      <ScriptSection
        timestamp="4:30 — 5:00"
        title="What a build engagement looks like"
        cue="(face cam)"
      >
        <p>
          Briefly on how we work — we&apos;re not selling software. We build
          bespoke. Two-week build, scoped to what your stack actually is and
          what your team actually does. We&apos;d start with a 30-minute
          scoping call — you walk us through the workflow, we point at the
          parts that look automatable, we tell you honestly whether
          there&apos;s something worth building or not. If there&apos;s not, we
          say so. We don&apos;t take projects that don&apos;t ship measurable
          hours back.
        </p>
      </ScriptSection>

      <ScriptSection
        timestamp="5:00 — 5:15"
        title="Close"
        cue="(face cam)"
      >
        <p>
          That&apos;s it. Reply with a time that works for the scoping call, or
          there&apos;s a link in my signature — getpossibleminds.com/consult.
          Either works.
        </p>
        <p>Thanks for replying yesterday. Talk soon.</p>
      </ScriptSection>

      <Section title="Delivery notes" icon={<Camera className="h-4 w-4" />}>
        <div className="mobile-table-card md:overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="text-[11px] uppercase tracking-wider text-neutral-500">
            <tr>
              <th className="pb-2 pr-4 text-left font-medium">Do</th>
              <th className="pb-2 text-left font-medium">Don&apos;t</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-neutral-100">
            <DoDontRow
              dos="Record in one take. If you flub, flub. Authenticity > polish."
              donts="Multiple cuts, B-roll, music. Loom isn't YouTube."
            />
            <DoDontRow
              dos="Energy: confident-but-conversational. Same as how you'd talk to a peer over coffee."
              donts="Read off a teleprompter. Eye-line drift kills it instantly."
            />
            <DoDontRow
              dos="When showing the real Precise inbox — actually let it scroll. Real-world volume is itself the proof."
              donts="Mock data. Michael will smell it."
            />
            <DoDontRow
              dos="When sketching the Beverly Law analog, sketch slowly. Drawing live signals 'this is real, not pre-baked.'"
              donts="Pre-render a slide deck of the architecture."
            />
            <DoDontRow
              dos="If you mention the 100-hr/wk figure, mention it once."
              donts="Loop back to it three times. It loses force."
            />
            <DoDontRow
              dos="Show LaTrice's review name + date on screen, but say 'from a few years back' — frames it as systemic, not 'I dug up your worst review.'"
              donts="Quote multiple reviewers by name in a row. Reads as a hit job."
            />
            <DoDontRow
              dos="Cap at 6 minutes. If running long, cut the architecture sketch shorter, not the Yelp moment or the Precise demo."
              donts="Add a CTA slide. Voice-only close, signature link is enough."
            />
          </tbody>
        </table>
        </div>
      </Section>

      <Section title="Two judgment calls before you record" icon={<Clock className="h-4 w-4" />}>
        <ol className="list-decimal space-y-3 pl-5">
          <li>
            <strong>Naming LaTrice on screen.</strong> I&apos;d do it — her
            review is public, it&apos;s been up since 2020, and pretending you
            couldn&apos;t read who said it is weirder than just acknowledging
            it. Calibrate the tone with{" "}
            <em>&ldquo;I&apos;m not bringing this up to point fingers&rdquo;</em>
            {" "}— that line is doing a lot of work. Alternative: blur the name
            in your screenshot, say <em>&ldquo;a recent reviewer.&rdquo;</em>{" "}
            Less punchy, safer.
          </li>
          <li>
            <strong>
              Whether to show the <em>actual</em> Precise inbox or a sanitized
              recreation.
            </strong>{" "}
            Real is dramatically more credible. If Precise has a contract clause
            about not showing their inbox to outside parties, you can&apos;t.
            Sanitized recreation is a clear second-best, but still better than
            slides about it.
          </li>
        </ol>
      </Section>

      <Section title="Reply email when you send the Loom" icon={<Film className="h-4 w-4" />}>
        <pre className="whitespace-pre-wrap rounded border border-neutral-200 bg-neutral-50 p-3 font-sans text-sm leading-relaxed text-neutral-800">
{`Hey Michael — Loom's here: [link]

~5 minutes. Quick walk through what we built for Precise, then how the same shape would land at Beverly. Reply with a time that works for a scoping call, or grab one off the link below.

— Pranav`}
        </pre>
        <p className="mt-2 text-xs text-neutral-500">
          Three lines, link, sign. Don&apos;t pre-summarize the Loom in the
          email — that defeats the point of sending the Loom.
        </p>
      </Section>
    </article>
  );
}


function Section({
  title,
  icon,
  children,
}: {
  title: string;
  icon?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <section className="rounded-xl border border-neutral-200 bg-white p-5">
      <h3 className="mb-3 flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-neutral-500">
        {icon}
        {title}
      </h3>
      <div className="space-y-2 text-sm leading-relaxed text-neutral-800">
        {children}
      </div>
    </section>
  );
}


function ScriptSection({
  timestamp,
  title,
  cue,
  children,
}: {
  timestamp: string;
  title: string;
  cue: string;
  children: React.ReactNode;
}) {
  return (
    <section className="rounded-xl border border-neutral-200 bg-white p-5">
      <header className="mb-3 flex items-baseline gap-3 border-b border-neutral-100 pb-3">
        <span className="font-mono text-xs text-neutral-400">{timestamp}</span>
        <h3 className="text-sm font-semibold text-neutral-900">{title}</h3>
      </header>
      <p className="mb-3 italic text-xs text-neutral-500">{cue}</p>
      <div className="space-y-3 text-sm leading-relaxed text-neutral-800">
        {children}
      </div>
    </section>
  );
}


function Stage({ children }: { children: React.ReactNode }) {
  return (
    <p className="my-2 rounded border border-amber-200 bg-amber-50 px-3 py-1.5 text-xs italic text-amber-800">
      {children}
    </p>
  );
}


function Badge({ children }: { children: React.ReactNode }) {
  return (
    <span className="rounded-full bg-neutral-100 px-2 py-0.5 text-[11px] font-medium text-neutral-700">
      {children}
    </span>
  );
}


function DoDontRow({ dos, donts }: { dos: string; donts: string }) {
  return (
    <tr className="align-top">
      <td data-label="Do" className="py-2 pr-4 text-emerald-800">{dos}</td>
      <td data-label="Don't" className="py-2 text-red-700">{donts}</td>
    </tr>
  );
}
