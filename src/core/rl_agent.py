"""
PATCH: RL Agent (DQN) — Deep Q-Learning for trading decisions.

Lightweight Q-learning implementation (no neural network, using Q-table).
Learns which actions (HOLD, LONG, SHORT) maximize cumulative rewards.

Key mechanisms:
- Epsilon-greedy exploration: balances exploration vs exploitation
- Experience replay: batch learning from past transitions
- Q-value updates: Bellman equation with discount factor
- Decay: gradually reduce exploration as learning progresses

State: [rsi, adx, macd, ema_diff, bb_width, health, ev, wr] (8 features)
Actions: {0: HOLD, 1: LONG, 2: SHORT}
Rewards: Trade PnL with bonuses/penalties
"""

import random
import numpy as np
from collections import deque
import logging

logger = logging.getLogger(__name__)


class DQNAgent:
    """
    Deep Q-Network Agent (lightweight Q-table implementation).
    
    Learns optimal trading actions through reinforcement learning.
    """
    
    def __init__(self, state_size: int = 8, action_size: int = 3):
        """
        Initialize RL agent.
        
        Args:
            state_size: Size of state vector (default 8 features)
            action_size: Number of actions (default 3: HOLD, LONG, SHORT)
        """
        self.state_size = state_size
        self.action_size = action_size
        
        # ────────────────────────────────────────────────────────────────
        # Learning parameters
        # ────────────────────────────────────────────────────────────────
        self.memory = deque(maxlen=5000)  # Experience replay buffer
        
        self.gamma = 0.95             # Discount factor (0.95 = value future rewards)
        self.epsilon = 1.0            # Exploration rate (start at 100% random)
        self.epsilon_min = 0.05       # Minimum exploration (5% random forever)
        self.epsilon_decay = 0.995    # Decay per training step
        
        self.learning_rate = 0.001    # Q-value update speed
        
        # ────────────────────────────────────────────────────────────────
        # Q-table: lightweight alternative to neural network
        # Key: discretized state tuple
        # Value: Q-values for each action [q_hold, q_long, q_short]
        # ────────────────────────────────────────────────────────────────
        # BUG-020 fix: bounded OrderedDict to prevent memory leak
        from collections import OrderedDict
        self.q_table = OrderedDict()
        self._q_table_max = 50_000
        
        # Statistics
        self.training_steps = 0
        self.episode_rewards = deque(maxlen=100)
        self.avg_reward = 0.0

    def _state_key(self, state):
        """
        Convert state vector to hashable Q-table key.
        Discretizes continuous values to 3 decimal places.
        """
        if isinstance(state, (list, np.ndarray)):
            return tuple(np.round(np.array(state), 3))
        return tuple(state)

    def act(self, state, training: bool = True) -> int:
        """
        Choose action using epsilon-greedy policy.
        
        Args:
            state: State vector [8 features]
            training: If True, use exploration; if False, pure exploitation
            
        Returns:
            Action index (0=HOLD, 1=LONG, 2=SHORT)
        """
        # Exploration: random action
        if training and np.random.rand() < self.epsilon:
            return random.randrange(self.action_size)
        
        # Exploitation: best known action from Q-table
        state_key = self._state_key(state)
        
        # If state unseen before, initialize Q-values
        if state_key not in self.q_table:
            self.q_table[state_key] = np.zeros(self.action_size)
        
        q_values = self.q_table[state_key]
        
        # Return action with highest Q-value (with tie-breaking)
        return np.argmax(q_values + np.random.randn(self.action_size) * 1e-6)

    def remember(self, state, action, reward, next_state, done):
        """
        Store experience in replay buffer.
        
        Args:
            state: Current state
            action: Action taken
            reward: Reward received
            next_state: Resulting state
            done: Episode done flag
        """
        self.memory.append((state, action, reward, next_state, done))

    def replay(self, batch_size: int = 32):
        """
        Train on batch of experiences (experience replay).
        
        Updates Q-values using Bellman equation:
        Q(s,a) = Q(s,a) + α * [r + γ * max(Q(s',a')) - Q(s,a)]
        
        Args:
            batch_size: Size of training batch (default 32)
        """
        if len(self.memory) < batch_size:
            return  # Need enough experiences to train
        
        # Sample random batch from memory
        batch = random.sample(self.memory, batch_size)
        
        total_loss = 0.0
        
        for state, action, reward, next_state, done in batch:
            state_key = self._state_key(state)
            next_state_key = self._state_key(next_state)
            
            # Initialize Q-values if state unseen
            if state_key not in self.q_table:
                self.q_table[state_key] = np.zeros(self.action_size)
            if next_state_key not in self.q_table:
                self.q_table[next_state_key] = np.zeros(self.action_size)
            
            # Bellman target: r + γ * max(Q(s', a'))
            if done:
                target = reward
            else:
                target = reward + self.gamma * np.max(self.q_table[next_state_key])
            
            # Current Q-value
            q_values = self.q_table[state_key]
            current_q = q_values[action]
            
            # TD error
            td_error = target - current_q
            total_loss += td_error ** 2
            
            # Q-value update
            q_values[action] += self.learning_rate * td_error
            self.q_table[state_key] = q_values
            # Evict oldest entries when table grows too large
            if len(self.q_table) > self._q_table_max:
                self.q_table.popitem(last=False)
        
        # Decay exploration rate
        if self.epsilon > self.epsilon_min:
            self.epsilon *= self.epsilon_decay
        
        self.training_steps += 1
        
        # Log progress every 100 training steps
        if self.training_steps % 100 == 0:
            avg_loss = total_loss / batch_size
            logger.info(
                f"RL TRAIN: steps={self.training_steps}, epsilon={self.epsilon:.3f}, "
                f"loss={avg_loss:.5f}, q_table_size={len(self.q_table)}"
            )

    def update_reward(self, reward: float, episode_done: bool = False):
        """Track episode reward for monitoring."""
        self.episode_rewards.append(reward)
        if episode_done and len(self.episode_rewards) > 0:
            self.avg_reward = np.mean(self.episode_rewards)
            logger.info(f"RL EPISODE: avg_reward={self.avg_reward:.5f}")

    def force_exploration(self, epsilon: float = 1.0):
        """
        Force high exploration rate (e.g., during self-healing crisis).
        
        Args:
            epsilon: Exploration rate to set
        """
        self.epsilon = min(epsilon, 1.0)
        logger.info(f"RL: Forcing exploration epsilon={self.epsilon:.3f}")

    def force_exploitation(self, epsilon: float = 0.05):
        """
        Force low exploration rate (conservative mode).
        
        Args:
            epsilon: Exploration rate to set
        """
        self.epsilon = max(epsilon, self.epsilon_min)
        logger.info(f"RL: Forcing exploitation epsilon={self.epsilon:.3f}")

    def get_stats(self) -> dict:
        """Get agent statistics for monitoring."""
        return {
            'training_steps': self.training_steps,
            'epsilon': round(self.epsilon, 3),
            'epsilon_min': self.epsilon_min,
            'learning_rate': self.learning_rate,
            'gamma': self.gamma,
            'q_table_size': len(self.q_table),
            'memory_size': len(self.memory),
            'avg_reward': round(self.avg_reward, 5),
        }

    def __repr__(self):
        return (
            f"DQN(state={self.state_size}, actions={self.action_size}, "
            f"epsilon={self.epsilon:.3f}, steps={self.training_steps})"
        )
