# Memory techniques for system design: 5 sessions with Claude

This guide gives you one memory session each morning of the 5-day bootcamp (06:00 to 08:00). Each session teaches one technique and then puts it to work straight away on real system design material. The goal is not to learn about memory. It is to walk into the interview able to recall any design and present it calmly.

## How memory works in an interview

- **Recall beats rereading.** Every time you pull something out of memory, it gets easier to pull out again. Rereading only feels like learning. So close the notes and say it.
- **Spacing beats cramming.** Revisit material a day later, then three days later, then a week later. Each revisit just before you would have forgotten locks it in.
- **Structure beats detail.** Under pressure you remember a fixed shape (5 boxes, 3 numbers, 2 trade-offs), not 5 pages. The recall cards give every design the same shape.
- **Sleep stores it.** What you learn in the day is consolidated at night. Never trade sleep for an extra hour of study this week.

## The recall card template: P-N-H-B-D-F-C

Every design has a one-page recall card in this fixed order. Remember the order with the sentence **"Please Never Hide Bad Design From Customers."**

| Letter | Line | What you say |
|---|---|---|
| P | Problem | "It's really a ___ problem." |
| N | Numbers | Three numbers, each with "so ___" (the design consequence) |
| H | Hard part | The one or two things that make it hard |
| B | Boxes | 4-7 boxes on the critical path, left to right |
| D | Decisions | Three trade-offs: "X over Y, because Z" |
| F | Failures | Two: "what breaks → what happens" |
| C | Close | A 30-second spoken wrap-up |

On top of each card is a **Hook**: the whole design as one chain of 4-7 steps, for example "Counter → Shuffle → Base62 → Cache → 302". Recall the hook first, then expand it into the seven lines.

This order matches the interview itself: problem and numbers are your opening, the hard part and boxes are your design, decisions and failures are your deep dive, and the close is your last minute.

## How to run each session

1. Open a new chat with Claude.
2. Attach the PDF of the cards listed for that session (Interview Prep → Recall cards, or the link in your planner block).
3. Paste the session prompt below and follow Claude's lead. Answer out loud before you type.

Keep a sheet of paper with three columns: **Green** (recalled cleanly), **Amber** (recalled with hesitation), **Red** (missed). Red cards come back the next morning; amber ones on Day 5.

## Session 1 (Day 1): Memory palace for the interview framework

**Technique:** the memory palace (method of loci). You place items along a route you know well, such as the rooms of your home, and later walk the route in your mind to recall them in order.

**Apply it to:** the 10 stages of "What to say" (opening, assumptions, requirements, numbers, hard part, drawing, handing control, deep dive, scale and failures, closing), and the P-N-H-B-D-F-C card order. Then learn your first card, URL shortener.

**Cards to attach:** url-shortener.

**Prompt to paste:**

> Teach me the memory palace technique in 10 minutes, then help me use it. I am preparing for system design interviews. Step 1: help me place these 10 interview stages along a route through my home, one vivid image per stage: opening, assumptions, requirements, numbers, naming the hard part, drawing the design, handing control to the interviewer, deep dive and trade-offs, scale and failures, closing. Step 2: test me on the order three times, with gaps of a few minutes, asking me to walk the route aloud. Step 3: using the attached recall card, teach me the P-N-H-B-D-F-C order ("Please Never Hide Bad Design From Customers"), then ask me to present the URL shortener from memory in that order. Correct me line by line. Keep your messages short and make me do most of the talking.

## Session 2 (Day 2): Retrieval practice and numbers

**Technique:** active recall with a Leitner system (green, amber and red piles), and anchoring numbers to their consequence. A number on its own is forgotten; "40K reads a second, so design the cache first" is remembered because it does a job.

**Also learn:** the three estimation anchors that rebuild most numbers: a day is about 100,000 seconds (86,400), a month is about 2.6 million seconds, and a year is about 30 million seconds.

**Cards to attach:** the Day 1 cards (url-shortener, unique-id-generator, api-rate-limiter, distributed-cache, read-heavy-cache, cache-invalidation, hot-key-counter, distributed-kv-store).

**Prompt to paste:**

