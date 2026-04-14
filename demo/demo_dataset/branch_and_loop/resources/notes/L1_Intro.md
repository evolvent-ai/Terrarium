# Lecture 1: Introduction to RL

## What is RL?
- learning by interacting with env, not from labeled data
- agent takes actions -> gets rewards -> learns policy
- goal: maximize cumulative reward

## Key concepts
- agent, environment, state, action, reward
- policy π(a|s): mapping from states to actions
- value function V(s): expected return from state s
- episode vs continuing tasks

## RL vs supervised/unsupervised
- supervised: need labels, iid data
- unsupervised: find structure
- RL: sequential decisions, delayed reward, exploration vs exploitation tradeoff

## Applications mentioned in class
- Atari (DQN), Go (AlphaGo), robotics
- Prof Zhang said "RL is the closest thing to how humans actually learn"
