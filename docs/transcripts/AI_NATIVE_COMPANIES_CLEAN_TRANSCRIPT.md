# Building AI-Native Companies

## Clean Transcript

**Source:** User-provided transcript  
**Length:** Approximately 21 minutes  
**Editorial treatment:** Repeated filler words, false starts, and transcription errors have been removed or corrected for readability. Section timestamps and the speaker's meaning have been preserved. A short fragment around 4:27 was inaudible in the source and has been omitted.

## Introduction

**[00:03]**

How is your day going so far? Good. Great.

I've got about 25 minutes, and I'm going to talk about building AI-native companies. This is based on a talk I gave about a month or six weeks ago that is on YouTube. I've updated it and added some thoughts.

The main caveat I want to start with is that no one knows how to do this. This is very theoretical. It is based on hundreds of YC companies we are working with right now. Lots of people are trying things, and if anyone tells you they have it all figured out, they are probably lying.

Internally at YC, we have an amazing software team. We have been pushing the boundaries of what LLMs can do for a couple of years, and we have a number of interesting use cases. I will give examples as we go, but I do not think we have it fully figured out yet.

By the end of 2026, or possibly by the first batch in 2027, I expect it will be technically possible—whether or not we take the public-relations risk—to have an AI run YC's process end to end: read all the applications, choose the companies to interview, conduct the interviews, select the companies to fund, advise them throughout the batch, introduce them to investors, review their pitch decks, and debug their pitch meetings.

I think an AI will be able to do all of that end to end by the end of this year, if not within the first three months of next year. We already have quite a lot of it working and are exposing much of it to our founders. That is where this talk comes from.

## Why Roman Legions Built Your Org Chart

**[01:53]**

What is an AI-native company? The first place to start is with what is *not* an AI-native company.

This is how Roman legions were structured. The smallest unit was the *contubernium*: eight soldiers who shared a tent, equipment, and a mule, with a *decanus* in charge. Ten contubernia formed a century, which was actually 80 men rather than 100.

You see this hierarchical way of organizing humans. The Roman legions used it to project power across North Africa, the Near East, and into Britain as far as Hadrian's Wall. Information passed down and reports came back up, with a human responsible for acting as the conduit at every level.

Bizarrely, roughly 2,000 years later, we are still running essentially the same structure. Organizations look slightly different, but the same principle holds: humans are the conduit for information moving up and down the hierarchy.

A Jack Dorsey post kicked off this line of thinking for me a couple of months ago. There is an underlying assumption that organizations must be hierarchical, with humans serving as the coordinating mechanism. I think AI breaks that assumption apart. Humans no longer have to be the coordinating mechanism.

Most companies first experience ChatGPT as a question-and-answer bot: they put questions in and receive answers. They may then move to longer-running, agentic systems. But the pattern is still that you ask an agent to do something, it works until it gets stuck, and then it comes back to you. The human remains the gate.

## Humans as the Bottleneck

**[03:57]**

While you are asleep, the system cannot work. If it stops halfway through at three in the morning, it waits for your input. You are the gating mechanism.

This setup can make engineers 20 percent more productive, add copilots that improve lawyers' existing workflows, or help companies ship more software. But it still depends on humans as the coordinating mechanism.

The more interesting question is not how AI increases productivity, but what entirely new capabilities it enables: a single person doing work that once required thousands of people, an entire company becoming queryable, and software becoming agent-native rather than merely being produced faster with AI.

These terms can sound like buzzwords, so I want to explain what I mean in more detail.

Many companies currently bolt AI onto the side of the organization. They add question-and-answer bots or lightweight agents that can call tools such as web search. But if you instead imagine the company from the ground up as a series of self-improving AI loops, you reach a very different conclusion.

Previously, the goal was to make each person 20 or 30 percent more productive. What happens if we reimagine the company itself as a series of AI loops?

## What a Real AI Loop Looks Like

**[05:46]**

What is an AI loop?

At the top, you have signals from the real world: product telemetry, inbound messages, billing signals, support tickets, code changes, and other data.

Then you have a policy layer: what rules constrain the AI, what requires approval, and what must be logged.

