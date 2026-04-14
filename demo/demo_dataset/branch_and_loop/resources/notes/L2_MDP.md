# Lecture 2: Markov Decision Processes

## MDP definition
- tuple (S, A, P, R, γ)
- S = state space, A = action space
- P(s'|s,a) = transition dynamics
- R(s,a,s') = reward, γ = discount factor

## Markov property
- memoryless: future only depends on current state
- P(s_{t+1}|s_t,a_t) is all you need
- this is a BIG assumption, doesn't always hold in practice

## Bellman equation (IMPORTANT)
- V(s) = max_a Σ P(s'|s,a)[R(s,a,s') + γV(s')]
- recursive structure: value = immediate reward + discounted future
- this is basically the foundation of everything in this course

## Bellman optimality
- V*(s) = max_a Q*(s,a)
- Q*(s,a) = R(s,a) + γ Σ P(s'|s,a)V*(s')
- optimal policy satisfies both equations simultaneously

## Dynamic programming
- value iteration: keep applying Bellman update until convergence
- policy iteration: evaluate -> improve -> repeat
- both guaranteed to converge but need full model (P and R)
- complexity: polynomial in |S| and |A|

## My questions
- when does Markov property break down in real problems?
- TODO: review the gridworld example from homework
