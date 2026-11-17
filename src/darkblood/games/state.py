"""Process-wide game state shared by the game and relay connections."""

from collections import deque

# Last character selected by any game connection (2006). Only a fallback:
# each GameSession keeps its own selection (GameSession.char_id) so two
# clients can play different characters at the same time.
selected_character = {'id': 0}

# Characters selected on a game connection whose relay connection has not
# joined yet. The relay (9401) is a separate TCP connection without a login,
# so it takes the oldest pending selection on its first JoinGroup.
pending_relay = deque()