Next is a tool layer. The AI might call internal APIs, send emails, update billing, or use MCP-based tools.

Then you have quality gates. A gate could be human, although I would argue that humans should be reserved for the most extreme cases. Often the quality gate can be a second, adversarial LLM. It might inspect an output for prompt injection, determine whether a bank's agent is improperly giving financial advice, or simply review code produced by another model.

Finally, you have a learning mechanism that closes the loop. You deploy the change, observe its effect in the real world, and feed that result back into the system.

If you can run this entire loop without a human, your product begins improving itself while you sleep.

## The Data Agent That Changed Everything

**[07:19]**

The first time I saw one of these loops, it broke my brain a little.

At YC, we have data on about 7,000 companies, 20,000 founders, and hundreds of thousands of applications. A year or two ago, we built an AI data-query agent. It was essentially English-to-SQL. You could ask, "What was the split of European versus American founders in this batch?" The agent translated the question into SQL, ran it, and returned the answer.

That felt magical, but it was still a productivity tool. It might make a data analyst 20 or 30 percent more productive, or make me 10 or 20 percent more productive because I did not have to hire a data analyst.

The agent kept hitting edge cases. It could not do certain things, encountered permission problems, or ran into missing database indexes.

Then, two or three months ago, we shipped a second agent on top of the data-query agent. That was the head-explosion moment for me.

## The Self-Improving System

**[08:19]**

The second agent runs overnight. It reviews all the queries humans made during the day and looks for evidence of success or failure.

Success might mean someone copied the answer, sent the resulting email, or otherwise used the output. Failure might mean the query did not work, hit a permission problem, or needed a database index that did not exist.

Overnight, the second agent opens pull requests to fix the previous day's problems. If a human runs the same query on the second day, it now works.

The system evaluates what it is doing, proposes changes to itself, and updates itself. That is what makes it self-improving.

PostHog is doing something similar for products. The system consumes product telemetry, identifies where the product is breaking, and opens pull requests. Eventually, some of those pull requests may be merged automatically.

The whole product surface can become self-improving. You define headline metrics and product-vision documents that specify what is in and out of scope. The AI examines product telemetry, proposes ideas, deploys them, tests them with humans, and sees whether they moved the metric.

Andrej Karpathy recently described a similar auto-research loop applied to machine learning: generate research ideas, test them overnight, and hill-climb. That is fundamentally what this is. If you have a measurable outcome, you can generate ideas, test them, and ask whether you moved uphill or downhill. Discard changes that move downhill; keep changes that move uphill; repeat.

Computers are exceptionally good at hill-climbing because they do not stop. They can run indefinitely until they reach a local maximum.

## Office Hours Become a Living User Manual

**[10:31]**

Here is another YC example. We started recording office hours about six months ago.

I had been assigned to rewrite a section of our internal user manual. It has been written over roughly 15 years and is around 500 pages long. Much of the advice was excellent five years ago, but AI happened, and some of it is no longer relevant. I procrastinated on rewriting it.

Now we have three or four thousand hours of recorded office hours. Someone on the team had the idea to transcribe them, extract the advice we actually give founders, and use that evidence to rewrite the manual.

When our advice changes, the AI can observe what humans are saying, extract the new insight, update the manual, and publish it. The manual becomes a living guide to how we actually advise companies.

Once that knowledge is in the manual, it can become queryable through an advice agent. Founders repeatedly ask similar questions: How should I price my first customer? My third customer is about to churn—what should I do? A customer has requested an esoteric feature—should I build it?

We have answered versions of those questions hundreds of times. An AI could provide not just one partner's answer, but synthesize how several partners would answer. It could potentially give superhuman advice because it has perfect recall and can access the combined intelligence of 16 partners rather than one person's fallible memory.

These loops can run in the background and continuously improve.

## The AI Employee With a VM

**[12:31]**

The next step is to give the agent a virtual machine and useful tools: web search, access to the internal company directory, Slack history, and persistent file storage.

Persistent storage allows the agent to create a plan and write it to disk. If it fails halfway through, it can resume. It can write and execute code to solve a problem, compare the result with its plan, adjust, and repeat.

