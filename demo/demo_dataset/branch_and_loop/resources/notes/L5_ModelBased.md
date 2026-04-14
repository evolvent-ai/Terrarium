# Lecture 5: Model-Based RL

## Model-free vs model-based
- model-free: learn policy/value directly from experience (Q-learning, PG)
- model-based: learn a model of the environment, then plan
- tradeoff: sample efficiency vs model accuracy

## Learning the model
- learn transition P(s'|s,a) and reward R(s,a)
- can use neural networks for complex envs
- model error compounds over long horizons -> "model bias"

## Planning with a learned model
- Dyna-Q: mix real experience with simulated experience
- generate imaginary rollouts from model to speed up learning
- simple but effective idea

## Monte Carlo Tree Search (MCTS)
- used in AlphaGo
- build search tree by simulation
- UCB for exploration in tree
- combine with neural network for evaluation

## World models
- learn latent representation of environment
- plan in latent space (faster than raw observation space)
- "World Models" paper (Ha & Schmidhuber)
- Dreamer, MuZero

## Tradeoffs discussion
- model-based is more sample efficient
- but model errors can be catastrophic
- Prof Zhang: "in practice, the best approach is often a hybrid"

## This lecture was dense, need to review
