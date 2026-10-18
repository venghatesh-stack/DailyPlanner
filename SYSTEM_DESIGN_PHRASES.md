# System design: what to say, step by step

Use these lines in order during a system design round. Fill the blanks with the problem in front of you (Uber, WhatsApp, a URL shortener...). Say them out loud a few times before the interview so they come naturally.

## 1. Opening (first minute)

- When the question is given: **"Before I design, I'd like to ask a few clarifying questions so I build the right thing."**
- Then ask: **"Should I focus on the core flow, or also extra features like ___?"**
- And: **"What scale should I assume: one city or the whole country?"**

## 2. Assumptions (after their answers)

- **"Let me state my assumptions."**
- **"I'll assume ___. Please correct me if that's wrong."**

## 3. Requirements

- **"Let me split requirements into two parts: functional and non-functional."**
- **"Functional: the user can ___, ___ and ___."**
- **"Non-functional: it should be fast, highly available, and ___ must be consistent."**

## 4. Numbers

- **"Let me do a quick estimate."**
- **"This means about ___ requests per second. So the main load is on ___."**

## 5. Naming the hard part

- **"The hardest parts will be ___ and ___."**

## 6. Drawing the design

- **"Let me start simple, then improve it."**
- **"Let me walk through what happens when a user ___."** This is the ride story: follow one request from start to end.

## 7. Handing control to the interviewer (after the basic design)

- **"Which part would you like me to go deeper into?"**

## 8. Deep dive and trade-offs

- **"There's a trade-off here. Option A gives ___, option B gives ___. I'd choose ___ because ___."**
- **"Here, consistency is more important than speed, because ___."** (Or the other way round.)

## 9. Scale and failures

- **"Now let's see what breaks at scale."**
- **"If ___ fails, the system will ___."**

## 10. Closing (last minute)

- **"To summarize: ___, ___ and ___."**
- **"If I had more time, I would add ___."**

## Rescue phrases (any time)

- **Need time:** "Let me think for a moment."
- **Didn't understand:** "Could you repeat that, please? I want to make sure I understand."
- **Don't know:** "I haven't worked on that directly, but my approach would be ___."
- **Interviewer pushes back:** "That's a good point. Let me reconsider."
- **Lost your place:** "Let me quickly recap where we are."