> Run a 90-minute active-recall session on the attached system design recall cards. First, 10 minutes: teach me how to anchor numbers to consequences and the three time anchors (a day is about 100K seconds, a month 2.6M, a year 30M), then give me 3 quick estimation drills. Then, for each card in random order: give me only the design name and ask for its hook; then ask for the 7 lines in P-N-H-B-D-F-C order; then ask its 3 quiz questions. Do not show me the card before I answer. After each card, tell me what I missed and mark it green, amber or red. At the end, list my red and amber cards.

## Session 3 (Day 3): Chunking, hooks and a pattern palace

**Technique:** chunking (grouping details into a few meaningful units) and the link method (turning a chain of boxes into a short story). You also build a second palace for the 10 patterns you will reuse in almost every design: cache-aside, fan-out on write or read, sharding by key, consistent hashing, outbox, saga, idempotency keys, leader election and leases, CDN, and queues to absorb spikes.

**Cards to attach:** the Day 2 cards (object-storage-s3, file-storage, events-table-partitioning, time-range-queries, audit-log, autocomplete, ecommerce-search, web-crawler, geo-search-nearby) plus yesterday's red cards.

**Prompt to paste:**

> Teach me chunking and the link method for remembering system designs, in 10 minutes. Then help me build a memory palace along my route to work for these 10 patterns: cache-aside, fan-out on write vs on read, sharding by key, consistent hashing, transactional outbox, saga, idempotency keys, leader election and leases, CDN, queues to absorb spikes. For each, give me one vivid image and a one-line definition. Test me on the palace twice. Then, for each attached recall card, ask me to turn its boxes into a 2-sentence story, and to name which of the 10 patterns the design uses. Finally quiz me on the hooks of all cards in random order.

## Session 4 (Day 4): Explain it, then defend it

**Technique:** elaborative interrogation (asking "why?" and "what if?" until the reason is clear) and the Feynman teach-back (explaining it simply, as if to a junior engineer). Understanding why a box exists is what lets you rebuild it when memory fails. Also interleaving: mixing similar designs so you learn what makes each one different.

**Cards to attach:** the Day 3 cards (distributed-message-queue, idempotent-processing, job-queue, pubsub-notifications, backpressure-pipeline, order-processing-workflow, payment-system, messaging-app, chat-presence, websocket-scaling) plus red cards so far.

**Prompt to paste:**

> Act as a senior system design interviewer. Use the attached recall cards. For each card in random order: ask me to explain the design in 2 minutes as if to a junior engineer, using P-N-H-B-D-F-C. Then ask me 2 sharp "why?" or "what if this fails?" questions taken from its decisions and failures. Push back once on each answer, the way a real interviewer would. Then pick two similar designs from the set (for example job queue vs message queue) and ask me to name the 3 biggest differences. Keep a score and tell me my 3 weakest designs at the end.

## Session 5 (Day 5): Mixed, timed recall under pressure

**Technique:** interleaved, timed recall. In the real interview you will not know which design is coming, so practise drawing any card at random and starting cleanly within 30 seconds.

**Cards to attach:** all cards from Days 1 to 4 (or the full deck).

**Prompt to paste:**

> Run a timed, mixed recall drill on the attached system design recall cards. Pick a card at random and give me only the design name. I have 30 seconds to say the hook and the problem line, then 3 minutes to present the full card in P-N-H-B-D-F-C order. Score me out of 7, one point per line, and tell me exactly what I missed. Do 12 cards. Then give me a final list sorted from weakest to strongest, and a spaced review schedule for the next two weeks (tomorrow, in 3 days, in a week, in two weeks) built from my weak cards.

## Every study block, every day

- **Start each design with its hook.** Read it before the summary so the details have somewhere to land.
- **End each design with the card, from memory.** Close everything and say the 7 lines aloud in 3 minutes. Only then look at the card and fix the gaps.
- **Evenings:** after the mock, recall the day's hooks on paper in 10 minutes, without looking.
- **After the bootcamp:** review the red and amber cards the next day, in 3 days, in a week and in two weeks. Ten minutes a day keeps them fresh.