At that point, you effectively have an AI employee.

We are at the very early stages of this with systems such as OpenClaw or Hermes: an agent living inside a VM and operating on a repeating loop.

YC currently has a few of these loops internally. Humans occasionally intervene when a loop goes wrong or when an insight needs to move from one loop to another.

The next step is for the loops—or AI employees—to communicate with each other, share ideas, replan, and assess their work.

## What “Company Brain” Actually Means

**[13:52]**

“Company brain” is an overused term, but the underlying idea matters.

In a conventional company, intelligence is distributed across people and routed through the hierarchy. In the new model, intelligence lives in the system.

Companies often try to document standard operating procedures: the way things are supposed to be done. But when you observe people doing the job, you discover many edge cases and exceptions that live only in their heads. Making that tacit knowledge explicit creates enormous value.

A company brain combines all of the organization's data: YC's application data, transcripts of every founder meeting, the advice we give, and the way we select companies. You record it and make it legible so AI can access it.

Then you add reinforcing loops that run indefinitely and communicate with each other. The organization becomes self-improving. You provide compute and access to company data, and the system continually improves.

Humans live at the edge, where this intelligence makes contact with reality.

## Humans at the Edge

**[15:36]**

People reach into places the model cannot yet go. They sense things the model cannot perceive: intuition, opinionated direction, cultural context, trust dynamics, and the feeling in a room.

They make decisions that a model should not make alone, especially ethical decisions, novel situations, and high-stakes moments in which the cost of being wrong is existential.

A company brain that cannot touch the real world is only a database. Humans remain present in sales calls, client visits, CEO conversations, and investor pitches. They do the emotional and interpersonal work.

But humans are no longer required to route information. The system can automatically deliver information to the person or agent that needs it without moving it through layers of management.

Companies will therefore be much smaller. They will be centered around a company brain and a set of self-reinforcing loops. People will interface with the real world and feed what they learn back into the brain.

That sounds good in theory, but it can also sound like science fiction. What can founders actually do now?

## Burn Tokens, Not Headcount

**[17:14]**

The first practical recommendation is to burn tokens, not headcount.

We are seeing founders reach Demo Day with $1 million in revenue, and sometimes Series A with $10 million in revenue, using a fraction of the people companies previously needed. Someone who is versatile and knows how to use these tools can be worth many times more than before.

The result is a smaller company with fewer layers of middle management. Everyone should be an individual contributor who does the work and comes to meetings with working prototypes rather than decks.

The directly responsible individual is especially important: one person whose head is on the block for making an outcome happen. Committees grind execution to a halt. A single person should be directly responsible for the result.

## Make Everything Legible to AI

**[18:30]**

Make everything in the organization legible to AI—meaning that AI can read it.

Record everything. Transcribe every meeting. If the AI cannot access Slack direct messages, consider moving work into accessible public channels. Every action should create a written or recorded artifact. Otherwise, from the AI's perspective, it did not happen.

On-demand internal software for company operations will also become necessary.

## Simulating Investor Calls

**[19:13]**

Here is an example. Companies already record sales meetings and feed them into AI to ask, “How did I do?” The same approach can be applied to investor meetings.

Imagine access to hundreds or thousands of companies that meet many of the same investors every three months. The first use is coaching founders: you spent 90 percent of the meeting talking; you fumbled this question; you need to be more concise about go-to-market.

Many founders take 40, 50, or 60 investor calls. If the calls are recorded, AI can identify what is going well and what is going badly.

The organization also sees patterns on the other side of the conversation because founders repeatedly meet the same investors. It could simulate an investment call and explain the questions a firm or specific partner tends to ask—for example, questions about the company's wedge or its defense against a major competitor—and help the founder practice strong answers.

Those investors are likely recording the same conversations and learning from them too.

If you can record an interaction and make it legible, AI can comprehend it and give you leverage.

## Closing

**[20:50]**

If you were starting a company today, would you build it like this?

This talk was originally for very early-stage YC founders. Many of you are even earlier, and you are small enough to build this way from the start.

Thank you.

