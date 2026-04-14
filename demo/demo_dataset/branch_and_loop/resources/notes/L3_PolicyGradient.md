# Lecture 3: Policy Gradient Methods

## Why policy gradient?
- value-based methods (Q-learning) learn V or Q, derive policy
- policy gradient: directly optimize the policy π_θ
- advantages: can handle continuous actions, stochastic policies

## REINFORCE algorithm
- ∇J(θ) = E[Σ ∇log π_θ(a_t|s_t) * G_t]
- G_t = total return from timestep t
- intuition: increase prob of actions that led to high return
- simple but HIGH VARIANCE

## Variance reduction
- baseline: subtract b(s) from return -> doesn't change expectation
- common baseline: V(s) -> advantage A(s,a) = Q(s,a) - V(s)
- actor-critic: learn both policy (actor) and value (critic)

## Actor-Critic
- actor: policy network π_θ
- critic: value network V_φ
- update critic with TD error, update actor with policy gradient
- A2C, A3C variants

## Prof Zhang's tips
- "REINFORCE is elegant but you'd never use it in practice"
- actor-critic is the real workhorse
- pay attention to entropy regularization for exploration

## Missed the last 10 min, need to get notes from someone
