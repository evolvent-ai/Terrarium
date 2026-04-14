# Lecture 6: Course Review

## Exam format
- Prof Zhang said: mix of conceptual questions and derivations
- need to know Bellman equation derivation by heart
- probably a question on comparing methods

## Key themes across the course
1. exploration vs exploitation
2. bias vs variance (MC vs TD)
3. model-free vs model-based
4. on-policy vs off-policy
5. value-based vs policy-based

## Method comparison table (from whiteboard)
| Method | Type | On/Off Policy | Key Idea |
|--------|------|---------------|----------|
| REINFORCE | PG | On | log-prob * return |
| Actor-Critic | PG | On | advantage + critic |
| Q-Learning | Value | Off | max Q target |
| DQN | Value | Off | neural Q + replay |
| Dyna-Q | Model-based | Off | real + simulated exp |

## What to focus on for the exam
- Bellman equations (will definitely be on the exam)
- REINFORCE derivation
- DQN tricks (why experience replay, why target network)
- when to use which method

## Prof Zhang's closing remarks
- "if you understand Bellman equation deeply, you understand 80% of RL"
- office hours before exam: Thursday 3-5pm
