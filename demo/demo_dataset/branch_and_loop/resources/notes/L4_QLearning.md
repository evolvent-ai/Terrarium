# Lecture 4: Q-Learning and DQN

## Temporal difference learning
- TD(0): V(s) <- V(s) + α[r + γV(s') - V(s)]
- no need to wait for episode to end (unlike MC)
- biased but lower variance than Monte Carlo

## Q-Learning
- off-policy TD control
- Q(s,a) <- Q(s,a) + α[r + γ max_a' Q(s',a') - Q(s,a)]
- the max makes it off-policy (learning about greedy policy while following ε-greedy)
- guaranteed to converge to Q* with enough exploration

## Deep Q-Networks (DQN)
- use neural network to approximate Q(s,a)
- key tricks that made it work:
  1. experience replay buffer (break correlations)
  2. target network (stabilize training)
  3. reward clipping

## DQN variants
- Double DQN: fix overestimation bias
- Dueling DQN: separate V and A streams
- Prioritized experience replay

## ε-greedy exploration
- with prob ε take random action, otherwise greedy
- ε usually annealed from 1.0 to 0.01
- simple but effective, not great for hard exploration problems

## Arrived late, might have missed something at the beginning
